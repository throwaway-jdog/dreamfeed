"""A comic panel animated: a short seamless loop, the way comic artists animate a panel.

    python -m dreamfeed comic-panels [--again]   panels and thumbnails for comics saved without them

The reader's "Animate a panel" queues a job (kind "comic_animate") for one panel of one page:
the panel is cut out of the page, Wan 2.2 animates it for about four seconds (moving as asked,
or by the act's motion LoRA: a forced last frame equal to the first left it all but still),
the clip gets the video checks (every sampled frame, and no drifting away from the panel), and
it's cut where the motion comes back closest to the start and blended there (or played forward
then back) so it loops without a jump. It's kept beside the comic.
The reader plays it over its panel, looping.

The person can draw loops around what should move (the characters): then only that moves, the
rest of the clip is the drawing itself (text and speech bubbles stay put), and the reader shows
the page through everywhere else (the clip's mask). Loops may reach past the panel, for a
character breaking out of it: the clip then covers both.

Panels are found once, when a comic is saved: the page is cut along its gutters (whatever their
colour). Panels with no gutter between them come out as one; the reader lets the person draw
the box instead.
"""
import datetime as dt
import json
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

THUMB = 360             # a thumbnail's width
PANEL_SIDE = 1000       # pages are searched for panels at this long side
PANEL_MIN = 0.02        # a panel is at least this share of the page
PAPER = 200             # a page edge this bright is paper (see _paper_panels)
GUTTER_LIKE = 28        # this close in grey to the page's edge is gutter
GUTTER_SHARE = 0.8      # a row or column this much gutter is a gutter (a bubble or tail may cross it)
GUTTER_MIN = 2          # pixels (at PANEL_SIDE) a gutter is at least
LOOP = {"frames": 65}   # about four seconds at Wan's 16 fps, cut down to a loop (_loop)
LOOP_MIN = 16           # frames a loop is at least
SETTLE = 3              # first frames left out (the clip moving off the drawing)
LOOP_FPS = 12           # loops play a little slower than Wan's 16 fps: its motion LoRAs run fast
LOOP_CLOSE = 8.0        # mean difference (0-255) from the first frame close enough to loop back to it
BLEND = 5               # frames blended into the start at the loop's end
AREA = 480 * 704        # the clip's pixels (Wan's usual size), in the panel's shape
GROW = 0.02            # an outline is widened this share of the clip's long side (motion past it)
FEATHER = 0.01          # and its edge softened over this share
IDLE_MOTION = "small natural movements, breathing, blinking, hair swaying"
LOOP_WORDS = "continuous repeating motion, still camera"


