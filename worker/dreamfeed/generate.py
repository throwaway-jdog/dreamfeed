"""Nightly run, in three phases so ComfyUI and the vision models never share the GPU:
1. generate: split IMAGES_PER_NIGHT between the personas in data/personas.json and have
             ComfyUI make their posts (plus a profile picture for anyone without one)
2. check:    the adults-only checks (worker/dreamfeed/checks.py), stricter for strict personas;
             anything flagged is deleted
3. rank:     score the rest against what you liked and skipped from that persona, keep the
             best FEED_KEEP_TOP, spread over the night as posts in the timeline
4. caption:  with CAPTION_MODEL set, a fresh caption for each kept post (captions.py)
"""
import datetime as dt
import json
import random
from collections import defaultdict
from pathlib import Path

import numpy as np

from . import captions, db, personas as people
from .config import Config, GenConfig

MAX_ATTEMPTS = 3
TOP_K = 5            # taste score: mean similarity to the closest K liked posts
SKIP_PENALTY = 0.5   # how much looking like something you skipped lowers the score
THUMB_WIDTH = 480
AVATAR_SIZE = 256
AVATAR_TRIES = 3     # candidates per missing profile picture; the first that passes is used


def night_key(now: dt.datetime, window: tuple[int, int]) -> str | None:
    """The night a moment belongs to if it's inside the window (named after the start date)."""
    start, end = window
    minute = now.hour * 60 + now.minute
    if start <= end:
        return now.date().isoformat() if start <= minute < end else None
    if minute >= start:
        return now.date().isoformat()
    if minute < end:
        return (now.date() - dt.timedelta(days=1)).isoformat()
    return None


def due_night(cfg: Config) -> str | None:
    """Tonight's key if we're in the window and tonight's run hasn't finished."""
    gen = cfg.generation()
    night = night_key(dt.datetime.now(), gen.window)
    if not night:
        return None
    conn = db.connect(cfg.db_path)
    row = conn.execute("SELECT status, attempts FROM runs WHERE night = ?", (night,)).fetchone()
    conn.close()
    if row and (row[0] in ("done", "cancelled") or row[1] >= MAX_ATTEMPTS):
        return None
    return night




def active_personas(cfg: Config, gen: GenConfig, conn, mediums: list[str] | None = None,
                    handles: list[str] | None = None) -> list[people.Persona]:
    """Personas from the file that have a checkpoint on disk, optionally narrowed down."""
    out = []
    loaded = people.load(cfg.personas_path)
    people.sync(conn, loaded)
    for p in loaded:
        if (mediums and p.medium not in mediums) or (handles and p.handle not in handles):
            continue
        if p.paused and not handles:   # paused: only posts when asked for by name (Post now)
            continue
        ckpt = gen.checkpoints.get(p.medium)
        if not ckpt or not (cfg.models_dir / "checkpoints" / ckpt).exists():
            print(f"generate: @{p.handle} skipped, no {p.medium} checkpoint on disk", flush=True)
            continue
        if p.lora and not (cfg.models_dir / "loras" / p.lora[0]).exists():
            print(f"generate: @{p.handle} posting without {p.lora[0]} (not in models/loras)", flush=True)
            p.lora, p.trigger = None, ""
        out.append(p)
    return out


