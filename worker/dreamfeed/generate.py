"""Nightly run, in three phases so ComfyUI and the vision models never share the GPU:
1. generate: split IMAGES_PER_NIGHT between mediums and have ComfyUI make them
2. check:    the same adults-only checks as bookmarks; anything flagged is deleted
3. rank:     score the rest against the medium's bookmarks, keep the best FEED_KEEP_TOP
"""
import datetime as dt
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from . import db, safety
from .config import Config, GenConfig

MAX_ATTEMPTS = 3
TOP_K = 5   # taste score: mean similarity to the closest K bookmarks

# Tags that describe the file, not the content; never used in prompts.
META_TAGS = {
    "no humans", "1other", "text", "english text", "japanese text", "watermark", "signature",
    "artist name", "web address", "patreon username", "twitter username", "logo", "dated",
    "multiple views", "comic", "speech bubble", "censored", "mosaic censoring", "bar censor",
    "blurry", "jpeg artifacts", "lowres", "letterboxed", "border", "subtitled", "copyright name",
    "meme", "user interface", "artist logo", "fine art parody", "parody", "out-of-frame censoring",
    "monochrome", "greyscale", "spot color", "pokemon (creature)", "spoken heart", "commentary",
    "translated", "virtual youtuber", "screencap", "lens flare", "what", "photo background",
}
MAX_TAGS = 24
GIRL_COUNTS = ["1girl", "2girls", "3girls", "multiple girls"]
BOY_COUNTS = ["1boy", "2boys", "3boys", "multiple boys"]
COUNT_TAGS = GIRL_COUNTS + BOY_COUNTS
PHOTO_COUNTS = {"1girl": "a woman", "2girls": "two women", "3girls": "three women",
                "multiple girls": "several women", "1boy": "a man", "2boys": "two men",
                "3boys": "three men", "multiple boys": "several men"}
PHOTO_DROP = {"realistic", "photorealistic", "photo (medium)", "solo", "solo focus", "cosplay photo"}
RATING_PREFIX = {"explicit": "nsfw, explicit, ", "questionable": "nsfw, ", "sensitive": "", "general": ""}


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
    if row and (row[0] == "done" or row[1] >= MAX_ATTEMPTS):
        return None
    return night


def enabled_mediums(cfg: Config, gen: GenConfig, conn) -> dict[str, int]:
    """Mediums with a checkpoint on disk and at least one bookmark, with bookmark counts."""
    counts = dict(conn.execute("SELECT medium, count(*) FROM bookmarks GROUP BY medium").fetchall())
    out = {}
    for medium, ckpt in gen.checkpoints.items():
        if not ckpt:
            continue
        if not (cfg.models_dir / "checkpoints" / ckpt).exists():
            print(f"generate: {medium} skipped, checkpoint {ckpt} not found", flush=True)
            continue
        if counts.get(medium):
            out[medium] = counts[medium]
    return out


def plan(counts: dict[str, int], total_images: int, min_share: float) -> dict[str, int]:
    total = sum(counts.values())
    shares = {m: max(min_share, n / total) for m, n in counts.items()}
    norm = sum(shares.values())
    alloc = {m: int(total_images * s / norm) for m, s in shares.items()}
    for m in sorted(shares, key=shares.get, reverse=True)[: total_images - sum(alloc.values())]:
        alloc[m] += 1
    return alloc


