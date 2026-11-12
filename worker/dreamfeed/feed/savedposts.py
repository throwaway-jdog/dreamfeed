"""Your saved Feed posts, kept: `python -m dreamfeed follow save <id>`, started by the follow
service for each post you tap Save on (saved_posts, status queued). Each picture and video is
downloaded in full quality (X's original files and biggest video, e621's original, Reddit's
own videos with sound through ffmpeg) into data/saved/<source>/<post>/ (backed up, like
liked/). Saved then shows these copies, so a post deleted on the site stays here. Unsaving it
deletes them (the web app).

Only the sites' own media servers are fetched (HOSTS), over https. These are real people:
nothing here goes to training, styles, comics or generation. Standard library only: the web
app checks saved posts' addresses with allowed() and finds their files with folder().
"""
import json
import os
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path


HOSTS = ("pbs.twimg.com", "video.twimg.com", "i.redd.it", "preview.redd.it", "external-preview.redd.it", "v.redd.it",
         "i.imgur.com", "static1.e621.net", "cdn.bsky.app", "video.bsky.app")      # and redgifs' (*.redgifs.com)
MAX_BYTES = 2 << 30          # a file bigger than this isn't kept
AGENT = "dreamfeed/1.0 (saving a post you saved)"
POST_ID = re.compile(r"^(x|reddit|e621|bsky):([A-Za-z0-9_]{1,60})$")
EXTS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif",
        "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov"}


def folder(data: Path, post_id: str) -> Path:
    m = POST_ID.match(post_id)
    if not m:
        raise ValueError("bad post id")
    return data / "saved" / m.group(1) / m.group(2)


def allowed(url: str) -> bool:
    u = urllib.parse.urlparse(url or "")
    host = u.hostname or ""
    return u.scheme == "https" and (host in HOSTS or host.endswith(".redgifs.com"))


def _fetch(url: str, dest_stem: Path) -> Path:
    """One file into dest_stem + its extension (from the address, else its type)."""
    if not allowed(url):
        raise ValueError(f"not a site's media address: {url[:80]}")
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        ext = Path(urllib.parse.urlparse(url).path).suffix.lower()
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        if q.get("format"):                       # pbs.twimg.com/media/X?format=jpg, preview.redd.it ...?format=mp4
            ext = "." + q["format"][0].replace("pjpg", "jpg")
        if ext not in EXTS.values():
            ext = EXTS.get(r.headers.get_content_type(), ".bin")
        dest = dest_stem.with_suffix(ext)
        part = dest.with_name("." + dest.name + ".part")
        size = 0
        with part.open("wb") as f:
            while chunk := r.read(1 << 20):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError("over 2 GB")
                f.write(chunk)
    part.replace(dest)
    return dest


def _hls(url: str, dest_stem: Path) -> Path:
    """A Reddit video (HLS): its best picture and sound, copied into one MP4."""
    if not allowed(url):
        raise ValueError("not a site's media address")
    dest = dest_stem.with_suffix(".mp4")
    part = dest.with_name("." + dest.name + ".part.mp4")
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-user_agent", AGENT, "-i", url, "-c", "copy",
                        "-fs", str(MAX_BYTES), "-movflags", "+faststart", str(part)], check=True, timeout=1800,
                       capture_output=True)
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)
    return dest


def run(post_id: str) -> None:
    from ..core.db import connect          # (here: the web app uses the rest without the worker's db)
    data = Path(os.environ["DATA_DIR"])
    conn = connect(data / "feed.db")
    row = conn.execute("SELECT data FROM saved_posts WHERE id = ? AND status = 'running'", (post_id,)).fetchone()
    if not row:
        return
    post = json.loads(row[0])
    out = folder(data, post_id)
    tmp = out.with_name("." + out.name + ".saving")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    files = []
    try:
        for n, m in enumerate(post.get("media") or [], 1):
            src = m.get("full") or m.get("url") or ""
            stem = tmp / f"{n:02d}"
            got = _hls(src, stem) if m.get("kind") == "hls" else _fetch(src, stem)
            entry = {"kind": "image" if got.suffix in (".jpg", ".png", ".webp") else "video", "file": got.name}
            if m.get("poster") and entry["kind"] == "video":
                try:
                    entry["poster"] = _fetch(m["poster"], tmp / f"{n:02d}-poster").name
                except (OSError, ValueError):
                    pass
            files.append(entry)
        if not conn.execute("SELECT 1 FROM saved_posts WHERE id = ? AND status = 'running'", (post_id,)).fetchone():
            shutil.rmtree(tmp, ignore_errors=True)       # unsaved while it downloaded
            return
        shutil.rmtree(out, ignore_errors=True)
        tmp.replace(out)
        with conn:
            conn.execute("UPDATE saved_posts SET status = 'done', error = NULL, files = ? WHERE id = ?", (json.dumps(files), post_id))
        print(f"follow: saved {post_id} ({len(files)} file{'s' if len(files) != 1 else ''})", flush=True)
    except Exception as e:      # any failure is this post's, shown on it in Saved
        shutil.rmtree(tmp, ignore_errors=True)
        with conn:
            conn.execute("UPDATE saved_posts SET status = 'failed', error = ? WHERE id = ? AND status = 'running'",
                         (str(e)[:300], post_id))
        print(f"follow: saving {post_id} failed: {e}", flush=True)