def run(cfg: Config, night: str | None = None, images: int | None = None, keep: int | None = None,
        ignore_window: bool = False, mediums: list[str] | None = None, handles: list[str] | None = None) -> str:
    """Returns the run's final status: done | cancelled."""
    from .comfy import Comfy

    gen = cfg.generation()
    night = night or night_key(dt.datetime.now(), gen.window)
    if not night:
        raise SystemExit("generate: outside GENERATE_WINDOW (use --now to run anyway)")
    images = images or gen.images_per_night
    keep = keep or gen.keep_top
    conn = db.connect(cfg.db_path)
    with conn:
        conn.execute("INSERT INTO runs(night, status, attempts, started_at) VALUES (?, 'running', 1, datetime('now'))"
                     " ON CONFLICT(night) DO UPDATE SET status='running', attempts=attempts+1, cancel=0",
                     (night,))

    expire_old(cfg, conn, gen.feed_keep_days)
    cast = active_personas(cfg, gen, conn, mediums, handles)
    if not cast:
        _finish(conn, night, "done", {"note": f"no personas to post: add some to {cfg.personas_path.name}"})
        return "done"
    rng = random.Random()
    made = conn.execute("SELECT count(*) FROM generations WHERE night = ? AND kind = 'image' AND persona IS NOT NULL AND status != 'queued'",
                        (night,)).fetchone()[0]   # earlier attempt of the same night
    targets = people.plan(conn, cast, max(0, images - made), rng)
    have_avatar = {h for (h,) in conn.execute("SELECT handle FROM personas WHERE avatar IS NOT NULL")}
    tried = {h for (h,) in conn.execute("SELECT DISTINCT persona FROM generations WHERE night = ? AND kind = 'avatar'",
                                        (night,))}
    need_avatar = [p for p in cast if p.handle not in have_avatar and p.handle not in tried]
    total = sum(targets.values()) + AVATAR_TRIES * len(need_avatar)
    done = 0
    _progress(conn, night, "generating", done, total)
    cancelled = False
    print(f"generate: night {night}, {sum(targets.values())} posts for {len(targets)} personas, "
          f"{len(need_avatar)} profile pictures", flush=True)

    out_dir = cfg.data_dir / "generated"
    comfy = Comfy(gen.comfy_url, gen.supervisor_url, out_dir)

    def make(p: people.Persona, kind: str, prompt: str, caption: str | None) -> None:
        ckpt = gen.checkpoints[p.medium]
        seed = rng.randrange(2 ** 32)
        lora = p.lora_for(prompt)
        if p.trigger and not lora:   # no LoRA for this one, so its trigger word means nothing
            prompt = ", ".join(t for t in prompt.split(", ") if t != p.trigger)
        with conn:
            gid = conn.execute(
                "INSERT INTO generations(night, medium, checkpoint, prompt, seed, persona, caption, kind, status)"
                " VALUES (?,?,?,?,?,?,?,?, 'queued')",
                (night, p.medium, ckpt, prompt, seed, p.handle, caption, kind)).lastrowid
        try:
            path = comfy.txt2img(ckpt, p.medium, prompt, seed, night, f"{kind}-{p.handle}-{gid}", strict=p.strict,
                                 lora=lora, extra_negative=p.negative if kind == "image" else "")
        except ValueError as e:   # safety.prompts refused it
            _set(conn, gid, status="dropped", reason=f"blocked prompt: {e}")
            return
        _set(conn, gid, status="generated", file=str(path.relative_to(out_dir)))

    by_handle = {p.handle: p for p in cast}
    order = [h for h, n in targets.items() for _ in range(n)]
    rng.shuffle(order)
    try:
        for p in need_avatar:
            for _ in range(AVATAR_TRIES):
                make(p, "avatar", people.RATINGS["general"] + p.avatar_prompt(rng), None)
                done += 1
                _progress(conn, night, "generating", done, total)
        for handle in order:
            if not ignore_window and night_key(dt.datetime.now(), gen.window) != night:
                print("generate: window closed, stopping generation", flush=True)
                break
            if _cancel_requested(conn, night):
                cancelled = True
                print("generate: cancelled, checking what was made so far", flush=True)
                break
            p = by_handle[handle]
            post = people.pick_post(p, rng)
            make(p, "image", p.prompt_for(post, rng), p.caption_for(post, rng))
            done += 1
            _progress(conn, night, "generating", done, total, p.medium)
    finally:
        comfy.stop()

    stats = check_and_rank(cfg, conn, night, keep)
    if not cancelled and not ignore_window and gen.videos_per_night:
        sources = pick_sources(conn, gen.videos_per_night, night)
        if sources:
            stats["videos"] = animate(cfg, conn, night, sources, until_window_closes=gen.window)
    status = "cancelled" if cancelled else "done"
    _finish(conn, night, status, stats)
    print(f"generate: night {night} {status} {stats}", flush=True)
    return status


