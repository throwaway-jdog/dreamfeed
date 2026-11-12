"""Comics imported from a link, kept as drawn, to read and animate panels of.

The dashboard's Comics page queues an import as a job (kind "comic_import"):
1. The pages are downloaded (gallery-dl, any gallery it reads, in the gallery's order; multporn
   by its own page list, which gallery-dl doesn't read).
2. Each page goes through the adults-only checks (checks.problem, strict). Pages that fail are
   dropped; if more than MAX_DROPPED of them fail, the import stops: it isn't a comic to keep.
3. The comic is saved like the comics made here (generated/comic-import-.../comic.json), with
   its panels found for animating (comicanim.add_panels) and the characters in them outlined
   (comicanim.add_outlines). Every file its source listed is remembered ("seen_files").

New pages (kind "comic_update", once a day for every imported comic, or one comic from the
reader): the source is listed again without downloading, and only pages it hasn't listed before
are downloaded, checked like an import's and added at the end ("updated": when, how many).
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


def _host(url: str) -> str:
    return (url.split("/")[2].lower() if url.count("/") >= 2 else "").removeprefix("www.")


def _gallery_dl(url: str, folder: Path, extra: list[str]) -> subprocess.CompletedProcess:
    from ..art.styles import COOKIE_HOSTS, x_cookies
    conf = {"extractor": {"directory": [], "base-directory": str(folder), "filename": "{num:>04}_{filename}.{extension}",
                          "cookies-update": False}, "downloader": {"part-directory": str(folder / ".part")}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(conf, f)
    cmd = ["gallery-dl", "--config-ignore", "--config", f.name, "--filter", "extension in ('jpg', 'jpeg', 'png', 'webp')"]
    if _host(url).removeprefix("mobile.") in COOKIE_HOSTS and x_cookies():
        cmd += ["--cookies", str(x_cookies())]
    try:
        return subprocess.run(cmd + extra + [url], capture_output=True, text=True, timeout=3600)
    finally:
        Path(f.name).unlink(missing_ok=True)
        shutil.rmtree(folder / ".part", ignore_errors=True)


def listing(url: str) -> list[str]:
    """The names the source's pages are saved under ("0001_name.jpg"), in its order, without
    downloading them."""
    if _host(url) == "multporn.net":
        return [name for name, _ in _multporn_pages(url)]
    with tempfile.TemporaryDirectory() as tmp:
        r = _gallery_dl(url, Path(tmp), ["--range", f"1-{MAX_PAGES}", "-j"])
    try:
        msgs = json.loads(r.stdout or "[]")
    except ValueError:
        raise RuntimeError("the source couldn't be read")
    return [f"{m[2].get('num', 0):>04}_{m[2].get('filename')}.{m[2].get('extension')}" for m in msgs
            if m and m[0] == 3 and isinstance(m[-1], dict) and str(m[2].get("extension", "")).lower() in
            ("jpg", "jpeg", "png", "webp")]


def _download(url: str, folder: Path, only: list[str] | None = None) -> list[Path]:
    """The gallery's images, in its order (only: just the pages saved under these names)."""
    folder.mkdir(parents=True, exist_ok=True)
    if _host(url) == "multporn.net":
        return _multporn(url, folder, only)
    extra = ["--range", f"1-{MAX_PAGES}"]
    if only is not None:
        names = listing(url)
        picks = [str(i) for i, n in enumerate(names, 1) if n in set(only)]
        if not picks:
            return []
        extra = ["--range", ",".join(picks)]
    _gallery_dl(url, folder, extra)
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGES)


def _get(u: str) -> bytes:
    import urllib.request
    return urllib.request.urlopen(urllib.request.Request(u, headers=AGENT), timeout=60).read()


def _multporn_pages(url: str) -> list[tuple[str, list[str]]]:
    """A multporn comic's pages: (name to save it under, [full size, preview]). The comic page
    names its pages' gallery list (Juicebox XML), in order; each page's full size is its
    preview's address without the resizing style."""
    import html
    import urllib.parse
    found = MULTPORN_PAGES.search(_get(url).decode("utf-8", "replace"))
    if not found:
        raise RuntimeError("no comic pages on that multporn page: use the comic's own page (multporn.net/comics/...)")
    pages = urllib.parse.urljoin(url, found.group(1).replace("\\/", "/"))
    previews = [html.unescape(u) for u in MULTPORN_IMAGE.findall(_get(pages).decode("utf-8", "replace"))][:MAX_PAGES]
    out = []
    for n, preview in enumerate(previews, 1):
        full = re.sub(r"/styles/[^/]+/public/", "/", preview.split("?")[0])
        name = Path(urllib.parse.urlparse(full).path).name
        if Path(name).suffix.lower() in IMAGES:
            out.append((f"{n:04d}_{name}", [full, preview]))
    return out


def _multporn(url: str, folder: Path, only: list[str] | None = None) -> list[Path]:
    out = []
    for name, urls in _multporn_pages(url):
        if only is not None and name not in only:
            continue
        for u in urls:                     # the preview if the full size isn't there
            try:
                data = _get(u)
                break
            except OSError:
                data = None
        if data:
            dest = folder / name
            dest.write_bytes(data)
            out.append(dest)
    return out