def find_panels(img: Image.Image) -> list[list[float]]:
    """Each panel's box [x0, y0, x1, y1], as shares of the page, in reading order. The gutter
    colour is read off the page's edge. Dark or coloured gutters: the page is cut along rows
    or columns that are nearly all gutter, and each piece again, until a piece has none (an XY
    cut). White paper: _paper_panels."""
    r = PANEL_SIDE / max(img.size)
    y = np.asarray(ImageOps.grayscale(img).resize((max(1, round(img.width * r)), max(1, round(img.height * r)))),
                   dtype=np.float32)
    h, w = y.shape
    edge = np.concatenate([y[:3].ravel(), y[-3:].ravel(), y[:, :3].ravel(), y[:, -3:].ravel()])
    ground = float(np.median(edge)) if float(np.percentile(np.abs(edge - np.median(edge)), 80)) <= GUTTER_LIKE else 255.0
    gutter = np.abs(y - ground) <= GUTTER_LIKE
    if ground >= PAPER:
        return _paper_panels(gutter)
    found = []

    def runs(line: np.ndarray) -> list[tuple[int, int]]:
        """Spans of line that are gutter, at least GUTTER_MIN long."""
        out, start = [], None
        for i, g in enumerate(list(line) + [False]):
            if g and start is None:
                start = i
            elif not g and start is not None:
                if i - start >= GUTTER_MIN:
                    out.append((start, i))
                start = None
        return out

    def cut(x0, y0, x1, y1, depth):
        part = gutter[y0:y1, x0:x1]
        rows, cols = part.mean(1) >= GUTTER_SHARE, part.mean(0) >= GUTTER_SHARE
        # The piece without the gutter around it.
        keep_r, keep_c = np.nonzero(~rows)[0], np.nonzero(~cols)[0]
        if not len(keep_r) or not len(keep_c):
            return
        x0, x1, y0, y1 = x0 + keep_c[0], x0 + keep_c[-1] + 1, y0 + keep_r[0], y0 + keep_r[-1] + 1
        part = gutter[y0:y1, x0:x1]
        if depth < 8:
            for axis in (0, 1):    # rows first: a page reads top to bottom, then left to right
                line = part.mean(1 - axis) >= GUTTER_SHARE
                gaps = runs(line)
                if gaps:
                    edges = [0] + [v for g in gaps for v in g] + [len(line)]
                    for a, b in zip(edges[::2], edges[1::2]):
                        if b > a:
                            cut(x0, y0 + a, x1, y0 + b, depth + 1) if axis == 0 else cut(x0 + a, y0, x0 + b, y1, depth + 1)
                    return
        if (x1 - x0) * (y1 - y0) >= PANEL_MIN * h * w:
            found.append([x0 / w, y0 / h, x1 / w, y1 / h])

    cut(0, 0, w, h, 0)
    return [[round(v, 4) for v in b] for b in found]


def _paper_panels(paper: np.ndarray) -> list[list[float]]:
    """On white paper: the panels are what the paper reaching in from the page's edge goes
    around. (Cutting along mostly-white rows would also cut through white things in a panel.)"""
    from PIL import ImageDraw
    h, w = paper.shape
    fill = Image.fromarray(np.pad(paper, 1, constant_values=True).astype(np.uint8) * 255).copy()   # own memory
    ImageDraw.floodfill(fill, (0, 0), 128)
    label = Image.fromarray((np.asarray(fill) != 128)[1:-1, 1:-1].astype(np.uint8) * 255).copy()
    boxes, value = [], 1
    for yy in range(0, h, 4):
        for xx in range(0, w, 4):
            if label.getpixel((xx, yy)) != 255:
                continue
            ImageDraw.floodfill(label, (xx, yy), value)
            ys, xs = np.nonzero(np.asarray(label) == value)
            if len(xs) >= PANEL_MIN * h * w:
                boxes.append([xs.min() / w, ys.min() / h, (xs.max() + 1) / w, (ys.max() + 1) / h])
            value = value % 254 + 1
    rows = sorted(boxes, key=lambda b: (round(b[1] * 8), b[0]))
    return [[round(v, 4) for v in b] for b in rows]


def add_panels(meta: dict, out_dir: Path) -> dict:
    """meta with "panels": {"N": boxes} for each of its pages (counted from 1), and "thumbs":
    small copies of the pages (thumb-N.jpg beside them) for the reader's grid and the list."""
    panels, thumbs = {}, []
    for n, page in enumerate(meta.get("pages") or [], 1):
        path = out_dir / page
        try:
            with Image.open(path) as im:
                img = im.convert("RGB")
        except OSError:
            panels[str(n)] = []
            thumbs.append(page)
            continue
        panels[str(n)] = find_panels(img)
        img.thumbnail((THUMB, THUMB * 2))
        thumb = path.with_name(f"thumb-{n}.jpg")
        img.save(thumb, quality=82)
        thumbs.append(str(thumb.relative_to(out_dir)))
    return meta | {"panels": panels, "thumbs": thumbs}


def _clip_size(w: int, h: int) -> tuple[int, int]:
    r = (AREA / (w * h)) ** 0.5
    return max(256, round(w * r / 16) * 16), max(256, round(h * r / 16) * 16)


