"""Black-and-white comic pages coloured from their colour cover.

    python -m dreamfeed colorize --cover COVER.png PAGE.png... --medium furry --out DIR   (a test)

The dashboard's Comics page queues an import as a job (kind "comic_import"):
1. The pages are downloaded (gallery-dl, any gallery it reads, in the gallery's order) and each
   goes through the adults-only checks (checks.problem, strict). Pages that fail are dropped;
   if more than MAX_DROPPED of them fail, the import stops: it isn't a comic to keep.
2. Colour pages and black-and-white ones are told apart by their saturation. The cover is the
   most colourful page (or --cover N, counting from 1).
3. Each black-and-white page gets a colour hint from the colour pages: every patch of the page
   is matched to the most alike patches of the colour pages (DINOv2 features of both in grey,
   with their surroundings, about as bright once the colour pages' greys are spread like the
   page's) and takes their colour; bare paper inside the panels takes their brightness too
   (skin and fur are often left white in black and white). Matching by what's drawn is what
   gets each character her own colours; a cover shown whole to the image model (IP-Adapter)
   or a list of colour tags put them on whoever.
4. The image model redraws the hint (img2img, about half of it), held to the page's own lines
   (ControlNet, line-art mode) and told what the page shows (its tags): clean colours that
   follow the drawing. Then the artist's page goes back on top: its brightness everywhere but
   bare paper inside the panels, the model's hues except on ink and the margins, so lines,
   shading and lettering are exactly as drawn. The coloured page is checked again.
5. The comic is saved like the comics made here (generated/comic-import-.../comic.json), with
   the original pages kept beside the coloured ones for the reader's switch.
"""
import argparse
import datetime as dt
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

