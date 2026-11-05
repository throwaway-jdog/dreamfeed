"""Scenes: a short edited sex scene of about a minute, made the way animators do it: a few
looping shots, each a new drawing, cut together and building to a climax.

From the viewer ("Make a scene", a job of kind "scene"), or by hand:
    python -m dreamfeed scene-preview POST_ID [--seed N]   plan and draw the shots, contact sheet
    python -m dreamfeed scene-render POST_ID [--shots 4,5]  animate what scene-preview drew

A scene starts from a feed post with two characters. The post gives the cast and setting
(its tags minus the act, position and cum); each shot adds its own position, framing and
intensity. Only the climax and aftermath shots may show cum, and the others ask the model
not to draw it, so the scene can build up.

1. draw: one picture per shot (the persona's own model and style LoRA, the same image checks
   as posts; of SHOT_CANDIDATES, the one that shows the intended act and looks most like the
   post wins).
2. render: each picture becomes a 5-second Wan clip that ends on its own first frame, a
   seamless loop played shot.loops times before a hard cut. The climax plays once and builds.
   Every clip is checked before it's used; one that keeps failing is left out.
"""
import argparse
import json
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import motion

SHOT_CANDIDATES = 4
# What the tagger must see for a shot's picture to show its act, beyond the position.
PENETRATION = ({"penis"}, {"vaginal", "sex", "penetration"})
ORAL = ({"penis"}, {"fellatio", "oral"})
SHOT_TRIES = 3         # a shot whose clip fails a check is made again, then left out
# Scene clips, picked by eye against the plain-clip settings (same picture and seed): the act
# LoRA at full strength moves the bodies; the style LoRA lower so it doesn't fight it; one more
# step without the speed-up LoRA so the motion keeps its detail.
ACT_STRENGTH = 1.0
STYLE_STRENGTH = 0.3
SCENE_WAN = {"motion_steps": 3}

# What a position looks like in a picture (booru tags for the image model), and the act
# the tagger should then find in it (motion.ACTS names; None when no act LoRA covers it).
POSITIONS = {
    "missionary": ("missionary, on back, spread legs, sex, vaginal, penis", "missionary"),
    "doggy": ("doggystyle, sex from behind, all fours, sex, vaginal, penis", "doggy"),
    "cowgirl": ("cowgirl position, girl on top, straddling, sex, vaginal, penis", "cowgirl"),
    "reverse cowgirl": ("reverse cowgirl position, girl on top, from behind, sex, vaginal, penis", "reverse cowgirl"),
    "blowjob": ("fellatio, oral, penis, kneeling, looking up", "blowjob"),
}
# Penetration shots are drawn side-on with both bodies whole: from below, it sits on the
# picture's bottom edge and Wan makes the penis vanish instead of moving it.
SIDE_ON = "(from side:1.4), (full body:1.2), profile, his whole body"
SIDE_ON_NEGATIVE = "(pov:1.3), (from below:1.3), (from front:1.2), close-up, cropped, out of frame, head out of frame"
SIDE_TAGS = {"from side", "profile"}   # the tagger must see one of these in a side-on shot
SHOT_CANDIDATES_SIDE = 6
TAG_SURE = 0.35
OPENERS = ("missionary", "blowjob")
MIDDLE = ("doggy", "cowgirl", "missionary", "reverse cowgirl")

NO_CUM = "cum, semen, cum on body, cum in pussy, cum in mouth, creampie, ejaculation, cum string"
# Every shot: the partner mustn't turn into a second copy of her, and no artist text.
SCENE_NEGATIVE = ("2girls, multiple girls, twins, watermark, signature, text, logo, patreon username, "
                  "comic, multiple views, panels, split screen, inset, furry male")
FURRY_PARTNER = {"furry male", "rabbit boy"}   # he's drawn as a second animal; a worse pick
PANELS = {"comic", "multiple views", "split screen", "inset", "4koma", "2koma", "panel"}   # a shot is one picture
PARTNER = "faceless male"   # how artists often draw him; keeps him from borrowing her tags
PARTNER_LOOKS = ("dark-skinned male", "tan skin", "muscular male, dark skin")   # not grey: reads as fur   # one per scene
CROP = 0.04   # off the top and bottom of each shot: style LoRAs learn the artist's signature strip