# What the person says moves, to an act's motion LoRA (motion.ACTS by name).
SAID_ACTS = ((r"squirt|female ejaculation", "squirt"), (r"blow ?job|suck|fellat|deepthroat", "blowjob"), (r"reverse cowgirl", "reverse cowgirl"),
             (r"\bri(d|de|des|ding)\b|cowgirl|bounc", "cowgirl"), (r"lick(ing)? (her|pussy)|cunnilingus|eat(ing)? (her )?out", "cunnilingus"),
             (r"\bkiss", "kissing"), (r"finger", "fingering"), (r"scissor|tribad", "scissoring"),
             (r"dildo|toy", "toy"), (r"doggy|from behind", "doggy"), (r"missionary", "missionary"))

# Who's in the panel, as the person says (the tagger misreads close-ups: a hand and a crotch can
# come out "2boys, bara"): their tags replace whatever it said about who's there.
CASTS = {"woman": "1girl, solo focus, female", "women": "2girls, yuri", "woman and man": "1girl, 1boy, hetero",
         "man": "1boy, solo focus, male", "men": "2boys, yaoi"}
WHO_TAGS = {"1girl", "2girls", "3girls", "multiple girls", "1boy", "2boys", "3boys", "multiple boys", "solo", "solo focus",
            "male focus", "female focus", "yaoi", "yuri", "hetero", "bara", "muscular male", "mature male", "mature female",
            "furry male", "furry female", "male", "female", "androgynous", "trap", "otoko no ko", "futanari"}


def _act(tags: list[str], said: str):
    """The act whose motion LoRA moves this panel: what the person said first, then the tags,
    then plain thrusting if there's sex in it."""
    import re
    from . import motion
    by_name = {a.name: a for a in (*motion.ACTS, *motion.CLIMAXES.values())}
    for pattern, name in SAID_ACTS:
        if re.search(pattern, said, re.I) and name in by_name:
            return by_name[name]
    if set(tags) & set(motion.SQUIRT.tags):
        return motion.SQUIRT
    act = motion.act_for(tags)
    if act:
        return act
    if set(tags) & motion.SEX or re.search(r"thrust|penetrat|fuck|pound|in and out", said, re.I):
        return motion.Act("thrusting", "", (), "he thrusts in and out of her in a steady rhythm, their bodies rocking with each thrust")
    return None


def _loop(frames: np.ndarray) -> np.ndarray:
    """A clip's frames made into a loop without a jump: the longest-lasting cycle in it (two
    frames at least LOOP_MIN apart that look alike, as in thrusting), its last frames blended
    into its first; if nothing comes back close, forward then backward. The first frames are
    skipped: the clip settles there from the drawing."""
    small = np.stack([np.asarray(Image.fromarray(f).resize((96, 96)), dtype=np.float32) for f in frames])
    best = None
    for i in range(SETTLE, min(SETTLE + 12, len(frames) - LOOP_MIN)):
        far = np.abs(small[i + LOOP_MIN:] - small[i]).mean(axis=(1, 2, 3))
        for k in np.argsort(far)[:3]:
            j = i + LOOP_MIN + int(k)
            score = far[k] - 0.02 * (j - i)        # alike first, then longer
            if far[k] <= LOOP_CLOSE and (best is None or score < best[0]):
                best = (score, i, j)
    if best:
        _, i, j = best
        out = frames[i:j].astype(np.float32)
        blend = min(BLEND, (j - i) // 3)
        for t in range(blend):   # the last frames fade into the first ones
            k = (t + 1) / (blend + 1)
            out[-blend + t] = out[-blend + t] * (1 - k) + frames[i + t] * k
        return out.clip(0, 255).astype(np.uint8)
    return np.concatenate([frames[SETTLE:], frames[-2:SETTLE:-1]])


def _write(frames: np.ndarray, path: Path, fps: int) -> None:
    import subprocess
    h, w = frames.shape[1:3]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps),
                    "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-movflags", "+faststart", str(path)],
                   input=frames.tobytes(), check=True, timeout=300)