COLOUR = 0.12          # mean HSV saturation above which a page is in colour
MAX_PAGES = 200
MAX_DROPPED = 0.2      # share of pages that may fail the checks before the import stops
PIXELS = 1024 * 1024   # the size pages are coloured at
LINES = 0.85           # ControlNet strength: the drawing stays the artist's
PAPER = 240                   # page brightness of paper
INK, INK_DARK = 25, 70         # ink (no colour) below INK, full colour above INK_DARK
HINT_SLACK = 15               # how much darker than the hint bare paper may come out
HINT_COLOURED = 12            # hint chroma at which bare paper takes the colours' full shade
DENOISE = 0.5                 # how much of the colour hint the image model redraws
# Colour hints. Tuned on a page of ours turned grey (and hard-inked), scored against its own
# colours: about 90% (grey) and 75% (inked) of its coloured parts got the right colour, where
# the cover through IP-Adapter got 5%.
DINO = "timm/vit_base_patch14_dinov2.lvd142m@4685c99dabffe5affac90bd99dbffd25801ae58d"   # pinned
MATCH_SIDE = 896       # long side the pages are matched at (64 patches)
NEAREST, SHARPNESS = 8, 0.03   # colour from the 8 most alike patches, softmax temperature
AROUND = 4             # patches of surroundings each patch is matched with
SAME_BRIGHTNESS = 0.5  # how much a difference in grey counts against a match
BOOST = 1.5            # matched colours are averages, a little duller than the real ones
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
    and its colours (a grey page's "grey hair" is wrong; the colours come from the hint)."""
    from . import safety
    tags = [t for t, s in sorted(general.items(), key=lambda kv: -kv[1])
            if s >= TAG_MIN and t not in NOT_COLOUR and not safety.blocked(t) and not _colour(t)][:30]
    return ", ".join(["masterpiece, best quality, full color, comic"] + tags)


def _colour(tag: str) -> bool:
    return tag.split(" ")[0] in COLOURS and tag.split(" ")[-1] in COLOUR_WORDS


class Hints:
    """Colour hints for black-and-white pages from the comic's colour pages (see the top)."""

    def __init__(self, colour_pages: list[Image.Image]):
        import timm
        import torch
        self.torch = torch
        self.model = timm.create_model(f"hf-hub:{DINO}", pretrained=True, dynamic_img_size=True).eval().cuda()
        self.refs = colour_pages

    def close(self) -> None:
        del self.model
        self.torch.cuda.empty_cache()

    def _features(self, grey: np.ndarray):
        """(patches x features, normalised; grid (h, w)) of a grey picture."""
        torch, F = self.torch, self.torch.nn.functional
        r = MATCH_SIDE / max(grey.shape)
        h, w = max(1, round(grey.shape[0] * r / 14)), max(1, round(grey.shape[1] * r / 14))
        img = Image.fromarray(grey.clip(0, 255).astype(np.uint8)).convert("RGB").resize((w * 14, h * 14), Image.BICUBIC)
        x = torch.from_numpy(np.asarray(img, dtype=np.float32) / 255)
        x = ((x - torch.tensor([0.485, 0.456, 0.406])) / torch.tensor([0.229, 0.224, 0.225])).permute(2, 0, 1)[None].cuda()
        with torch.no_grad():
            f = F.normalize(self.model.forward_features(x)[0, self.model.num_prefix_tokens:].float(), dim=-1)
        around = F.avg_pool2d(f.T.reshape(1, -1, h, w), 2 * AROUND + 1, 1, AROUND, count_include_pad=False)
        around = F.normalize(around.reshape(f.shape[1], -1).T, dim=-1)
        return F.normalize(torch.cat([f, around], 1), dim=-1), (h, w)

    def hint(self, page: Image.Image) -> Image.Image:
        torch, F = self.torch, self.torch.nn.functional
        y = np.asarray(ImageOps.grayscale(page), dtype=np.float32)
        pf, (h, w) = self._features(y)
        feats, values = [], []      # per reference patch: features; (cb, cr, grey, brightness)
        for ref in self.refs:
            ry = np.asarray(ImageOps.grayscale(ref), dtype=np.float32)
            spread = _match_histogram(ry, y)
            f, (rh, rw) = self._features(spread)
            _, cb, cr = (np.asarray(c, dtype=np.float32) for c in ref.convert("YCbCr").split())
            v = torch.from_numpy(np.stack([cb - 128, cr - 128, spread, ry]))[None]
            values.append(F.adaptive_avg_pool2d(v, (rh, rw))[0].reshape(4, -1).T)
            feats.append(f)
        rf, rv = torch.cat(feats), torch.cat(values).cuda()
        py = F.adaptive_avg_pool2d(torch.from_numpy(y)[None, None], (h, w)).flatten().cuda()
        sim = pf @ rf.T - SAME_BRIGHTNESS * (py[:, None] - rv[None, :, 2]).abs() / 255
        best, which = sim.topk(min(NEAREST, sim.shape[1]), dim=1)
        weight = torch.softmax(best / SHARPNESS, dim=1)
        got = (rv[which] * weight[..., None]).sum(1).T.reshape(4, h, w)
        got = F.interpolate(got[None], size=y.shape, mode="bilinear", align_corners=False)[0].cpu().numpy()
        cb, cr = got[0] * BOOST, got[1] * BOOST
        bright = _guided(y / 255, got[3], 4)
        paper = (y >= PAPER) & ~_margins(y)
        hy = np.where(paper, np.minimum(y, bright), y)
        out = np.stack([hy, cb + 128, cr + 128], axis=-1).clip(0, 255).astype(np.uint8)
        return Image.fromarray(out, "YCbCr").convert("RGB")


def _match_histogram(src: np.ndarray, like: np.ndarray) -> np.ndarray:
    """src's greys spread like like's."""
    order = np.sort(src.ravel())
    q = np.searchsorted(order, src.ravel()) / max(1, order.size - 1)
    return np.interp(q, np.linspace(0, 1, like.size), np.sort(like.ravel())).reshape(src.shape)


def _guided(guide: np.ndarray, src: np.ndarray, r: int, eps: float = 1e-3) -> np.ndarray:
    """src smoothed without crossing guide's edges (a guided filter)."""
    import torch
    import torch.nn.functional as F
    i, p = torch.from_numpy(guide)[None, None], torch.from_numpy(src.astype(np.float32))[None, None]
    box = lambda x: F.avg_pool2d(x, 2 * r + 1, 1, r, count_include_pad=False)
    mi, mp = box(i), box(p)
    a = (box(i * p) - mi * mp) / (box(i * i) - mi * mi + eps)
    return (box(a) * i + box(mp - a * mi))[0, 0].numpy()


def colour_page(comfy, checkpoint: str, page: Image.Image, hint: Image.Image, prompt: str, medium: str,
                subdir: str, name: str, seed: int) -> Image.Image:
    """page in colour: the image model's redrawing of the hint, the page laid over it."""
    size = _size(page)
    tmp = Path(tempfile.mkdtemp(prefix="lines-"))
    try:
        lines_path, init = tmp / "lines.png", tmp / "hint.png"
        line_art(page, size).save(lines_path)
        hint.resize(size, Image.LANCZOS).save(init)
        path = comfy.txt2img(checkpoint, medium, prompt, seed, subdir, name,
                             strict=True, extra_negative=NEGATIVE, init=init, denoise=DENOISE,
                             control=(lines_path, LINES), size=size)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    with Image.open(path) as im:
        colours = im.convert("RGB").resize(page.size, Image.LANCZOS)
    path.unlink(missing_ok=True)
    return blend(page, colours, hint)


def blend(page: Image.Image, colours: Image.Image, hint: Image.Image | None = None) -> Image.Image:
    """The page laid over the colours: its brightness (lines, shading, lettering exactly) except
    on bare paper inside the panels, which keeps the colours' own shade where the hint has a colour
    and no darker than the hint (so the model's own scribbles in a speech bubble don't show); the colours' hues except
    on ink and on the paper around the panels (margins, gutters), which stay black and white."""
    y = np.asarray(ImageOps.grayscale(page), dtype=np.float32)
    cy, cb, cr = (np.asarray(c, dtype=np.float32) for c in colours.convert("YCbCr").split())
    if hint is not None:     # paper is shaded only where the hint has a colour (white stays white)
        hy, hb, hr = (np.asarray(c, dtype=np.float32) for c in hint.resize(page.size, Image.LANCZOS).convert("YCbCr").split())
        tinted = np.clip(np.hypot(hb - 128, hr - 128) / HINT_COLOURED, 0, 1)
        cy = y - (y - np.maximum(cy, hy - HINT_SLACK)) * tinted
    margins = _margins(y)
    paper = (y >= PAPER) & ~margins
    keep = np.clip((y - INK) / (INK_DARK - INK), 0, 1) * ~margins
    out = np.stack([np.where(paper, np.minimum(y, cy), y), 128 + (cb - 128) * keep, 128 + (cr - 128) * keep], axis=-1)
    return Image.fromarray(out.clip(0, 255).astype(np.uint8), "YCbCr").convert("RGB")


def _margins(y: np.ndarray) -> np.ndarray:
    """The paper joined to the page's edge: near-white pixels reachable from outside the page."""
    from PIL import ImageDraw
    light = Image.fromarray(np.pad((y >= PAPER) * 255, 1, constant_values=255).astype(np.uint8)).copy()   # its own memory: floodfill writes to it
    ImageDraw.floodfill(light, (0, 0), 128)
    return (np.asarray(light) == 128)[1:-1, 1:-1]


def _download(url: str, folder: Path) -> list[Path]:
    """The gallery's images, in its order."""
    from .styles import COOKIES, COOKIE_HOSTS
    folder.mkdir(parents=True, exist_ok=True)
    host = url.split("/")[2].lower() if url.count("/") >= 2 else ""
    if host.removeprefix("www.") == "multporn.net":
        return _multporn(url, folder)
    conf = {"extractor": {"directory": [], "base-directory": str(folder), "filename": "{num:>04}_{filename}.{extension}",
                          "cookies-update": False}, "downloader": {"part-directory": str(folder / ".part")}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(conf, f)
    cmd = ["gallery-dl", "--config-ignore", "--config", f.name, "--range", f"1-{MAX_PAGES}",
           "--filter", "extension in ('jpg', 'jpeg', 'png', 'webp')"]
    if host.removeprefix("www.").removeprefix("mobile.") in COOKIE_HOSTS and COOKIES.is_file():
        cmd += ["--cookies", str(COOKIES)]
    subprocess.run(cmd + [url], capture_output=True, text=True, timeout=3600)
    Path(f.name).unlink(missing_ok=True)
    shutil.rmtree(folder / ".part", ignore_errors=True)
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGES)


MULTPORN_PAGES = re.compile(r'configUrl":"([^"]+)"')
MULTPORN_IMAGE = re.compile(r'imageURL="([^"]+)"')
AGENT = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}   # the site turns away scripts' own


