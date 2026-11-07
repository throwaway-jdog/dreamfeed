"""Black-and-white comic pages coloured from their colour cover.

    python -m dreamfeed colorize --cover COVER.png PAGE.png... --medium furry --out DIR   (a test)

Imports come in two kinds. Automatic: steps 1-5 in one job. Marked (the person marks who is
who): the job stops after step 2 and the comic waits on the Comics page; the person names the
characters and scribbles over each one on every page (the cover too), and a second job (kind
"comic_colour") does steps 3-5 with the marks: each scribble spreads over its character, up
to the ink lines (spread), and a patch marked as one character only takes colours from that
character on the colour pages. On a tangled page that took the right colours from 77% to 88%.

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
SPREAD_SIDE = 1024     # marks spread over the page at this long side
SPREAD = 0.3           # how far a scribble reaches, as a share of the page's long side
INK_LINE, INK_COST = 110, 400  # darker than this is a line; a pixel of it costs more than a scribble reaches
OTHER_CHARACTER = 10   # a match with another character, once said who is who: never taken
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

    def __init__(self, colour_pages: list[Image.Image], labels: list[np.ndarray | None] | None = None):
        """labels: per colour page, which character each pixel is (0: not said; see who())."""
        import timm
        import torch
        self.torch = torch
        self.model = timm.create_model(f"hf-hub:{DINO}", pretrained=True, dynamic_img_size=True).eval().cuda()
        self.refs = colour_pages
        self.labels = labels or [None] * len(colour_pages)

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

    def hint(self, page: Image.Image, labels: np.ndarray | None = None) -> Image.Image:
        """labels: which character each pixel of the page is (0: not said). A patch said to be
        one character only takes colours from patches of the colour pages said to be her."""
        torch, F = self.torch, self.torch.nn.functional
        y = np.asarray(ImageOps.grayscale(page), dtype=np.float32)
        pf, (h, w) = self._features(y)
        feats, values = [], []      # per reference patch: features; (cb, cr, grey, brightness)
        who = []
        for ref, ref_labels in zip(self.refs, self.labels):
            ry = np.asarray(ImageOps.grayscale(ref), dtype=np.float32)
            spread = _match_histogram(ry, y)
            f, (rh, rw) = self._features(spread)
            _, cb, cr = (np.asarray(c, dtype=np.float32) for c in ref.convert("YCbCr").split())
            v = torch.from_numpy(np.stack([cb - 128, cr - 128, spread, ry]))[None]
            values.append(F.adaptive_avg_pool2d(v, (rh, rw))[0].reshape(4, -1).T)
            feats.append(f)
            who.append(_patch_labels(ref_labels, (rh, rw)))
        rf, rv = torch.cat(feats), torch.cat(values).cuda()
        py = F.adaptive_avg_pool2d(torch.from_numpy(y)[None, None], (h, w)).flatten().cuda()
        sim = pf @ rf.T - SAME_BRIGHTNESS * (py[:, None] - rv[None, :, 2]).abs() / 255
        page_who, ref_who = _patch_labels(labels, (h, w)).cuda(), torch.cat(who).cuda()
        sim = sim - OTHER_CHARACTER * ((page_who[:, None] > 0) & (ref_who[None, :] > 0)
                                       & (page_who[:, None] != ref_who[None, :]))
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


def _patch_labels(labels: np.ndarray | None, grid: tuple[int, int]):
    """Each patch's character: the one most of its said pixels are, if they're at least a
    third of it; else 0."""
    import torch
    import torch.nn.functional as F
    if labels is None:
        return torch.zeros(grid[0] * grid[1], dtype=torch.long)
    lab = torch.from_numpy(labels.astype(np.int64))
    n = int(lab.max()) + 1
    share = F.adaptive_avg_pool2d(F.one_hot(lab, n).permute(2, 0, 1).float()[None], grid)[0]   # (n, h, w)
    share[0] = 0
    best, which = share.max(0)
    return torch.where(best >= 1 / 3, which, torch.zeros_like(which)).flatten()


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


def spread(page: Image.Image, marks: list[dict]) -> np.ndarray:
    """Which character each pixel is (0: none), from scribbles: each grows from its strokes
    over the page, held back by ink lines and only so far (SPREAD), the nearest one winning.
    marks: [{"who": 1.., "width": share of the page's width, "points": [[x, y] shares]}]."""
    import torch
    import torch.nn.functional as F
    from PIL import ImageDraw
    y = np.asarray(ImageOps.grayscale(page), dtype=np.float32)
    r = SPREAD_SIDE / max(y.shape)
    h, w = max(1, round(y.shape[0] * r)), max(1, round(y.shape[1] * r))
    # Shrunk keeping the darkest pixel of each block: thin lines stay lines.
    k = max(1, int(np.ceil(1 / r)))
    dark = torch.from_numpy(y)[None, None]
    dark = -F.max_pool2d(-dark, k, k, ceil_mode=True)
    small = F.interpolate(dark, size=(h, w), mode="nearest")[0, 0].numpy()
    cost = torch.from_numpy(1 + INK_COST * np.clip((INK_LINE - small) / 40, 0, 1)).cuda()
    who = sorted({int(m["who"]) for m in marks})
    if not who:
        return np.zeros(y.shape, np.uint8)
    far = torch.full((len(who), h, w), float("inf"), device="cuda")
    for i, n in enumerate(who):
        seeds = Image.new("L", (w, h), 0)
        d = ImageDraw.Draw(seeds)
        for m in marks:
            if int(m["who"]) != n or not m["points"]:
                continue
            pts = [(px * w, py * h) for px, py in m["points"]]
            width = max(1, round(float(m["width"]) * w))
            d.line(pts, fill=255, width=width, joint="curve")
            for px, py in pts[:1] + pts[-1:]:
                d.ellipse([px - width / 2, py - width / 2, px + width / 2, py + width / 2], fill=255)
        far[i][torch.from_numpy(np.asarray(seeds) > 0).cuda()] = 0
    limit = SPREAD * max(h, w)
    for step in range(4 * max(h, w)):
        nearest = -F.max_pool2d(-far[:, None], 3, 1, 1)[:, 0] + cost
        grown = torch.minimum(far, nearest)
        if step % 25 == 0 and torch.equal(grown, far):
            break
        far = grown
    best, which = far.min(0)
    lab = torch.tensor(who, device="cuda")[which].where(best <= limit, torch.zeros_like(which))
    out = np.asarray(Image.fromarray(lab.to(torch.uint8).cpu().numpy()).resize(page.size, Image.NEAREST))
    return np.where(_margins(y), 0, out).astype(np.uint8)


def prepare(cfg, pages: list[Path], medium: str, cover_index: int | None = None,
            progress=lambda phase, done, total: None) -> dict:
    """Steps 1-2: the pages checked (failing ones deleted), their tags, which are in colour, the
    cover. {"files": [Path], "colour": [bool], "tags": [{tag: score}], "cover": index, "dropped"}"""
    from .checks import problem
    from .vision import Vision
    files, colour, tags, dropped = [], [], [], 0
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
            files.append(p)
            colour.append(saturation(img) >= COLOUR)
            tags.append({t: round(s, 3) for t, s in a.general.items() if s >= TAG_MIN})
    finally:
        vision.close()
    if not files or dropped > MAX_DROPPED * len(pages):
        raise RuntimeError(f"{dropped} of {len(pages)} pages failed the checks; not imported")
    if cover_index:
        cover = min(cover_index, len(files)) - 1
    elif any(colour):
        cover = max((i for i in range(len(files)) if colour[i]), key=lambda i: _saturation_of(files[i]))
    else:
        raise RuntimeError("no page is in colour to colour the others from")
    colour[cover] = True
    print(f"colorize: cover {files[cover].name}", flush=True)
    return {"files": files, "colour": colour, "tags": tags, "cover": cover, "dropped": dropped}


def _saturation_of(p: Path) -> float:
    with Image.open(p) as im:
        return saturation(im.convert("RGB"))


def colour(cfg, prep: dict, medium: str, folder: Path, marks: dict | None = None,
           progress=lambda phase, done, total: None, seed: int | None = None) -> dict:
    """Steps 3-5. marks: {page index: [scribbles]} (see spread). Returns the comic's meta (paths
    under generated/): {"pages": coloured where they were black and white, "originals",
    "cover", "dropped", "seed"}. The models take turns on the GPU."""
    from .checks import problem
    from .comfy import Comfy
    from .vision import Vision
    gen = cfg.generation()
    out_dir = cfg.data_dir / "generated"
    marks = marks or {}
    if seed is None:
        seed = random.Random().randrange(2 ** 32)   # one for the whole comic: its pages are drawn alike
    files, cover = prep["files"], prep["cover"]
    refs = [cover] + [i for i, c in enumerate(prep["colour"]) if c and i != cover]
    bw = [i for i, c in enumerate(prep["colour"]) if not c]
    open_page = lambda i: Image.open(files[i]).convert("RGB")
    rel = lambda p: str(p.relative_to(out_dir))
    if not bw:   # all in colour already: kept as they are
        return {"pages": [rel(p) for p in files], "originals": [rel(p) for p in files], "cover": rel(files[cover]),
                "dropped": prep["dropped"], "seed": seed}
    tmp = Path(tempfile.mkdtemp(prefix="hints-"))
    coloured = {}
    try:
        # 3. Who is who (from the marks), and colour hints from the colour pages.
        labels = {}
        for n, i in enumerate(i for i in range(len(files)) if marks.get(i)):
            progress("reading the marks", n, len(marks))
            labels[i] = spread(open_page(i), marks[i])
        hints = Hints([open_page(i) for i in refs], [labels.get(i) for i in refs])
        try:
            for n, i in enumerate(bw):
                progress("matching colours", n, len(bw))
                hints.hint(open_page(i), labels.get(i)).save(tmp / f"{i}.png")
        finally:
            hints.close()
        # 4. The image model.
        comfy = Comfy(gen.comfy_url, gen.supervisor_url, out_dir)
        try:
            for n, i in enumerate(bw):
                progress("colouring", n, len(bw))
                with Image.open(tmp / f"{i}.png") as hint:
                    out = colour_page(comfy, gen.checkpoints[medium], open_page(i), hint.convert("RGB"),
                                      page_prompt(prep["tags"][i]), medium, str(folder.relative_to(out_dir)),
                                      f"col-{files[i].stem}", seed)
                dest = files[i].with_name(f"{files[i].stem}-colour.jpg")
                out.save(dest, quality=92)
                coloured[i] = dest
        finally:
            comfy.stop()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # 5. The coloured pages are checked again; one that fails stays as it was drawn.
    vision = Vision(cfg.models_dir)
    try:
        for n, (i, dest) in enumerate(list(coloured.items())):
            progress("checking the colours", n, len(coloured))
            with Image.open(dest) as im:
                img = im.convert("RGB")
            if problem(vision.analyze([img]), medium, [img], cfg, strict=True):
                print(f"colorize: {files[i].name} failed a check in colour; kept as drawn", flush=True)
                dest.unlink(missing_ok=True)
                del coloured[i]
    finally:
        vision.close()
    return {"pages": [rel(coloured.get(i, p)) for i, p in enumerate(files)], "originals": [rel(p) for p in files],
            "cover": rel(files[cover]), "dropped": prep["dropped"], "seed": seed}


def _prep_meta(prep: dict, out_dir: Path) -> dict:
    """What a comic waiting to be marked keeps in its comic.json."""
    pages = [str(p.relative_to(out_dir)) for p in prep["files"]]
    return {"pages": pages, "originals": pages, "colour": prep["colour"], "tags": prep["tags"],
            "cover_index": prep["cover"], "cover": pages[prep["cover"]], "dropped": prep["dropped"]}


def _job(conn, job_id: int, night: str, work) -> None:
    """Runs work(progress) -> message as job job_id, keeping its runs row."""
    from .generate import _progress
    with conn:
        conn.execute("UPDATE jobs SET status = 'running', night = ? WHERE id = ?", (night, job_id))
        conn.execute("INSERT INTO runs(night, status, attempts, started_at) VALUES (?, 'running', 1, datetime('now'))",
                     (night,))
    status, message = "done", None
    try:
        message = work(lambda phase, d, t: _progress(conn, night, phase, d, t))
    except Exception as e:
        status, message = "failed", str(e)[:300]
        print(f"colorize: job {job_id} failed: {message}", flush=True)
    finally:
        with conn:
            conn.execute("UPDATE runs SET status = ?, progress = NULL, finished_at = datetime('now') WHERE night = ?",
                         (status, night))
            conn.execute("UPDATE jobs SET status = ?, message = ?, finished_at = datetime('now') WHERE id = ?",
                         (status, message, job_id))


def run_job(cfg, conn, job_id: int, params: dict) -> None:
    """An import queued from the Comics page: {"kind": "comic_import", "url", "title", "medium",
    "cover", "mark"}. Marked: stops for the marks (the comic's status is "comic_marking")."""
    from .comicanim import add_panels
    from .generate import _set
    out_dir = cfg.data_dir / "generated"
    folder = out_dir / f"comic-import-{dt.datetime.now():%Y%m%d-%H%M%S}"
    medium = params.get("medium", "furry")
    night = f"comicimport-{job_id}"

    def work(progress):
        try:
            progress("downloading", 0, 1)
            pages = _download(params["url"], folder)
            if not pages:
                raise RuntimeError("nothing downloaded from that link")
            prep = prepare(cfg, pages, medium, params.get("cover"), progress)
            base = {"title": params.get("title") or "Imported comic", "source": params["url"], "imported": True,
                    "cast": [], "medium": medium}
            marking = params.get("mark") and not all(prep["colour"])   # nothing to mark in a colour comic
            if marking:
                meta, status = base | _prep_meta(prep, out_dir) | {"marking": True}, "comic_marking"
            else:
                meta, status = add_panels(base | colour(cfg, prep, medium, folder, progress=progress), out_dir), "comic"
            (folder / "comic.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        with conn:
            gid = conn.execute(
                "INSERT INTO generations(night, medium, checkpoint, prompt, seed, caption, kind, status, file)"
                " VALUES (?, ?, 'comic import', ?, 0, ?, 'comic', ?, ?)",
                (night, medium, params["url"], meta["title"], status, meta["pages"][0])).lastrowid
        _set(conn, gid, posted_at=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
        if marking:
            return f"{len(meta['pages'])} pages, {meta['dropped']} dropped by the checks: waiting for the marks"
        return f"{len(meta['pages'])} pages, {meta['dropped']} dropped by the checks"

    _job(conn, job_id, night, work)


def run_colour_job(cfg, conn, job_id: int, params: dict) -> None:
    """A marked comic coloured: {"kind": "comic_colour", "id": its generations row}. The marks
    are in marks.json beside comic.json: {"characters": [names], "pages": {"1": [scribbles]}}
    (pages counted from 1)."""
    from .comicanim import add_panels
    out_dir = cfg.data_dir / "generated"

    def work(progress):
        row = conn.execute("SELECT file FROM generations WHERE id = ? AND kind = 'comic' AND status = 'comic_colouring'",
                           (params["id"],)).fetchone()
        if not row:
            raise RuntimeError("that comic isn't waiting to be coloured")
        folder = (out_dir / row[0]).parent
        status, first = "comic_marking", row[0]   # if it fails: back to waiting, the marks kept, to try again
        try:
            meta = json.loads((folder / "comic.json").read_text())
            saved = json.loads((folder / "marks.json").read_text())
            marks = {int(k) - 1: v for k, v in saved.get("pages", {}).items() if v}
            prep = {"files": [out_dir / p for p in meta["originals"]], "colour": meta["colour"], "tags": meta["tags"],
                    "cover": meta["cover_index"], "dropped": meta["dropped"]}
            done = colour(cfg, prep, meta.get("medium", "furry"), folder, marks, progress)
            meta = {k: v for k, v in meta.items() if k not in ("marking", "colour", "tags", "cover_index")} | done \
                | {"characters": saved.get("characters", [])}
            meta = add_panels(meta, out_dir)
            (folder / "comic.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
            status, first = "comic", meta["pages"][0]
        finally:
            with conn:
                conn.execute("UPDATE generations SET status = ?, file = ? WHERE id = ?", (status, first, params["id"]))
        return f"{len(meta['pages'])} pages coloured"

    _job(conn, job_id, f"comiccolour-{job_id}", work)


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
    meta = colour(cfg, prepare(cfg, pages, a.medium, cover_index=1), a.medium, folder, seed=a.seed)
    print(json.dumps(meta, indent=1))
    sys.exit(0)
