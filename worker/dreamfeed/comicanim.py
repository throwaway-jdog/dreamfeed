"""A comic panel animated: a short seamless loop, the way comic artists animate a panel.

    python -m dreamfeed comic-panels            find the panels of comics saved before panels were kept

The reader's "Animate a panel" queues a job (kind "comic_animate") for one panel of one page:
the panel is cut out of the page, Wan 2.2 animates it for about three seconds ending on the
same picture it started from (so it loops without a jump), the clip gets the video checks
(every sampled frame, and no drifting away from the panel), and it's kept beside the comic.
The reader plays it over its panel, looping.

Panels are found once, when a comic is saved: the page is cut along its gutters (whatever their
colour). Panels with no gutter between them come out as one; the reader lets the person draw
the box instead.
"""
import json
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

PANEL_SIDE = 1000       # pages are searched for panels at this long side
PANEL_MIN = 0.02        # a panel is at least this share of the page
PAPER = 200             # a page edge this bright is paper (see _paper_panels)
GUTTER_LIKE = 28        # this close in grey to the page's edge is gutter
GUTTER_SHARE = 0.8      # a row or column this much gutter is a gutter (a bubble or tail may cross it)
GUTTER_MIN = 2          # pixels (at PANEL_SIDE) a gutter is at least
LOOP = {"frames": 49}   # about three seconds at Wan's 16 fps
AREA = 480 * 704        # the clip's pixels (Wan's usual size), in the panel's shape
LOOP_MOTION = "subtle looping animation, small natural movements, gentle breathing, blinking, hair swaying, still camera"


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
    """meta with "panels": {"N": boxes} for each of its pages (counted from 1)."""
    panels = {}
    for n, page in enumerate(meta.get("pages") or [], 1):
        try:
            with Image.open(out_dir / page) as im:
                panels[str(n)] = find_panels(im.convert("RGB"))
        except OSError:
            panels[str(n)] = []
    return meta | {"panels": panels}


def _clip_size(w: int, h: int) -> tuple[int, int]:
    r = (AREA / (w * h)) ** 0.5
    return max(256, round(w * r / 16) * 16), max(256, round(h * r / 16) * 16)


def animate_panel(cfg, folder: Path, meta: dict, page: int, box: list[float], motion_text: str,
                  strict: bool, progress=lambda phase, done, total: None) -> dict:
    """The clip for one panel; returns its entry for meta["animations"]."""
    from . import motion
    from .comfy import Comfy
    from .generate import MOTION
    from .scene import _check_shots, _frames
    from .vision import Vision
    gen = cfg.generation()
    out_dir = cfg.data_dir / "generated"
    medium = meta.get("medium") or "furry"
    with Image.open(out_dir / meta["pages"][page - 1]) as im:
        img = im.convert("RGB")
    x0, y0, x1, y1 = (round(v * s) for v, s in zip(box, (img.width, img.height, img.width, img.height)))
    if x1 - x0 < 64 or y1 - y0 < 64:
        raise ValueError("that panel is too small to animate")
    panel = img.crop((x0, y0, x1, y1))
    n = len(meta.get("animations") or []) + 1
    still = folder / f"panel-{page}-{n}.png"
    panel.save(still)
    progress("reading the panel", 0, 1)
    vision = Vision(cfg.models_dir)
    try:
        seen = vision.analyze([panel]).general
    finally:
        vision.close()
    tags = [t for t, s in sorted(seen.items(), key=lambda kv: -kv[1]) if s >= 0.35][:25]
    act = motion.act_for(tags)
    use_lora = motion.lora_for(act, gen.act_lora, cfg.models_dir) if act else None
    prompt = ", ".join(p for p in (act.trigger if use_lora else "", motion_text.strip(), LOOP_MOTION,
                                   act.motion if act else "", ", ".join(tags), MOTION.get(medium, "")) if p)
    w, h = _clip_size(*panel.size)
    progress("animating", 0, 1)
    comfy = Comfy(gen.comfy_url, gen.supervisor_url, out_dir)
    try:
        path = comfy.img2vid(still, medium, prompt, random.Random().randrange(2 ** 32), str(folder.relative_to(out_dir)),
                             f"anim-{page}-{n}", strict=strict, loras=[use_lora] if use_lora else [],
                             end=still, wan=LOOP | {"width": w, "height": h})
    finally:
        comfy.stop()
        still.unlink(missing_ok=True)
    progress("checking the clip", 0, 1)
    reason = _check_shots(cfg, {0: _frames(path)}, {"medium": medium, "strict": strict}).get(0)
    if reason:
        path.unlink(missing_ok=True)
        raise RuntimeError(f"the clip failed a check ({reason[0]}): try again, or another panel")
    dest = folder / f"anim-{page}-{n}.mp4"
    path.replace(dest)
    return {"page": page, "box": box, "file": str(dest.relative_to(out_dir)), "motion": motion_text.strip()}


def run_job(cfg, conn, job_id: int, params: dict) -> None:
    """{"kind": "comic_animate", "id": the comic's generations row, "page", "box", "motion"}."""
    from .colorize import _job
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
                              strict, progress)
        meta = json.loads((folder / "comic.json").read_text())   # read again: it may have changed meanwhile
        meta["animations"] = (meta.get("animations") or []) + [entry]
        (folder / "comic.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
        return f"page {entry['page']} animated"

    _job(conn, job_id, f"comicanim-{job_id}", work)


def main(args: list[str]) -> None:
    """comic-panels: panels for the comics saved before they were kept."""
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
        if "panels" in meta and "--again" not in args:
            continue
        path.write_text(json.dumps(add_panels(meta, out_dir), ensure_ascii=False, indent=1))
        done += 1
    print(f"comic-panels: {done} comics")
    sys.exit(0)