def _multporn(url: str, folder: Path) -> list[Path]:
    """A multporn comic (gallery-dl has no extractor for it): the comic page names its pages'
    gallery list (Juicebox XML), in order; each page's full size is its preview's address
    without the resizing style."""
    import html
    import urllib.parse
    import urllib.request
    get = lambda u: urllib.request.urlopen(urllib.request.Request(u, headers=AGENT), timeout=60).read()
    found = MULTPORN_PAGES.search(get(url).decode("utf-8", "replace"))
    if not found:
        raise RuntimeError("no comic pages on that multporn page")
    listing = urllib.parse.urljoin(url, found.group(1).replace("\\/", "/"))
    previews = [html.unescape(u) for u in MULTPORN_IMAGE.findall(get(listing).decode("utf-8", "replace"))][:MAX_PAGES]
    out = []
    for n, preview in enumerate(previews, 1):
        full = re.sub(r"/styles/[^/]+/public/", "/", preview.split("?")[0])
        name = Path(urllib.parse.urlparse(full).path).name
        if Path(name).suffix.lower() not in IMAGES:
            continue
        for u in (full, preview):          # the preview if the full size isn't there
            try:
                data = get(u)
                break
            except OSError:
                data = None
        if data:
            dest = folder / f"{n:04d}_{name}"
            dest.write_bytes(data)
            out.append(dest)
    return out