class PromptBuilder:
    """Prompts start from one random bookmark's tags, plus a couple of the medium's
    most common tags, so combinations stay coherent but vary."""

    def __init__(self, conn, medium: str):
        self.medium = medium
        self.tags: dict[int, dict[str, float]] = defaultdict(dict)
        self.rating: dict[int, str] = {}
        for bid, rating in conn.execute("SELECT id, rating FROM bookmarks WHERE medium = ?", (medium,)):
            self.rating[bid] = rating or "general"
        for bid, tag, score in conn.execute(
                "SELECT t.bookmark_id, t.tag, t.score FROM bookmark_tags t JOIN bookmarks b"
                " ON b.id = t.bookmark_id WHERE b.medium = ?", (medium,)):
            if tag not in META_TAGS and tag not in safety.NEVER_PROMPT_TAGS:
                self.tags[bid][tag] = score
        self.ids = sorted(self.rating)
        freq = Counter(t for tags in self.tags.values() for t in tags)
        self.popular = [t for t, _ in freq.most_common(60)]

    def build(self, rng: random.Random) -> tuple[str, int]:
        bid = rng.choice(self.ids)
        tags = self.tags.get(bid, {})
        # One people count per gender: the one the tagger was surest of.
        counts = [max((c for c in group if c in tags), key=tags.get)
                  for group in (GIRL_COUNTS, BOY_COUNTS) if any(c in tags for c in group)]
        content = {t: s for t, s in tags.items() if t not in COUNT_TAGS}
        strong = sorted((t for t, s in content.items() if s >= 0.5), key=content.get, reverse=True)
        weak = [t for t, s in content.items() if s < 0.5]
        chosen = strong + rng.sample(weak, k=len(weak) // 2)
        extra = [t for t in self.popular if t not in chosen and t not in COUNT_TAGS]
        chosen = chosen[: MAX_TAGS - len(counts) - 2] + rng.sample(extra, k=min(2, len(extra)))
        rng.shuffle(chosen)
        return self._format(counts, chosen, self.rating.get(bid, "general")), bid

    def _format(self, counts: list[str], rest: list[str], rating: str) -> str:
        esc = lambda t: t.replace("(", r"\(").replace(")", r"\)")
        if self.medium == "photo":
            people = " and ".join(PHOTO_COUNTS[c] for c in counts)
            body = [esc(t) for t in rest if t not in PHOTO_DROP]
            return "photo, " + RATING_PREFIX[rating] + ", ".join(([people] if people else []) + body)
        return RATING_PREFIX[rating] + ", ".join(esc(t) for t in counts + rest)


def run(cfg: Config, night: str | None = None, images: int | None = None, keep: int | None = None,
        ignore_window: bool = False) -> None:
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
                     " ON CONFLICT(night) DO UPDATE SET status='running', attempts=attempts+1",
                     (night,))

    counts = enabled_mediums(cfg, gen, conn)
    if not counts:
        _finish(conn, night, "done", {"note": "no medium has both a checkpoint and bookmarks"})
        return
    targets = plan(counts, images, gen.min_share)
    print(f"generate: night {night}, plan {targets}", flush=True)

    out_dir = cfg.data_dir / "generated"
    comfy = Comfy(gen.comfy_url, gen.supervisor_url, out_dir)
    rng = random.Random()
    try:
        for medium, target in targets.items():
            done = conn.execute("SELECT count(*) FROM generations WHERE night = ? AND medium = ?"
                                " AND status != 'queued'", (night, medium)).fetchone()[0]
            builder = PromptBuilder(conn, medium)
            for _ in range(max(0, target - done)):
                if not ignore_window and night_key(dt.datetime.now(), gen.window) != night:
                    print("generate: window closed, stopping generation", flush=True)
                    break
                prompt, source = builder.build(rng)
                seed = rng.randrange(2 ** 32)
                with conn:
                    gid = conn.execute(
                        "INSERT INTO generations(night, medium, checkpoint, prompt, seed, source_bookmark, status)"
                        " VALUES (?,?,?,?,?,?, 'queued')",
                        (night, medium, gen.checkpoints[medium], prompt, seed, source)).lastrowid
                try:
                    path = comfy.txt2img(gen.checkpoints[medium], medium, prompt, seed, night, f"{medium}-{gid}")
                except ValueError as e:   # safety.prompts refused it
                    _set(conn, gid, status="dropped", reason=f"blocked prompt: {e}")
                    continue
                _set(conn, gid, status="generated", file=str(path.relative_to(out_dir)))
    finally:
        comfy.stop()

    stats = check_and_rank(cfg, conn, night, keep)
    _finish(conn, night, "done", stats)
    print(f"generate: night {night} done {stats}", flush=True)


def check_and_rank(cfg: Config, conn, night: str, keep: int) -> dict:
    from PIL import Image
    from .tagging import drop_reason
    from .vision import Vision

    out_dir = cfg.data_dir / "generated"
    rows = conn.execute("SELECT id, medium, file FROM generations WHERE night = ? AND status = 'generated'",
                        (night,)).fetchall()
    if rows:
        vision = Vision(cfg.models_dir)
        taste = _taste_matrices(conn)
        for gid, medium, file in rows:
            path = out_dir / file
            try:
                img = Image.open(path).convert("RGB")
            except Exception as e:
                _set(conn, gid, status="dropped", reason=f"unreadable: {e}"[:200])
                continue
            a = vision.analyze([img])
            reason = drop_reason(a, medium, [img], cfg)
            if reason:
                path.unlink(missing_ok=True)
                _set(conn, gid, status="dropped", reason=f"{reason[0]}: {reason[1]}")
                continue
            emb = a.embedding.astype(np.float32)
            sims = np.sort(taste[medium] @ emb)[::-1][:TOP_K] if medium in taste else np.zeros(1)
            _set(conn, gid, status="scored", score=float(sims.mean()))

    # Keep the best per medium, in proportion to what each medium produced.
    scored = conn.execute("SELECT id, medium, file, score FROM generations WHERE night = ? AND status = 'scored'",
                          (night,)).fetchall()
    by_medium = defaultdict(list)
    for row in scored:
        by_medium[row[1]].append(row)
    total = len(scored)
    for medium, items in by_medium.items():
        quota = max(1, round(keep * len(items) / total))
        items.sort(key=lambda r: r[3], reverse=True)
        for gid, _, file, _ in items[:quota]:
            _set(conn, gid, status="feed")
        for gid, _, file, _ in items[quota:]:
            (out_dir / file).unlink(missing_ok=True)
            _set(conn, gid, status="ranked-out")

    return dict(conn.execute("SELECT status, count(*) FROM generations WHERE night = ? GROUP BY status",
                             (night,)).fetchall())


def _taste_matrices(conn) -> dict[str, np.ndarray]:
    rows = defaultdict(list)
    for medium, blob in conn.execute("SELECT medium, embedding FROM bookmarks"):
        rows[medium].append(np.frombuffer(blob, dtype=np.float16).astype(np.float32))
    return {m: np.stack(v) for m, v in rows.items()}


def _set(conn, gid: int, **fields) -> None:
    cols = ", ".join(f"{k} = ?" for k in fields)
    with conn:
        conn.execute(f"UPDATE generations SET {cols} WHERE id = ?", (*fields.values(), gid))


def _finish(conn, night: str, status: str, stats: dict) -> None:
    with conn:
        conn.execute("UPDATE runs SET status = ?, stats = ?, finished_at = datetime('now') WHERE night = ?",
                     (status, json.dumps(stats), night))