# Tags that belong to what's happening, not to who and where: dropped from the post's own
# tags to get the cast and setting.
SCENE_ONLY = re.compile(r"\b(cum|semen|creampie|ejaculat|bukkake|facial|after sex|orgasm|"
                        r"motion lines|trembling|heavy breathing|sweat|ahegao|tongue out|open mouth|"
                        r"from behind|on back|all fours|straddling|spread legs|lying|kneeling|"
                        r"girl on top|on top|penetration|vaginal|anal|sex|penis|fellatio|oral|"
                        r"doggystyle|missionary|cowgirl|paizuri|handjob|blowjob)\b", re.I)


@dataclass
class Shot:
    name: str          # what it is, for the plan and the contact sheet
    tags: str          # position, framing and intensity, added to the cast and setting
    act: str | None    # the act the picture must show (and the motion LoRA for the clip)
    cum: bool          # may show cum
    pace: str          # for the motion description: how fast and intense
    loops: int = 2     # times the 5-second clip plays before the cut
    climax: str = ""   # motion.CLIMAXES name: the clip adds that LoRA to the position's, and plays
                       # once without looping (a climax builds; it doesn't reset)


def _frames(path: Path) -> np.ndarray:
    """Every frame of a video, as one RGB array."""
    import subprocess
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=60).stdout.strip().split(",")
    w, h = int(probe[0]), int(probe[1])
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, timeout=300, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)


def _sample(frames: np.ndarray, count: int) -> list[Image.Image]:
    idx = [int(len(frames) * (i + 0.5) / count) for i in range(count)]
    return [Image.fromarray(frames[i]) for i in idx]


def cast_tags(prompt: str, partner: str = "") -> str:
    """The post's prompt minus everything that belongs to the act: who and where. partner: his
    look, the same in every shot of a scene."""
    keep = [t.strip() for t in prompt.split(",") if t.strip() and not SCENE_ONLY.search(t)]
    keep = [t for t in keep if t not in ("duo", "male", "1boy", PARTNER)]
    # Rating first, then the pair, then her.
    rating = [t for t in keep if t in ("nsfw", "explicit", "questionable")]
    rest = [t for t in keep if t not in rating]
    return ", ".join(rating + ["duo", PARTNER] + ([partner] if partner else []) + rest)


def plan(rng: random.Random) -> list[Shot]:
    """Opener, a position, a close-up in it, another position, the climax in that one, after."""
    opener = rng.choice(OPENERS)
    a = rng.choice([p for p in MIDDLE if p != opener])
    b = rng.choice([p for p in MIDDLE if p not in (a, opener)] or [p for p in MIDDLE if p != a])
    act = lambda name: POSITIONS[name][1]

    def pos(name: str, view: str = SIDE_ON) -> str:
        return POSITIONS[name][0] if name == "blowjob" else f"{POSITIONS[name][0]}, {view}"
    return [
        Shot(f"opening: {opener}", f"{pos(opener)}, blush, half-closed eyes", act(opener), False,
             "slow and gentle, just starting"),
        Shot(f"{a}", f"{pos(a)}, blush, open mouth", act(a), False,
             "a steady rhythm"),
        # No "close-up" here: in this kind of art it draws inset panels.
        Shot(f"{a}, from the side", f"{pos(a, '(from side:1.3), (three-quarter view:1.1), (full body:1.2)')}, blush, open mouth, sweat, "
             "heavy breathing", act(a), False, "faster, she's lost in it"),
        Shot(f"{b}", f"{pos(b)}, open mouth, sweat, heavy breathing, motion lines", act(b), False,
             "fast and intense, building toward climax"),
        Shot(f"climax: {b}", f"{pos(b)}, orgasm, cum in pussy, creampie, cum overflow, trembling, open mouth, "
             "sweat", act(b), True, "the climax: he cums inside her, both shuddering", loops=1, climax="creampie"),
        Shot("aftermath", "after sex, lying, on back, cum in pussy, cum on body, sweat, heavy breathing, "
             "half-closed eyes, smile", None, True, "slow, catching their breath", loops=1),
    ]


def _crop(path: Path) -> None:
    with Image.open(path) as im:
        im = im.convert("RGB")
        w, h = im.size
        cut = round(h * CROP)
        im = im.crop((0, cut, w, h - cut))
    im.save(path)


