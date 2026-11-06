"""Black-and-white comic pages coloured from their colour cover.

    python -m dreamfeed colorize --cover COVER.png PAGE.png... --medium furry --out DIR   (a test)

The dashboard's Comics page queues an import as a job (kind "comic_import"):
1. The pages are downloaded (gallery-dl, any gallery it reads, in the gallery's order) and each
   goes through the adults-only checks (checks.problem, strict). Pages that fail are dropped;
   if more than MAX_DROPPED of them fail, the import stops: it isn't a comic to keep.
2. Colour pages and black-and-white ones are told apart by their saturation. The cover is the
   most colourful page (or --cover N, counting from 1).
3. Each black-and-white page is drawn again in colour by the image model, held to the page's
   own lines (ControlNet, line-art mode), shown the cover (IP-Adapter: the characters' colours),
   and told what the page shows (its tags), starting from the page itself. It's drawn at about a
   megapixel in the page's shape and scaled back up; only its hues are kept, over the page's own
   brightness, so the artist's lines, shading and lettering stay exactly as they were (and the
   margins white). The coloured page is checked again.
4. The comic is saved like the comics made here (generated/comic-import-.../comic.json), with
   the original pages kept beside the coloured ones for the reader's switch.
"""
import argparse
import datetime as dt
import json
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

COLOUR = 0.12          # mean HSV saturation above which a page is in colour
MAX_DROPPED = 0.2      # share of pages that may fail the checks before the import stops
PIXELS = 1024 * 1024   # the size pages are coloured at
LINES = 0.85           # ControlNet strength: the drawing stays the artist's
REFERENCE = (0.7, "linear")   # IP-Adapter weight and type: the cover's colours come from here
PAPER = 240                   # page brightness of paper
INK, INK_DARK = 25, 70         # ink (no colour) below INK, full colour above INK_DARK
DENOISE = 0.85                # the page is redrawn from itself in grey, not from noise
TAG_MIN = 0.35
NOT_COLOUR = {"monochrome", "greyscale", "lineart", "sketch", "black and white", "spot color",
              "partially colored", "halftone", "screentones"}
NEGATIVE = ", ".join(sorted(NOT_COLOUR)) + ", blurry, rainbow, neon"
COLOUR_WORDS = ("hair", "eyes", "fur", "skin", "body", "clothes", "shirt", "dress", "skirt", "jacket",
                "pants", "shorts", "thighhighs", "socks", "gloves", "bikini", "swimsuit", "panties", "bra")
IMAGES = (".png", ".jpg", ".jpeg", ".webp")
COLOURS = ("red", "orange", "yellow", "green", "blue", "purple", "pink", "brown", "black", "white",
           "grey", "gray", "blonde", "silver", "aqua")


def saturation(img: Image.Image) -> float:
    return float(np.asarray(img.convert("HSV"), dtype=np.float32)[:, :, 1].mean() / 255)


def line_art(page: Image.Image, size: tuple[int, int]) -> Image.Image:
    """White lines on black, the page's size scaled to size: what ControlNet's line-art mode takes."""
    grey = ImageOps.grayscale(page).resize(size, Image.LANCZOS)
    grey = ImageOps.autocontrast(grey, cutoff=1)
    return ImageOps.invert(grey).convert("RGB")


def _size(page: Image.Image) -> tuple[int, int]:
    r = (PIXELS / (page.width * page.height)) ** 0.5
    return max(512, round(page.width * r / 64) * 64), max(512, round(page.height * r / 64) * 64)


def page_prompt(general: dict) -> str:
    """What a black-and-white page shows: its own tags, less the ones saying it's black and white
    and its colours (a grey page's "grey hair" is wrong). The cover's colours aren't named either:
    a list of them lands on whoever, so they come from the cover picture itself (IP-Adapter)."""
    from . import safety
    tags = [t for t, s in sorted(general.items(), key=lambda kv: -kv[1])
            if s >= TAG_MIN and t not in NOT_COLOUR and not safety.blocked(t) and not _colour(t)][:30]
    return ", ".join(["masterpiece, best quality, full color, comic"] + tags)


def _colour(tag: str) -> bool:
    return tag.split(" ")[0] in COLOURS and tag.split(" ")[-1] in COLOUR_WORDS