def check_and_rank(cfg: Config, conn, night: str, keep: int) -> dict:
    from PIL import Image
    from .checks import drop_reason
    from .vision import Vision

    out_dir = cfg.data_dir / "generated"
    rows = conn.execute(
        "SELECT g.id, g.medium, g.file, g.kind, g.persona, coalesce(p.strict, 1) FROM generations g"
        " LEFT JOIN personas p ON p.handle = g.persona"
        " WHERE g.night = ? AND g.status = 'generated' AND g.kind IN ('image', 'avatar')", (night,)).fetchall()
    rng = random.Random()
    tags = {}   # what the tagger saw in each post, for its caption
    if rows:
        _progress(conn, night, "checking", 0, len(rows))
        vision = Vision(cfg.models_dir)
        like, skip = _taste_matrices(conn)
        for n, (gid, medium, file, kind, handle, strict) in enumerate(rows, 1):
            if n % 5 == 0:
                _progress(conn, night, "checking", n, len(rows))
            path = out_dir / file
            try:
                img = Image.open(path).convert("RGB")
            except Exception as e:
                _set(conn, gid, status="dropped", reason=f"unreadable: {e}"[:200])
                continue
            a = vision.analyze([img])
            reason = drop_reason(a, medium, [img], cfg, strict=bool(strict)) or _feral(a)
            if reason:
                path.unlink(missing_ok=True)
                _set(conn, gid, status="dropped", reason=f"{reason[0]}: {reason[1]}")
                continue
            if kind == "avatar":
                _use_avatar(conn, out_dir, gid, handle, path, img)
                continue
            emb = a.embedding.astype(np.float32)
            likes = like.get(handle) if handle in like else like.get(medium)
            skips = skip.get(handle) if handle in skip else skip.get(medium)
            score = _closest(likes, emb)
            if skips is not None:
                score -= SKIP_PENALTY * max(0.0, _closest(skips, emb) - score)
            score += rng.random() * 1e-3   # breaks ties while nothing is liked yet
            tags[gid] = captions.picture(a.general)
            _set(conn, gid, status="scored", score=score, embedding=a.embedding.tobytes(), tags=", ".join(tags[gid]))
        vision.close()

    _progress(conn, night, "ranking", 0, 0)
    # Keep the best per persona, in proportion to how many posts each one made.
    scored = conn.execute("SELECT id, persona, file, score FROM generations WHERE night = ? AND status = 'scored'",
                          (night,)).fetchall()
    by_persona = defaultdict(list)
    for row in scored:
        by_persona[row[1]].append(row)
    started = conn.execute("SELECT started_at FROM runs WHERE night = ?", (night,)).fetchone()
    start = dt.datetime.fromisoformat(started[0]) if started and started[0] else _utcnow()
    span = max(60.0, (_utcnow() - start).total_seconds())
    winners = []
    for handle, items in by_persona.items():
        quota = max(1, round(keep * len(items) / len(scored)))
        items.sort(key=lambda r: r[3], reverse=True)
        winners += items[:quota]
        for gid, _, file, _ in items[quota:]:
            (out_dir / file).unlink(missing_ok=True)
            _set(conn, gid, status="ranked-out")
    written = captions.write_all(cfg, conn, night, [(gid, h, tags[gid]) for gid, h, _, _ in winners if gid in tags],
                                 lambda done, total: _progress(conn, night, "captioning", done, total))
    for gid, _, file, _ in winners:
        full, thumb = _to_jpeg(out_dir, file)
        # Posts are spread over the run so the timeline interleaves personas.
        posted = start + dt.timedelta(seconds=rng.uniform(0, span))
        extra = {"caption": written[gid]} if gid in written else {}
        _set(conn, gid, status="feed", file=full, thumb=thumb, posted_at=posted.strftime("%Y-%m-%d %H:%M:%S"),
             **extra)

    return dict(conn.execute("SELECT status, count(*) FROM generations WHERE night = ? GROUP BY status",
                             (night,)).fetchall())