def colorize(cfg, pages: list[Path], medium: str, folder: Path, cover_index: int | None = None,
             progress=lambda phase, done, total: None, seed: int | None = None) -> dict:
    """Check pages, pick the cover, colour the black-and-white ones. Returns the comic's meta
    (paths under generated/): {"pages": in order, coloured where it was black and white,
    "originals", "cover", "dropped"}. The tagger and the image model take turns on the GPU."""
    from .checks import problem
    from .comfy import Comfy
    from .vision import Vision
    gen = cfg.generation()
    out_dir = cfg.data_dir / "generated"
    if seed is None:
        seed = random.Random().randrange(2 ** 32)   # one for the whole comic: its pages are drawn alike
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
    bw = [k for k in kept if k[1] < COLOUR and k is not cover]
    if not bw:
        raise RuntimeError("no page is in black and white: nothing to colour")
    # 2. Colour hints, from the cover and any other colour pages (the cover first).
    tmp = Path(tempfile.mkdtemp(prefix="hints-"))
    coloured = {}
    try:
        refs = []
        for p in [cover[0]] + [k[0] for k in kept if k[1] >= COLOUR and k is not cover]:
            with Image.open(p) as im:
                refs.append(im.convert("RGB"))
        hints = Hints(refs)
        try:
            for n, (p, _, _) in enumerate(bw):
                progress("matching colours", n, len(bw))
                with Image.open(p) as im:
                    hints.hint(im.convert("RGB")).save(tmp / f"{n}.png")
        finally:
            hints.close()
        # 3. The image model.
        comfy = Comfy(gen.comfy_url, gen.supervisor_url, out_dir)
        try:
            for n, (p, _, general) in enumerate(bw):
                progress("colouring", n, len(bw))
                with Image.open(p) as im, Image.open(tmp / f"{n}.png") as hint:
                    out = colour_page(comfy, gen.checkpoints[medium], im.convert("RGB"), hint.convert("RGB"),
                                      page_prompt(general), medium, str(folder.relative_to(out_dir)), f"col-{p.stem}", seed)
                dest = p.with_name(f"{p.stem}-colour.jpg")
                out.save(dest, quality=92)
                coloured[p] = dest
        finally:
            comfy.stop()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # 4. The coloured pages are checked again; one that fails stays as it was drawn.
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
            "cover": rel(cover[0]), "dropped": dropped, "seed": seed}


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
    ap.add_argument("--seed", type=int)
    a = ap.parse_args(args)
    cfg = Config()
    folder = Path(a.out)
    folder.mkdir(parents=True, exist_ok=True)
    pages = []
    for i, p in enumerate([a.cover] + a.pages):
        dest = folder / f"{i:04d}_{Path(p).stem}{Path(p).suffix}"
        shutil.copy(p, dest)
        pages.append(dest)
    meta = colorize(cfg, pages, a.medium, folder, cover_index=1, seed=a.seed)
    print(json.dumps(meta, indent=1))
    sys.exit(0)