def colour_page(comfy, checkpoint: str, page: Image.Image, prompt: str, cover: Path, medium: str,
                subdir: str, name: str, rng: random.Random) -> Image.Image:
    """page in colour: the model's colours with the original page laid over them."""
    size = _size(page)
    tmp = Path(tempfile.mkdtemp(prefix="lines-"))
    try:
        lines_path, init = tmp / "lines.png", tmp / "page.png"
        line_art(page, size).save(lines_path)
        page.resize(size, Image.LANCZOS).save(init)
        path = comfy.txt2img(checkpoint, medium, prompt, rng.randrange(2 ** 32), subdir, name,
                             strict=True, extra_negative=NEGATIVE, init=init, denoise=DENOISE,
                             reference=(cover, *REFERENCE), control=(lines_path, LINES), size=size)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    with Image.open(path) as im:
        colours = im.convert("RGB").resize(page.size, Image.LANCZOS)
    path.unlink(missing_ok=True)
    return blend(page, colours)


def blend(page: Image.Image, colours: Image.Image) -> Image.Image:
    """The page's own brightness (its lines, shading and lettering, exactly) with the model's
    hues. Ink stays black, and the paper around the panels (margins, gutters) stays white. White
    inside the panels takes colour: in black and white, skin and fur are often bare paper."""
    y = np.asarray(ImageOps.grayscale(page), dtype=np.float32)
    _, cb, cr = (np.asarray(c, dtype=np.float32) for c in colours.convert("YCbCr").split())
    keep = np.clip((y - INK) / (INK_DARK - INK), 0, 1) * ~_margins(y)
    cb, cr = 128 + (cb - 128) * keep, 128 + (cr - 128) * keep
    out = np.stack([y, cb, cr], axis=-1).clip(0, 255).astype(np.uint8)
    return Image.fromarray(out, "YCbCr").convert("RGB")


def _margins(y: np.ndarray) -> np.ndarray:
    """The paper joined to the page's edge: near-white pixels reachable from outside the page."""
    from PIL import ImageDraw
    light = Image.fromarray(np.pad((y >= PAPER) * 255, 1, constant_values=255).astype(np.uint8))
    ImageDraw.floodfill(light, (0, 0), 128)
    return (np.asarray(light) == 128)[1:-1, 1:-1]


def _download(url: str, folder: Path) -> list[Path]:
    """The gallery's images, in its order."""
    from .styles import COOKIES, COOKIE_HOSTS
    folder.mkdir(parents=True, exist_ok=True)
    conf = {"extractor": {"directory": [], "base-directory": str(folder), "filename": "{num:>04}_{filename}.{extension}",
                          "cookies-update": False}, "downloader": {"part-directory": str(folder / ".part")}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(conf, f)
    cmd = ["gallery-dl", "--config-ignore", "--config", f.name, "--range", "1-200",
           "--filter", "extension in ('jpg', 'jpeg', 'png', 'webp')"]
    host = url.split("/")[2].lower() if url.count("/") >= 2 else ""
    if host.removeprefix("www.").removeprefix("mobile.") in COOKIE_HOSTS and COOKIES.is_file():
        cmd += ["--cookies", str(COOKIES)]
    subprocess.run(cmd + [url], capture_output=True, text=True, timeout=3600)
    Path(f.name).unlink(missing_ok=True)
    shutil.rmtree(folder / ".part", ignore_errors=True)
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGES)


def colorize(cfg, pages: list[Path], medium: str, folder: Path, cover_index: int | None = None,
             progress=lambda phase, done, total: None) -> dict:
    """Check pages, pick the cover, colour the black-and-white ones. Returns the comic's meta
    (paths under generated/): {"pages": in order, coloured where it was black and white,
    "originals", "cover", "dropped"}. The tagger and the image model take turns on the GPU."""
    from .checks import problem
    from .comfy import Comfy
    from .vision import Vision
    gen = cfg.generation()
    out_dir = cfg.data_dir / "generated"
    rng = random.Random()
    # 1. Checks and tags.
    kept, dropped = [], 0      # (path, saturation, tags)
    vision = Vision(cfg.models_dir)
    try:
        for n, p in enumerate(pages):
            progress("checking the pages", n, len(pages))
            with Image.open(p) as im:
                img = im.convert("RGB")
            a = vision.analyze([img])
            if problem(a, medium, [img], cfg, strict=True):
                dropped += 1
                p.unlink(missing_ok=True)
                continue
            kept.append((p, saturation(img), a.general))
    finally:
        vision.close()
    if not kept or dropped > MAX_DROPPED * len(pages):
        raise RuntimeError(f"{dropped} of {len(pages)} pages failed the checks; not imported")
    if cover_index:
        cover = kept[min(cover_index, len(kept)) - 1]
    elif any(k[1] >= COLOUR for k in kept):
        cover = max(kept, key=lambda k: k[1])
    else:
        raise RuntimeError("no page is in colour to colour the others from")
    print(f"colorize: cover {cover[0].name}", flush=True)
    # 2. Colour.
    bw = [k for k in kept if k[1] < COLOUR and k is not cover]
    coloured = {}
    comfy = Comfy(gen.comfy_url, gen.supervisor_url, out_dir)
    try:
        for n, (p, _, general) in enumerate(bw):
            progress("colouring", n, len(bw))
            with Image.open(p) as im:
                img = im.convert("RGB")
            out = colour_page(comfy, gen.checkpoints[medium], img, page_prompt(general), cover[0],
                              medium, str(folder.relative_to(out_dir)), f"col-{p.stem}", rng)
            dest = p.with_name(f"{p.stem}-colour.jpg")
            out.save(dest, quality=92)
            coloured[p] = dest
    finally:
        comfy.stop()
    # 3. The coloured pages are checked again; one that fails stays as it was drawn.
    vision = Vision(cfg.models_dir)
    try:
        for n, (p, dest) in enumerate(list(coloured.items())):
            progress("checking the colours", n, len(coloured))
            with Image.open(dest) as im:
                img = im.convert("RGB")
            if problem(vision.analyze([img]), medium, [img], cfg, strict=True):
                print(f"colorize: {p.name} failed a check in colour; kept as drawn", flush=True)
                dest.unlink(missing_ok=True)
                del coloured[p]
    finally:
        vision.close()
    rel = lambda p: str(p.relative_to(out_dir))
    return {"pages": [rel(coloured.get(p, p)) for p, _, _ in kept], "originals": [rel(p) for p, _, _ in kept],
            "cover": rel(cover[0]), "dropped": dropped}