def check_pages(cfg, pages: list[Path], medium: str, progress=lambda phase, done, total: None,
                whole: bool = True) -> tuple[list[Path], int]:
    """The pages that pass the checks (the others deleted), and how many were dropped. whole:
    it's a whole comic, refused if too many fail (new pages of one are taken one by one)."""
    from ..core.checks import problem
    from ..art.vision import Vision
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
    if whole and (not kept or dropped > MAX_DROPPED * len(pages)):
        raise RuntimeError(f"{dropped} of {len(pages)} pages failed the checks; not imported")
    return kept, dropped


def _job(conn, job_id: int, night: str, work) -> None:
    """Runs work(progress) -> message as job job_id, keeping its runs row."""
    from ..art.generate import _progress
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
    from .comicanim import add_outlines, add_panels
    from ..art.generate import _set
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
            seen = [p.name for p in pages]
            meta = add_panels({"title": params.get("title") or "Imported comic", "source": params["url"], "imported": True,
                               "cast": [], "medium": medium, "pages": rel, "cover": rel[0], "dropped": dropped,
                               "seen_files": seen}, out_dir)
            meta = add_outlines(meta, out_dir, progress)
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


def update(cfg, folder: Path, progress=lambda phase, done, total: None) -> int:
    """New pages of an imported comic, checked and added at the end; how many were added."""
    from .comicanim import add_outlines, add_panels
    out_dir = cfg.data_dir / "generated"
    path = folder / "comic.json"
    meta = json.loads(path.read_text())
    if not meta.get("imported") or not str(meta.get("source", "")).startswith("http"):
        return 0
    names = listing(meta["source"])
    # Comics imported before "seen_files" was kept: their pages' names (a page dropped back then
    # comes up as new once, and is dropped again by the checks).
    seen = set(meta.get("seen_files") or [Path(p).name for p in meta.get("pages") or []])
    new = [n for n in names if n not in seen]
    added = []
    if new:
        tmp = folder / ".new"
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            got = _download(meta["source"], tmp, only=new)
            kept, dropped = check_pages(cfg, got, meta.get("medium", "furry"), progress, whole=False) if got else ([], 0)
            for p in sorted(kept, key=lambda p: names.index(p.name) if p.name in names else 0):
                dest = folder / p.name
                if dest.exists():
                    dest = folder / f"new-{p.name}"
                shutil.move(p, dest)
                added.append(str(dest.relative_to(out_dir)))
            meta["dropped"] = meta.get("dropped", 0) + dropped
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    meta = json.loads(path.read_text()) | {k: meta[k] for k in ("dropped",) if k in meta}  # what changed meanwhile (animations)
    meta["seen_files"] = sorted(seen | set(names))
    if added:
        first = len(meta["pages"]) + 1
        meta["pages"] = meta["pages"] + added
        meta = add_panels(meta, out_dir)
        meta = add_outlines(meta, out_dir, progress, pages=set(range(first, len(meta["pages"]) + 1)))
        meta["updated"] = {"at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "new": len(added)}
    tmp_json = path.with_suffix(".tmp")
    tmp_json.write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    tmp_json.replace(path)
    return len(added)


UPDATE_EVERY = 24 * 3600


def due_update(cfg) -> None:
    """Queues the daily look for new pages of every imported comic, once a day."""
    import time
    from ..core import db
    mark = cfg.data_dir / "generated" / ".comic-updates"
    try:
        if time.time() - mark.stat().st_mtime < UPDATE_EVERY:
            return
    except OSError:
        pass
    conn = db.connect(cfg.db_path)
    try:
        if not conn.execute("SELECT 1 FROM jobs WHERE status IN ('queued', 'running')"
                            " AND params LIKE '%comic_update%'").fetchone():
            with conn:
                conn.execute("INSERT INTO jobs(params, status) VALUES (?, 'queued')", (json.dumps({"kind": "comic_update"}),))
    finally:
        conn.close()
    mark.touch()


def run_update_job(cfg, conn, job_id: int, params: dict) -> None:
    """{"kind": "comic_update"} every imported comic, or {"kind": "comic_update", "id": N} one."""
    out_dir = cfg.data_dir / "generated"
    q = "SELECT id, file FROM generations WHERE kind = 'comic' AND status = 'comic'"
    rows = conn.execute(q + (" AND id = ?" if params.get("id") else ""),
                        (params["id"],) if params.get("id") else ()).fetchall()
    folders = [(out_dir / f).parent for _, f in rows if f and (out_dir / f).parent.joinpath("comic.json").is_file()]

    def work(progress):
        total, failed = 0, 0
        for i, folder in enumerate(folders):
            progress("looking for new pages", i, len(folders))
            try:
                total += update(cfg, folder, progress)
            except Exception as e:      # one comic's source being down doesn't stop the rest
                failed += 1
                print(f"comic update: {folder.name}: {e}", flush=True)
        return f"{total} new pages" + (f"; {failed} couldn't be read" if failed else "")

    _job(conn, job_id, f"comicupdate-{job_id}", work)