def draw(cfg, comfy, persona, post: dict, shots: list[Shot], subdir: str, name: str,
         rng: random.Random) -> list[tuple[Path | None, str]]:
    """One checked picture per shot: (path or None, note). Candidates that lose are deleted;
    winners are cropped (CROP)."""
    from . import captions
    from .checks import drop_reason
    from .generate import _feral
    from .vision import Vision
    cast = cast_tags(post["prompt"], rng.choice(PARTNER_LOOKS))
    print(f"scene: cast and setting: {cast}", flush=True)
    lora = persona.lora_for(post["prompt"]) if persona else None
    negative = persona.negative if persona else ""
    cands: list[list[Path]] = []
    try:
        for i, shot in enumerate(shots):
            side_on = shot.act not in (None, "blowjob")
            neg = ", ".join(n for n in (negative, SCENE_NEGATIVE, "" if shot.cum else NO_CUM,
                                        SIDE_ON_NEGATIVE if side_on else "") if n)
            cands.append([comfy.txt2img(post["checkpoint"], post["medium"], f"{cast}, {shot.tags}",
                                        rng.randrange(2 ** 32), subdir, f"{name}-shot{i}-{c}",
                                        extra_negative=neg, strict=post["strict"], lora=lora)
                          for c in range(SHOT_CANDIDATES_SIDE if side_on else SHOT_CANDIDATES)])
    finally:
        comfy.stop()
    vision = Vision(cfg.models_dir)
    out = []
    try:
        with Image.open(post["file"]) as im:
            base = vision.analyze([im.convert("RGB")]).embedding.astype(np.float32)
        for shot, paths in zip(shots, cands):
            scored = []
            for p in paths:
                with Image.open(p) as im:
                    img = im.convert("RGB")
                a = vision.analyze([img])
                if drop_reason(a, post["medium"], [img], cfg, strict=post["strict"]) or _feral(a):
                    continue
                if PANELS & set(captions.picture(a.general)):
                    continue
                # Every tag the tagger is sure of: its top-tags list cuts off "penis" and the view.
                seen = {t for t, sc in a.general.items() if sc >= TAG_SURE}
                shows = {act.name for act in motion.ACTS if seen & set(act.tags)}
                # Side-on, the tagger can't tell which way she faces on top.
                if shot.act == "reverse cowgirl" and "cowgirl" in shows:
                    shows.add("reverse cowgirl")
                # Showing the intended act matters more than looking like the post: the position,
                # and the penis actually in it (a cowgirl on his lap with nothing inside isn't).
                need = ORAL if shot.act == "blowjob" else PENETRATION if shot.act else None
                fits = (shot.act is None or shot.act in shows) and \
                    (need is None or (need[0] <= seen and bool(need[1] & seen)))
                # Then side-on, for penetration: from below, Wan loses the penis at the edge.
                side = shot.act in (None, "blowjob") or bool(SIDE_TAGS & seen)
                fits = (fits and not (FURRY_PARTNER & seen), side)
                scored.append((fits, float(a.embedding.astype(np.float32) @ base), p))
            best = max(scored, key=lambda s: s[:2]) if scored else None
            for p in paths:
                if not best or p != best[2]:
                    p.unlink(missing_ok=True)
            if best:
                _crop(best[2])
            out.append((best[2], f"{'' if best[0][0] else 'act not seen, '}{'' if best[0][1] else 'not side-on, '}look {best[1]:.2f}") if best
                       else (None, f"all {len(paths)} failed the checks"))
    finally:
        vision.close()
    return out