def _feral(a) -> tuple[str, str] | None:
    from . import safety
    hits = safety.feral_hits(a.general)
    return ("feral", ", ".join(f"{h} {a.general[h]:.2f}" for h in hits)) if hits else None


def _use_avatar(conn, out_dir: Path, gid: int, handle: str, path: Path, img) -> None:
    """The first passing candidate becomes the profile picture: a square around the head, which
    SDXL puts near the top centre even when asked for a portrait."""
    have = conn.execute("SELECT avatar FROM personas WHERE handle = ?", (handle,)).fetchone()
    if have and have[0]:
        path.unlink(missing_ok=True)
        _set(conn, gid, status="ranked-out")
        return
    w, h = img.size
    side = int(min(w, h) * 0.6)
    left, top = (w - side) // 2, int(h * 0.02)
    face = img.crop((left, top, left + side, top + side)).resize((AVATAR_SIZE, AVATAR_SIZE))
    rel = Path("avatars") / f"{handle}-{gid}.jpg"
    (out_dir / rel).parent.mkdir(parents=True, exist_ok=True)
    face.save(out_dir / rel, quality=88, optimize=True)
    path.unlink(missing_ok=True)
    _set(conn, gid, status="avatar", file=str(rel))
    with conn:
        conn.execute("UPDATE personas SET avatar = ? WHERE handle = ?", (str(rel), handle))


def _taste_matrices(conn) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    """Liked and skipped posts, keyed both by persona handle and by medium (the fallback for a
    persona you haven't rated yet)."""
    like, skip = defaultdict(list), defaultdict(list)
    for handle, medium, blob, action in conn.execute(
            "SELECT g.persona, g.medium, g.embedding, f.action FROM feedback f JOIN generations g"
            " ON g.id = f.generation_id WHERE g.embedding IS NOT NULL AND g.persona IS NOT NULL"):
        target = like if action == "like" else skip
        target[handle].append(blob)
        target[medium].append(blob)
    stack = lambda d: {k: np.stack([np.frombuffer(b, dtype=np.float16).astype(np.float32) for b in v])
                       for k, v in d.items()}
    return stack(like), stack(skip)


def _utcnow() -> dt.datetime:
    """Naive UTC, the way SQLite's datetime('now') stores times."""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def _closest(matrix: np.ndarray | None, emb: np.ndarray) -> float:
    if matrix is None or not len(matrix):
        return 0.0
    return float(np.sort(matrix @ emb)[::-1][:TOP_K].mean())


def _to_jpeg(out_dir: Path, file: str) -> tuple[str, str]:
    """Feed images become a full-size JPEG and a small thumbnail, for phones on mobile data."""
    from PIL import Image
    src = out_dir / file
    full, thumb = src.with_suffix(".jpg"), src.with_name(src.stem + ".thumb.jpg")
    with Image.open(src) as img:
        img = img.convert("RGB")
        img.save(full, quality=90, optimize=True)
        img.thumbnail((THUMB_WIDTH, THUMB_WIDTH * 2))
        img.save(thumb, quality=78, optimize=True)
    src.unlink(missing_ok=True)
    return str(full.relative_to(out_dir)), str(thumb.relative_to(out_dir))


def expire_old(cfg: Config, conn, keep_days: float) -> None:
    """Delete feed images older than keep_days. Liked ones live on in data/liked."""
    out_dir = cfg.data_dir / "generated"
    rows = conn.execute(
        "SELECT id, file, thumb FROM generations WHERE status = 'feed'"
        " AND created_at < datetime('now', ?)", (f"-{keep_days} days",)).fetchall()
    for gid, file, thumb in rows:
        for f in (file, thumb):
            if f:
                (out_dir / f).unlink(missing_ok=True)
        _set(conn, gid, status="expired")
    for night_dir in out_dir.iterdir() if out_dir.is_dir() else []:
        if night_dir.is_dir() and not any(night_dir.iterdir()):
            night_dir.rmdir()
    if rows:
        print(f"generate: expired {len(rows)} feed images older than {keep_days:g} days", flush=True)


