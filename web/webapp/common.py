"""What the web app's parts share: its settings (from the environment), the database, the page's
security policy, and small helpers.
"""
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"web: {name} is not set")
    return value


DATA = Path(required("DATA_DIR"))
STATE = required("STATE_DIR")
GENERATED = DATA / "generated"
DB_PATH = DATA / "feed.db"
WEB = Path(__file__).resolve().parent.parent       # web/: the page, its static files, the vendor scripts
PAGE = WEB / "index.html"
STATIC = (WEB / "static").resolve()     # its style and scripts


# Where the page is served from, as the reverse proxy says (X-Forwarded-Prefix: e.g. Caddy's
# handle_path strips it, so the page needs it for its own links); none: the site's root.
PREFIX = re.compile(r"^(?:/[A-Za-z0-9._~-]+)*$")


PAGE_SIZE = 30
FOLLOW = GENERATED / "follow"
FEED_SOURCES = ("x", "bsky", "reddit", "e621")
FEED_MODES = ("following", "foryou")   # your follows; X's For you and Reddit's Best; what you saved
LIVE_DAYS = 28         # live times this far back give a room's usual hours
ROOM = re.compile(r"^[a-z0-9_]{1,64}$")
# The one thing from elsewhere a page may load: a live room's video, straight from Chaturbate's
# video servers (the Live tab's player; hls.js, served from here, plays it through blob: URLs).
LIVE_VIDEO = "https://*.live.mmcdn.com"
LIVE_INFO = "https://chaturbate.com/api/chatvideocontext/{}/"
# And the live Feed's pictures and videos, straight from the sites (livefeeds; no referrer is sent).
FEED_IMAGES = ("https://pbs.twimg.com https://i.redd.it https://preview.redd.it https://external-preview.redd.it"
               " https://styles.redditmedia.com https://a.thumbs.redditmedia.com https://b.thumbs.redditmedia.com"
               " https://*.xvideos-cdn.com"
               " https://i.imgur.com https://static1.e621.net https://media.redgifs.com https://*.redgifs.com"
               " https://cdn.bsky.app https://video.bsky.app https://multporn.net")
FEED_VIDEO = ("https://video.twimg.com https://v.redd.it https://preview.redd.it https://i.imgur.com"
              " https://static1.e621.net https://media.redgifs.com https://*.redgifs.com https://video.bsky.app"
              " https://*.xvideos-cdn.com")       # (xvideos' files, played in dreamfeed's own player)
CSP = (f"default-src 'self'; img-src 'self' data: {FEED_IMAGES}; style-src 'self' 'unsafe-inline'; "
       f"media-src 'self' blob: {LIVE_VIDEO} {FEED_VIDEO}; connect-src 'self' {LIVE_VIDEO} https://v.redd.it https://video.bsky.app https://*.xvideos-cdn.com; worker-src 'self' blob:; frame-src 'none'; "
       "script-src 'self' 'unsafe-inline'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    # The worker owns the schema; this one table is created here too so likes work
    # even before the worker's next start.
    conn.execute("""CREATE TABLE IF NOT EXISTS feedback (
        generation_id INTEGER PRIMARY KEY REFERENCES generations(id),
        action TEXT NOT NULL, liked_file TEXT,
        at TEXT NOT NULL DEFAULT (datetime('now')))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY, params TEXT NOT NULL, status TEXT NOT NULL, night TEXT, message TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')), finished_at TEXT)""")
    # and these, so the live Feed's Saved and Discover work before it too (as in the worker's db.py)
    conn.execute("""CREATE TABLE IF NOT EXISTS saved_posts (id TEXT PRIMARY KEY, source TEXT NOT NULL, data TEXT NOT NULL,
        saved_at TEXT NOT NULL DEFAULT (datetime('now')), status TEXT NOT NULL DEFAULT 'queued', files TEXT, error TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS x_seen (handle TEXT NOT NULL COLLATE NOCASE, kind TEXT NOT NULL, post TEXT NOT NULL,
        by TEXT, at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY (handle, kind, post))""")
    if not _migrated:            # (once a start) links found across sites: where each came from (linking.py)
        _migrated.append(True)
        conn.execute("""CREATE TABLE IF NOT EXISTS links (room TEXT NOT NULL, source TEXT NOT NULL, handle TEXT NOT NULL,
            state TEXT NOT NULL, via TEXT, PRIMARY KEY (room, source, handle))""")
        if "via" not in {r[1] for r in conn.execute("PRAGMA table_info(links)")}:
            conn.execute("ALTER TABLE links ADD COLUMN via TEXT")
        conn.execute("CREATE TABLE IF NOT EXISTS link_checks (room TEXT PRIMARY KEY, at TEXT NOT NULL, found TEXT)")
        # rooms recorded for one stream only (dvr_action "once"): listed = on the recorder's list
        # before (paused again after; else taken off), seen = its recording started, quiet = since when it's stopped
        # posts shown to you where something new is wanted (For you, More videos): when first shown
        conn.execute("CREATE TABLE IF NOT EXISTS shown (id TEXT PRIMARY KEY, at REAL NOT NULL)")
        conn.execute("""CREATE TABLE IF NOT EXISTS dvr_once (room TEXT PRIMARY KEY, listed INTEGER NOT NULL,
            seen INTEGER NOT NULL DEFAULT 0, quiet REAL, at REAL NOT NULL)""")
        conn.commit()
    return conn


_migrated: list = []


X_HANDLE = re.compile(r"^@?([A-Za-z0-9_]{1,15})$")
REDDIT_USER = re.compile(r"^(?:u/|/u/)?([A-Za-z0-9_-]{3,20})$")
_cache: dict[str, tuple[float, object]] = {}      # Chaturbate answers and bios, briefly


def _cached(key: str, ttl: float, fetch):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    value = fetch()
    if len(_cache) > 500:
        _cache.clear()
    _cache[key] = (time.time(), value)
    return value


def _unix(utc: str) -> int:
    import calendar
    return calendar.timegm(time.strptime(utc, "%Y-%m-%d %H:%M:%S"))


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


MAX_BODY = 16 * 1024 * 1024   # a request's size