def contact_sheet(post_file: Path, shots: list[Shot], pictures: list[tuple[Path | None, str]],
                  out: Path, width: int = 300) -> Path:
    """The post, then each shot's picture, labelled, in one image."""
    tiles = [(post_file, "the post")] + [(p, f"{i + 1}. {s.name}\n{note}")
                                        for i, (s, (p, note)) in enumerate(zip(shots, pictures))]
    cols, label = 4, 34
    rows = -(-len(tiles) // cols)
    cell_h = int(width * 1.5) + label
    sheet = Image.new("RGB", (cols * width, rows * cell_h), (24, 22, 20))
    pen = ImageDraw.Draw(sheet)
    for k, (path, text) in enumerate(tiles):
        x, y = (k % cols) * width, (k // cols) * cell_h
        if path:
            with Image.open(path) as im:
                im = im.convert("RGB")
                im.thumbnail((width, cell_h - label))
                sheet.paste(im, (x, y))
        pen.multiline_text((x + 6, y + cell_h - label + 2), text, fill=(235, 230, 220), spacing=2)
    sheet.save(out, quality=85)
    return out


def load_post(cfg, conn, gid: int) -> dict:
    row = conn.execute("SELECT g.medium, g.prompt, g.file, g.persona, g.checkpoint, coalesce(p.strict, 1)"
                       " FROM generations g LEFT JOIN personas p ON p.handle = g.persona"
                       " WHERE g.id = ? AND g.kind = 'image'", (gid,)).fetchone()
    if not row:
        raise LookupError(f"no image post {gid}")
    medium, prompt, file, handle, ckpt, strict = row
    return {"medium": medium, "prompt": prompt, "file": cfg.data_dir / "generated" / file, "persona": handle,
            "checkpoint": ckpt, "strict": bool(strict)}


def preview(args: list[str]) -> None:
    from . import db, personas as people
    from .comfy import Comfy
    from .config import Config
    ap = argparse.ArgumentParser(prog="dreamfeed scene-preview")
    ap.add_argument("post", type=int)
    ap.add_argument("--seed", type=int)
    a = ap.parse_args(args)
    cfg = Config()
    gen = cfg.generation()
    conn = db.connect(cfg.db_path)
    post = load_post(cfg, conn, a.post)
    persona = {p.handle: p for p in people.load(cfg.personas_path)}.get(post["persona"])
    rng = random.Random(a.seed)
    shots = plan(rng)
    out_dir = cfg.data_dir / "generated"
    subdir = f"scene-preview-{a.post}"
    comfy = Comfy(gen.comfy_url, gen.supervisor_url, out_dir)
    pictures = draw(cfg, comfy, persona, post, shots, subdir, f"post{a.post}", rng)
    sheet = contact_sheet(post["file"], shots, pictures, out_dir / subdir / "contact-sheet.jpg")
    from dataclasses import asdict
    (out_dir / subdir / "plan.json").write_text(json.dumps(
        [asdict(s) | {"picture": str(p) if p else None, "note": n} for s, (p, n) in zip(shots, pictures)], indent=1))
    print(f"scene-preview: {sheet}", flush=True)


def _shot_prompt(writer, cast: str, shot: Shot, act) -> str | None:
    """A written, checked description of the shot's motion for its point in the scene."""
    where = (f"This is one shot of a longer scene: {shot.pace}. The clip loops, so the motion is a "
             f"repeating cycle that ends where it started.")
    return motion.describe(writer, [t.strip() for t in f"{cast}, {shot.tags}".split(",")], act, context=where)


def render(cfg, comfy, post: dict, shots: list[Shot], pictures: list[Path | None], out: Path,
           rng: random.Random, progress=None, cancelled=lambda: False, act_strength: float | None = None,
           style_strength: float | None = None, wan: dict | None = None,
           seed: int | None = None) -> tuple[Path | None, list[str]]:
    """Animate each shot's picture into a 5-second loop (Wan, first and last frame the same
    picture), check it, play it shot.loops times, and cut to the next. Returns the scene file
    (None if no shot passed) and a note per shot."""
    import subprocess
    from . import personas as people, videolora
    from .comfy import WAN
    from .generate import MOTION, VIDEO_CHECK_FRAMES, _check_frames
    gen = cfg.generation()
    persona = {p.handle: p for p in people.load(cfg.personas_path)}.get(post["persona"])
    own = persona and persona.lora and videolora.for_style(cfg, persona.lora[0])
    acts = {a.name: a for a in motion.ACTS}
    cast = cast_tags(post["prompt"])
    # Descriptions first: the text model and Wan don't share the GPU.
    comfy.stop()
    texts = [None] * len(shots)
    if cfg.caption_model:
        from .captions import Writer
        writer = Writer(cfg.caption_model)
        try:
            for i, shot in enumerate(shots):
                clip_act = motion.CLIMAXES.get(shot.climax) or acts.get(shot.act)
                texts[i] = _shot_prompt(writer, cast, shot, clip_act)
        finally:
            writer.close()
    notes, writer = [], None
    try:
        for i, (shot, pic) in enumerate(zip(shots, pictures)):
            if cancelled():
                notes.append("cancelled")
                break
            if pic is None:
                notes.append("no picture")
                continue
            # The position's motion LoRA, plus the climax's on a climax shot.
            used = [a for a in (acts.get(shot.act), motion.CLIMAXES.get(shot.climax)) if a]
            with_lora = [(a, motion.lora_for(a, gen.act_lora, cfg.models_dir)) for a in used]
            with_lora = [(a, l) for a, l in with_lora if l]
            act_s = ACT_STRENGTH if act_strength is None else act_strength
            with_lora = [(a, (l[0], l[1], act_s)) for a, l in with_lora]
            style_s = STYLE_STRENGTH if style_strength is None else style_strength
            loras = [l for _, l in with_lora] + ([(own[0], own[1], style_s)] if own and style_s > 0 else [])
            clip_act = used[-1] if used else None
            body = texts[i] or ", ".join(p for p in (clip_act.motion if clip_act else "", shot.pace) if p)
            prompt = ", ".join(p for p in (own[2] if own else "", *(a.trigger for a, _ in with_lora),
                                           body, MOTION[post["medium"]]) if p)
            frames = None
            for attempt in range(SHOT_TRIES):
                try:
                    path = comfy.img2vid("wan", pic, post["medium"], prompt,
                                         seed if seed is not None else rng.randrange(2 ** 32), out.parent.name,
                                         f"{out.stem}-shot{i}", strict=post["strict"], loras=loras,
                                         end=None if shot.climax else pic, wan=SCENE_WAN | (wan or {}))
                finally:
                    comfy.stop()
                frames = _frames(path)
                path.unlink(missing_ok=True)
                reason = _check_frames(cfg, _sample(frames, VIDEO_CHECK_FRAMES), post["medium"], post["strict"])
                if not reason:
                    break
                print(f"scene: shot {i + 1} try {attempt + 1} dropped ({reason[0]}: {reason[1]})", flush=True)
                frames = None
            if frames is None:
                notes.append(f"dropped after {SHOT_TRIES} tries")
                continue
            if writer is None:
                h, w = frames.shape[1:3]
                writer = subprocess.Popen(
                    ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                     "-r", str(WAN["fps"]), "-i", "-", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                     "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)
            cycle = (frames if shot.climax else frames[:-1]).tobytes()   # a loop's last frame is its first
            for _ in range(shot.loops):
                writer.stdin.write(cycle)
            notes.append("ok " + " + ".join(l[0].split("-high")[0] for _, l in with_lora))
            print(f"scene: shot {i + 1} {shot.name}: {notes[-1]}", flush=True)
            if progress:
                progress(i + 1, len(shots))
        if writer is None:
            return None, notes
        writer.stdin.close()
        if writer.wait() != 0:
            raise RuntimeError("ffmpeg couldn't join the shots")
        writer = None
        return out, notes
    except BaseException:
        if writer:
            writer.kill()
            writer.wait()
        out.unlink(missing_ok=True)
        raise


def render_preview(args: list[str]) -> None:
    """scene-render POST_ID [--shots 4,5]: animate the pictures scene-preview drew."""
    from . import db
    from .comfy import Comfy
    from .config import Config
    from dataclasses import fields
    ap = argparse.ArgumentParser(prog="dreamfeed scene-render")
    ap.add_argument("post", type=int)
    ap.add_argument("--shots", help="which shots, e.g. 4,5 (default all)")
    ap.add_argument("--act-strength", type=float)
    ap.add_argument("--style-strength", type=float, help="0 turns the style video LoRA off")
    ap.add_argument("--motion-steps", type=int, help="steps without the speed-up LoRA (WAN motion_steps)")
    ap.add_argument("--high-steps", type=int, help="steps on the high-noise expert (WAN high_steps)")
    ap.add_argument("--size", help="WxH, e.g. 576x848")
    ap.add_argument("--seed", type=int, help="the same seed for every try, to compare settings")
    ap.add_argument("--out", default="scene.mp4")
    a = ap.parse_args(args)
    cfg = Config()
    gen = cfg.generation()
    conn = db.connect(cfg.db_path)
    post = load_post(cfg, conn, a.post)
    out_dir = cfg.data_dir / "generated"
    subdir = out_dir / f"scene-preview-{a.post}"
    saved = json.loads((subdir / "plan.json").read_text())
    names = {f.name for f in fields(Shot)}
    shots = [Shot(**{k: v for k, v in d.items() if k in names}) for d in saved]
    pics = [Path(d["picture"]) if d["picture"] else None for d in saved]
    if a.shots:
        pick = [int(x) - 1 for x in a.shots.split(",")]
        shots, pics = [shots[i] for i in pick], [pics[i] for i in pick]
    comfy = Comfy(gen.comfy_url, gen.supervisor_url, out_dir)
    wan = {}
    if a.motion_steps is not None:
        wan["motion_steps"] = a.motion_steps
    if a.high_steps is not None:
        wan["high_steps"] = a.high_steps
    if a.size:
        wan["width"], wan["height"] = (int(x) for x in a.size.lower().split("x"))
    path, notes = render(cfg, comfy, post, shots, pics, subdir / a.out, random.Random(),
                         act_strength=a.act_strength, style_strength=a.style_strength, wan=wan or None, seed=a.seed)
    print(f"scene-render: {path} {notes}", flush=True)


def run_job(cfg, conn, job_id: int, params: dict) -> None:
    """A "Make a scene" request from the viewer: params {"kind": "scene", "ids": [post]}."""
    import datetime as dt
    from . import personas as people
    from .comfy import Comfy
    from .generate import _cancel_requested, _finish, _progress, _set, check_videos
    night = f"scene-{dt.datetime.now():%Y%m%d-%H%M%S}"
    with conn:
        conn.execute("UPDATE jobs SET status = 'running', night = ? WHERE id = ?", (night, job_id))
        conn.execute("INSERT INTO runs(night, status, attempts, started_at) VALUES (?, 'running', 1, datetime('now'))",
                     (night,))
    status, message, pictures = "done", None, []
    gen = cfg.generation()
    out_dir = cfg.data_dir / "generated"
    comfy = Comfy(gen.comfy_url, gen.supervisor_url, out_dir)
    try:
        src = int(params["ids"][0])
        post = load_post(cfg, conn, src)
        persona = {p.handle: p for p in people.load(cfg.personas_path)}.get(post["persona"])
        rng = random.Random()
        shots = plan(rng)
        with conn:
            gid = conn.execute(
                "INSERT INTO generations(night, medium, checkpoint, prompt, seed, source_generation, persona,"
                " caption, kind, status) SELECT ?, medium, 'wan2.2-i2v scene', ?, 0, id, persona, caption,"
                " 'video', 'queued' FROM generations WHERE id = ?",
                (night, " | ".join(s.name for s in shots), src)).lastrowid
        _progress(conn, night, "drawing", 0, len(shots))
        drawn = draw(cfg, comfy, persona, post, shots, night, f"scene-{gid}", rng)
        pictures = [p for p, _ in drawn if p]
        _progress(conn, night, "animating", 0, len(shots))
        path, notes = render(cfg, comfy, post, shots, [p for p, _ in drawn], out_dir / night / f"video-{gid}.mp4",
                             rng, progress=lambda d, t: _progress(conn, night, "animating", d, t),
                             cancelled=lambda: _cancel_requested(conn, night))
        print(f"scene: {night} {notes}", flush=True)
        if path:
            from .comfy import WAN
            seconds = round(len(_frames(path)) / WAN["fps"])
            _set(conn, gid, status="generated", file=str(path.relative_to(out_dir)),
                 checkpoint=f"wan2.2-i2v scene {seconds}s")
        else:
            _set(conn, gid, status="dropped", reason="no shot passed: " + "; ".join(notes)[:180])
        stats = check_videos(cfg, conn, night)
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
        comfy.stop()
        for p in pictures:
            p.unlink(missing_ok=True)
        with conn:
            conn.execute("UPDATE jobs SET status = ?, message = ?, finished_at = datetime('now') WHERE id = ?",
                         (status, message, job_id))