def _set(conn, gid: int, **fields) -> None:
    cols = ", ".join(f"{k} = ?" for k in fields)
    with conn:
        conn.execute(f"UPDATE generations SET {cols} WHERE id = ?", (*fields.values(), gid))


def _progress(conn, night: str, phase: str, done: int, total: int, medium: str | None = None) -> None:
    with conn:
        conn.execute("UPDATE runs SET progress = ? WHERE night = ?",
                     (json.dumps({"phase": phase, "done": done, "total": total, "medium": medium}), night))


def _cancel_requested(conn, night: str) -> bool:
    row = conn.execute("SELECT cancel FROM runs WHERE night = ?", (night,)).fetchone()
    return bool(row and row[0])


def run_job(cfg: Config, job_id: int) -> None:
    """Run a generation request queued from the dashboard."""
    conn = db.connect(cfg.db_path)
    row = conn.execute("SELECT params, status FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row or row[1] != "queued":
        return
    params = json.loads(row[0])
    if params.get("kind") == "animate":
        return animate_job(cfg, conn, job_id, params)
    if params.get("kind") == "style":
        from . import styles
        return styles.run(cfg, conn, job_id, params)
    night = f"manual-{dt.datetime.now():%Y%m%d-%H%M%S}"
    with conn:
        conn.execute("UPDATE jobs SET status = 'running', night = ? WHERE id = ?", (night, job_id))
    try:
        status = run(cfg, night=night, images=int(params["images"]), keep=int(params["keep"]),
                     ignore_window=True, mediums=params.get("mediums") or None,
                     handles=params.get("personas") or None)
        message = None
    except Exception as e:
        status, message = "failed", str(e)[:300]
        with conn:
            conn.execute("UPDATE runs SET status = 'failed', finished_at = datetime('now') WHERE night = ?", (night,))
        raise
    finally:
        with conn:
            conn.execute("UPDATE jobs SET status = ?, message = ?, finished_at = datetime('now') WHERE id = ?",
                         (status, message, job_id))


MOTION = {   # follows each clip's own motion description
    "anime": "fluid anime animation, natural motion, hair and clothes moving",
    "furry": "fluid animation, natural motion, fur, hair and clothes moving",
}
VIDEO_CHECK_FRAMES = 8   # every generated clip is checked on at least this many frames


def pick_sources(conn, count: int, night: str | None = None) -> list[int]:
    """Posts to animate: recent likes first, then a draw from the given night (or everything
    still in the feed) weighted by each persona's video_share, skipping posts that already
    have a clip."""
    have = "SELECT source_generation FROM generations WHERE kind = 'video' AND source_generation IS NOT NULL"
    liked = [r[0] for r in conn.execute(
        f"SELECT g.id FROM feedback f JOIN generations g ON g.id = f.generation_id WHERE f.action = 'like'"
        f" AND g.kind = 'image' AND g.status = 'feed' AND g.persona IS NOT NULL AND g.id NOT IN ({have})"
        f" ORDER BY f.at DESC")]
    where, args = ("AND g.night = ?", (night,)) if night else ("", ())
    pool = conn.execute(
        f"SELECT g.id, coalesce(p.video_share, 0.2) FROM generations g LEFT JOIN feedback f ON f.generation_id = g.id"
        f" LEFT JOIN personas p ON p.handle = g.persona WHERE g.kind = 'image' AND g.status = 'feed'"
        f" AND g.persona IS NOT NULL AND (f.action IS NULL OR f.action = 'like') AND g.id NOT IN ({have}) {where}"
        f" ORDER BY g.score DESC", args).fetchall()
    out = [gid for gid in liked][:count]
    pool = [r for r in pool if r[0] not in out]
    rng = random.Random()
    while pool and len(out) < count:
        pick = rng.choices(pool, weights=[max(0.01, w) for _, w in pool])[0]
        pool.remove(pick)
        out.append(pick[0])
    return out


def animate(cfg: Config, conn, night: str, sources: list[int],
            until_window_closes: tuple[int, int] | None = None, motion_text: str = "") -> dict:
    """Turn feed images into ~5 s Wan 2.2 clips, check every clip, put the passing ones in the feed.
    motion_text, when given, leads the prompt; the image's own tags follow to keep the clip
    consistent with the picture."""
    from . import motion
    from .comfy import Comfy
    gen = cfg.generation()
    out_dir = cfg.data_dir / "generated"
    comfy = Comfy(gen.comfy_url, gen.supervisor_url, out_dir)
    rng = random.Random()
    # The act and a written motion description per clip, before ComfyUI needs the GPU.
    comfy.stop()   # may still hold the GPU from an earlier job
    _progress(conn, night, "planning", 0, len(sources))
    picture = {}
    for src in sources:
        row = conn.execute("SELECT tags, prompt FROM generations WHERE id = ?", (src,)).fetchone()
        if row:   # posts from before tags were saved: their prompt's tags instead
            picture[src] = [t.strip() for t in (row[0] or row[1]).split(",") if t.strip()]
    plans = motion.plan(cfg, list(picture.items()), motion_text.strip())
    _progress(conn, night, "animating", 0, len(sources))
    made = 0
    try:
        for n, src in enumerate(sources, 1):
            if until_window_closes and night_key(dt.datetime.now(), until_window_closes) != night:
                print("animate: window closed, stopping", flush=True)
                break
            if _cancel_requested(conn, night):
                break
            row = conn.execute("SELECT g.medium, g.prompt, g.file, g.persona, g.caption, coalesce(p.strict, 1)"
                               " FROM generations g LEFT JOIN personas p ON p.handle = g.persona"
                               " WHERE g.id = ? AND g.kind = 'image' AND g.status = 'feed'", (src,)).fetchone()
            if not row or not (out_dir / row[2]).is_file() or row[0] not in MOTION:
                continue
            medium, prompt, file, handle, caption, strict = row
            act, written = plans.get(src, (None, None))
            use_lora = gen.act_lora if act else None
            # Wan follows sentences; without a written one, the act's fixed description and the
            # picture's tags keep the clip consistent with the image.
            body = written or ", ".join(p for p in (act.motion if act else "", prompt) if p)
            motion_prompt = ", ".join(p for p in (act.trigger if use_lora else "", motion_text.strip(), body,
                                                  MOTION[medium]) if p)
            seed = rng.randrange(2 ** 32)
            with conn:
                gid = conn.execute(
                    "INSERT INTO generations(night, medium, checkpoint, prompt, seed, source_generation, persona,"
                    " caption, kind, status) VALUES (?,?,?,?,?,?,?,?, 'video', 'queued')",
                    (night, medium, "wan2.2-i2v" + (f" +{act.name}" if use_lora else ""), motion_prompt, seed,
                     src, handle, caption)).lastrowid
            try:
                path = comfy.img2vid("wan", out_dir / file, medium, motion_prompt, seed, night, f"video-{gid}",
                                     strict=bool(strict), act_lora=use_lora)
            except ValueError as e:   # safety.prompts refused it
                _set(conn, gid, status="dropped", reason=f"blocked prompt: {e}")
                continue
            except (OSError, RuntimeError) as e:   # ComfyUI died, e.g. killed for low memory
                _set(conn, gid, status="dropped", reason=f"ComfyUI failed: {e}"[:200])
                print(f"animate: ComfyUI failed ({e}); stopping clips for this run", flush=True)
                break
            finally:
                comfy.stop()   # fresh ComfyUI per clip, so Wan's models don't pile up in RAM
            _set(conn, gid, status="generated", file=str(path.relative_to(out_dir)))
            made += 1
            _progress(conn, night, "animating", n, len(sources))
    finally:
        comfy.stop()
    return check_videos(cfg, conn, night)


def check_videos(cfg: Config, conn, night: str) -> dict:
    from . import media
    from .checks import drop_reason
    from .vision import Vision
    out_dir = cfg.data_dir / "generated"
    rows = conn.execute("SELECT g.id, g.medium, g.file, s.score, coalesce(p.strict, 1) FROM generations g"
                        " LEFT JOIN generations s ON s.id = g.source_generation"
                        " LEFT JOIN personas p ON p.handle = g.persona"
                        " WHERE g.night = ? AND g.kind = 'video' AND g.status = 'generated'", (night,)).fetchall()
    if rows:
        _progress(conn, night, "checking", 0, len(rows))
        vision = Vision(cfg.models_dir)
        for n, (gid, medium, file, score, strict) in enumerate(rows, 1):
            path = out_dir / file
            try:
                frames = media.load_frames(path, VIDEO_CHECK_FRAMES)
            except media.Unreadable as e:
                path.unlink(missing_ok=True)
                _set(conn, gid, status="dropped", reason=f"unreadable: {e}"[:200])
                continue
            a = vision.analyze(frames)
            reason = drop_reason(a, medium, frames, cfg, strict=bool(strict)) or _feral(a)
            if reason:
                path.unlink(missing_ok=True)
                _set(conn, gid, status="dropped", reason=f"{reason[0]}: {reason[1]}")
                continue
            poster = path.with_name(path.stem + ".thumb.jpg")
            first = frames[0].copy()
            first.thumbnail((THUMB_WIDTH, THUMB_WIDTH * 2))
            first.save(poster, quality=78, optimize=True)
            _set(conn, gid, status="feed", score=score or 0, thumb=str(poster.relative_to(out_dir)),
                 embedding=a.embedding.tobytes(), posted_at=_utcnow().strftime("%Y-%m-%d %H:%M:%S"))
            _progress(conn, night, "checking", n, len(rows))
    return dict(conn.execute("SELECT status, count(*) FROM generations WHERE night = ? AND kind = 'video'"
                             " GROUP BY status", (night,)).fetchall())


def animate_job(cfg: Config, conn, job_id: int, params: dict) -> None:
    """Dashboard / viewer request: animate given images, or the best N not yet animated."""
    night = f"video-{dt.datetime.now():%Y%m%d-%H%M%S}"
    with conn:
        conn.execute("UPDATE jobs SET status = 'running', night = ? WHERE id = ?", (night, job_id))
        conn.execute("INSERT INTO runs(night, status, attempts, started_at) VALUES (?, 'running', 1, datetime('now'))",
                     (night,))
    status, message = "done", None
    try:
        sources = [int(i) for i in params.get("ids") or []] or pick_sources(conn, int(params.get("count", 0)))
        stats = animate(cfg, conn, night, sources, motion_text=str(params.get("prompt") or ""))
        if _cancel_requested(conn, night):
            status = "cancelled"
        _finish(conn, night, status, stats)
    except Exception as e:
        status, message = "failed", str(e)[:300]
        with conn:
            conn.execute("UPDATE runs SET status = 'failed', progress = NULL, finished_at = datetime('now')"
                         " WHERE night = ?", (night,))
        raise
    finally:
        with conn:
            conn.execute("UPDATE jobs SET status = ?, message = ?, finished_at = datetime('now') WHERE id = ?",
                         (status, message, job_id))


def next_job(cfg: Config) -> int | None:
    conn = db.connect(cfg.db_path)
    row = conn.execute("SELECT id FROM jobs WHERE status = 'queued' ORDER BY id LIMIT 1").fetchone()
    conn.close()
    return row[0] if row else None


def recover(cfg: Config) -> None:
    """At worker start: anything left 'running' died with the previous worker."""
    conn = db.connect(cfg.db_path)
    with conn:
        conn.execute("UPDATE jobs SET status = 'failed', message = 'worker restarted', finished_at = datetime('now')"
                     " WHERE status = 'running'")
        conn.execute("UPDATE runs SET status = 'failed', finished_at = datetime('now')"
                     " WHERE status = 'running' AND night NOT GLOB '[0-9]*'")
    conn.close()


def _finish(conn, night: str, status: str, stats: dict) -> None:
    with conn:
        conn.execute("UPDATE runs SET status = ?, stats = ?, progress = NULL, finished_at = datetime('now')"
                     " WHERE night = ?", (status, json.dumps(stats), night))
