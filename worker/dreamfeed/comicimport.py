"""Comics imported from a link, kept as drawn, to read and animate panels of.

The dashboard's Comics page queues an import as a job (kind "comic_import"):
1. The pages are downloaded (gallery-dl, any gallery it reads, in the gallery's order; multporn
   by its own page list, which gallery-dl doesn't read).
2. Each page goes through the adults-only checks (checks.problem, strict). Pages that fail are
   dropped; if more than MAX_DROPPED of them fail, the import stops: it isn't a comic to keep.
3. The comic is saved like the comics made here (generated/comic-import-.../comic.json), with
   its panels found for animating (comicanim.add_panels).
"""
import datetime as dt
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

MAX_PAGES = 200
MAX_DROPPED = 0.2      # share of pages that may fail the checks before the import stops
IMAGES = (".png", ".jpg", ".jpeg", ".webp")
MULTPORN_PAGES = re.compile(r'configUrl":"([^"]+)"')
MULTPORN_IMAGE = re.compile(r'imageURL="([^"]+)"')
AGENT = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}   # the site turns away scripts' own


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


def _multporn(url: str, folder: Path) -> list[Path]:
    """A multporn comic: the comic page names its pages' gallery list (Juicebox XML), in order;
    each page's full size is its preview's address without the resizing style."""
    import html
    import urllib.parse
    import urllib.request
    get = lambda u: urllib.request.urlopen(urllib.request.Request(u, headers=AGENT), timeout=60).read()
    found = MULTPORN_PAGES.search(get(url).decode("utf-8", "replace"))
    if not found:
        raise RuntimeError("no comic pages on that multporn page: use the comic's own page (multporn.net/comics/...)")
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


def check_pages(cfg, pages: list[Path], medium: str, progress=lambda phase, done, total: None) -> tuple[list[Path], int]:
    """The pages that pass the checks (the others deleted), and how many were dropped."""
    from .checks import problem
    from .vision import Vision
    kept, dropped = [], 0
    vision = Vision(cfg.models_dir)
    try:
        for n, p in enumerate(pages):
            progress("checking the pages", n, len(pages))
            with Image.open(p) as im:
                img = im.convert("RGB")
            if problem(vision.analyze([img]), medium, [img], cfg, strict=True):
                dropped += 1
                p.unlink(missing_ok=True)
            else:
                kept.append(p)
    finally:
        vision.close()
    if not kept or dropped > MAX_DROPPED * len(pages):
        raise RuntimeError(f"{dropped} of {len(pages)} pages failed the checks; not imported")
    return kept, dropped


def _job(conn, job_id: int, night: str, work) -> None:
    """Runs work(progress) -> message as job job_id, keeping its runs row."""
    from .generate import _progress
    with conn:
        conn.execute("UPDATE jobs SET status = 'running', night = ? WHERE id = ?", (night, job_id))
        conn.execute("INSERT INTO runs(night, status, attempts, started_at) VALUES (?, 'running', 1, datetime('now'))",
                     (night,))
    status, message = "done", None
    try:
        message = work(lambda phase, d, t, share=None: _progress(conn, night, phase, d, t, share=share))
    except Exception as e:
        status, message = "failed", str(e)[:300]
        print(f"{night}: job {job_id} failed: {message}", flush=True)
    finally:
        with conn:
            conn.execute("UPDATE runs SET status = ?, progress = NULL, finished_at = datetime('now') WHERE night = ?",
                         (status, night))
            conn.execute("UPDATE jobs SET status = ?, message = ?, finished_at = datetime('now') WHERE id = ?",
                         (status, message, job_id))


def run_job(cfg, conn, job_id: int, params: dict) -> None:
    """An import queued from the Comics page: {"kind": "comic_import", "url", "title", "medium"}."""
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
            kept, dropped = check_pages(cfg, pages, medium, progress)
            rel = [str(p.relative_to(out_dir)) for p in kept]
            meta = add_panels({"title": params.get("title") or "Imported comic", "source": params["url"], "imported": True,
                               "cast": [], "medium": medium, "pages": rel, "cover": rel[0], "dropped": dropped}, out_dir)
            (folder / "comic.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        with conn:
            gid = conn.execute(
                "INSERT INTO generations(night, medium, checkpoint, prompt, seed, caption, kind, status, file)"
                " VALUES (?, ?, 'comic import', ?, 0, ?, 'comic', 'comic', ?)",
                (night, medium, params["url"], meta["title"], meta["pages"][0])).lastrowid
        _set(conn, gid, posted_at=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
        return f"{len(meta['pages'])} pages, {dropped} dropped by the checks"

    _job(conn, job_id, night, work)