def run_job(cfg, conn, job_id: int, params: dict) -> None:
    """An import queued from the Comics page: {"kind": "comic_import", "url", "title", "medium", "cover"}."""
    from .generate import _progress, _set
    night = f"comicimport-{job_id}"
    folder = cfg.data_dir / "generated" / f"comic-import-{dt.datetime.now():%Y%m%d-%H%M%S}"
    with conn:
        conn.execute("UPDATE jobs SET status = 'running', night = ? WHERE id = ?", (night, job_id))
        conn.execute("INSERT INTO runs(night, status, attempts, started_at) VALUES (?, 'running', 1, datetime('now'))",
                     (night,))
    status, message = "done", None
    try:
        _progress(conn, night, "downloading", 0, 1)
        pages = _download(params["url"], folder)
        if not pages:
            raise RuntimeError("nothing downloaded from that link")
        meta = colorize(cfg, pages, params.get("medium", "furry"), folder, params.get("cover"),
                        progress=lambda phase, d, t: _progress(conn, night, phase, d, t))
        meta |= {"title": params.get("title") or "Imported comic", "source": params["url"], "imported": True,
                 "cast": []}
        (folder / "comic.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
        with conn:
            gid = conn.execute(
                "INSERT INTO generations(night, medium, checkpoint, prompt, seed, caption, kind, status, file)"
                " VALUES (?, ?, 'comic import', ?, 0, ?, 'comic', 'comic', ?)",
                (night, params.get("medium", "furry"), params["url"], meta["title"], meta["pages"][0])).lastrowid
        _set(conn, gid, posted_at=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
        message = f"{len(meta['pages'])} pages, {meta['dropped']} dropped by the checks"
    except Exception as e:
        status, message = "failed", str(e)[:300]
        print(f"colorize: job {job_id} failed: {message}", flush=True)
        shutil.rmtree(folder, ignore_errors=True)
    finally:
        with conn:
            conn.execute("UPDATE runs SET status = ?, progress = NULL, finished_at = datetime('now') WHERE night = ?",
                         (status, night))
            conn.execute("UPDATE jobs SET status = ?, message = ?, finished_at = datetime('now') WHERE id = ?",
                         (status, message, job_id))


def main(args: list[str]) -> None:
    """colorize --cover C PAGE... --medium M --out DIR: colour pages from a cover (a test)."""
    from .config import Config
    ap = argparse.ArgumentParser(prog="dreamfeed colorize")
    ap.add_argument("pages", nargs="+")
    ap.add_argument("--cover", required=True)
    ap.add_argument("--medium", default="furry")
    ap.add_argument("--out", required=True, help="a folder under data/generated")
    a = ap.parse_args(args)
    cfg = Config()
    folder = Path(a.out)
    folder.mkdir(parents=True, exist_ok=True)
    pages = []
    for i, p in enumerate([a.cover] + a.pages):
        dest = folder / f"{i:04d}_{Path(p).stem}{Path(p).suffix}"
        shutil.copy(p, dest)
        pages.append(dest)
    meta = colorize(cfg, pages, a.medium, folder, cover_index=1)
    print(json.dumps(meta, indent=1))
    sys.exit(0)