def _region(box: list[float], outline: list) -> list[float]:
    """The panel, grown to take in outlines reaching past it."""
    if not outline:
        return box
    xs = [x for loop in outline for x, _ in loop] + [box[0], box[2]]
    ys = [y for loop in outline for _, y in loop] + [box[1], box[3]]
    return [max(0.0, min(xs)), max(0.0, min(ys)), min(1.0, max(xs)), min(1.0, max(ys))]


def _mask(outline: list, region: list[float], size: tuple[int, int]) -> Image.Image:
    """What moves (255) at size, from loops in page shares, widened by GROW and softened."""
    w, h = size
    x0, y0, x1, y1 = region
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    for loop in outline:
        d.polygon([((x - x0) / (x1 - x0) * w, (y - y0) / (y1 - y0) * h) for x, y in loop], fill=255)
    grow = max(1, round(GROW * max(size)))
    m = m.filter(ImageFilter.MaxFilter(2 * grow + 1))
    return m.filter(ImageFilter.GaussianBlur(max(1, FEATHER * max(size))))


def animate_panel(cfg, folder: Path, meta: dict, page: int, box: list[float], motion_text: str,
                  strict: bool, progress=lambda phase, done, total: None, cast: str = "",
                  outline: list | None = None) -> dict:
    """The clip for one panel; returns its entry for meta["animations"]. outline: loops (page
    shares) around what moves; the rest stays as drawn."""
    from . import motion, safety
    from .comfy import Comfy
    from .generate import MOTION
    from .scene import _check_shots, _frames
    from .vision import Vision
    gen = cfg.generation()
    out_dir = cfg.data_dir / "generated"
    medium = meta.get("medium") or "furry"
    with Image.open(out_dir / meta["pages"][page - 1]) as im:
        img = im.convert("RGB")
    box = _region(box, outline or [])
    x0, y0, x1, y1 = (round(v * s) for v, s in zip(box, (img.width, img.height, img.width, img.height)))
    if x1 - x0 < 64 or y1 - y0 < 64:
        raise ValueError("that panel is too small to animate")
    panel = img.crop((x0, y0, x1, y1))
    # Never reused (the reader's cached copy of a clip is kept by its name).
    n = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    still = folder / f"panel-{page}-{n}.png"
    panel.save(still)
    progress("reading the panel", 0, 1)
    vision = Vision(cfg.models_dir)
    try:
        seen = vision.analyze([panel]).general
    finally:
        vision.close()
    tags = [t for t, s in sorted(seen.items(), key=lambda kv: -kv[1]) if s >= 0.35][:25]
    if cast in CASTS:
        tags = [t.strip() for t in CASTS[cast].split(",")] + [t for t in tags if t not in WHO_TAGS]
    said = motion_text.strip()
    act = _act(tags, said)
    use_lora = motion.lora_for(act, gen.act_lora, cfg.models_dir) if act else None
    # Asked-for or act motion leads; "subtle" only when nothing moves on its own.
    lead = [said, act.motion if act else ""] if (said or act) else [IDLE_MOTION]
    prompt = ", ".join(p for p in [act.trigger if use_lora and act else "", *lead, LOOP_WORDS, ", ".join(tags),
                                   MOTION.get(medium, "")] if p)
    print(f"comicanim: page {page}, act {act.name if act else None}, lora {bool(use_lora)}: {prompt[:200]}", flush=True)
    w, h = _clip_size(*panel.size)
    progress("animating", 0, 1)
    comfy = Comfy(gen.comfy_url, gen.supervisor_url, out_dir)
    try:
        path = comfy.img2vid(still, medium, prompt, random.Random().randrange(2 ** 32), str(folder.relative_to(out_dir)),
                             f"anim-{page}-{n}", strict=strict, loras=[use_lora] if use_lora else [],
                             wan=LOOP | {"width": w, "height": h})
    finally:
        comfy.stop()
        still.unlink(missing_ok=True)
    progress("checking the clip", 0, 1)
    frames = _frames(path)
    path.unlink(missing_ok=True)
    reason = _check_shots(cfg, {0: frames}, {"medium": medium, "strict": strict}).get(0)
    if reason:
        print(f"comicanim: page {page} dropped: {reason[0]}: {reason[1]}", flush=True)
        raise RuntimeError(f"Dropped by the safety checks: {safety.explain(*reason)}. Every try is drawn anew, so "
                           "trying again (or describing the motion differently) can pass; otherwise pick another panel.")
    looped = _loop(frames)
    entry = {}
    if outline:   # only what was outlined moves; the rest is the drawing
        size = (looped.shape[2], looped.shape[1])
        m = _mask(outline, box, size)
        still = np.asarray(panel.resize(size, Image.LANCZOS), np.float32)
        a = np.asarray(m, np.float32)[None, ..., None] / 255
        looped = (looped.astype(np.float32) * a + still[None] * (1 - a)).round().clip(0, 255).astype(np.uint8)
        mask_file = folder / f"anim-{page}-{n}-mask.png"
        Image.merge("RGBA", (*Image.new("RGB", size, (255, 255, 255)).split(), m)).save(mask_file)
        entry["mask"] = str(mask_file.relative_to(out_dir))
    dest = folder / f"anim-{page}-{n}.mp4"
    _write(looped, dest, LOOP_FPS)
    moved = float(np.abs(np.diff(frames.astype(np.float32), axis=0)).mean())
    print(f"comicanim: {dest.name}: {len(looped)} frames, motion {moved:.2f}", flush=True)
    return {"page": page, "box": box, "file": str(dest.relative_to(out_dir)), "motion": said, "cast": cast} | entry


