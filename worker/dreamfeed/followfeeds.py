"""Posts from who you follow on X and Reddit, checked before they show: `python -m dreamfeed
follow feeds` (the follow service runs it every FEEDS_EVERY seconds, as a child that exits
when done, so the checking models' memory is given back).

1. New posts are downloaded: X with gallery-dl and your cookies (the Following timeline,
   x.com/home); Reddit from the public RSS feeds of the subreddits and users in REDDIT_FOLLOW
   (no account: Reddit's API needs an approved app), their pictures (i.redd.it) and redgifs
   (gallery-dl); galleries and Reddit's own videos aren't in the RSS feed's link, so they're
   left out. What's been read is remembered (gallery-dl's archive; reddit.seen).
2. Every file goes through the adults-only checks (checks.problem, strict), a video's
   VIDEO_FRAMES frames spread over it, and a face in a drawing gets the age estimate too. A
   post with any file that fails is deleted, all of it.
3. Posts that pass are kept KEEP_DAYS days in data/generated/follow/media (left out of the
   backup) and listed in follow_posts for the Following page.

These are real people: nothing here goes to training, styles, comics or generation.
"""
import datetime as dt
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

KEEP_DAYS = 14
MAX_FILES = 150            # files read from a feed at a time
STOP_AFTER_SEEN = 10       # a feed is read up to this many files in a row it already has
VIDEO_FRAMES = 4
CHECK_SIDE = 1536          # pictures are checked at most this big
MAX_SIZE = "200M"
IMAGES = {".jpg", ".jpeg", ".png", ".webp"}
VIDEOS = {".mp4", ".webm", ".mov", ".m4v", ".gif"}
FEEDS = {
    "x": {"url": "https://x.com/home", "cookies": Path("/config/x-cookies.txt"), "name": "X"},
    "reddit": {"name": "Reddit"},
}
# Reddit's rules for scripts: a user agent that says what it is.
REDDIT_AGENT = "linux:dreamfeed:1.0 (personal feed reader)"
REDDIT_RSS = "https://www.reddit.com/{}/new/.rss?limit=25"
REDDIT_GAP = 7             # seconds between Reddit requests (unsigned readers get very few)
REDDIT_IMAGES = ("i.redd.it",)
REDDIT_LINKED = ("redgifs.com", "www.redgifs.com", "v3.redgifs.com")
SEEN_KEEP = 5000
ATOM = {"a": "http://www.w3.org/2005/Atom"}


def reddit_follow() -> list[str]:
    """REDDIT_FOLLOW: "r/name" and "u/name", comma-separated (a bare name is a subreddit)."""
    import re
    out = []
    for item in os.environ.get("REDDIT_FOLLOW", "").split(","):
        item = item.strip().strip("/").removeprefix("user/").replace("user/", "u/")
        kind, _, name = item.rpartition("/")
        kind = {"": "r", "r": "r", "u": "u"}.get(kind)
        if kind and re.fullmatch(r"[A-Za-z0-9_-]{2,30}", name):
            out.append(f"{kind}/{name}")
    return out


def _signed_in(source: str) -> str | None:
    """Why this feed can't be read, or None."""
    if source == "reddit":
        return None if reddit_follow() else "no subreddits or users to follow yet (REDDIT_FOLLOW in .env)"
    cookies = FEEDS[source]["cookies"]
    if not cookies.is_file() or not any(line.strip() and not line.startswith("# ") for line in cookies.open()):
        return f"no {FEEDS[source]['name']} cookies yet"
    return None


def download(source: str, incoming: Path, archive: Path) -> str | None:
    """The feed's new files into incoming, each with its post's details (FILE.json); an error, or None."""
    incoming.mkdir(parents=True, exist_ok=True)
    if source == "reddit":
        return _reddit(incoming, archive.with_suffix(".seen"))
    conf = {"extractor": {
        "base-directory": str(incoming), "directory": [], "archive": str(archive), "cookies-update": False,
        "filename": "{category}_{filename}.{extension}",
        "twitter": {"text-tweets": False, "retweets": False, "quoted": False, "filename": "{tweet_id}_{num}.{extension}"},
    }, "downloader": {"part-directory": str(incoming / ".part"), "filesize-max": MAX_SIZE}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(conf, f)
    try:
        r = subprocess.run(["gallery-dl", "--config-ignore", "--config", f.name, "--cookies", str(FEEDS[source]["cookies"]),
                            "--range", f"1-{MAX_FILES}", "--abort", str(STOP_AFTER_SEEN), "--write-metadata",
                            FEEDS[source]["url"]], capture_output=True, text=True, timeout=1800)
    finally:
        Path(f.name).unlink(missing_ok=True)
        shutil.rmtree(incoming / ".part", ignore_errors=True)
    errors = [line for line in r.stderr.splitlines() if "][error]" in line]
    if r.returncode and errors and not any(incoming.iterdir()):
        return errors[-1].split("][error]", 1)[1].strip()[:200]
    return None


def _fetch(url: str) -> bytes:
    """Reddit, politely: one request at a time, REDDIT_GAP apart, once more after a 429."""
    import time
    import urllib.error
    import urllib.request
    for attempt in range(2):
        time.sleep(REDDIT_GAP)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": REDDIT_AGENT}), timeout=60) as r:
                return r.read(200 << 20)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt:
                raise
            time.sleep(min(60, float(e.headers.get("x-ratelimit-reset") or 30)))
    raise OSError("rate limited")


def _entries(feed: bytes) -> list[dict]:
    """An RSS (Atom) feed's posts: {"id", "author", "subreddit", "title", "date", "permalink", "media"}."""
    import html
    import re
    import xml.etree.ElementTree as ET
    out = []
    for e in ET.fromstring(feed).findall("a:entry", ATOM):
        content = html.unescape(e.findtext("a:content", "", ATOM))
        media = re.search(r'<a href="([^"]+)">\[link\]</a>', content)
        link = (e.find("a:link", ATOM).get("href") if e.find("a:link", ATOM) is not None else "") or ""
        sub = re.search(r"/r/([^/]+)/comments/", link)
        when = (e.findtext("a:published", "", ATOM) or "")[:19].replace("T", " ")
        out.append({"id": e.findtext("a:id", "", ATOM).removeprefix("t3_"), "title": e.findtext("a:title", "", ATOM),
                    "author": e.findtext("a:author/a:name", "", ATOM).removeprefix("/u/"),
                    "subreddit": sub.group(1) if sub else None, "date": when,
                    "permalink": link.removeprefix("https://www.reddit.com"), "media": media.group(1) if media else None})
    return out


def _reddit(incoming: Path, seen_file: Path) -> str | None:
    import re
    import urllib.parse
    seen = seen_file.read_text().split() if seen_file.is_file() else []
    known, errors, new = set(seen), [], []
    for who in reddit_follow():
        try:
            posts = _entries(_fetch(REDDIT_RSS.format(who.replace("u/", "user/"))))
        except (OSError, ValueError) as e:
            errors.append(f"{who}: {e}")
            continue
        for p in posts:
            if not re.fullmatch(r"[a-z0-9]{3,12}", p["id"]) or p["id"] in known:
                continue
            known.add(p["id"]); new.append(p["id"])
            url = p.pop("media") or ""
            host = urllib.parse.urlparse(url).hostname or ""
            meta = json.dumps(p)
            try:
                if host in REDDIT_IMAGES:
                    ext = Path(urllib.parse.urlparse(url).path).suffix.lower()
                    if ext in IMAGES | VIDEOS:
                        dest = incoming / f"{p['id']}_1{ext}"
                        dest.write_bytes(_fetch(url))
                        dest.with_name(dest.name + ".json").write_text(meta)
                elif host in REDDIT_LINKED:
                    _redgifs(url, p["id"], incoming, meta)
            except (OSError, subprocess.SubprocessError) as e:
                print(f"follow: reddit post {p['id']}: {e}", flush=True)
    seen_file.write_text("\n".join((seen + new)[-SEEN_KEEP:]))
    return "; ".join(errors)[:200] if errors and not new else None


def _redgifs(url: str, post_id: str, incoming: Path, meta: str) -> None:
    """A redgifs clip a Reddit post links to, with the post's details (gallery-dl reads redgifs'
    own API)."""
    folder = incoming / f".redgifs-{post_id}"
    subprocess.run(["gallery-dl", "--config-ignore", "-D", str(folder), "-o", f"filesize-max={MAX_SIZE}",
                    "-o", "extractor.redgifs.format=[\"hd\",\"sd\"]", url], capture_output=True, timeout=600)
    clips = sorted(f for f in folder.iterdir() if f.suffix.lower() in VIDEOS) if folder.is_dir() else []
    for n, f in enumerate(clips, 1):              # (redgifs' are .m4v)
        dest = incoming / f"{post_id}_{n}{f.suffix.lower()}"
        shutil.move(f, dest)
        dest.with_name(dest.name + ".json").write_text(meta)
    shutil.rmtree(folder, ignore_errors=True)


def _post(source: str, md: dict) -> dict:
    """A downloaded file's post: its id, who posted it, where, what they wrote, the link and when."""
    if source == "x":
        author = md.get("author") or {}
        return {"post_id": str(md["tweet_id"]), "author": author.get("name") or "", "place": None,
                "text": md.get("content") or "", "posted_at": str(md.get("date") or ""),
                "link": f"https://x.com/{author.get('name')}/status/{md['tweet_id']}"}
    p = md.get("_parent") or md
    return {"post_id": str(p["id"]), "author": p.get("author") or "", "place": p.get("subreddit"),
            "text": p.get("title") or "", "posted_at": str(p.get("date") or ""),
            "link": "https://www.reddit.com" + p["permalink"] if p.get("permalink") else None}


def _frames(path: Path) -> list[Image.Image]:
    """A picture, or VIDEO_FRAMES frames spread over a video; at most CHECK_SIDE."""
    if path.suffix.lower() in IMAGES:
        with Image.open(path) as im:
            frames = [im.convert("RGB")]
    else:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        length = float(out) if out and out != "N/A" else 0.0
        frames = []
        for i in range(VIDEO_FRAMES):
            at = length * (i + 0.5) / VIDEO_FRAMES
            png = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{at:.2f}", "-i", str(path), "-frames:v", "1",
                                  "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, timeout=120).stdout
            if png:
                import io
                frames.append(Image.open(io.BytesIO(png)).convert("RGB"))
        if not frames:
            raise ValueError("no frames could be read")
    for f in frames:
        f.thumbnail((CHECK_SIDE, CHECK_SIDE))
    return frames


def _problem(vision, cfg, frames) -> tuple[str, str] | None:
    from . import safety
    from .checks import face_ages, problem
    a = vision.analyze(frames)
    photo = safety.photo_signs(a.general, a.medium_probs) is not None
    reason = problem(a, "photo" if photo else "drawing", frames, cfg, strict=True)
    if reason or photo:
        return reason
    ages = face_ages(frames, cfg)      # a drawing that's close to a photo gets the estimate too
    if ages and min(ages) < cfg.photo_min_age:
        return "age-estimate", f"{min(ages):.0f}"
    return None


def check_new(conn, source: str, incoming: Path, media: Path, vision, cfg) -> tuple[int, int]:
    """The downloaded files, checked and kept or deleted, post by post: (kept, dropped). If a
    job or training starts meanwhile it stops, and the rest wait in incoming for next time."""
    from .follow import busy
    for meta in incoming.glob("*.json"):       # details whose file is gone
        if not meta.with_suffix("").exists():
            meta.unlink()
    posts: dict[str, dict] = {}
    for f in sorted(incoming.iterdir()):
        if not f.is_file() or f.suffix == ".json":
            continue
        if f.suffix.lower() not in IMAGES | VIDEOS:     # nothing the page can show
            f.unlink()
            continue
        meta = f.with_name(f.name + ".json")
        try:
            post = _post(source, json.loads(meta.read_text()))
        except (OSError, ValueError, KeyError) as e:
            print(f"follow: {source}: {f.name} has no details ({e}); left out", flush=True)
            f.unlink(missing_ok=True)
            continue
        posts.setdefault(post["post_id"], {**post, "files": []})["files"].append(f)
    kept = dropped = 0
    for pid, post in posts.items():
        if busy(conn, cfg.data_dir):
            print(f"follow: {source}: stopped for a job or training; the rest next time", flush=True)
            break
        reason, frames_of = None, {}
        for f in post["files"]:
            try:
                frames_of[f] = _frames(f)
                reason = _problem(vision, cfg, frames_of[f])
            except (OSError, ValueError, subprocess.SubprocessError) as e:
                reason = ("unreadable", str(e)[:100])
            if reason:
                break
        for f in post["files"]:
            f.with_name(f.name + ".json").unlink(missing_ok=True)
        if reason:
            dropped += 1
            for f in post["files"]:
                f.unlink(missing_ok=True)
            print(f"follow: {source} post {pid} dropped: {reason[0]} ({reason[1]})", flush=True)
            continue
        folder = media / source / pid
        folder.mkdir(parents=True, exist_ok=True)
        items = []
        for f in post["files"]:
            dest = folder / f.name
            shutil.move(f, dest)
            # A GIF shows as a picture (it plays itself) but is checked frame by frame like a video.
            item = {"file": str(dest.relative_to(media)), "kind": "video" if f.suffix.lower() in VIDEOS - {".gif"} else "image"}
            if item["kind"] == "video":
                poster = dest.with_suffix(".poster.jpg")
                frames_of[f][0].save(poster, quality=85)
                item["poster"] = str(poster.relative_to(media))
            items.append(item)
        with conn:
            conn.execute("INSERT OR IGNORE INTO follow_posts(source, post_id, author, place, text, link, posted_at, media)"
                         " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (source, pid, post["author"], post["place"], post["text"][:2000], post["link"], post["posted_at"],
                          json.dumps(items)))
        kept += 1
    return kept, dropped