def run_job(cfg, conn, job_id: int, params: dict) -> None:
    """{"kind": "comic_animate", "id": the comic's generations row, "page", "box", "motion", "cast",
    "outline"}."""
    from .comicimport import _job
    out_dir = cfg.data_dir / "generated"

    def work(progress):
        row = conn.execute("SELECT g.file, coalesce(p.strict, 1), g.medium FROM generations g"
                           " LEFT JOIN personas p ON p.handle = g.persona"
                           " WHERE g.id = ? AND g.kind = 'comic' AND g.status = 'comic'", (params["id"],)).fetchone()
        if not row:
            raise RuntimeError("that comic isn't there any more")
        folder = (out_dir / row[0]).parent
        meta = json.loads((folder / "comic.json").read_text())
        meta.setdefault("medium", row[2])
        # Imported comics get the stricter adult checks; a comic made here, its persona's.
        strict = True if meta.get("imported") else bool(row[1])
        entry = animate_panel(cfg, folder, meta, int(params["page"]), params["box"], params.get("motion", ""),
                              strict, progress, params.get("cast", ""), params.get("outline"))
        meta = json.loads((folder / "comic.json").read_text())   # read again: it may have changed meanwhile
        meta["animations"] = (meta.get("animations") or []) + [entry]
        (folder / "comic.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
        return f"page {entry['page']} animated"

    _job(conn, job_id, f"comicanim-{job_id}", work)


def main(args: list[str]) -> None:
    """comic-panels: panels and thumbnails for the comics saved before they were kept."""
    import sqlite3
    from .config import Config
    cfg = Config()
    out_dir = cfg.data_dir / "generated"
    conn = sqlite3.connect(cfg.db_path)
    done = 0
    for (file,) in conn.execute("SELECT file FROM generations WHERE kind = 'comic' AND status LIKE 'comic%'"):
        path = (out_dir / file).parent / "comic.json"
        try:
            meta = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if "thumbs" in meta and "--again" not in args:
            continue
        path.write_text(json.dumps(add_panels(meta, out_dir), ensure_ascii=False, indent=1))
        done += 1
    print(f"comic-panels: {done} comics")
    sys.exit(0)