def expire(conn, media: Path) -> None:
    with conn:
        old = conn.execute("SELECT id, source, post_id FROM follow_posts WHERE added_at < datetime('now', ?)",
                           (f"-{KEEP_DAYS} days",)).fetchall()
        for pid, source, post_id in old:
            shutil.rmtree(media / source / post_id, ignore_errors=True)
            conn.execute("DELETE FROM follow_posts WHERE id = ?", (pid,))


def main() -> None:
    import torch
    from .config import Config, need
    from .db import connect
    from .vision import Vision
    torch.set_num_threads(int(need("FOLLOW_THREADS")))
    cfg = Config()
    conn = connect(cfg.db_path)
    root = cfg.data_dir / "generated" / "follow"
    media = root / "media"
    status = {"at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")}
    vision = None
    try:
        for source in FEEDS:
            why = _signed_in(source)
            if why:
                status[source] = {"error": why}
                continue
            incoming = root / "incoming" / source
            error = download(source, incoming, root / f"{source}.archive")
            if error:
                status[source] = {"error": f"{FEEDS[source]['name']}: {error}"}
                continue
            if vision is None and any(incoming.iterdir()):
                vision = Vision(cfg.models_dir)
            kept, dropped = check_new(conn, source, incoming, media, vision, cfg) if vision else (0, 0)
            status[source] = {"kept": kept, "dropped": dropped}
            print(f"follow: {source}: {kept} new posts, {dropped} dropped by the checks", flush=True)
        expire(conn, media)
    finally:
        if vision is not None:
            vision.close()
        tmp = root / "feeds.tmp"
        tmp.write_text(json.dumps(status))
        tmp.replace(root / "feeds.json")

