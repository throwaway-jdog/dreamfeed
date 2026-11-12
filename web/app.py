"""dreamfeed feed page. Everything except the sign-in page needs a signed-in session (formlogin).

GET  /                  the page
GET  /api/feed          ?view=feed|liked&medium=all|anime|furry&persona=HANDLE&offset=N
GET  /api/personas      the fictional posters, with post and like counts
GET  /avatar/<handle>   profile picture
GET  /api/summary       counts and the last run, for the header
GET  /thumb/<id>        small JPEG for the grid
GET  /img/<id>          full image for the viewer
GET  /api/dashboard     queue and recent runs
GET  /api/following     the Chaturbate rooms you follow, live first (kept by the follow service)
GET  /follow/thumb/chaturbate/<name>.jpg   a live room's last thumbnail
GET  /api/live/stream    ?name=ROOM  a followed room's live video (HLS address), or why there isn't one
GET  /api/live/videos    ?name=ROOM  your own videos of a room you follow (CB_VIDEOS), newest first
GET  /cb-videos/<room>/<path>   one of them;  /cb-videos/poster/<key>.jpg  its poster
GET  /api/discover/cb   ?mode=foryou|top|search&q=WORDS&gender=f|m|c|t&offset=N  live rooms you don't follow
GET  /api/discover/x    X accounts you might like: linked from your rooms, mentioned by your follows
GET  /api/reddit/browse  ?sub=NAME&sort=hot|new|top&after=A  Browse now: a subreddit as it is now (live)
GET  /api/reddit/browses   the last few subreddits browsed
GET  /api/person/posts  ?source=x|bsky|reddit|e621&handle=H&cursor=C  someone's latest posts, live (their profile)
GET  /cb-thumb/<room>.jpg  a discovered room's thumbnail (fetched from Chaturbate)
GET  /api/signins      your sign-ins to the sites (cookies.py): which are set, when they run out (never the values)
GET  /reddit/login     Sign in with Reddit (your app's keys from the dashboard): off to reddit.com to approve it,
GET  /reddit/callback  and back here, where the sign-in is kept
POST /api/signins      {"site": "x"|"chaturbate", "cookies": TEXT} set them (a cookies.txt or JSON export, or a
                        Cookie header) and check they work; {"site", "forget": true} drop the dashboard's;
                        {"site": "reddit", "client_id", "client_secret"} your Reddit app's keys;
                        {"site": "e621", "username", "api_key"} your e621 account (checked before it's kept);
                        {"site": "bsky", "identifier", "password"} your Bluesky handle and an app password (the same);
                        {"site", "from_browser": true} take them from the server's browser (BROWSER_PROFILE)
POST /api/e621/vote    {"id": "e621:ID", "score": 1|-1} vote on it as you (signed in to e621; the same again takes it back)
POST /api/browser/start  start the server's browser (it stops itself when no one's using it)
GET  /api/auth-check   200 when signed in here (the proxy asks before letting you into the server's browser)
POST /api/dvr           {"name": ROOM, "action": "record"|"once"|"stop"|"pause"|"remove"}  your recorder (streamonitor), for that room:
                        record = all their streams, once = this stream (or the next) only, stop = end either
GET  /api/reddit/random ?not=SUB  a random subreddit from RANDOM_SUBREDDITS_URL's list that has posts now
GET  /api/videos/more  ?id=reddit:ID|e621:ID&cursor=C  more videos after that one: its subreddit, your subscriptions (Reddit); its search, yours (e621)
GET  /api/x/related    ?id=TWEET&handle=H&cursor=C  the videos X shows after that one (its full-screen player's swipe-up feed)
GET  /api/redgifs      ?name=PROFILE&page=N  a RedGifs creator's clips (a room's linked one), live; /api/redgifs/clip?id=ID one
POST /api/profile/relink {"room"}  look for the room's accounts across sites again (linking.py)
GET  /api/xvideos      ?name=PROFILE&page=N  an xvideos profile's videos (a room's linked one), live
GET  /api/post         ?id=x:ID|reddit:ID|e621:ID  one post (its own page): your kept copy if you saved it, else live
GET  /api/post/comments ?id=x:ID|reddit:ID|e621:ID  a post's comments, live from its site
GET  /api/profile       ?room=ROOM | ?x=HANDLE | ?reddit=NAME | ?e621=ARTIST  one profile across sites
GET  /vendor/hls.min.js the Live player's HLS library (hls.js, Apache 2.0)
GET  /api/comics/search ?q=TEXT&page=N&site=multporn|e621  comics matching TEXT (title, link, cover), to import
GET  /comic-search/thumb ?u=URL  a search result's cover, fetched from multporn
GET  /api/following/settings  the subreddits and users read for the Feed, and how many top posts a day
POST /api/following/settings  {"reddit": {"follow": ["r/name", "u/name"], "top": N}} or
                        {"e621": {"searches": ["tag tag", ...], "top": N}} change them
GET  /api/following/posts  ?mode=following|foryou&source=all|x,bsky,reddit,e621&cursor=C&tags=T  the Feed, live from the sites
                        (source: all, or the sites you picked, with commas)
                           (tags: e621 only shows posts with them)
                        (its pictures and videos load from them); what you save is in Saved (/api/feed?view=liked)
GET  /api/personas/edit every persona as stored in data/personas.json, plus the trained styles
POST /api/personas/save {"persona": {...}, "original": HANDLE|null} add or change one (checked first)
POST /api/personas/delete  {"handle": H} remove one; their posts leave the timeline
POST /api/personas/avatar  {"handle": H} new profile picture the next time they post
POST /api/personas/draft   {"description": "..."} have the worker draft a whole persona from it
GET  /api/personas/draft   ?job=N its progress, and the draft when ready (opened in the editor)
GET  /api/styles        trained and in-progress style LoRAs
POST /api/styles/train  {"name", "medium", "source", "limit", "steps", "videos"} download, check and train one
                        (videos: the artist only posts animations; frames of them are the pictures)
POST /api/styles/cancel {"name": N} stop a style job
POST /api/feedback      {"id": N, "action": "like"|"skip"|"clear"}
POST /api/generate      {"images": N, "keep": K, "mediums": [...], "personas": [...]} queue a generation run
POST /api/cancel        {"night": "..."} or {"job": N} stop a run or queued request
POST /api/comics/update {"id": N} look for new pages of an imported comic now
POST /api/live/highlights {"name": ROOM, "path": P, "keep": 0.1-0.5} cut one of a room's videos down to its action
POST /api/live/delete   {"name": ROOM, "path": P} a room's video into the trash ({"undo": token})
POST /api/live/restore  {"undo": token} put it back
POST /api/profile/link  {"room", "source": "x"|"reddit", "handle", "remove": bool} link or unlink an account
POST /api/following/save {"post": {...}, "save": bool} keep a post in Saved, its files downloaded in full quality
                        (the follow service; and saved on Reddit too, for Reddit's)
GET  /saved-media/<source>/<post>/<file>  a saved post's kept picture or video
POST /api/saved/import  {} bring your X bookmarks and Reddit saved posts into Saved (in the background)
GET  /api/saved/import  how that went, and how many saved posts' files are kept
POST /api/live/follow   {"name": ROOM, "follow": bool} follow or unfollow it on Chaturbate
POST /api/animate       {"id": N, "prompt": "..."} or {"count": N} make Wan 2.2 clips from feed images;
                        {"id": N, "scene": true} makes a ~1 minute scene from a post with two characters
(POSTs are JSON only.)
"""
import base64
import json
import os
import random
import re
import shutil
import sqlite3
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import dvr
import formlogin
import formlogin.httpserver

from dreamfeed import acts, cbprofile, cbvideos, cookies, e621, linking, livefeeds, personas as people, safety, savedposts   # the worker's own rules (see Dockerfile)


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"web: {name} is not set")
    return value


DATA = Path(required("DATA_DIR"))
STATE = required("STATE_DIR")
GENERATED = DATA / "generated"
LIKED = DATA / "liked"
DB_PATH = DATA / "feed.db"
PAGE = Path(__file__).with_name("index.html")
# Each part of the page has its own address (the page reads it and opens that part):
PAGES = {"home", "feed", "saved", "live", "comics", "dashboard", "personas", "p", "item", "room", "watch",
         "x", "u", "r", "e621", "post", "xvideos", "redgifs", "videos", "bsky"}
# Where the page is served from, as the reverse proxy says (X-Forwarded-Prefix: e.g. Caddy's
# handle_path strips it, so the page needs it for its own links); none: the site's root.
PREFIX = re.compile(r"^(?:/[A-Za-z0-9._~-]+)*$")
PERSONAS = DATA / "personas.json"
LORA_DIR = Path(required("LORA_DIR"))
GENERATE_WINDOW = required("GENERATE_WINDOW")
MAX_IMAGES = 400
PORT = 8000
PAGE_SIZE = 30
MEDIUMS = ("anime", "furry")
HANDLE = re.compile(r"^[a-z0-9_]{2,20}$")
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
               " https://cdn.bsky.app https://video.bsky.app")
FEED_FRAMES = "https://www.xvideos.com"     # xvideos' own player, for a profile's xvideos tab
FEED_VIDEO = ("https://video.twimg.com https://v.redd.it https://preview.redd.it https://i.imgur.com"
              " https://static1.e621.net https://media.redgifs.com https://*.redgifs.com https://video.bsky.app")
CSP = (f"default-src 'self'; img-src 'self' data: {FEED_IMAGES}; style-src 'self' 'unsafe-inline'; "
       f"media-src 'self' blob: {LIVE_VIDEO} {FEED_VIDEO}; connect-src 'self' {LIVE_VIDEO} https://v.redd.it https://video.bsky.app; worker-src 'self' blob:; frame-src {FEED_FRAMES}; "
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


def clip_seconds(checkpoint: str | None) -> int:
    """A clip's length: scenes carry it in their label ("... 55s"), the rest are 5 seconds."""
    m = re.search(r" (\d+)s$", checkpoint or "")
    return int(m.group(1)) if m else 5


def item(row) -> dict:
    return {"id": row["id"], "night": row["night"], "medium": row["medium"], "kind": row["kind"],
            "score": round(row["score"] or 0, 3), "liked": row["action"] == "like",
            "animated": bool(row["animated"]), "caption": row["caption"] or "",
            "seconds": clip_seconds(row["checkpoint"]) if row["kind"] == "video" else None,
            "posted": row["posted_at"] or row["created_at"],
            "persona": {"handle": row["persona"], "name": row["name"] or row["persona"],
                        "avatar": bool(row["avatar"])} if row["persona"] else None}


def feed(view: str, medium: str, offset: int, persona: str = "", gid: int | None = None) -> dict:
    """A page of the persona feed; gid: just that post (its own page), unless you skipped it."""
    where, args = [], []
    if gid is not None:
        where.append("g.id = ? AND g.status = 'feed' AND (f.action IS NULL OR f.action = 'like')")
        args.append(gid)
        view, medium, persona = "item", "", ""
    if medium in MEDIUMS:
        where.append("g.medium = ?")
        args.append(medium)
    if persona:
        where.append("g.persona = ?")
        args.append(persona)
    if view == "liked":
        return saved_view(medium, offset)
    elif view == "item":
        order = "g.id"
    else:   # the timeline: persona posts only (v1 images stay reachable from Liked)
        where.append("g.status = 'feed' AND p.active = 1 AND (f.action IS NULL OR f.action = 'like')")
        order = "coalesce(g.posted_at, g.created_at) DESC, g.id DESC"
    sql = (f"SELECT g.id, g.night, g.medium, g.score, g.kind, g.caption, g.persona, g.posted_at, g.created_at,"
           f" g.checkpoint,"
           f" f.action, p.name, p.avatar,"
           f" EXISTS(SELECT 1 FROM generations v WHERE v.source_generation = g.id AND v.kind = 'video'"
           f"        AND v.status IN ('queued', 'generated', 'feed')) AS animated FROM generations g"
           f" LEFT JOIN feedback f ON f.generation_id = g.id LEFT JOIN personas p ON p.handle = g.persona"
           f" WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ? OFFSET ?")
    try:
        with db() as conn:
            rows = conn.execute(sql, (*args, PAGE_SIZE + 1, offset)).fetchall()
    except sqlite3.OperationalError:   # worker hasn't created its tables yet
        return {"items": [], "more": False}
    return {"items": [item(r) for r in rows[:PAGE_SIZE]], "more": len(rows) > PAGE_SIZE}


SAVED_SOURCES = ("all", "personas", "x", "bsky", "reddit", "e621")


def saved_view(medium: str, offset: int, source: str = "all") -> dict:
    """Saved: the persona posts you liked and the Feed posts you saved, newest first, as
    {"items": [an item, or {"post": a Feed post}]}. source: all, personas (the liked ones) or a
    site's; a medium (anime, furry) is the personas' only."""
    if source not in SAVED_SOURCES:
        raise ValueError("bad source")
    gen_where, args = "f.action = 'like'", []
    if medium in MEDIUMS:
        gen_where += " AND g.medium = ?"
        args.append(medium)
    posts = ""
    if medium not in MEDIUMS and source != "personas":
        posts = " UNION ALL SELECT 'post', id, saved_at FROM saved_posts WHERE status != 'removed'"
        if source != "all":
            posts += " AND source = ?"
    if source not in ("all", "personas"):
        gen_where += " AND 0"
    args += [source] if posts and source != "all" else []
    try:
        with db() as conn:
            keys = conn.execute(f"SELECT 'gen' AS k, CAST(g.id AS TEXT) AS key, f.at AS at FROM feedback f JOIN generations g"
                                f" ON g.id = f.generation_id WHERE {gen_where}{posts} ORDER BY at DESC LIMIT ? OFFSET ?",
                                (*args, PAGE_SIZE + 1, offset)).fetchall()
            more, keys = len(keys) > PAGE_SIZE, keys[:PAGE_SIZE]
            gids = [int(k["key"]) for k in keys if k["k"] == "gen"]
            gens = {r["id"]: item(r) for r in conn.execute(
                "SELECT g.id, g.night, g.medium, g.score, g.kind, g.caption, g.persona, g.posted_at, g.created_at, g.checkpoint,"
                " f.action, p.name, p.avatar,"
                " EXISTS(SELECT 1 FROM generations v WHERE v.source_generation = g.id AND v.kind = 'video'"
                "        AND v.status IN ('queued', 'generated', 'feed')) AS animated FROM generations g"
                " LEFT JOIN feedback f ON f.generation_id = g.id LEFT JOIN personas p ON p.handle = g.persona"
                f" WHERE g.id IN ({','.join('?' * len(gids)) or 'NULL'})", gids)}
            pids = [k["key"] for k in keys if k["k"] == "post"]
            saved = {r["id"]: _saved_json(r) for r in conn.execute(
                f"SELECT * FROM saved_posts WHERE id IN ({','.join('?' * len(pids)) or 'NULL'})", pids)}
    except sqlite3.OperationalError:   # worker hasn't created its tables yet
        return {"items": [], "more": False}
    out = [gens.get(int(k["key"])) if k["k"] == "gen" else ({"post": saved[k["key"]]} if k["key"] in saved else None) for k in keys]
    return {"items": [x for x in out if x], "more": more}


def personas() -> dict:
    try:
        with db() as conn:
            rows = conn.execute(
                "SELECT p.handle, p.name, p.medium, p.bio, p.avatar IS NOT NULL AS avatar,"
                " (SELECT count(*) FROM generations g WHERE g.persona = p.handle AND g.status = 'feed') AS posts,"
                " (SELECT count(*) FROM generations g JOIN feedback f ON f.generation_id = g.id"
                "  WHERE g.persona = p.handle AND f.action = 'like') AS likes"
                " FROM personas p WHERE p.active = 1 ORDER BY p.name").fetchall()
    except sqlite3.OperationalError:   # worker hasn't created its tables yet
        return {"personas": []}
    return {"personas": [dict(r) | {"avatar": bool(r["avatar"])} for r in rows]}


def avatar_path(handle: str) -> Path | None:
    if not HANDLE.match(handle):
        return None
    with db() as conn:
        row = conn.execute("SELECT avatar FROM personas WHERE handle = ?", (handle,)).fetchone()
    if not row or not row["avatar"]:
        return None
    path = (GENERATED / row["avatar"]).resolve()
    return path if path.is_relative_to(GENERATED.resolve()) and path.is_file() else None


def summary() -> dict:
    out = {"unrated": 0, "liked": 0, "last_run": None, "live": 0}
    try:
        with db() as conn:
            out["unrated"] = conn.execute(
                "SELECT count(*) FROM generations g LEFT JOIN feedback f ON f.generation_id = g.id"
                " JOIN personas p ON p.handle = g.persona"
                " WHERE g.status = 'feed' AND p.active = 1 AND f.action IS NULL").fetchone()[0]
            out["liked"] = conn.execute("SELECT count(*) FROM feedback WHERE action = 'like'").fetchone()[0]
            run = conn.execute("SELECT night, status, finished_at FROM runs WHERE night NOT LIKE 'test-%'"
                               " ORDER BY started_at DESC LIMIT 1").fetchone()
            if run:
                out["last_run"] = dict(run)
            out["live"] = conn.execute("SELECT count(*) FROM follows WHERE live = 1").fetchone()[0]
    except sqlite3.OperationalError:    # (follows: the follow service hasn't started yet)
        pass
    return out


def following() -> dict:
    """The rooms you follow, live ones first (most watched first), each with its live times of
    the last LIVE_DAYS days as [start, end] Unix seconds (the page works out the usual hours in
    your own time)."""
    rooms, times = [], {}
    try:
        with db() as conn:
            for r in conn.execute("SELECT source, name, start_at, end_at FROM live_times"
                                  " WHERE end_at >= datetime('now', ?)", (f"-{LIVE_DAYS} days",)):
                times.setdefault((r["source"], r["name"]), []).append([_unix(r["start_at"]), _unix(r["end_at"])])
            follows = conn.execute("SELECT * FROM follows ORDER BY name").fetchall()
            videos = cbvideos.scan(r["name"] for r in follows if r["source"] == "chaturbate")
            for r in follows:
                thumb = FOLLOW / r["source"] / f"{r['name']}.jpg"
                rooms.append({"source": r["source"], "name": r["name"], "live": bool(r["live"]),
                              "info": json.loads(r["info"]) if r["info"] else {},
                              "last_live": _unix(r["last_live"]) if r["last_live"] else None,
                              "thumb": f"follow/thumb/{r['source']}/{r['name']}.jpg?t={int(thumb.stat().st_mtime)}"
                                       if thumb.is_file() else None,
                              "times": times.get((r["source"], r["name"]), []),
                              "videos": len(videos.get(r["name"], [])) if r["source"] == "chaturbate" else 0})
    except sqlite3.OperationalError:    # the follow service hasn't started yet
        pass
    rooms.sort(key=lambda r: (not r["live"], -(r["info"].get("viewers") or 0) if r["live"] else -(r["last_live"] or 0)))
    rec, once = _dvr(), _once_rooms()
    for r in rooms:
        r["dvr"] = _with_once(rec.get("rooms", {}).get(r["name"]), r["name"], once) if r["source"] == "chaturbate" else None
    return {"rooms": rooms, "status": read_json(FOLLOW / "status.json"), "feeds": read_json(FOLLOW / "feeds.json"),
            "dvr": {"on": dvr.enabled(), "free": rec.get("free"), "error": rec.get("error")}}


def _dvr() -> dict:
    """Your recorder's list (dvr.py), or {"error"} when it doesn't answer; {} when it's off."""
    try:
        return dvr.rooms()
    except (LookupError, ValueError) as e:
        return {"error": str(e)[:200]}


# Sign-ins (the dashboard): the sites' cookies, set by pasting an export (cookies.py). The files
# mounted for them (X_COOKIES_FILE, CHATURBATE_COOKIES_FILE) are used until then.
# The server's own browser (the browser service, a Firefox you sign in to the sites in, opened
# from the Dashboard at BROWSER_URL): its profile, where Take its cookies reads them.
BROWSER_PROFILE = os.environ.get("BROWSER_PROFILE", "").strip()
BROWSER_URL = os.environ.get("BROWSER_URL", "").strip()
# It runs only when needed: started for you (Sign in on the server's browser) or for a refresh,
# stopped when no one's watching it. dreamfeed only asks, leaving a file in BROWSER_POWER_DIR;
# systemd on the host starts and stops it (browserpower/install.sh): nothing here has a say
# over Docker. BROWSER_SCREEN: its page (host:port), to tell when it's up.
BROWSER_POWER_DIR = os.environ.get("BROWSER_POWER_DIR", "").strip()
BROWSER_SCREEN = os.environ.get("BROWSER_SCREEN", "").strip()
BROWSER_REFRESH = 86400    # cookies taken from it are taken again (it opening the sites) this often
BROWSER_LOAD = 90          # seconds it's given to open the sites before they're taken
BROWSER_TICK = 60
_browser = {"refresh": {}}   # site -> {"at", "error"}: its last refresh
MOUNTED_COOKIES = {"x": os.environ.get("X_COOKIES", "").strip() or None,
                   "chaturbate": os.environ.get("CHATURBATE_COOKIES", "").strip() or None}


def _signin_check(site: str) -> str | None:
    """Whether the site takes the cookies now: None when it does, else what's wrong."""
    import http.cookiejar
    import urllib.request
    try:
        if site == "x":
            livefeeds.forget("x:")
            items = livefeeds._x("https://x.com/home", 1, 1, timeout=60)
            return None if any(isinstance(i, list) and i and i[0] == 3 for i in items) else "X showed nothing: the cookies may be out of date"
        file = cookies.path(site, MOUNTED_COOKIES[site])
        if not file:
            return "no cookies set"
        jar = http.cookiejar.MozillaCookieJar(str(file))
        jar.load(ignore_discard=True, ignore_expires=True)
        req = urllib.request.Request("https://chaturbate.com/api/ts/roomlist/room-list/?follow=true&limit=5&offline=true",
                                     headers={"User-Agent": "dreamfeed (personal follow list)", "Accept": "application/json",
                                              "Referer": "https://chaturbate.com/"})
        with urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)).open(req, timeout=30) as r:
            rooms = json.loads(r.read()).get("rooms") or []
        # (signed out, it ignores follow=true and lists everyone's)
        return None if all(x.get("is_following") for x in rooms) else "Chaturbate doesn't see you signed in with these"
    except (LookupError, OSError, ValueError) as e:
        return str(e)[:200]


REDDIT_SCOPES = "identity read mysubreddits save history"     # save: the Save button; history: your saved posts
_reddit_states: dict[str, float] = {}       # sign-ins started (state -> when), each good for 10 minutes
HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}(?::\d{1,5})?$")


def reddit_redirect(headers) -> str:
    """Where Reddit sends you back after you approve: this page's own address (your Reddit app's
    redirect uri must be exactly this)."""
    host = headers.get("X-Forwarded-Host") or headers.get("Host") or ""
    proto = (headers.get("X-Forwarded-Proto") or "https").split(",")[0].strip()
    prefix = (headers.get("X-Forwarded-Prefix") or "").rstrip("/")
    if not HOST.match(host) or proto not in ("http", "https") or not PREFIX.match(prefix):
        raise ValueError("can't tell this page's address")
    return f"{proto}://{host}{prefix}/reddit/callback"


def _reddit_status(headers) -> dict:
    c = cookies.reddit()
    try:
        redirect = reddit_redirect(headers)
    except ValueError:
        redirect = None
    return {"site": "reddit", "name": "Reddit", "from": c["from"], "app": bool(c["client_id"] and c["client_secret"]),
            "client_id": c["client_id"], "signed_in": livefeeds.reddit_ready(), "username": c["username"] or None,
            "redirect": redirect}


def reddit_login_url(headers) -> str:
    c = cookies.reddit()
    if c["from"] != "dashboard" or not c["client_secret"]:
        raise ValueError("set your Reddit app's id and secret first")
    import secrets
    now = time.time()
    for k in [k for k, t in _reddit_states.items() if now - t > 600]:
        _reddit_states.pop(k, None)
    state = secrets.token_urlsafe(16)
    _reddit_states[state] = now
    return "https://www.reddit.com/api/v1/authorize?" + urllib.parse.urlencode(
        {"client_id": c["client_id"], "response_type": "code", "state": state, "redirect_uri": reddit_redirect(headers),
         "duration": "permanent", "scope": REDDIT_SCOPES})


def reddit_callback(query: dict, headers) -> str:
    """Reddit's answer: the sign-in kept (with your username). What to say on the dashboard."""
    import urllib.request
    if query.get("error"):
        return f"Reddit said: {query['error'][:80]}"
    if _reddit_states.pop(query.get("state", ""), 0) < time.time() - 600:
        return "That sign-in had run out: try again"
    c = cookies.reddit()
    auth = "Basic " + base64.b64encode(f"{c['client_id']}:{c['client_secret']}".encode()).decode()
    form = {"grant_type": "authorization_code", "code": query.get("code", ""), "redirect_uri": reddit_redirect(headers)}
    try:
        req = urllib.request.Request("https://www.reddit.com/api/v1/access_token", data=urllib.parse.urlencode(form).encode(),
                                     headers={"User-Agent": livefeeds.REDDIT_AGENT, "Authorization": auth})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
        if not d.get("refresh_token"):
            return f"Reddit refused: {str(d.get('error') or d)[:80]}"
        me = urllib.request.Request("https://oauth.reddit.com/api/v1/me", headers={
            "User-Agent": livefeeds.REDDIT_AGENT, "Authorization": "bearer " + d["access_token"]})
        with urllib.request.urlopen(me, timeout=30) as r:
            name = str(json.load(r).get("name") or "")
    except (OSError, ValueError) as e:
        return f"Reddit didn't answer ({str(e)[:80]})"
    cookies.save_reddit_signin(d["refresh_token"], name if livefeeds.REDDIT_USER.match(name) else "")
    livefeeds.forget()            # (your subscriptions and the rest, read again as you)
    return f"Signed in to Reddit as u/{name}" if name else "Signed in to Reddit"


def _power(action: str) -> dict:
    """The server's browser: {"running", "viewers"}, after asking it to start or stop (a file left in
    BROWSER_POWER_DIR, which systemd on the host acts on: browserpower/) or just as it is now."""
    import socket
    if not BROWSER_POWER_DIR or not os.path.isdir(BROWSER_POWER_DIR):
        raise LookupError("the server's browser can't be started from here (sudo browserpower/install.sh)")
    folder = Path(BROWSER_POWER_DIR)

    def now() -> dict | None:
        d = read_json(folder / "status.json")
        return d if isinstance(d, dict) and time.time() - float(d.get("at") or 0) < 180 else None
    if action == "status":
        d = now()
        if d is None:
            raise LookupError("the server's browser isn't looked after (sudo browserpower/install.sh)")
        return d
    asked = time.time()
    (folder / action).write_text("")
    for _ in range(90):
        time.sleep(1)
        d = now()
        if d and float(d.get("at") or 0) >= int(asked) and not (folder / action).exists():
            if action == "start":
                host, _, port = BROWSER_SCREEN.rpartition(":")
                for _ in range(60):                 # its page answers once its desktop is up
                    try:
                        with socket.create_connection((host, int(port)), timeout=2):
                            return d
                    except OSError:
                        time.sleep(1)
                raise LookupError("the server's browser started, but its page doesn't answer")
            return d
    raise LookupError("the server's browser didn't answer: is browserpower installed? (sudo browserpower/install.sh)")


def browser_start(req: dict) -> dict:
    """Starts the server's browser, for you to use (stopped again once no one's watching)."""
    cookies.firefox_prefs(BROWSER_PROFILE)
    return _power("start")


def _browser_refresh() -> None:
    """Takes again the cookies taken from the server's browser, once a day: it's started out of
    sight, opens the sites (which freshens them), and stopped. Not while you're using it."""
    due = [s for s in cookies.SITES if cookies.status(s).get("browser")
           and time.time() - (cookies.status(s).get("updated") or 0) >= BROWSER_REFRESH
           and time.time() - _browser["refresh"].get(s, {}).get("at", 0) >= BROWSER_REFRESH]
    if not due:
        return
    st = _power("status")
    if st["viewers"]:
        return                     # (you're in it: next time)
    was = st["running"]
    try:
        if not was:
            cookies.firefox_prefs(BROWSER_PROFILE)
            _power("start")
        time.sleep(BROWSER_LOAD)
        for site in due:
            try:
                cookies.from_firefox(site, BROWSER_PROFILE)
                error = _signin_check(site)
            except (ValueError, OSError) as e:
                error = str(e)[:200]
            _browser["refresh"][site] = {"at": time.time(), "error": error}
            print(time.strftime("%F %T"), f"web: {site}'s cookies from the server's browser:", error or "taken again", flush=True)
            if site == "x":
                livefeeds.forget("x:")
    finally:
        if not was:
            _power("stop")        # (it's stopped only if no one's watching it)


def _browser_keeper() -> None:
    """Refreshes the cookies taken from the server's browser (stopping it when unused is the
    host's: browserpower's idle timer)."""
    while True:
        time.sleep(BROWSER_TICK)
        try:
            _browser_refresh()
        except LookupError as e:
            print(time.strftime("%F %T"), f"web: {e}", flush=True)
            time.sleep(BROWSER_TICK * 59)


def _bsky_status() -> dict:
    c = cookies.bsky()
    out = {"site": "bsky", "name": "Bluesky", "from": c["from"], "handle": None, "signed_in": False}
    if c["from"]:
        try:
            sess = livefeeds._bsky_session()
            out.update(signed_in=True, handle=sess.get("handle") or c["identifier"])
        except LookupError as e:
            out["error"] = str(e)[:200]
    return out


def _e621_status() -> dict:
    c = cookies.e621()
    out = {"site": "e621", "name": "e621", "from": c["from"], "username": c["username"] or None, "signed_in": False}
    if c["from"]:
        try:
            me = livefeeds._cached("e621-me", e621.me, 600)
            out.update(signed_in=True, favorites=me["favorites"], blacklist=len(me["blacklist"]))
        except (LookupError, OSError, ValueError) as e:
            out["error"] = str(e)[:200]
    return out


def signins(headers=None) -> dict:
    return {"sites": [{**cookies.status(s, MOUNTED_COOKIES[s]), "refresh": _browser["refresh"].get(s)} for s in cookies.SITES],
            "e621": _e621_status(), "bsky": _bsky_status(),
            "browser": BROWSER_URL if BROWSER_PROFILE and BROWSER_URL else None,
            "reddit": _reddit_status(headers or {})}


def save_signin(req: dict) -> dict:
    """{"site", "cookies": TEXT} keeps them and checks them; {"site", "forget": true} drops them;
    {"site": "reddit", "client_id", "client_secret"} your Reddit app's keys."""
    site = str(req.get("site", ""))
    if site == "bsky":
        if req.get("forget"):
            cookies.forget_bsky()
            livefeeds.forget("bsky:")
            return {"site": _bsky_status()}
        cookies.save_bsky(str(req.get("identifier", "")), str(req.get("password", "")))
        livefeeds.forget("bsky:")
        try:
            livefeeds._bsky_session(fresh=True)        # (checked by signing in now)
        except LookupError as e:
            cookies.forget_bsky()
            raise ValueError(str(e))
        return {"site": _bsky_status()}
    if site == "e621":
        if req.get("forget"):
            cookies.forget_e621()
        else:
            cookies.save_e621(str(req.get("username", "")), str(req.get("api_key", "")))
        livefeeds.forget()
        st = _e621_status()
        if not req.get("forget") and not st["signed_in"]:
            cookies.forget_e621()            # (a key e621 doesn't take isn't kept)
            livefeeds.forget()
            raise ValueError(st.get("error") or "e621 didn't take them")
        return {"site": st}
    if site == "reddit":
        if req.get("forget"):
            cookies.forget_reddit()
        elif req.get("from_env"):          # the keys and sign-in from .env, kept here instead
            env = cookies.reddit()
            if env["from"] != "env":
                raise ValueError("there are no Reddit keys in the environment")
            cookies.save_reddit_app(env["client_id"], env["client_secret"])
            if env["refresh_token"]:
                cookies.save_reddit_signin(env["refresh_token"], env["username"])
        else:
            cookies.save_reddit_app(str(req.get("client_id", "")), str(req.get("client_secret", "")))
        livefeeds.forget()
        return {"ok": True}
    if req.get("from_browser"):
        if not BROWSER_PROFILE:
            raise ValueError("no server browser set up (BROWSER_PROFILE)")
        cookies.from_firefox(site, BROWSER_PROFILE)
        problem = _signin_check(site)
        if site == "x":
            livefeeds.forget("x:")
        return {"site": cookies.status(site, MOUNTED_COOKIES.get(site)), "check": problem}
    if req.get("forget"):
        st = cookies.forget(site)
        return {"site": cookies.status(site, MOUNTED_COOKIES.get(site))}
    cookies.save(site, str(req.get("cookies", "")))
    problem = _signin_check(site)
    if site == "x":
        livefeeds.forget("x:")
    return {"site": cookies.status(site, MOUNTED_COOKIES.get(site)), "check": problem}


DVR_ONCE_POLL = 30        # seconds between looks at the rooms recorded for one stream
DVR_ONCE_GAP = 180        # seconds a once room's recording has stopped before its stream counts as over
                          # (a short drop and the recorder picking it up again isn't the end)


def _once_rooms() -> set:
    try:
        with db() as conn:
            return {r[0] for r in conn.execute("SELECT room FROM dvr_once")}
    except sqlite3.Error:
        return set()


def _with_once(st: dict | None, room: str, once: set) -> dict | None:
    return {**st, "once": room in once} if st else None


def _end_once(room: str, conn) -> dict:
    """A once room done (its stream over, or you stopped it): paused again if it was on the
    recorder's list before, else taken off it. Its recordings stay."""
    row = conn.execute("SELECT listed FROM dvr_once WHERE room = ?", (room,)).fetchone()
    out = dvr.act(room, "pause" if row and row["listed"] else "remove")     # (on failure: tried again)
    conn.execute("DELETE FROM dvr_once WHERE room = ?", (room,))
    conn.commit()
    return out


def dvr_action(req: dict) -> dict:
    """{"name": ROOM, "action"}: tell your recorder (streamonitor). record: all their streams;
    once: only this stream (or their next, when they're not live); stop: end either; pause, remove."""
    name, action = str(req.get("name", "")), str(req.get("action", ""))
    if not ROOM.match(name):
        raise ValueError("bad room")
    if action not in ("record", "once", "stop", "pause", "remove"):
        raise ValueError("bad action")
    with db() as conn:
        had = conn.execute("SELECT listed FROM dvr_once WHERE room = ?", (name,)).fetchone()
        if action == "once":
            listed = had["listed"] if had else int(dvr.rooms().get("rooms", {}).get(name) is not None)
            out = dvr.act(name, "record")
            conn.execute("INSERT OR REPLACE INTO dvr_once (room, listed, seen, quiet, at) VALUES (?, ?, 0, NULL, ?)",
                         (name, listed, time.time()))
            conn.commit()
        elif action == "stop" and had:
            out = _end_once(name, conn)
        else:
            conn.execute("DELETE FROM dvr_once WHERE room = ?", (name,))
            conn.commit()
            out = dvr.act(name, "pause" if action == "stop" else action)
    out["dvr"] = _with_once(out.get("dvr"), name, {name} if action == "once" else set())
    return out


def _dvr_once_watch() -> None:
    """Ends each once room's recording when its stream is over: it was recording, and has
    stopped for DVR_ONCE_GAP. One paused or taken off the list elsewhere is let go."""
    while True:
        time.sleep(DVR_ONCE_POLL)
        try:
            with db() as conn:
                rows = conn.execute("SELECT * FROM dvr_once").fetchall()
                if not rows:
                    continue
                rec = dvr.rooms().get("rooms", {})
                now = time.time()
                for r in rows:
                    st = rec.get(r["room"])
                    if st is None or not st["running"]:
                        conn.execute("DELETE FROM dvr_once WHERE room = ?", (r["room"],))
                    elif st["state"] == "recording":
                        conn.execute("UPDATE dvr_once SET seen = 1, quiet = NULL WHERE room = ?", (r["room"],))
                    elif r["seen"] and r["quiet"] is None:
                        conn.execute("UPDATE dvr_once SET quiet = ? WHERE room = ?", (now, r["room"]))
                    elif r["seen"] and now - r["quiet"] >= DVR_ONCE_GAP:
                        print(time.strftime("%F %T"), f"web: {r['room']}'s stream is over: recorder stops", flush=True)
                        _end_once(r["room"], conn)
                conn.commit()
        except (sqlite3.Error, LookupError, ValueError) as e:
            print(time.strftime("%F %T"), f"web: once recordings: {e}", flush=True)


MULTPORN = "https://multporn.net"
COMIC_PATHS = ("/comics/", "/hentai_manga/")
SEARCH_AGENT = {"User-Agent": "dreamfeed (comic search)"}
_covers: dict[str, bytes] = {}      # search covers already fetched (a few hundred at most)


def comic_search(q: str, page: int, site: str = "multporn") -> dict:
    """multporn's search for q: its comics and manga (not videos or games), each {"title", "url",
    "thumb"}. A search with words the dashboard never takes is refused, and so is a result
    whose title has them."""
    import html
    import urllib.parse
    import urllib.request
    if site == "e621":
        try:
            d = e621.pools(q, page)
        except OSError as e:
            raise LookupError(f"e621 didn't answer ({e})")
        d["results"] = [r for r in d["results"] if not safety.story_blocked(r["title"])]   # (what Import takes)
        for r in d["results"]:
            r["thumb"] = "comic-search/thumb?u=" + urllib.parse.quote(r.pop("cover") or "", safe="") if r.get("cover") else None
        return d
    if site != "multporn":
        raise ValueError("bad site")
    q = q.strip()
    if not 1 <= len(q) <= 100:
        raise ValueError("type what to look for (up to 100 characters)")
    bad = safety.request_blocked(q)
    if bad:
        raise ValueError(f"not something to look for: {', '.join(bad)}")
    url = f"{MULTPORN}/search?" + urllib.parse.urlencode({"search_api_views_fulltext": q, "page": page})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=SEARCH_AGENT), timeout=30) as r:
            page_html = r.read().decode("utf-8", "replace")
    except OSError as e:
        raise LookupError(f"multporn didn't answer ({e})")
    out = []
    for row in re.split(r'<div class="masonry-item views-row', page_html)[1:]:
        # the title's own link; its text can have the searched words in <strong>
        link = re.search(r'views-field-title">\s*<span class="field-content"><a href="([^"]+)">(.*?)</a>', row, re.S)
        img = re.search(r'<img[^>]+src="(https://multporn\.net/sites/default/files/[^"]+)"', row)
        if not link or not link.group(1).startswith(COMIC_PATHS):
            continue
        title = html.unescape(re.sub(r"<[^>]+>", "", link.group(2))).strip()
        if safety.story_blocked(title):     # what Import would refuse isn't offered
            continue
        out.append({"title": title, "url": MULTPORN + link.group(1),
                    "thumb": "comic-search/thumb?u=" + urllib.parse.quote(html.unescape(img.group(1)), safe="") if img else None})
    return {"results": out, "more": f"page={page + 1}" in page_html}


def comic_cover(u: str) -> bytes | None:
    """A search result's cover: multporn's, or the preview of an e621 pool's first post (whose
    tags e621.pools already checked)."""
    import urllib.request
    multporn, e6 = u.startswith(MULTPORN + "/sites/default/files/"), u.startswith("https://static1.e621.net/data/preview/")
    if not (multporn or e6) or ".." in u:
        return None
    if u not in _covers:
        try:
            if e6:
                data = e621.fetch(u, 4 << 20)
            else:
                with urllib.request.urlopen(urllib.request.Request(u, headers=SEARCH_AGENT), timeout=30) as r:
                    data = r.read(4 << 20)
        except (OSError, ValueError):
            return None
        if data[:3] != b"\xff\xd8\xff":     # covers are JPEGs
            return None
        if len(_covers) > 400:
            _covers.clear()
        _covers[u] = data
    return _covers[u]


def live_stream(name: str) -> dict:
    """{"status", "hls", "title", "viewers"}: hls is the room's video while it's a public show, else None."""
    import urllib.parse
    import urllib.request
    if not ROOM.match(name):     # any room (Discover too); only public, age-verified shows play
        raise ValueError("bad room")
    try:
        with urllib.request.urlopen(LIVE_INFO.format(name), timeout=20) as r:
            d = json.load(r)
    except (OSError, ValueError):
        return {"status": "unreachable", "hls": None}
    hls = str(d.get("hls_source") or "")
    u = urllib.parse.urlparse(hls)
    ok = (d.get("room_status") == "public" and d.get("is_age_verified") and u.scheme == "https"
          and (u.hostname or "").endswith(".live.mmcdn.com"))
    return {"status": d.get("room_status") or "offline", "hls": hls if ok else None,
            "title": str(d.get("room_title") or "")[:300], "viewers": d.get("num_viewers")}


def _followed() -> list[str]:
    with db() as conn:
        return [n for (n,) in conn.execute("SELECT name FROM follows WHERE source = 'chaturbate'")]


def live_videos(name: str) -> dict:
    """A followed room's videos from your own folder, newest first, each with its poster and
    length (made by the follow service; until then none). Highlights come just before the video
    they're cut from, and each video has its latest highlights request (job)."""
    if not ROOM.match(name):
        raise ValueError("bad room")
    rooms = _followed()
    if name not in rooms:
        raise LookupError("you don't follow that room")
    index = read_json(cbvideos.posters(DATA) / "index.json") or {}
    with db() as conn:
        jobs = {}
        for r in conn.execute("SELECT path, status, progress, error FROM highlights WHERE room = ? ORDER BY id", (name,)):
            jobs[r["path"]] = {"status": r["status"], "error": r["error"],
                               **(json.loads(r["progress"]) if r["progress"] else {})}
    items = {}
    for v in cbvideos.scan(rooms).get(name, []):
        made = index.get(cbvideos.key(v)) or {}
        high = cbvideos.is_highlight(v["path"])
        title = Path(v["path"]).stem
        if high:
            title = re.sub(r" \[[0-9a-f]{6}\]\.highlights$", "", title, flags=re.I)
        items[v["path"]] = {"path": v["path"], "title": title.replace("_", " "), "size": v["size"], "mtime": v["mtime"],
                            "url": f"cb-videos/{name}/" + urllib.parse.quote(v["path"]),
                            "duration": made.get("duration") or None, "highlight": high,
                            "poster": f"cb-videos/poster/{cbvideos.key(v)}.jpg" if made.get("poster") else None}
    groups = []
    paired = set()
    for v in items.values():
        if v["highlight"]:
            continue
        group = [v]
        h = items.get(cbvideos.highlight_of(v["path"], name))
        if h:
            h["of"] = v["duration"]
            group.insert(0, h)
            paired.add(h["path"])
        v["has_highlight"] = bool(h)
        v["job"] = jobs.get(v["path"])
        groups.append((v["mtime"], group))
    groups += [(v["mtime"], [v]) for v in items.values() if v["highlight"] and v["path"] not in paired]
    groups.sort(key=lambda g: -g[0])
    return {"videos": [v for _, g in groups for v in g], "folder": cbvideos.root() is not None}


def _room_video(req: dict) -> tuple[str, str, Path]:
    name, rel = str(req.get("name", "")), str(req.get("path", ""))
    if not ROOM.match(name):
        raise ValueError("bad room")
    file = cbvideos.file(name, rel, _followed())
    if not file:
        raise LookupError("that video isn't there")
    return name, rel, file


def queue_highlights(req: dict) -> dict:
    """{"name", "path", "keep": 0.1-0.5}: cut the video's highlights (the follow service)."""
    name, rel, _ = _room_video(req)
    keep = float(req.get("keep", 0.25))
    if not 0.05 <= keep <= 0.5:
        raise ValueError("keep is 0.05 to 0.5")
    if cbvideos.is_highlight(rel):
        raise ValueError("that's already highlights")
    with db() as conn:
        if conn.execute("SELECT 1 FROM highlights WHERE path = ? AND status IN ('queued', 'running')", (rel,)).fetchone():
            raise ValueError("already being cut")
        conn.execute("INSERT INTO highlights(room, path, keep) VALUES (?, ?, ?)", (name, rel, keep))
    return {"ok": True}


def delete_room_video(req: dict) -> dict:
    """{"name", "path"}: into the trash (gone after a week); returns the token for Undo."""
    name, rel, file = _room_video(req)
    with db() as conn:
        conn.execute("DELETE FROM highlights WHERE path = ? AND status = 'queued'", (rel,))
        if conn.execute("SELECT 1 FROM highlights WHERE path = ? AND status = 'running'", (rel,)).fetchone():
            raise ValueError("its highlights are being cut: wait for them")
    return {"undo": cbvideos.trash(file)}


def restore_room_video(req: dict) -> dict:
    return {"path": cbvideos.restore(str(req.get("undo", "")))}


FOLLOWING = DATA / "following.json"     # read by the follow service on each round
MAX_FOLLOW = 50
REDDIT_NAME = re.compile(r"^(?:https?://(?:www\.|old\.)?reddit\.com)?/?(?:(r|u|user)/)?([A-Za-z0-9_-]{2,30})/?$")


def follow_settings(subscribed: bool = True) -> dict:
    """The Dashboard's subreddits and e621 searches, and the subscriptions you have on Reddit
    (when signed in as you; asked of Reddit, kept 10 minutes)."""
    d = read_json(FOLLOWING).get("reddit") or {}
    subs = []
    if subscribed and livefeeds.reddit_ready():
        try:
            subs = livefeeds.subscriptions()
        except (LookupError, OSError, ValueError):
            pass
    e = read_json(FOLLOWING).get("e621") or {}
    return {"reddit": {"follow": d.get("follow") or [], "top": d.get("top") or 10,
                       "subscribed": [s for s in subs if isinstance(s, str)] if isinstance(subs, list) else []},
            "e621": {"searches": e.get("searches") or [], "top": e.get("top") or 10}}


def _write_following(data: dict) -> None:
    tmp = FOLLOWING.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(FOLLOWING)


def save_follow_settings(req: dict) -> dict:
    if isinstance(req.get("e621"), dict):
        e = req["e621"]
        if not isinstance(e.get("searches"), list):
            raise ValueError('send {"e621": {"searches": [...], "top": N}}')
        searches = []
        for q in e["searches"]:
            q = " ".join(str(q).split())
            e621.query(q)           # refused: ValueError
            if q.lower() not in {x.lower() for x in searches}:
                searches.append(q)
        if len(searches) > MAX_FOLLOW:
            raise ValueError(f"at most {MAX_FOLLOW}")
        _write_following({**read_json(FOLLOWING), "e621": {"searches": searches,
                                                           "top": int(_num(e.get("top", 10), 1, 100, "top"))}})
        return follow_settings()
    r = req.get("reddit")
    if not isinstance(r, dict) or not isinstance(r.get("follow"), list):
        raise ValueError('send {"reddit": {"follow": [...], "top": N}} or {"e621": {...}}')
    out = []
    for item in r["follow"]:
        m = REDDIT_NAME.match(str(item).strip())
        if not m:
            raise ValueError(f"not a subreddit or user: {str(item)[:40]} (r/name or u/name)")
        name = f"{'u' if m.group(1) in ('u', 'user') else 'r'}/{m.group(2)}"
        if name.lower() not in {x.lower() for x in out}:
            out.append(name)
    if len(out) > MAX_FOLLOW:
        raise ValueError(f"at most {MAX_FOLLOW}")
    top = _num(r.get("top", 10), 1, 100, "top")
    _write_following({**read_json(FOLLOWING), "reddit": {"follow": out, "top": int(top)}})   # (subscribed isn't stored here)
    return follow_settings()


X_SEEN_DAYS = 30       # X accounts in your timelines are remembered this long (Discover)


def _cursor(raw: str) -> dict | None:
    if not raw:
        return None
    try:
        c = json.loads(base64.urlsafe_b64decode(raw.encode() + b"==").decode())
    except (ValueError, UnicodeDecodeError) as e:
        raise ValueError("bad cursor") from e
    if not isinstance(c, dict):
        raise ValueError("bad cursor")
    return c


def _seen(posts: list[dict], users: list[dict]) -> None:
    """Remember who's in your X timelines (Discover) and who they are (profiles)."""
    rows, mentions = [], []
    for p in posts:
        if p["source"] != "x" or p.get("via") not in ("following", "foryou"):
            continue
        tid = p["id"].split(":", 1)[1]
        rows.append((p["author"], p["via"], tid, None))
        if p["via"] == "following":
            mentions += [(h, "mention", tid, p["author"]) for h in p.get("mentions") or []]
    try:
        with db() as conn:
            conn.executemany("INSERT OR IGNORE INTO x_seen(handle, kind, post, by) VALUES (?, ?, ?, ?)", rows + mentions)
            for u in users:
                if u.get("handle"):
                    conn.execute("INSERT INTO x_users(handle, nick, bio, location, followers, following, posts, image_url, updated_at)"
                                 " VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now')) ON CONFLICT(handle) DO UPDATE SET"
                                 " nick = excluded.nick, bio = excluded.bio, location = excluded.location, followers = excluded.followers,"
                                 " following = excluded.following, posts = excluded.posts, image_url = excluded.image_url,"
                                 " updated_at = excluded.updated_at",
                                 (u["handle"], u.get("nick"), u.get("bio"), u.get("location"), u.get("followers"),
                                  u.get("following"), u.get("posts"), u.get("image_url")))
            conn.execute("DELETE FROM x_seen WHERE at < datetime('now', ?)", (f"-{X_SEEN_DAYS} days",))
    except sqlite3.OperationalError:     # the follow service hasn't made the tables yet
        pass


def _mark_saved(posts: list[dict]) -> list[dict]:
    if not posts:
        return posts
    try:
        with db() as conn:
            ids = {r[0] for r in conn.execute(f"SELECT id FROM saved_posts WHERE status != 'removed' AND id IN ({','.join('?' * len(posts))})",
                                              [p["id"] for p in posts])}
    except sqlite3.OperationalError:
        ids = set()
    for p in posts:
        p["saved"] = p["id"] in ids or (p["source"] == "reddit" and p.get("saved", False))
    return posts


SHOWN_AGAIN = 1800        # seconds a post can be shown again (paging back, reloading); after, it's passed over
SHOWN_DAYS = 14           # how long what you were shown is remembered
FRESH_MIN = 6             # For you reads further (FRESH_READS pages at most) until it has this many new posts
FRESH_READS = 3


def _stale(ids) -> set:
    """Those of ids shown to you more than SHOWN_AGAIN ago."""
    ids = list(dict.fromkeys(ids))
    if not ids:
        return set()
    with db() as conn:
        return {r[0] for r in conn.execute(f"SELECT id FROM shown WHERE at < ? AND id IN ({','.join('?' * len(ids))})",
                                           [time.time() - SHOWN_AGAIN, *ids])}


def _now_shown(posts: list[dict]) -> None:
    now = time.time()
    with db() as conn:
        conn.executemany("INSERT OR IGNORE INTO shown (id, at) VALUES (?, ?)", [(p["id"], now) for p in posts])
        conn.execute("DELETE FROM shown WHERE at < ?", (now - SHOWN_DAYS * 86400,))
        conn.commit()


def _unshown(posts: list[dict]) -> list[dict]:
    """posts without those you were shown before (more than SHOWN_AGAIN ago); the rest noted as shown."""
    old = _stale(p["id"] for p in posts)
    out = [p for p in posts if p["id"] not in old]
    _now_shown(out)
    return out


def follow_posts(source: str, cursor: str, mode: str = "following", tags: str = "") -> dict:
    """A page of the Feed, live from the sites (livefeeds). tags: e621 only shows posts with
    these tags (e.g. "anal" or "anal canine")."""
    picked = source.split(",")
    if not (source == "all" or picked and all(s in FEED_SOURCES for s in picked)) or mode not in FEED_MODES:
        raise ValueError("bad source")
    tags = " ".join(tags.split())
    if tags:
        e621.query(tags)            # a search e621 and dreamfeed take (raises ValueError)
    s = follow_settings(subscribed=False)
    d = livefeeds.feed(mode, source, _cursor(cursor), s["reddit"]["follow"], s["e621"]["searches"], tags)
    _seen(d["posts"], d["users"])
    if mode == "foryou":            # something new each time: what you were shown before is passed over
        posts, reads = _unshown(d["posts"]), 1
        while len(posts) < FRESH_MIN and d["more"] and reads < FRESH_READS:
            more = livefeeds.feed(mode, source, d["cursor"], s["reddit"]["follow"], s["e621"]["searches"], tags)
            _seen(more["posts"], more["users"])
            have = {p["id"] for p in posts}
            posts += [p for p in _unshown(more["posts"]) if p["id"] not in have]
            d = {**more, "errors": {**d["errors"], **more["errors"]}}
            reads += 1
        d = {**d, "posts": posts}
    nxt = base64.urlsafe_b64encode(json.dumps(d["cursor"]).encode()).decode().rstrip("=") if d["more"] else None
    return {"posts": _mark_saved(d["posts"]), "more": d["more"], "cursor": nxt, "errors": d["errors"]}


SUBREDDIT = re.compile(r"^(?:/?r/)?([A-Za-z0-9_]{2,21})/?$")
BROWSE_SORTS = {"hot": "/hot", "new": "/new", "top": "/top?t=day"}


# A random subreddit (Browse's 🎲): from a list of names, one a line (RANDOM_SUBREDDITS_URL, an
# https address of a text file; read again each day). Off when it's not set.
RANDOM_SUBS_URL = os.environ.get("RANDOM_SUBREDDITS_URL", "").strip()
RANDOM_TRIES = 6           # banned, private or empty ones are passed over


def _random_names() -> list[str]:
    def fetch():
        import urllib.request
        if not RANDOM_SUBS_URL.startswith("https://"):
            raise ValueError("RANDOM_SUBREDDITS_URL isn't an https address")
        req = urllib.request.Request(RANDOM_SUBS_URL, headers={"User-Agent": "dreamfeed (random subreddit list)"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                text = r.read(4 << 20).decode("utf-8", "replace")
        except OSError as e:
            raise LookupError(f"the subreddit list didn't load ({e})")
        names = {}
        for line in text.splitlines():
            n = line.strip().removeprefix("r/").removeprefix("/r/").strip("/")
            if SUBREDDIT.match(n) and not livefeeds.place_blocked(n):      # (the usual rules still apply)
                names.setdefault(n.lower(), n)
        return list(names.values())
    return _cached("random-subs", 86400, fetch)


def random_subreddit(avoid: str = "") -> dict:
    """{"sub"}: a random one from the list that has posts to show now."""
    import random
    if not RANDOM_SUBS_URL:
        raise ValueError("no subreddit list set up (RANDOM_SUBREDDITS_URL)")
    names = [n for n in _random_names() if n.lower() != avoid.lower()]
    if not names:
        raise LookupError("the subreddit list is empty")
    for name in random.sample(names, min(RANDOM_TRIES, len(names))):
        try:
            posts, _ = livefeeds.reddit_page(f"/r/{name}/hot", None, "browse")   # (kept: Browse shows it at once)
        except LookupError:
            continue
        if posts:
            return {"sub": name}
    raise LookupError("no luck this time: try again")


def browse(sub: str, sort: str, after: str) -> dict:
    """Browse now: a subreddit as it is now, REDDIT_PAGE posts at a time (live)."""
    m = SUBREDDIT.match(sub.strip())
    if not m or sort not in BROWSE_SORTS:
        raise ValueError("a subreddit's name, like r/yiff")
    sub = m.group(1)
    if livefeeds.place_blocked(sub):
        raise ValueError("not a subreddit dreamfeed reads")
    posts, nxt = livefeeds.reddit_page(f"/r/{sub}{BROWSE_SORTS[sort]}", after or None, "browse")
    if not after:
        with db() as conn:
            conn.execute("DELETE FROM browses WHERE lower(sub) = lower(?) AND sort = ?", (sub, sort))
            conn.execute("INSERT INTO browses(sub, sort, status) VALUES (?, ?, 'done')", (sub, sort))
            conn.execute("DELETE FROM browses WHERE id NOT IN (SELECT id FROM browses ORDER BY id DESC LIMIT 30)")
    return {"sub": sub, "sort": sort, "posts": _mark_saved(posts), "after": nxt}


def recent_browses() -> dict:
    with db() as conn:
        rows = conn.execute("SELECT sub, sort, id, created_at AS at FROM browses WHERE status != 'failed'"
                            " ORDER BY id DESC LIMIT 8").fetchall()
    return {"browses": [dict(r) for r in rows]}


def person_posts(source: str, handle: str, cursor: str) -> dict:
    """An X account's latest media, a Reddit user's latest posts or an e621 artist's, live (their profile)."""
    if source == "x":
        m = X_HANDLE.match(handle.strip())
        if not m:
            raise ValueError("bad X handle")
        page = livefeeds.x_page("@" + m.group(1), int(cursor or 1))
        _seen([], [u for u in page["users"] if u["handle"].lower() == m.group(1).lower()])
        posts = [p for p in page["posts"] if p["author"].lower() == m.group(1).lower()]
        nxt = page["next"]
    elif source == "reddit":
        m = REDDIT_USER.match(handle.strip())
        if not m:
            raise ValueError("bad Reddit username")
        posts, nxt = livefeeds.reddit_page(livefeeds.user_path(m.group(1)), cursor or None, "profile")
    elif source == "e621":
        name = handle.strip().lower()
        if not e621.ARTIST.match(name):
            raise ValueError("bad e621 artist")
        try:
            posts, nxt = livefeeds.e621_page(name, int(cursor) if cursor.isdigit() else None)
        except OSError as e:
            raise LookupError(f"e621 didn't answer ({e})")
    elif source == "bsky":
        h = handle.strip().lstrip("@")
        if not livefeeds.BSKY_HANDLE.match(h):
            raise ValueError("bad Bluesky handle")
        posts, nxt = livefeeds.bsky_page("@" + h, cursor or None)
    else:
        raise ValueError("bad source")
    return {"posts": _mark_saved(posts), "cursor": str(nxt) if nxt else None}


def save_post(req: dict) -> dict:
    """{"post": {...}, "save": bool}: keep a post in Saved (as it was shown); a Reddit post is
    saved on Reddit too, an e621 one favorited (signed in)."""
    p, save = req.get("post") or {}, bool(req.get("save"))
    pid = str(p.get("id") or "")
    m = livefeeds.POST_ID.fullmatch(pid)
    if not m or p.get("source") != m.group(1) or not isinstance(p.get("media"), list):
        raise ValueError("bad post")
    sync = None
    if m.group(1) == "reddit":
        try:
            livefeeds.reddit_save(m.group(2), save)
            sync = {"status": "done"}
        except (LookupError, ValueError) as e:
            sync = {"status": "failed", "error": str(e)}
    elif m.group(1) == "e621" and e621.creds() and m.group(2).isdigit():
        try:
            e621.favorite(m.group(2), save)
            sync = {"status": "done"}
        except (LookupError, OSError) as e:
            sync = {"status": "failed", "error": str(e)[:200]}
    media = []
    for x in p["media"][:livefeeds.MAX_GALLERY]:
        if not isinstance(x, dict) or x.get("kind") not in ("image", "video", "hls"):
            raise ValueError("bad post")
        item = {k: x[k] for k in ("kind", "url", "full", "poster", "fallback") if isinstance(x.get(k), str) and x[k]}
        if any(not savedposts.allowed(item[k]) for k in ("url", "full", "poster", "fallback") if k in item) or "url" not in item:
            raise ValueError("not a site's media address")
        media.append(item)
    keep = {k: p.get(k) for k in ("id", "source", "author", "nick", "avatar", "place", "text", "posted_at", "link")}
    keep["media"] = media
    with db() as conn:
        if save:      # (saved again while kept: left as it is)
            conn.execute("INSERT INTO saved_posts(id, source, data) VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET"
                         " data = excluded.data, status = 'queued', error = NULL, files = NULL, saved_at = datetime('now')"
                         " WHERE saved_posts.status = 'removed'", (pid, m.group(1), json.dumps(keep)[:200_000]))
        else:         # kept as removed, so an import of what you saved on the site doesn't bring it back
            conn.execute("UPDATE saved_posts SET status = 'removed', files = NULL, error = NULL WHERE id = ?", (pid,))
            shutil.rmtree(savedposts.folder(DATA, pid), ignore_errors=True)
        r = conn.execute("SELECT status, error FROM saved_posts WHERE id = ? AND status != 'removed'", (pid,)).fetchone()
    return {"saved": save, "sync": sync, "keep": dict(r) if r else None}


_import = {"running": False, "at": None, "x": None, "reddit": None, "e621": None}


def e621_vote(req: dict) -> dict:
    """{"id": "e621:ID", "score": 1 | -1}: vote on it as you (the same again takes it back)."""
    m = re.fullmatch(r"e621:(\d{1,12})", str(req.get("id", "")))
    score = req.get("score")
    if not m or score not in (1, -1):
        raise ValueError("bad vote")
    return e621.vote(m.group(1), score)
_import_lock = threading.Lock()


def import_saved(req: dict) -> dict:
    """Bring what you saved on the sites into Saved: your X bookmarks and your Reddit saved posts
    (with pictures or videos), their files then kept like any you save here. Ones you unsaved
    here stay out. In the background; GET /api/saved/import says how it went."""
    with _import_lock:
        if _import["running"]:
            return dict(_import)
        _import.update(running=True, x=None, reddit=None, e621=None)
    threading.Thread(target=_run_import, daemon=True).start()
    return dict(_import)


def _run_import() -> None:
    try:
        for source, read in (("x", livefeeds.x_bookmarks), ("reddit", livefeeds.reddit_saved), ("e621", livefeeds.e621_favorites)):
            if source == "reddit" and not livefeeds.reddit_ready():
                _import["reddit"] = {"error": "Reddit isn't signed in"}
                continue
            if source == "e621" and not e621.creds():
                _import["e621"] = {"error": "e621 isn't signed in"}
                continue
            try:
                posts = read()
            except (LookupError, OSError, ValueError) as e:
                _import[source] = {"error": str(e)[:300]}
                continue
            added = 0
            with db() as conn:
                # saved when you saved it on the site (X bookmarks say when); else (Reddit doesn't) now,
                # each a second older than the one before, so they keep the site's order
                for n, p in enumerate(posts):
                    keep = {k: p.get(k) for k in ("id", "source", "author", "nick", "avatar", "place", "text", "posted_at", "link", "media")}
                    when = p.get("saved_at") if re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", str(p.get("saved_at") or "")) else None
                    added += conn.execute("INSERT INTO saved_posts(id, source, data, saved_at) VALUES (?, ?, ?, coalesce(?, datetime('now', ?)))"
                                          " ON CONFLICT(id) DO NOTHING", (p["id"], source, json.dumps(keep)[:200_000], when, f"-{n} seconds")).rowcount
            _import[source] = {"found": len(posts), "added": added}
    finally:
        _import.update(running=False, at=time.strftime("%Y-%m-%d %H:%M:%S"))


def import_status() -> dict:
    with db() as conn:
        counts = {r["status"]: r["n"] for r in conn.execute("SELECT status, count(*) AS n FROM saved_posts GROUP BY status")}
    return {**_import, "files": counts}


def _saved_json(r) -> dict:
    """A saved post as Saved shows it: from its kept files once they're downloaded."""
    p = {**json.loads(r["data"]), "saved": True, "keep": {"status": r["status"], "error": r["error"]}}
    if r["status"] == "done" and r["files"]:
        base = "saved-media/" + "/".join(savedposts.folder(Path("."), r["id"]).parts[1:]) + "/"
        p["media"] = [{"kind": f["kind"], "url": base + f["file"], "poster": base + f["poster"] if f.get("poster") else None}
                      for f in json.loads(r["files"])]
    return p


VIDEO_KINDS = ("video", "hls")
MORE_VIDEOS = 8            # videos a page of More videos (several listing pages read for them, at most MORE_READS)
MORE_READS = 4


def more_videos(post_id: str, cursor: str) -> dict:
    """More videos after a Reddit or e621 post (the Reddit app's swipe-up feed, rebuilt from the
    public API): Reddit, more from its subreddit (hot, then the week's top), then from your
    subscriptions and the Dashboard's subreddits, newest first; e621, more of the search it came
    from (or its artist), then the Dashboard's searches. Videos only. {"posts", "cursor"}."""
    m = re.fullmatch(r"(reddit|e621):([A-Za-z0-9_]{1,30})", post_id or "")
    if not m:
        raise ValueError("bad post")
    site = m.group(1)
    c = _cursor(cursor) or {}
    if not c:                                  # the first page: what the post itself says where to look
        p = one_post(post_id)["post"]
        if site == "reddit":
            sub = p.get("place") or ""
            # its subreddit's listings in a different order each time (hot, new, the week's and month's top)
            lists = [f"/r/{sub}/{x}" for x in random.sample(["hot", "new", "top?t=week", "top?t=month"], 4)]
            stages = ([["sub", x] for x in lists] if SUBREDDIT.match(sub) else []) + [["subs", ""]]
        else:
            first = p.get("place") or ((p.get("artists") or [""])[0])
            stages = [["e621", q] for q in dict.fromkeys([first] + follow_settings(subscribed=False)["e621"]["searches"]) if q]
        c = {"stages": stages, "i": 0, "at": None, "seen": [post_id]}
    stages = c.get("stages") or []
    ok = {"sub": re.compile(r"^/r/[A-Za-z0-9_]{2,21}/(?:hot|new|top\?t=week|top\?t=month)$"), "subs": re.compile(r"^$"), "e621": re.compile(r"^.{1,300}$")}
    if (not isinstance(stages, list) or len(stages) > 40 or not isinstance(c.get("i"), int)
            or any(not (isinstance(x, list) and len(x) == 2 and x[0] in ok and isinstance(x[1], str) and ok[x[0]].match(x[1]))
                   for x in stages)
            or (site == "e621") != all(x[0] == "e621" for x in stages)):
        raise ValueError("bad cursor")      # (it comes back from the page: only what this made)
    at = c.get("at")
    if at is not None and not (isinstance(at, int) if site == "e621" else isinstance(at, str) and re.fullmatch(r"t3_\w{1,20}", at)):
        raise ValueError("bad cursor")
    out, reads, seen = [], 0, set(str(x) for x in (c.get("seen") or [])[:300])
    while c["i"] < len(stages) and len(out) < MORE_VIDEOS and reads < MORE_READS:
        kind, where = stages[c["i"]]
        reads += 1
        try:
            if kind == "e621":
                posts, nxt = livefeeds.e621_page(f"{where} ~type:webm ~type:mp4", c["at"])
            else:
                if kind == "subs":
                    s = follow_settings()
                    subs = set(s["reddit"]["subscribed"]) | set(s["reddit"]["follow"])
                    rs = sorted({w[2:] for w in subs if w.startswith("r/") and not livefeeds.place_blocked(w[2:])}, key=str.lower)
                    if not rs:
                        c.update(i=c["i"] + 1, at=None); continue
                    where = "/r/" + "+".join(rs[:250]) + "/new"
                posts, nxt = livefeeds.reddit_page(where, c["at"], "videos")
        except ValueError:               # (a search dreamfeed won't run)
            posts, nxt = [], None
        old = _stale(p["id"] for p in posts)          # (shown to you before: passed over)
        for p in posts:
            if p["id"] not in seen and p["id"] not in old and any(x.get("kind") in VIDEO_KINDS for x in p["media"]):
                if kind == "e621":
                    p = {**p, "place": where}
                seen.add(p["id"]); out.append(p)
        if nxt:
            c["at"] = nxt
        else:
            c.update(i=c["i"] + 1, at=None)
    c["seen"] = list(seen)[-300:]
    _now_shown(out)
    more = c["i"] < len(stages)
    return {"posts": _mark_saved(out), "cursor": base64.urlsafe_b64encode(json.dumps(c).encode()).decode().rstrip("=") if more else None}


def one_post(post_id: str) -> dict:
    """A post's own page: a post you saved (from its kept copy), else live from its site."""
    with db() as conn:
        r = conn.execute("SELECT * FROM saved_posts WHERE id = ? AND status != 'removed'", (post_id,)).fetchone()
    if r:
        return {"post": _saved_json(r)}
    try:
        found = livefeeds.post(post_id)
    except OSError as e:
        raise LookupError(f"the site didn't answer ({e})")
    if not found:
        raise LookupError("that post isn't there any more (or dreamfeed leaves it out)")
    return {"post": _mark_saved([found])[0]}


def saved_file(rel: str) -> Path | None:
    from urllib.parse import unquote
    root = (DATA / "saved").resolve()
    path = (root / unquote(rel)).resolve()
    return path if path.is_relative_to(root) and path.is_file() and not path.name.startswith(".") else None


def _xuser(u) -> dict:
    return {"handle": u["handle"], "nick": u["nick"], "bio": u["bio"], "location": u["location"], "followers": u["followers"],
            "following": u["following"], "posts": u["posts"], "avatar": u["image_url"] or None}


# ---- Discover and profiles (one profile across sites) ----
CB_LIST = "https://chaturbate.com/api/ts/roomlist/room-list/"
CB_AGENT = {"User-Agent": "dreamfeed (personal follow list)", "Accept": "application/json"}
GENDERS = ("f", "m", "c", "t")
DISCOVER_PAGE = 60
COMMON_TAGS = {"new", "18", "lovense", "lush", "ohmibod", "domi", "interactive", "interactivetoy", "private", "pvt",
               "goal", "tip", "tips", "c2c", "hd", "lovensetoy"}
X_HANDLE = re.compile(r"^@?([A-Za-z0-9_]{1,15})$")
REDDIT_USER = re.compile(r"^(?:u/|/u/)?([A-Za-z0-9_-]{3,20})$")
_cache: dict[str, tuple[float, object]] = {}      # Chaturbate answers and bios, briefly
_thumbs: dict[str, str] = {}                      # room -> its thumbnail's address (from a listing)


def _cached(key: str, ttl: float, fetch):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    value = fetch()
    if len(_cache) > 500:
        _cache.clear()
    _cache[key] = (time.time(), value)
    return value


def _cb_list(params: dict) -> list[dict]:
    import urllib.request
    url = CB_LIST + "?" + urllib.parse.urlencode(params)

    def fetch():
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=CB_AGENT), timeout=30) as r:
                return json.load(r).get("rooms") or []
        except (OSError, ValueError) as e:
            raise LookupError(f"Chaturbate didn't answer ({e})")
    return _cached(url, 120, fetch)


def _room_ok(r: dict) -> bool:
    """Shown in Discover: age verified, 18 or over, no password, and nothing dreamfeed never
    takes in its tags or title."""
    age = r.get("display_age")
    words = " ".join([str(t) for t in r.get("tags") or []] + [re.sub(r"<[^>]+>", " ", str(r.get("room_subject") or r.get("subject") or ""))])
    return (bool(r.get("is_age_verified")) and not (isinstance(age, int) and age < 18) and not r.get("has_password")
            and ROOM.match(str(r.get("username", ""))) is not None
            and not safety.request_blocked(words.replace("_", " ")) and not safety.story_blocked(words.replace("_", " ")))


def _room_card(r: dict, followed: set) -> dict:
    name = r["username"]
    img = str(r.get("img") or "")
    if urllib.parse.urlparse(img).hostname == "thumb.live.mmcdn.com":
        if len(_thumbs) > 3000:
            _thumbs.clear()
        _thumbs[name] = img
    return {"name": name, "live": True, "followed": name in followed, "discovered": True,
            "info": {"title": re.sub(r"<[^>]+>", "", str(r.get("room_subject") or r.get("subject") or ""))[:300],
                     "tags": [str(t)[:40] for t in (r.get("tags") or [])][:12], "viewers": int(r.get("num_users") or 0),
                     "age": r.get("display_age"), "gender": r.get("gender"), "show": r.get("current_show"),
                     "since": r.get("start_dt_utc")},
            "thumb": f"cb-thumb/{name}.jpg?t={int(time.time() // 60)}" if name in _thumbs else None, "times": []}


def discover_cb(mode: str, q: str, gender: str, offset: int) -> dict:
    """Live rooms you don't follow: for you (sharing the tags of the rooms you follow), top (most
    watched) or a search; only rooms _room_ok lets through."""
    if gender and gender not in GENDERS:
        raise ValueError("bad gender")
    with db() as conn:
        follows = conn.execute("SELECT name, info FROM follows WHERE source = 'chaturbate'").fetchall()
    followed = {r["name"] for r in follows}
    base = {"genders": gender} if gender else {}
    if mode == "foryou":
        counts: dict[str, int] = {}
        for r in follows:
            for t in (json.loads(r["info"]) if r["info"] else {}).get("tags") or []:
                t = str(t).lower()
                if t not in COMMON_TAGS and not safety.request_blocked(t):
                    counts[t] = counts.get(t, 0) + 1
        tags = sorted(counts, key=lambda t: -counts[t])[:6]
        if not tags:
            return {"rooms": [], "more": False, "tags": [], "note": "Once the rooms you follow have been live a while, rooms with the same tags show here."}
        score: dict[str, list] = {}
        for t in tags:
            for r in _cb_list({**base, "hashtags": t, "limit": 90}):
                if r.get("username") in followed or not _room_ok(r):
                    continue
                entry = score.setdefault(r["username"], [0, r])
                entry[0] += counts[t]
        ranked = sorted(score.values(), key=lambda e: (-e[0], -int(e[1].get("num_users") or 0)))
        page = ranked[offset:offset + DISCOVER_PAGE]
        return {"rooms": [_room_card(r, followed) for _, r in page], "more": len(ranked) > offset + DISCOVER_PAGE, "tags": tags}
    if mode == "top":
        params = {**base, "limit": DISCOVER_PAGE, "offset": offset}
    elif mode == "search":
        q = q.strip().lower()
        if not 1 <= len(q) <= 60 or not re.fullmatch(r"[a-z0-9_ -]+", q):
            raise ValueError("type a tag or a few words (letters and numbers)")
        bad = safety.request_blocked(q.replace("_", " ")) + safety.story_blocked(q.replace("_", " "))
        if bad:
            raise ValueError(f"not something to look for: {', '.join(sorted(set(bad)))}")
        params = {**base, "keywords": q, "limit": DISCOVER_PAGE, "offset": offset}
    else:
        raise ValueError("bad mode")
    rooms = _cb_list(params)
    return {"rooms": [_room_card(r, followed) for r in rooms if _room_ok(r) and r["username"] not in followed],
            "more": len(rooms) >= DISCOVER_PAGE}     # (it sometimes gives one more than asked)


def cb_thumb(name: str) -> bytes | None:
    import urllib.request
    url = _thumbs.get(name)
    if not url:
        return None

    def fetch():
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=CB_AGENT), timeout=20) as r:
                data = r.read(2 << 20)
        except OSError:
            return None
        return data if data[:3] == b"\xff\xd8\xff" else None
    return _cached("thumb:" + name, 60, fetch)


def _bio(name: str) -> dict:
    def fetch():
        try:
            return cbprofile.bio(name)
        except (OSError, ValueError):
            return None
    return _cached("bio:" + name, 3600, fetch) or {}


LINK_DAYS = 7              # a room's links are looked for again after this
LINK_SWEEP = 1800          # seconds between looks at the rooms you follow (a few each time)
_linking: set = set()
_linking_lock = threading.Lock()


def start_linking(room: str) -> bool:
    """Look for the room's accounts across sites (linking.py), in the background, one room at a time."""
    with _linking_lock:
        if room in _linking or len(_linking) >= 2:
            return False
        _linking.add(room)
    threading.Thread(target=_run_linking, args=(room,), daemon=True).start()
    return True


def _run_linking(room: str) -> None:
    try:
        with db() as conn:
            known = [(l["source"], l["handle"]) for l in conn.execute(
                "SELECT source, handle FROM links WHERE room = ? AND state IN ('bio', 'yours')", (room,))]
            removed = {(l["source"], l["handle"].lower()) for l in conn.execute(
                "SELECT source, handle FROM links WHERE room = ? AND state = 'removed'", (room,))}
        try:
            bio = cbprofile.bio(room)["links"]          # (with their link pages, which aren't kept)
        except (OSError, ValueError):
            bio = []
        start = list(dict.fromkeys(known + [(s, h) for s, h in bio if (s, h.lower()) not in removed]))
        found = [f for f in linking.find(room, start) if (f[0], f[1].lower()) not in removed]
        with db() as conn:
            cbprofile.save_links(conn, room, [(s, h) for s, h in bio if s in cbprofile.ACCOUNTS])
            cbprofile.save_links(conn, room, found)
            conn.execute("INSERT INTO link_checks(room, at, found) VALUES (?, datetime('now'), ?)"
                         " ON CONFLICT(room) DO UPDATE SET at = excluded.at, found = excluded.found",
                         (room, json.dumps(found)))
        if found:
            print(time.strftime("%F %T"), f"web: {room}: {len(found)} account(s) found across sites", flush=True)
    except Exception as e:      # (the profile just shows what it had)
        print(time.strftime("%F %T"), f"web: looking for {room}'s accounts failed: {e}", flush=True)
    finally:
        with _linking_lock:
            _linking.discard(room)


def _link_sweep() -> None:
    """The rooms you follow, a few each half hour, each again after LINK_DAYS."""
    while True:
        time.sleep(LINK_SWEEP)
        try:
            with db() as conn:
                rooms = [r[0] for r in conn.execute(
                    "SELECT f.name FROM follows f LEFT JOIN link_checks c ON c.room = f.name WHERE f.source = 'chaturbate'"
                    " AND (c.at IS NULL OR c.at < datetime('now', ?)) ORDER BY c.at LIMIT 3", (f"-{LINK_DAYS} days",))]
            for r in rooms:
                while _linking:
                    time.sleep(5)
                start_linking(r)
        except sqlite3.Error:
            pass


def relink(req: dict) -> dict:
    """{"room"}: look for the room's accounts again now."""
    room = str(req.get("room", ""))
    if not ROOM.match(room):
        raise ValueError("bad room")
    return {"running": start_linking(room) or room in _linking}


def profile(room: str = "", x: str = "", reddit: str = "", e621_artist: str = "", bsky: str = "") -> dict:
    """One profile across sites: a Chaturbate room (or the room an X or Reddit account is linked
    to), its linked accounts (who they are on X and Reddit) and your videos of it; or an e621
    artist (their pages elsewhere, and their X account's posts when e621 lists one). Their
    posts are read live (person_posts)."""
    artist = None
    if e621_artist:
        try:
            artist = livefeeds.e621_artist(e621_artist)
        except OSError as e:
            raise LookupError(f"e621 didn't answer ({e})")
    with db() as conn:
        if not room and (x or reddit):
            src, h = ("x", x) if x else ("reddit", reddit)
            hit = conn.execute("SELECT room FROM links WHERE source = ? AND lower(handle) = lower(?) AND state != 'removed'"
                               " ORDER BY state = 'yours' DESC LIMIT 1", (src, h)).fetchone()
            room = hit["room"] if hit else ""
        if room and not ROOM.match(room):
            raise ValueError("bad room")
        out = {"room": room or None, "followed": False, "bio": {}, "links": [], "xusers": {}, "following_x": [], "videos": 0,
               "e621": [artist["name"]] if artist else [], "artist": artist, "reddituser": None, "bsky": [], "bskyuser": None}
        if bsky:                             # a Bluesky account on its own
            h = bsky.strip().lstrip("@")
            if not livefeeds.BSKY_HANDLE.match(h):
                raise ValueError("bad Bluesky handle")
            out["bsky"] = [h.lower()]
            try:
                out["bskyuser"] = livefeeds.bsky_user(h)
            except LookupError:
                pass
        if room:
            bio = _bio(room)
            if bio.get("links"):
                with conn:
                    cbprofile.save_links(conn, room, bio["links"])
            out["bio"] = {k: bio.get(k) for k in ("about", "followers", "age", "location", "last_broadcast")}
            r = conn.execute("SELECT * FROM follows WHERE source = 'chaturbate' AND name = ?", (room,)).fetchone()
            if r:
                out.update(followed=True, live=bool(r["live"]), info=json.loads(r["info"]) if r["info"] else {},
                           last_live=_unix(r["last_live"]) if r["last_live"] else None)
                out["times"] = [[_unix(t["start_at"]), _unix(t["end_at"])] for t in conn.execute(
                    "SELECT start_at, end_at FROM live_times WHERE source = 'chaturbate' AND name = ? AND end_at >= datetime('now', ?)",
                    (room, f"-{LIVE_DAYS} days"))]
                out["videos"] = len(cbvideos.scan(_followed()).get(room, []))
            act = conn.execute("SELECT action, status, error FROM cb_actions WHERE room = ? AND created_at >= datetime('now', '-10 minutes')"
                               " ORDER BY id DESC LIMIT 1", (room,)).fetchone()
            out["action"] = dict(act) if act else None
            rec = _dvr()
            out["dvr"] = {"on": dvr.enabled(), "room": _with_once(rec.get("rooms", {}).get(room), room, _once_rooms()), "free": rec.get("free"),
                          "error": rec.get("error")}
            out["links"] = [{"source": l["source"], "handle": l["handle"], "state": l["state"],
                             "via": l["via"] or ("their Chaturbate bio" if l["state"] == "bio" else None)} for l in conn.execute(
                "SELECT * FROM links WHERE room = ? AND state != 'removed' ORDER BY state = 'suggested', source, handle", (room,))]
            chk = conn.execute("SELECT at, at < datetime('now', ?) AS old FROM link_checks WHERE room = ?",
                               (f"-{LINK_DAYS} days", room)).fetchone()
            out["linking"] = {"running": room in _linking, "at": chk["at"] if chk else None}
            if not chk or chk["old"]:
                start_linking(room)                  # (in the background: the profile shows them when done)
                out["linking"]["running"] = True
        mine = [l for l in out["links"] if l["state"] != "suggested"]        # (a suggestion is only shown)
        xs = ({l["handle"].lower() for l in mine if l["source"] == "x"} | ({x.lower()} if x else set())
              | set(artist["x"] if artist else []))
        rs = {l["handle"].lower() for l in mine if l["source"] == "reddit"} | ({reddit.lower()} if reddit else set())
        out["x"], out["reddit"] = sorted(xs), sorted(rs)
        out["xvideos"] = sorted({l["handle"].lower() for l in mine if l["source"] == "xvideos"})
        out["redgifs"] = sorted({l["handle"].lower() for l in mine if l["source"] == "redgifs"})
        if rs and not xs and livefeeds.reddit_ready():      # their picture (X's own is in xusers)
            try:
                out["reddituser"] = livefeeds.reddit_user(sorted(rs)[0])
            except (LookupError, ValueError, OSError):
                pass
        if xs:
            marks = ",".join("?" * len(xs))
            following = {h.lower() for (h,) in conn.execute(
                f"SELECT DISTINCT handle FROM x_seen WHERE kind = 'following' AND lower(handle) IN ({marks})", [*xs])}
            out["following_x"] = sorted(following)
            out["xusers"] = {u["handle"].lower(): _xuser(u) for u in conn.execute(
                f"SELECT * FROM x_users WHERE lower(handle) IN ({marks})", [*xs])}
    return out


def follow_room(req: dict) -> dict:
    """{"name", "follow": bool}: follow or unfollow a room on Chaturbate (sent by the follow service)."""
    name = str(req.get("name", ""))
    if not ROOM.match(name):
        raise ValueError("bad room")
    with db() as conn:
        if conn.execute("SELECT 1 FROM cb_actions WHERE room = ? AND status = 'queued'", (name,)).fetchone():
            raise ValueError("already on its way")
        conn.execute("INSERT INTO cb_actions(room, action) VALUES (?, ?)", (name, "follow" if req.get("follow") else "unfollow"))
    return {"ok": True}


def save_link(req: dict) -> dict:
    """{"room", "source": "x"|"reddit"|"xvideos"|"redgifs"|"onlyfans"|"fansly", "handle", "remove": bool}:
    link an account to a room (or confirm a suggested one), or unlink it. A profile can be given as
    its address."""
    room, source, handle = str(req.get("room", "")), str(req.get("source", "")), str(req.get("handle", "")).strip()
    if not ROOM.match(room):
        raise ValueError("bad room")
    pattern = {"xvideos": cbprofile.XVIDEOS_LINK, "redgifs": cbprofile.REDGIFS_LINK, "onlyfans": cbprofile.ONLYFANS_LINK,
               "fansly": cbprofile.FANSLY_LINK}.get(source)
    if pattern:
        found = pattern.findall(handle + " ")
        handle = (found[0] if found else handle.lstrip("@")).lower()
        if not re.fullmatch(r"[a-z0-9_.-]{2,60}", handle):
            raise ValueError(f"a {source} name or address")
    else:
        m = (X_HANDLE if source == "x" else REDDIT_USER if source == "reddit" else None)
        m = m.match(handle) if m else None
        if not m:
            raise ValueError("an X handle (letters, numbers, _) or a Reddit username")
        handle = m.group(1)
    with db() as conn:
        conn.execute("DELETE FROM links WHERE room = ? AND source = ? AND lower(handle) = lower(?)", (room, source, handle))
        conn.execute("INSERT INTO links(room, source, handle, state) VALUES (?, ?, ?, ?)",
                     (room, source, handle, "removed" if req.get("remove") else "yours"))
    return {"ok": True}


def discover_x() -> dict:
    """X accounts you might like and don't follow: those the rooms you follow link to, those the
    people you follow mention (twice or more) and those in X's For you (twice or more), from the
    last X_SEEN_DAYS of your timelines."""
    with db() as conn:
        following = {h.lower() for (h,) in conn.execute("SELECT DISTINCT handle FROM x_seen WHERE kind = 'following'")}
        people: dict[str, dict] = {}

        def person(h: str) -> dict:
            return people.setdefault(h.lower(), {"handle": h, "rooms": [], "mentions": 0, "by": set(), "foryou": 0})
        for l in conn.execute("SELECT l.room, l.handle FROM links l JOIN follows f ON f.source = 'chaturbate' AND f.name = l.room"
                              " WHERE l.source = 'x' AND l.state != 'removed'"):
            if l["handle"].lower() not in following:
                person(l["handle"])["rooms"].append(l["room"])
        for r in conn.execute("SELECT handle, by FROM x_seen WHERE kind = 'mention'"):
            if r["handle"].lower() not in following and X_HANDLE.match(r["handle"]):
                p = person(r["handle"])
                p["mentions"] += 1
                p["by"].add(r["by"])
        for r in conn.execute("SELECT handle, count(*) AS n FROM x_seen WHERE kind = 'foryou' GROUP BY lower(handle)"):
            if r["handle"].lower() not in following:
                person(r["handle"])["foryou"] = r["n"]
        users = {u["handle"].lower(): u for u in conn.execute("SELECT handle, image_url FROM x_users")}
        out = []
        for key, p in people.items():
            if not p["rooms"] and p["mentions"] < 2 and p["foryou"] < 2:
                continue
            u = users.get(key)
            out.append({"handle": p["handle"], "rooms": p["rooms"], "mentions": p["mentions"], "by": sorted(p["by"])[:3],
                        "foryou": p["foryou"], "thumb": (u["image_url"] if u else None) or None})
    out.sort(key=lambda p: (-len(p["rooms"]), -(p["mentions"] + p["foryou"]), p["handle"].lower()))
    return {"people": out[:80]}


def _unix(utc: str) -> int:
    import calendar
    return calendar.timegm(time.strptime(utc, "%Y-%m-%d %H:%M:%S"))


def follow_thumb(source: str, file: str) -> Path | None:
    name = file.removesuffix(".jpg")
    if source != "chaturbate" or not file.endswith(".jpg") or not ROOM.match(name):
        return None
    path = FOLLOW / source / file
    return path if path.is_file() else None


def image_path(gid: int, thumb: bool) -> Path | None:
    with db() as conn:
        row = conn.execute("SELECT g.file, g.thumb, f.liked_file FROM generations g"
                           " LEFT JOIN feedback f ON f.generation_id = g.id WHERE g.id = ?", (gid,)).fetchone()
    if not row:
        return None
    candidates = [(GENERATED, row["thumb"] if thumb else None), (GENERATED, row["file"]),
                  (LIKED, row["liked_file"])]
    for base, rel in candidates:
        if rel:
            path = (base / rel).resolve()
            if path.is_relative_to(base.resolve()) and path.is_file():
                return path
    return None


def set_feedback(gid: int, action: str) -> dict:
    with db() as conn:
        row = conn.execute("SELECT g.id, g.night, g.medium, g.score, g.file, g.status, g.persona, f.action, f.liked_file"
                           " FROM generations g LEFT JOIN feedback f ON f.generation_id = g.id"
                           " WHERE g.id = ?", (gid,)).fetchone()
        if not row or row["status"] not in ("feed", "expired"):
            raise LookupError("no such image")
        old_copy = row["liked_file"]
        if action == "like":
            copy = old_copy
            if not copy:
                src = GENERATED / row["file"]
                if not src.is_file():
                    raise LookupError("this image has expired")
                copy = f"{row['night']}-{row['persona'] or row['medium']}-{gid}{src.suffix}"
                LIKED.mkdir(exist_ok=True)
                shutil.copy2(src, LIKED / copy)
            conn.execute("INSERT INTO feedback(generation_id, action, liked_file) VALUES (?, 'like', ?)"
                         " ON CONFLICT(generation_id) DO UPDATE SET action = 'like', liked_file = ?,"
                         " at = datetime('now')", (gid, copy, copy))
        else:
            if old_copy:
                (LIKED / old_copy).unlink(missing_ok=True)
            if action == "skip":
                conn.execute("INSERT INTO feedback(generation_id, action) VALUES (?, 'skip')"
                             " ON CONFLICT(generation_id) DO UPDATE SET action = 'skip', liked_file = NULL,"
                             " at = datetime('now')", (gid,))
            else:
                conn.execute("DELETE FROM feedback WHERE generation_id = ?", (gid,))
    return {"id": gid, "action": None if action == "clear" else action}


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def dashboard() -> dict:
    out = {"window": GENERATE_WINDOW, "runs": [], "jobs": [], "liked": 0}
    try:
        with db() as conn:
            out["liked"] = conn.execute("SELECT count(*) FROM feedback WHERE action = 'like'").fetchone()[0]
            for r in conn.execute("SELECT night, status, stats, progress, started_at, finished_at FROM runs"
                                  " WHERE night NOT LIKE 'test-%' ORDER BY started_at DESC LIMIT 8"):
                run = dict(r)
                run["stats"] = json.loads(run["stats"]) if run["stats"] else {}
                run["progress"] = json.loads(run["progress"]) if run["progress"] else None
                job = conn.execute("SELECT id, params, status, message FROM jobs WHERE night = ? ORDER BY id DESC LIMIT 1",
                                   (r["night"],)).fetchone()
                run["message"] = job["message"] if job else None   # why a job's run failed, what it made
                if job and job["status"] == "failed" and json.loads(job["params"]).get("kind") in RETRYABLE \
                        and not _retried(conn, job["id"], job["params"]):
                    run["retry"] = job["id"]
                out["runs"].append(run)
            out["jobs"] = [dict(r) | {"params": json.loads(r["params"])} for r in conn.execute(
                "SELECT id, params, status, night, message, created_at FROM jobs"
                " WHERE status IN ('queued', 'running') ORDER BY id")]
    except sqlite3.OperationalError:
        pass
    return out


def queue_generation(req: dict) -> dict:
    images, keep = int(req.get("images", 0)), int(req.get("keep", 0))
    mediums = [m for m in req.get("mediums") or [] if m in MEDIUMS]
    handles = [str(h) for h in req.get("personas") or [] if HANDLE.match(str(h))]
    if not 1 <= images <= MAX_IMAGES:
        raise ValueError(f"images must be between 1 and {MAX_IMAGES}")
    if not 1 <= keep <= images:
        raise ValueError("keep must be between 1 and the number of images")
    if req.get("mediums") and not mediums:
        raise ValueError("pick at least one style")
    with db() as conn:
        if handles:
            known = {r[0] for r in conn.execute("SELECT handle FROM personas WHERE active = 1")}
            if not set(handles) <= known:
                raise ValueError("unknown persona")
        params = {"images": images, "keep": keep, "mediums": mediums}
        if handles:
            params["personas"] = handles
        gid = conn.execute("INSERT INTO jobs(params, status) VALUES (?, 'queued')",
                           (json.dumps(params),)).lastrowid
    return {"job": gid}


MAX_PROMPT = 500


COMIC_STORY = 600
COMIC_PAGES = 4
COMIC_TITLE = 100
MAX_BODY = 16 * 1024 * 1024   # a request's size


def _comic_meta(file: str) -> dict:
    return read_json((GENERATED / file).parent / "comic.json")


def comics() -> dict:
    """Finished comics (newest first), and the ones being made."""
    out = {"comics": [], "making": []}
    with db() as conn:
        for r in conn.execute("SELECT g.id, g.caption, g.persona, g.file, g.created_at, g.status, p.name FROM generations g"
                              " LEFT JOIN personas p ON p.handle = g.persona"
                              " WHERE g.kind = 'comic' AND g.status = 'comic'"
                              " ORDER BY g.id DESC LIMIT 100"):
            meta = _comic_meta(r["file"])
            out["comics"].append({"id": r["id"], "title": r["caption"] or "", "persona": r["persona"],
                                  "name": r["name"] or r["persona"], "pages": len(meta.get("pages") or [1]),
                                  "cast": meta.get("cast") or [], "story": meta.get("story", ""),
                                  "imported": bool(meta.get("imported")),
                                  "updated": meta.get("updated"),
                                  "panels": meta.get("panels") or {},
                                  "outlines": meta.get("outlines") or {},
                                  "animations": [{"page": a["page"], "box": a["box"], "name": Path(a["file"]).name,
                                                  "mask": Path(a["mask"]).name if a.get("mask") else None}
                                                 for a in meta.get("animations") or []],
                                  "created": r["created_at"]})
        # Comic jobs that failed in the last day, with why: they'd otherwise just vanish from "being made".
        out["failed"] = []
        for r in conn.execute("SELECT id, params, message, finished_at FROM jobs WHERE status = 'failed'"
                              " AND params LIKE '%\"kind\": \"comic%' AND finished_at >= datetime('now', '-1 day')"
                              " ORDER BY id DESC LIMIT 10"):
            if _retried(conn, r["id"], r["params"]):   # tried again since: that one shows instead
                continue
            params = json.loads(r["params"])
            what = {"comic": "Making a comic", "comic_import": "Importing a comic",
                    "comic_update": "Looking for new pages",
                    "comic_animate": f"Animating a panel on page {params.get('page')}"}.get(params.get("kind"))
            if not what:
                continue
            title = ""
            if params.get("id"):
                row = conn.execute("SELECT caption FROM generations WHERE id = ?", (params["id"],)).fetchone()
                title = row["caption"] if row else ""
            out["failed"].append({"job": r["id"], "what": what, "title": title or params.get("url", ""),
                                  "message": r["message"] or "", "finished": r["finished_at"]})
        for r in conn.execute("SELECT j.id, j.params, j.status, r.progress FROM jobs j LEFT JOIN runs r ON r.night = j.night"
                              " WHERE j.status IN ('queued', 'running') AND j.params LIKE '%\"kind\": \"comic%'"):
            params = json.loads(r["params"])
            if params.get("kind") not in ("comic", "comic_import", "comic_animate", "comic_update"):
                continue
            item = {"job": r["id"], "status": r["status"], "progress": json.loads(r["progress"]) if r["progress"] else None}
            if params["kind"] == "comic_import":
                item |= {"imported": True, "title": params.get("title") or "", "url": params["url"]}
            elif params["kind"] == "comic_update":
                title = conn.execute("SELECT caption FROM generations WHERE id = ?", (params["id"],)).fetchone() \
                    if params.get("id") else None
                item |= {"imported": True, "title": title["caption"] if title else "Every imported comic",
                         "url": "looking for new pages"}
            elif params["kind"] == "comic_animate":
                title = conn.execute("SELECT caption FROM generations WHERE id = ?", (params["id"],)).fetchone()
                item |= {"imported": True, "title": title["caption"] if title else "",
                         "url": f"animating a panel of page {params['page']}",
                         "comic": params["id"], "page": params["page"], "box": params["box"]}
            else:
                item |= {"cast": params["cast"], "story": params["story"], "pages": params["pages"]}
            out["making"].append(item)
    return out


def comic_page(gid: int, n: int, thumb: bool = False) -> Path | None:
    """Page n of a comic; thumb: its small copy (the page itself if there's none yet)."""
    with db() as conn:
        row = conn.execute("SELECT file FROM generations WHERE id = ? AND kind = 'comic'", (gid,)).fetchone()
    if not row:
        return None
    meta = _comic_meta(row["file"])
    pages = (meta.get("thumbs") if thumb else None) \
        or meta.get("pages") or [row["file"]]
    if not 1 <= n <= len(pages):
        return None
    path = (GENERATED / pages[n - 1]).resolve()
    return path if path.is_relative_to(GENERATED.resolve()) and path.is_file() else None


def queue_comic(req: dict) -> dict:
    """{"cast": [persona, persona | "partner"], "story", "pages"}: checked here as the worker checks it."""
    cast = req.get("cast")
    if not isinstance(cast, list) or len(cast) != 2:
        raise ValueError("pick two characters")
    every = {p.handle: p for p in people.parse(read_personas())}
    a = every.get(str(cast[0]))
    if not a or not a.lora:
        raise ValueError("the first character must be a persona with a trained style")
    if cast[1] != "partner":
        b = every.get(str(cast[1]))
        if not b or b.handle == a.handle:
            raise ValueError("pick a second persona, or her partner")
        if b.medium != a.medium:
            raise ValueError(f"@{a.handle} is {a.medium} and @{b.handle} is {b.medium}")
        if a.strict or b.strict:
            raise ValueError("personas using the strict checks can't be in a comic together")
    story = " ".join(str(req.get("story") or "").split())
    if not story:
        raise ValueError("write a few words of story")
    if len(story) > COMIC_STORY:
        raise ValueError(f"keep the story under {COMIC_STORY} characters")
    bad = safety.story_blocked(story)
    if bad:
        raise ValueError(f"the story can't include: {', '.join(bad)}")
    try:
        pages = int(req.get("pages", 1))
    except (TypeError, ValueError):
        raise ValueError("bad page count")
    if not 1 <= pages <= COMIC_PAGES:
        raise ValueError(f"1 to {COMIC_PAGES} pages")
    with db() as conn:
        jid = conn.execute("INSERT INTO jobs(params, status) VALUES (?, 'queued')", (json.dumps(
            {"kind": "comic", "cast": [a.handle, str(cast[1])], "story": story, "pages": pages}),)).lastrowid
    return {"job": jid}


def queue_comic_import(req: dict) -> dict:
    """{"url", "title", "medium"}: a comic from its gallery's link, kept as drawn."""
    url = str(req.get("url") or "").strip()
    if not re.match(r"https?://[^\s/]+\.[^\s/]+/\S*$", url):
        raise ValueError("paste a link to the comic's gallery")
    if re.match(r"https?://(www\.)?multporn\.net/sites/", url):
        raise ValueError("that's multporn's full-screen viewer, which doesn't say which comic it shows: "
                         "paste the comic's own page instead (multporn.net/comics/...)")
    title = " ".join(str(req.get("title") or "").split())[:COMIC_TITLE]
    medium = req.get("medium")
    if medium not in MEDIUMS:
        raise ValueError("pick furry or anime")
    bad = safety.story_blocked(f"{title} {url}")
    if bad:
        raise ValueError(f"the comic can't include: {', '.join(bad)}")
    with db() as conn:
        jid = conn.execute("INSERT INTO jobs(params, status) VALUES (?, 'queued')", (json.dumps(
            {"kind": "comic_import", "url": url, "title": title, "medium": medium}),)).lastrowid
    return {"job": jid}


def queue_comic_update(req: dict) -> dict:
    """{"id": N}: look for new pages of that imported comic now (they're looked for daily anyway)."""
    try:
        gid = int(req["id"])
    except (KeyError, TypeError, ValueError):
        raise ValueError('send {"id": number}')
    _, meta = _finished_comic(gid)
    if not meta.get("imported"):
        raise ValueError("only imported comics have a source to look at")
    with db() as conn:
        if conn.execute("SELECT 1 FROM jobs WHERE status IN ('queued', 'running') AND params = ?",
                        (json.dumps({"kind": "comic_update", "id": gid}),)).fetchone():
            raise ValueError("already looking")
        jid = conn.execute("INSERT INTO jobs(params, status) VALUES (?, 'queued')",
                           (json.dumps({"kind": "comic_update", "id": gid}),)).lastrowid
    return {"job": jid}


ANIMATE_MOTION = 200      # characters of "what moves"
ANIMATE_CASTS = ("woman", "women", "woman and man", "man", "men")   # comicanim.CASTS
OUTLINE_LOOPS = 8         # loops drawn around what moves, per panel
OUTLINE_POINTS = 2000     # per loop


def _finished_comic(gid: int) -> tuple[Path, dict]:
    with db() as conn:
        row = conn.execute("SELECT file FROM generations WHERE id = ? AND kind = 'comic' AND status = 'comic'",
                           (gid,)).fetchone()
    if not row:
        raise LookupError("no such comic")
    folder = (GENERATED / row["file"]).parent.resolve()
    if not folder.is_relative_to(GENERATED.resolve()):
        raise LookupError("no such comic")
    return folder, read_json(folder / "comic.json")


def queue_comic_animation(req: dict) -> dict:
    """{"id", "page" (from 1), "box": [x0, y0, x1, y1] shares of the page, "motion", "cast",
    "outline": [[[x, y], ...], ...] loops drawn around what moves, shares of the page (optional;
    they may reach past the panel)}: one panel animated into a short loop."""
    gid = int(req.get("id", 0))
    folder, meta = _finished_comic(gid)
    try:
        page = int(req.get("page", 0))
    except (TypeError, ValueError):
        raise ValueError("bad page")
    if not 1 <= page <= len(meta.get("pages") or []):
        raise ValueError("bad page")
    box = req.get("box")
    if not isinstance(box, list) or len(box) != 4 or not all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in box):
        raise ValueError("bad panel")
    x0, y0, x1, y1 = (round(float(v), 4) for v in box)
    if x1 - x0 < 0.05 or y1 - y0 < 0.05:
        raise ValueError("that panel is too small")
    motion = " ".join(str(req.get("motion") or "").split())
    if len(motion) > ANIMATE_MOTION:
        raise ValueError(f"keep it under {ANIMATE_MOTION} characters")
    bad = safety.request_blocked(motion)
    if bad:
        raise ValueError(f"can't include: {', '.join(bad)}")
    cast = str(req.get("cast") or "")
    if cast and cast not in ANIMATE_CASTS:
        raise ValueError("bad choice of who's in it")
    outline = req.get("outline") or []
    if not isinstance(outline, list) or len(outline) > OUTLINE_LOOPS:
        raise ValueError(f"at most {OUTLINE_LOOPS} outlines")
    loops = []
    for loop in outline:
        if not isinstance(loop, list) or not 3 <= len(loop) <= OUTLINE_POINTS or not all(
                isinstance(q, list) and len(q) == 2 and all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in q) for q in loop):
            raise ValueError("bad outline")
        loops.append([[round(float(x), 4), round(float(y), 4)] for x, y in loop])
    params = {"kind": "comic_animate", "id": gid, "page": page, "box": [x0, y0, x1, y1], "motion": motion, "cast": cast}
    if loops:
        params["outline"] = loops
    with db() as conn:
        if conn.execute("SELECT count(*) FROM jobs WHERE status IN ('queued', 'running') AND params = ?",
                        (json.dumps(params),)).fetchone()[0]:
            raise ValueError("this exact animation is already waiting")
        jid = conn.execute("INSERT INTO jobs(params, status) VALUES (?, 'queued')", (json.dumps(params),)).lastrowid
    return {"job": jid}


def delete_comic_animation(req: dict) -> dict:
    """{"id", "index"}: an animated panel back to the still page."""
    gid, index = int(req.get("id", 0)), int(req.get("index", -1))
    folder, meta = _finished_comic(gid)
    anims = meta.get("animations") or []
    if not 0 <= index < len(anims):
        raise LookupError("no such animation")
    gone = anims.pop(index)
    for file in (gone["file"], gone.get("mask")):
        path = (GENERATED / file).resolve() if file else None
        if path and path.is_relative_to(folder):
            path.unlink(missing_ok=True)
    (folder / "comic.json").write_text(json.dumps(meta | {"animations": anims}, ensure_ascii=False, indent=1))
    return {"ok": True}


def comic_animation(gid: int, name: str) -> Path | None:
    """A comic's clip, or the mask of what moves in it, by its file name (names are never
    reused, so a cached copy is the right one)."""
    try:
        folder, meta = _finished_comic(gid)
    except LookupError:
        return None
    for a in meta.get("animations") or []:
        for file in (a["file"], a.get("mask")):
            if file and Path(file).name == name:
                path = (GENERATED / file).resolve()
                return path if path.is_relative_to(folder) and path.is_file() else None
    return None


def rename_comic(req: dict) -> dict:
    """{"id", "title"}"""
    gid = int(req.get("id", 0))
    title = " ".join(str(req.get("title") or "").split())[:COMIC_TITLE]
    if not title:
        raise ValueError("give it a title")
    bad = safety.story_blocked(title)
    if bad:
        raise ValueError(f"the title can't include: {', '.join(bad)}")
    folder, meta = _finished_comic(gid)
    (folder / "comic.json").write_text(json.dumps(meta | {"title": title}, ensure_ascii=False, indent=1))
    with db() as conn:
        conn.execute("UPDATE generations SET caption = ? WHERE id = ?", (title, gid))
    return {"ok": True, "title": title}


def delete_comic(req: dict) -> dict:
    gid = int(req.get("id", 0))
    with db() as conn:
        row = conn.execute("SELECT file FROM generations WHERE id = ? AND kind = 'comic'", (gid,)).fetchone()
        if not row:
            raise LookupError("no such comic")
        folder = (GENERATED / row["file"]).parent.resolve()
        if folder.is_relative_to(GENERATED.resolve()) and folder != GENERATED.resolve():
            shutil.rmtree(folder, ignore_errors=True)
        conn.execute("UPDATE generations SET status = 'deleted' WHERE id = ?", (gid,))
    return {"ok": True}


def scene_acts(req: dict) -> dict:
    """The acts a scene from this post can be made of, for the picker."""
    with db() as conn:
        row = conn.execute("SELECT prompt FROM generations WHERE id = ? AND kind = 'image'",
                           (int(req.get("id", 0)),)).fetchone()
    if not row:
        raise LookupError("no such image")
    k = acts.kind(row[0] or "")
    return {"kind": k, "slots": [{"slot": s, "label": label, "options": list(opts)} for s, label, opts in acts.SLOTS[k]]}


def request_animation(req: dict) -> dict:
    with db() as conn:
        if "id" in req:
            gid = int(req["id"])
            row = conn.execute("SELECT kind, status FROM generations WHERE id = ?", (gid,)).fetchone()
            if not row or row["kind"] != "image" or row["status"] != "feed":
                raise LookupError("only images in the feed can be animated")
            if req.get("scene"):
                tags = conn.execute("SELECT coalesce(tags, prompt) FROM generations WHERE id = ?", (gid,)).fetchone()[0]
                # POV pictures show only part of him: the tagger says 1boy or hetero, not duo.
                if not {"duo", "1boy", "hetero", "2girls", "yuri"} & {t.strip() for t in (tags or "").split(",")}:
                    raise ValueError("scenes need a post with two characters")
                prompt = conn.execute("SELECT prompt FROM generations WHERE id = ?", (gid,)).fetchone()[0] or ""
                picks = acts.checked(prompt, req.get("picks"))   # chosen acts; the rest random
                params = {"kind": "scene", "ids": [gid]} | ({"picks": picks} if picks else {})
                if conn.execute("SELECT count(*) FROM jobs WHERE status IN ('queued', 'running') AND params = ?",
                                (json.dumps(params),)).fetchone()[0]:
                    raise ValueError("a scene from this post is already waiting")
                jid = conn.execute("INSERT INTO jobs(params, status) VALUES (?, 'queued')",
                                   (json.dumps(params),)).lastrowid
                return {"job": jid}
            text = " ".join(str(req.get("prompt") or "").split())
            if len(text) > MAX_PROMPT:
                raise ValueError(f"keep the description under {MAX_PROMPT} characters")
            bad = safety.request_blocked(text)   # the worker checks every prompt again regardless
            if bad:
                raise ValueError(f"the description can't include: {', '.join(bad)}")
            params = {"kind": "animate", "ids": [gid]}
            if text:
                params["prompt"] = text
            # Same image with a new description is fine; the identical request twice is a double tap.
            dup = conn.execute("SELECT count(*) FROM jobs WHERE status IN ('queued', 'running') AND params = ?",
                               (json.dumps(params),)).fetchone()[0]
            if dup:
                raise ValueError("this exact animation is already waiting")
        else:
            count = int(req.get("count", 0))
            if not 1 <= count <= 50:
                raise ValueError("count must be between 1 and 50")
            params = {"kind": "animate", "count": count}
        jid = conn.execute("INSERT INTO jobs(params, status) VALUES (?, 'queued')", (json.dumps(params),)).lastrowid
    return {"job": jid}


RETRYABLE = ("comic_animate", "comic_import", "comic", "animate", "scene")   # job kinds Try again can repeat


def _retried(conn, job: int, params: str) -> bool:
    """Whether the same request was queued again after job."""
    return bool(conn.execute("SELECT 1 FROM jobs WHERE id > ? AND params = ? LIMIT 1", (job, params)).fetchone())


def retry_job(req: dict) -> dict:
    """{"job"}: a failed request queued again exactly as it was asked (a panel's outline too)."""
    with db() as conn:
        row = conn.execute("SELECT params, status FROM jobs WHERE id = ?", (int(req.get("job", 0)),)).fetchone()
        if not row:
            raise LookupError("no such request")
        if row["status"] != "failed" or json.loads(row["params"]).get("kind") not in RETRYABLE:
            raise ValueError("only a failed animation, scene or comic can be tried again")
        if conn.execute("SELECT count(*) FROM jobs WHERE status IN ('queued', 'running') AND params = ?",
                        (row["params"],)).fetchone()[0]:
            raise ValueError("it's already waiting to be tried again")
        jid = conn.execute("INSERT INTO jobs(params, status) VALUES (?, 'queued')", (row["params"],)).lastrowid
    return {"job": jid}


def cancel(req: dict) -> dict:
    with db() as conn:
        if "job" in req:
            conn.execute("UPDATE jobs SET status = 'cancelled', finished_at = datetime('now')"
                         " WHERE id = ? AND status = 'queued'", (int(req["job"]),))
        if "night" in req:
            conn.execute("UPDATE runs SET cancel = 1 WHERE night = ? AND status = 'running'", (str(req["night"]),))
    return {"ok": True}


# ---------- persona editor ----------
# Edits go to data/personas.json, the same file the worker reads every run. Each save is
# checked with the worker's own rules (blocked tags, placeholders, strict mode) before it is
# written, so a bad edit is refused here instead of breaking the nightly run.
EDIT_LOCK = threading.Lock()
TEXT_FIELDS = {"name": 60, "bio": 300, "look": 1000, "avatar": 500, "negative": 500, "based_on": 200}
LIST_FIELDS = {"characters": (30, 300), "outfits": (40, 200), "partners": (30, 200), "girlfriends": (30, 200), "friends": (10, 20), "must_not_show": (12, 60), "settings": (40, 200), "emoji": (10, 16),
               "hashtags": (10, 40)}
MAX_POST_KINDS = 12
NEW_FILE = {"_note": "Private. Fictional posters for the dreamfeed timeline, edited from the dashboard or by hand. "
                     "based_on is a private reminder only; it is never shown or used in prompts.", "personas": []}


def read_personas() -> dict:
    if not PERSONAS.is_file():
        return json.loads(json.dumps(NEW_FILE))
    raw = json.loads(PERSONAS.read_text())
    raw.setdefault("personas", [])
    return raw


def write_personas(raw: dict) -> None:
    tmp = PERSONAS.with_name(PERSONAS.name + ".tmp")
    tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
    if PERSONAS.is_file():
        shutil.copy2(PERSONAS, PERSONAS.with_name(PERSONAS.name + ".bak"))   # one step of undo
    os.replace(tmp, PERSONAS)


def styles() -> list[dict]:
    """Trained style LoRAs: a prep.json from lora-prep and the trainer's output file."""
    out = []
    for prep in sorted((DATA / "lora").glob("*/prep.json")):
        info, name = read_json(prep), prep.parent.name
        file = f"style-{name}.safetensors"
        if info.get("trigger") and info.get("medium") in MEDIUMS and (LORA_DIR / file).is_file():
            out.append({"name": name, "medium": info["medium"], "trigger": info["trigger"], "file": file})
    return out


def voices() -> dict[str, int]:
    """Styles with a saved voice (voice.json): name -> how many lines, the character's
    speech-bubble lines when there are any (what captions use), else the artist's posts."""
    out = {}
    for f in sorted((DATA / "lora").glob("*/voice.json")):
        d = read_json(f)
        n = len(d.get("speech") or d.get("posts") or [])
        if n:
            out[f.parent.name] = n
    return out


def persona_config() -> dict:
    out = {"personas": [], "styles": styles(), "voices": voices(), "error": None,
           "ratings": list(people.RATINGS), "mediums": list(MEDIUMS)}
    try:
        raw = read_personas()
    except ValueError as e:
        out["error"] = f"data/personas.json is not valid JSON: {e}"
        return out
    try:
        checked = {p.handle: p for p in people.parse(raw)}
    except (ValueError, TypeError) as e:
        checked, out["error"] = {}, str(e)
    with db() as conn:
        avatars = {r[0] for r in conn.execute("SELECT handle FROM personas WHERE avatar IS NOT NULL")}
    for entry in raw["personas"]:
        p = checked.get(entry.get("handle"))
        lo = entry.get("lora") or None
        art = entry.get("art") or None
        out["personas"].append(entry | {
            "art": art and {"style": str(art.get("file", "")).removeprefix("style-").removesuffix(".safetensors"),
                            "strength": art.get("strength", 0.5), "enabled": art.get("enabled", True) is not False},
            "strict": bool(p and p.strict), "has_avatar": entry.get("handle") in avatars,
            "lora": lo and {"style": str(lo.get("file", "")).removeprefix("style-").removesuffix(".safetensors"),
                            "strength": lo.get("strength", 0.8), "female_only": bool(lo.get("female_only")),
                            "enabled": lo.get("enabled", True) is not False}})
    return out


def _text(v, limit: int, what: str) -> str:
    v = " ".join(str(v or "").split())
    if len(v) > limit:
        raise ValueError(f"{what} is too long (at most {limit} characters)")
    return v


def _list(v, n: int, limit: int, what: str) -> list[str]:
    items = [_text(x, limit, what) for x in (v or []) if str(x).strip()]
    if len(items) > n:
        raise ValueError(f"at most {n} {what}")
    return items


def _num(v, lo: float, hi: float, what: str) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number")
    if not lo <= x <= hi:
        raise ValueError(f"{what} must be between {lo:g} and {hi:g}")
    return round(x, 3)


def _apply(entry: dict, src: dict) -> dict:
    """The editable fields from the dashboard onto the stored entry (other keys are kept)."""
    if not isinstance(src, dict):
        raise ValueError("send the persona as an object")
    entry = dict(entry)
    for k, limit in TEXT_FIELDS.items():
        if k in src:
            entry[k] = _text(src[k], limit, k)
            if not entry[k] and k != "name":
                entry.pop(k)
    for k, (n, limit) in LIST_FIELDS.items():
        if k in src:
            entry[k] = _list(src[k], n, limit, k)
            if not entry[k]:
                entry.pop(k)
    if "must_show" in src:   # traits, each a list of tags any of which counts
        groups = [_list(g, 6, 60, "must show") for g in (src["must_show"] or [])[:8] if isinstance(g, list)]
        entry["must_show"] = [g for g in groups if g]
        if not entry["must_show"]:
            entry.pop("must_show")
    if "medium" in src:
        entry["medium"] = src["medium"]
    if "weight" in src:
        entry["weight"] = _num(src["weight"], 0.1, 5, "how often they post")
    if "video_share" in src:
        entry["video_share"] = _num(src["video_share"], 0, 1, "video share")
    if "paused" in src:
        entry["paused"] = bool(src["paused"])
        if not entry["paused"]:
            entry.pop("paused")
    if "posts" in src:
        if not isinstance(src["posts"], list) or len(src["posts"]) > MAX_POST_KINDS:
            raise ValueError(f"at most {MAX_POST_KINDS} kinds of post")
        entry["posts"] = [{"kind": _text(k.get("kind") or "post", 40, "kind"),
                           "weight": _num(k.get("weight", 1), 0.1, 10, "post weight"),
                           "rating": k.get("rating") if k.get("rating") in people.RATINGS else "explicit",
                           "prompt": _text(k.get("prompt"), 1000, "prompt"),
                           "captions": _list(k.get("captions"), 30, 280, "captions")}
                          for k in src["posts"] if isinstance(k, dict)]
    if "voice" in src:
        v = str(src["voice"] or "")
        if v and v != entry.get("voice") and v not in voices():
            raise ValueError("pick a style that has saved posts for captions")
        entry["voice"] = v
        if not v:
            entry.pop("voice")
    if "lora" in src:
        entry["lora"] = _lora(entry.get("lora"), src["lora"], entry.get("medium"))
        if not entry["lora"]:
            entry.pop("lora")
    if "art" in src:   # the artist's style, with a character LoRA in "lora"
        entry["art"] = _lora(entry.get("art"), src["art"], entry.get("medium"))
        if entry["art"]:
            entry["art"].pop("female_only", None)
        else:
            entry.pop("art")
    return entry


def _lora(old: dict | None, want, medium: str | None) -> dict | None:
    if not want:
        return None
    if not isinstance(want, dict):
        raise ValueError("bad style settings")
    name = str(want.get("style", ""))
    style = next((s for s in styles() if s["name"] == name), None)
    if style:
        if style["medium"] != medium:
            raise ValueError(f"the {name} style is trained for {style['medium']}, not {medium}")
        out = {"file": style["file"], "trigger": style["trigger"]}
    elif old and str(old.get("file", "")) == f"style-{name}.safetensors":
        out = {"file": old["file"], "trigger": old.get("trigger", "")}   # file missing for now; keep it
    else:
        raise ValueError("pick a trained style")
    out["strength"] = _num(want.get("strength", 0.8), 0.2, 1.2, "style strength")
    if want.get("female_only"):
        out["female_only"] = True
    if want.get("enabled", True) is False:
        out["enabled"] = False
    return out


def _commit(raw: dict) -> list:
    checked = people.parse(raw)   # people.Invalid (a ValueError) becomes a 400 with its message
    write_personas(raw)
    with db() as conn:
        people.sync(conn, checked)
    return checked


def save_persona(req: dict) -> dict:
    original = req.get("original")
    with EDIT_LOCK:
        raw = read_personas()
        handles = [p.get("handle") for p in raw["personas"]]
        if original:
            if original not in handles:
                raise LookupError("that persona no longer exists; reload the page")
            i = handles.index(original)
            raw["personas"][i] = _apply(raw["personas"][i], req.get("persona")) | {"handle": original}
        else:
            handle = str((req.get("persona") or {}).get("handle", "")).strip().lower()
            if not HANDLE.match(handle):
                raise ValueError("handle must be 2-20 of a-z 0-9 _")
            if handle in handles:
                raise ValueError(f"@{handle} is taken")
            with db() as conn:   # a removed persona's old posts would come back under the new one
                if conn.execute("SELECT 1 FROM personas WHERE handle = ?", (handle,)).fetchone():
                    raise ValueError(f"@{handle} was used before; pick another handle")
            raw["personas"].append(_apply({"handle": handle}, req.get("persona")) | {"handle": handle})
        _commit(raw)
    return {"ok": True}


def delete_persona(req: dict) -> dict:
    handle = str(req.get("handle", ""))
    with EDIT_LOCK:
        raw = read_personas()
        keep = [p for p in raw["personas"] if p.get("handle") != handle]
        if len(keep) == len(raw["personas"]):
            raise LookupError("no such persona")
        raw["personas"] = keep
        _commit(raw)
    return {"ok": True}


def new_avatar(req: dict) -> dict:
    handle = str(req.get("handle", ""))
    if not HANDLE.match(handle):
        raise ValueError("bad handle")
    with db() as conn:
        row = conn.execute("SELECT avatar FROM personas WHERE handle = ? AND active = 1", (handle,)).fetchone()
        if not row:
            raise LookupError("no such persona")
        conn.execute("UPDATE personas SET avatar = NULL WHERE handle = ?", (handle,))
    if row["avatar"]:
        old = (GENERATED / row["avatar"]).resolve()
        if old.is_relative_to(GENERATED.resolve()):
            old.unlink(missing_ok=True)
    return {"ok": True}


# ---------- style training ----------
# A "style" job for the worker: download the source's images, check them (photos and
# anything the adults-only checks flag are dropped), then the trainer service trains.
STYLE_LIMITS = (100, 300, 600)
STYLE_STEPS = (1000, 2000, 3000)
VIDEO_LIMITS = (100, 300, 600)        # videos to download from the artist's page
VIDEO_STEPS = (1000, 1500, 2000)      # per half of Wan 2.2


def _jobs(kind: str) -> dict[str, dict]:
    """Queued and running jobs of one kind, by style name."""
    with db() as conn:
        return {json.loads(r["params"]).get("name"): dict(r) for r in conn.execute(
            "SELECT id, params, status FROM jobs WHERE status IN ('queued', 'running')"
            " AND params LIKE ?", (f'%"kind": "{kind}"%',))}


def _video(d: Path, st: dict, job: dict | None) -> dict:
    """A style's video LoRA: when both halves were trained, the clips, and progress."""
    halves = [LORA_DIR / f"video-{d.name}-{part}.safetensors" for part in ("high", "low")]
    prep = read_json(d / "video-prep.json")
    live = {k.removeprefix("video_"): v for k, v in st.items() if k.startswith("video_")}
    return {"trained": int(min(f.stat().st_mtime for f in halves)) if all(f.is_file() for f in halves) else None,
            "clips": prep.get("kept"), "limit": live.get("limit"), "steps": live.get("steps"),
            "job": job and {"status": job["status"]},
            "status": live if job or live.get("phase") in ("failed", "cancelled") else None}


def style_list() -> dict:
    lora = DATA / "lora"
    jobs, video_jobs = _jobs("style"), _jobs("video_style")
    try:
        users = {}
        for p in read_personas()["personas"]:
            f = str((p.get("lora") or {}).get("file", ""))
            if f and (p.get("lora") or {}).get("enabled", True) is not False:
                users.setdefault(f, []).append(p.get("name") or p.get("handle"))
    except ValueError:
        users = {}
    out = []
    for d in sorted(x for x in lora.iterdir() if x.is_dir() and not x.name.startswith(".")) if lora.is_dir() else []:
        prep, src, st = read_json(d / "prep.json"), read_json(d / "source.json"), read_json(d / "status.json")
        file = LORA_DIR / f"style-{d.name}.safetensors"
        job = jobs.get(d.name)
        out.append({"name": d.name, "medium": src.get("medium") or prep.get("medium"), "kept": prep.get("kept"),
                    "voice": len(read_json(d / "voice.json").get("posts") or []),
                    "source": src.get("source"), "limit": src.get("limit"), "steps": src.get("steps"),
                    "trained": int(file.stat().st_mtime) if file.is_file() else None,
                    "used_by": users.get(file.name, []),
                    "job": job and {"status": job["status"]},
                    # status.json is only live while a job runs; otherwise it is the last result
                    "status": st if job or st.get("phase") in ("failed", "cancelled") else None,
                    "video": _video(d, st, video_jobs.get(d.name))})
    return {"styles": out, "limits": STYLE_LIMITS, "steps": STYLE_STEPS,
            "video_limits": VIDEO_LIMITS, "video_steps": VIDEO_STEPS}


MAX_DESCRIPTION = 2000


def queue_draft(req: dict) -> dict:
    """Have the worker draft a persona from a description (worker/dreamfeed/builder.py)."""
    text = " ".join(str(req.get("description") or "").split())
    if len(text) < 10:
        raise ValueError("describe them in a few words: who they are and what they post")
    if len(text) > MAX_DESCRIPTION:
        raise ValueError(f"keep the description under {MAX_DESCRIPTION} characters")
    with db() as conn:
        if conn.execute("SELECT count(*) FROM jobs WHERE status IN ('queued', 'running')"
                        " AND params LIKE '%\"kind\": \"persona_draft\"%'").fetchone()[0]:
            raise ValueError("a persona is already being drafted; one at a time")
        jid = conn.execute("INSERT INTO jobs(params, status) VALUES (?, 'queued')",
                           (json.dumps({"kind": "persona_draft", "description": text}),)).lastrowid
    return {"job": jid}


def draft_status(job: int) -> dict:
    with db() as conn:
        row = conn.execute("SELECT params, status, message FROM jobs WHERE id = ?", (job,)).fetchone()
        if not row or json.loads(row["params"]).get("kind") != "persona_draft":
            raise LookupError("no such draft")
        ahead = conn.execute("SELECT count(*) FROM jobs WHERE status IN ('queued', 'running') AND id < ?",
                             (job,)).fetchone()[0]
        night = conn.execute("SELECT count(*) FROM runs WHERE status = 'running' AND night GLOB '[0-9]*'"
                             ).fetchone()[0]
    out = {"status": row["status"], "message": row["message"], "ahead": ahead, "night_running": bool(night)}
    if row["status"] == "done":
        out["draft"] = read_json(DATA / "drafts" / f"{job}.json") or None
    return out


def queue_style(req: dict) -> dict:
    name = str(req.get("name", "")).strip().lower()
    medium, source = req.get("medium"), str(req.get("source", "")).strip()
    if not HANDLE.match(name):
        raise ValueError("name must be 2-20 of a-z 0-9 _")
    if medium not in MEDIUMS:
        raise ValueError("pick anime or furry")
    if not re.match(r"^https://[^\s/]+\.[^\s/]+/\S*$", source) or len(source) > 300:
        raise ValueError("the source must be an https:// link to the artist's page")
    try:
        limit, steps = int(req.get("limit", 300)), int(req.get("steps", 2000))
    except (TypeError, ValueError):
        raise ValueError("bad numbers")
    if limit not in STYLE_LIMITS or steps not in STYLE_STEPS:
        raise ValueError("pick one of the offered sizes")
    known = next((s for s in style_list()["styles"] if s["name"] == name), None)
    if known and known["medium"] and known["medium"] != medium:
        raise ValueError(f"the {name} style is {known['medium']}; use another name for {medium}")
    with db() as conn:
        if conn.execute("SELECT count(*) FROM jobs WHERE status IN ('queued', 'running')"
                        " AND params LIKE '%\"kind\": \"style\"%'").fetchone()[0]:
            raise ValueError("a style is already being trained; one at a time")
        jid = conn.execute("INSERT INTO jobs(params, status) VALUES (?, 'queued')", (json.dumps(
            {"kind": "style", "name": name, "medium": medium, "source": source, "limit": limit,
             "steps": steps, "videos": bool(req.get("videos"))}),)).lastrowid
    return {"job": jid}


def cancel_style(req: dict) -> dict:
    name = str(req.get("name", ""))
    if not HANDLE.match(name):
        raise ValueError("bad name")
    with db() as conn:
        for r in conn.execute("SELECT id, params, status FROM jobs WHERE status IN ('queued', 'running')"
                              " AND params LIKE '%\"kind\": \"style\"%'").fetchall():
            if json.loads(r["params"]).get("name") != name:
                continue
            if r["status"] == "queued":
                conn.execute("UPDATE jobs SET status = 'cancelled', finished_at = datetime('now') WHERE id = ?",
                             (r["id"],))
            else:
                (DATA / "lora" / name / "cancel").touch()   # the worker and trainer watch for this
            return {"ok": True}
    raise LookupError("nothing is running for that style")


def queue_video(req: dict) -> dict:
    """Train a video LoRA for a trained style from the artist's own animations."""
    name = str(req.get("name", ""))
    if not HANDLE.match(name):
        raise ValueError("bad name")
    try:
        limit, steps = int(req.get("limit", 300)), int(req.get("steps", 1500))
    except (TypeError, ValueError):
        raise ValueError("bad numbers")
    if limit not in VIDEO_LIMITS or steps not in VIDEO_STEPS:
        raise ValueError("pick one of the offered sizes")
    style = next((s for s in style_list()["styles"] if s["name"] == name), None)
    if not style or not style["trained"] or not style["source"]:
        raise ValueError("train the style first: video training uses its artist's page")
    if style["job"]:
        raise ValueError("wait for the style's own training to finish")
    if _jobs("video_style"):
        raise ValueError("a video LoRA is already being trained; one at a time")
    with db() as conn:
        jid = conn.execute("INSERT INTO jobs(params, status) VALUES (?, 'queued')", (json.dumps(
            {"kind": "video_style", "name": name, "limit": limit, "steps": steps}),)).lastrowid
    return {"job": jid}


def cancel_video(req: dict) -> dict:
    name = str(req.get("name", ""))
    if not HANDLE.match(name):
        raise ValueError("bad name")
    job = _jobs("video_style").get(name)
    if not job:
        raise LookupError("no video training is running for that style")
    if job["status"] == "queued":
        with db() as conn:
            conn.execute("UPDATE jobs SET status = 'cancelled', finished_at = datetime('now') WHERE id = ?",
                         (job["id"],))
    else:
        (DATA / "lora" / name / "video-cancel").touch()   # the worker and video trainer watch for this
    return {"ok": True}


class Handler(BaseHTTPRequestHandler):
    def send(self, code: int, body, ctype="application/json", cache="no-store"):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Security-Policy", CSP)
        for k, v in formlogin.SECURITY_HEADERS:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, file: Path) -> None:
        """Images whole; videos also in byte ranges, which phones need to play them."""
        ctype = {".png": "image/png", ".mp4": "video/mp4", ".webp": "image/webp", ".webm": "video/webm",
                 ".gif": "image/gif", ".mov": "video/mp4", ".m4v": "video/mp4",
                 ".mkv": "video/x-matroska"}.get(file.suffix.lower(), "image/jpeg")
        size = file.stat().st_size
        start, end = 0, size - 1
        rng = self.headers.get("Range", "")
        partial = rng.startswith("bytes=") and "," not in rng
        if partial:
            a, _, b = rng[6:].partition("-")
            try:
                if a:
                    start, end = int(a), min(int(b) if b else size - 1, size - 1)
                else:
                    start = max(0, size - int(b))
            except ValueError:
                partial = False
            if partial and start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "private, max-age=604800, immutable")
        self.send_header("Content-Security-Policy", CSP)
        for k, v in formlogin.SECURITY_HEADERS:
            self.send_header(k, v)
        self.end_headers()
        with file.open("rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = f.read(min(1 << 20, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def query(self) -> dict:
        from urllib.parse import parse_qs, urlsplit
        return {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}

    def do_GET(self):
        path = self.path.split("?")[0]
        if formlogin.httpserver.handle(self, LOGIN, path):
            return
        if path in ("/", "/index.html") or path.strip("/").split("/")[0] in PAGES:
            prefix = (self.headers.get("X-Forwarded-Prefix") or "").rstrip("/")
            base = (prefix if PREFIX.match(prefix) else "") + "/"
            page = PAGE.read_bytes().replace(b"<head>", b'<head>\n<base href="' + base.encode() + b'">', 1)
            return self.send(200, page, "text/html; charset=utf-8")
        if path == "/api/feed":
            q = self.query()
            try:
                offset = max(0, int(q.get("offset", "0")))
            except ValueError:
                return self.send(400, {"error": "offset must be a number"})
            persona = q.get("persona", "")
            if persona and not HANDLE.match(persona):
                return self.send(400, {"error": "bad persona"})
            if q.get("view") == "liked":
                return self.send(200, saved_view(q.get("medium", "all"), offset, q.get("source", "all")))
            gid = q.get("id", "")
            if gid and not gid.isdigit():
                return self.send(400, {"error": "bad id"})
            return self.send(200, feed(q.get("view", "feed"), q.get("medium", "all"), offset, persona, int(gid) if gid else None))
        if path == "/api/personas":
            return self.send(200, personas())
        if path == "/api/personas/edit":
            return self.send(200, persona_config())
        if path == "/api/styles":
            return self.send(200, style_list())
        if path == "/api/personas/draft":
            job = self.query().get("job", "")
            if not job.isdigit():
                return self.send(400, {"error": "bad job"})
            try:
                return self.send(200, draft_status(int(job)))
            except LookupError as e:
                return self.send(404, {"error": str(e)})
        if path.startswith("/avatar/"):
            file = avatar_path(path[len("/avatar/"):])
            if not file:
                return self.send(404, {"error": "no profile picture yet"})
            return self.send_file(file)
        if path == "/api/comics":
            return self.send(200, comics())
        if path.startswith("/comic/"):
            parts = path.split("/")
            if len(parts) == 5 and parts[2].isdigit() and parts[3] == "anim" and re.fullmatch(r"[\w.-]+\.(mp4|png)", parts[4]):
                file = comic_animation(int(parts[2]), parts[4])
                if file:
                    return self.send_file(file)
            if len(parts) in (4, 5) and parts[2].isdigit() and parts[3].isdigit() and parts[4:] in ([], ["thumb"]):
                file = comic_page(int(parts[2]), int(parts[3]), thumb=parts[4:] == ["thumb"])
                if file:
                    return self.send_file(file)
            return self.send(404, {"error": "page not found"})
        if path == "/api/summary":
            return self.send(200, summary())
        if path == "/api/dashboard":
            return self.send(200, dashboard())
        if path == "/api/following":
            return self.send(200, following())
        if path == "/api/live/stream":
            try:
                return self.send(200, live_stream(self.query().get("name", "")))
            except ValueError as e:
                return self.send(400, {"error": str(e)})
            except LookupError as e:
                return self.send(404, {"error": str(e)})
        if path == "/api/discover/cb":
            q = self.query()
            try:
                return self.send(200, discover_cb(q.get("mode", "foryou"), q.get("q", ""), q.get("gender", ""), max(0, int(q.get("offset", "0") or 0))))
            except ValueError as e:
                return self.send(400, {"error": str(e)})
            except LookupError as e:
                return self.send(502, {"error": str(e)})
        if path == "/api/reddit/browse":
            q = self.query()
            try:
                return self.send(200, browse(q.get("sub", ""), q.get("sort", "hot"), q.get("after", "")))
            except ValueError as e:
                return self.send(400, {"error": str(e)})
            except LookupError as e:
                return self.send(502, {"error": str(e)})
        if path == "/api/person/posts":
            q = self.query()
            try:
                return self.send(200, person_posts(q.get("source", ""), q.get("handle", ""), q.get("cursor", "")))
            except ValueError as e:
                return self.send(400, {"error": str(e)})
            except LookupError as e:
                return self.send(502, {"error": str(e)})
        if path == "/api/reddit/browses":
            return self.send(200, recent_browses())
        if path == "/api/discover/x":
            return self.send(200, discover_x())
        if path == "/api/post":
            try:
                return self.send(200, one_post(self.query().get("id", "")))
            except ValueError as e:
                return self.send(400, {"error": str(e)})
            except LookupError as e:
                return self.send(404, {"error": str(e)[:200]})
        if path == "/api/reddit/random":
            try:
                return self.send(200, random_subreddit(self.query().get("not", "")))
            except ValueError as e:
                return self.send(400, {"error": str(e)})
            except LookupError as e:
                return self.send(502, {"error": str(e)})
        if path == "/api/videos/more":
            q = self.query()
            try:
                return self.send(200, more_videos(q.get("id", ""), q.get("cursor", "")))
            except ValueError as e:
                return self.send(400, {"error": str(e)})
            except (LookupError, OSError) as e:
                return self.send(502, {"error": str(e)[:200]})
        if path == "/api/x/related":
            q = self.query()
            try:
                d = livefeeds.x_related(q.get("id", ""), q.get("handle", ""), q.get("cursor", ""))
                _seen(d["posts"], [])
                posts, reads = _unshown(d["posts"]), 1     # (shown to you before: passed over, read on)
                while len(posts) < 3 and d["cursor"] and reads < FRESH_READS:
                    d = livefeeds.x_related(q.get("id", ""), q.get("handle", ""), d["cursor"])
                    _seen(d["posts"], [])
                    posts += _unshown(d["posts"]); reads += 1
                d = {**d, "posts": posts}
                return self.send(200, {"posts": _mark_saved(d["posts"]), "cursor": d["cursor"]})
            except ValueError as e:
                return self.send(400, {"error": str(e)})
            except LookupError as e:
                return self.send(502, {"error": str(e)})
        if path == "/api/redgifs":
            q = self.query()
            try:
                return self.send(200, livefeeds.redgifs_page(q.get("name", ""), int(q.get("page", "1") or 1)))
            except ValueError as e:
                return self.send(400, {"error": str(e)})
            except LookupError as e:
                return self.send(502, {"error": str(e)})
        if path == "/api/redgifs/clip":
            try:
                clip = livefeeds.redgifs_clip(self.query().get("id", ""))
            except ValueError as e:
                return self.send(400, {"error": str(e)})
            return self.send(200, {"clip": clip}) if clip else self.send(404, {"error": "that clip isn't there"})
        if path == "/api/xvideos":
            q = self.query()
            try:
                return self.send(200, livefeeds.xvideos_page(q.get("name", ""), int(q.get("page", "0") or 0)))
            except ValueError as e:
                return self.send(400, {"error": str(e)})
            except LookupError as e:
                return self.send(502, {"error": str(e)})
        if path == "/api/post/comments":
            try:
                return self.send(200, {"comments": livefeeds.comments(self.query().get("id", ""))})
            except ValueError as e:
                return self.send(400, {"error": str(e)})
            except (LookupError, OSError) as e:
                return self.send(502, {"error": str(e)[:200]})
        if path == "/api/signins":
            return self.send(200, signins(self.headers))
        if path == "/api/auth-check":          # (the proxy asks, before the server's browser: signed in here?)
            return self.send(200, {"ok": True})
        if path in ("/reddit/login", "/reddit/callback"):
            prefix = (self.headers.get("X-Forwarded-Prefix") or "").rstrip("/")
            back = (prefix if PREFIX.match(prefix) else "") + "/dashboard"
            try:
                if path == "/reddit/login":
                    where = reddit_login_url(self.headers)
                else:
                    where = back + "?reddit=" + urllib.parse.quote(reddit_callback(self.query(), self.headers))
            except ValueError as e:
                where = back + "?reddit=" + urllib.parse.quote(str(e))
            self.send_response(302)
            self.send_header("Location", where)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/api/profile":
            q = self.query()
            try:
                return self.send(200, profile(q.get("room", ""), q.get("x", ""), q.get("reddit", ""), q.get("e621", ""), q.get("bsky", "")))
            except ValueError as e:
                return self.send(400, {"error": str(e)})
            except LookupError as e:
                return self.send(502, {"error": str(e)})
        if path.startswith("/cb-thumb/"):
            name = path[len("/cb-thumb/"):].removesuffix(".jpg")
            data = cb_thumb(name) if ROOM.match(name) else None
            if not data:
                return self.send(404, {"error": "no thumbnail"})
            return self.send(200, data, "image/jpeg", cache="private, max-age=60")
        if path == "/api/live/videos":
            try:
                return self.send(200, live_videos(self.query().get("name", "")))
            except ValueError as e:
                return self.send(400, {"error": str(e)})
            except LookupError as e:
                return self.send(404, {"error": str(e)})
        if path.startswith("/cb-videos/poster/"):
            k = path[len("/cb-videos/poster/"):].removesuffix(".jpg")
            file = cbvideos.posters(DATA) / f"{k}.jpg"
            if not re.fullmatch(r"[0-9a-f]{20}", k) or not file.is_file():
                return self.send(404, {"error": "no poster"})
            return self.send_file(file)
        if path.startswith("/cb-videos/"):
            room, _, rel = path[len("/cb-videos/"):].partition("/")
            file = cbvideos.file(room, urllib.parse.unquote(rel), _followed())
            if not file:
                return self.send(404, {"error": "not found"})
            return self.send_file(file)
        if path == "/api/comics/search":
            q = self.query()
            try:
                return self.send(200, comic_search(q.get("q", ""), max(0, int(q.get("page", "0") or 0)), q.get("site", "multporn")))
            except ValueError as e:
                return self.send(400, {"error": str(e)})
            except LookupError as e:
                return self.send(502, {"error": str(e)})
        if path == "/comic-search/thumb":
            data = comic_cover(self.query().get("u", ""))
            if not data:
                return self.send(404, {"error": "no cover"})
            return self.send(200, data, "image/jpeg", cache="private, max-age=86400")
        if path == "/vendor/hls.min.js":
            return self.send(200, (Path(__file__).parent / "vendor" / "hls.min.js").read_bytes(),
                             "text/javascript; charset=utf-8", cache="private, max-age=604800")
        if path == "/api/following/settings":
            return self.send(200, follow_settings())
        if path == "/api/following/posts":
            q = self.query()
            try:
                return self.send(200, follow_posts(q.get("source", "all"), q.get("cursor", ""), q.get("mode", "following"),
                                                   q.get("tags", "")))
            except ValueError as e:
                return self.send(400, {"error": str(e)})
        if path == "/api/saved/import":
            return self.send(200, import_status())
        if path.startswith("/saved-media/"):
            file = saved_file(path[len("/saved-media/"):])
            if not file:
                return self.send(404, {"error": "not found"})
            return self.send_file(file)
        if path.startswith("/follow/thumb/"):
            parts = path.split("/")
            file = follow_thumb(parts[3], parts[4]) if len(parts) == 5 else None
            if not file:
                return self.send(404, {"error": "no thumbnail"})
            return self.send_file(file)   # its address changes with each new one (?t=)
        for prefix, thumb in (("/thumb/", True), ("/img/", False)):
            if path.startswith(prefix) and path[len(prefix):].isdigit():
                file = image_path(int(path[len(prefix):]), thumb)
                if not file:
                    return self.send(404, {"error": "image not found"})
                return self.send_file(file)
        self.send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        if formlogin.httpserver.handle(self, LOGIN, path):
            return
        actions = {"/api/feedback": self.feedback, "/api/generate": queue_generation, "/api/cancel": cancel, "/api/retry": retry_job,
                   "/api/animate": request_animation, "/api/scene-acts": scene_acts,
                   "/api/comics/create": queue_comic, "/api/comics/delete": delete_comic,
                   "/api/comics/import": queue_comic_import, "/api/comics/rename": rename_comic,
                   "/api/comics/animate": queue_comic_animation, "/api/comics/update": queue_comic_update, "/api/comics/animation-delete": delete_comic_animation,
                   "/api/personas/save": save_persona,
                   "/api/personas/delete": delete_persona, "/api/personas/avatar": new_avatar,
                   "/api/styles/train": queue_style, "/api/styles/cancel": cancel_style,
                   "/api/styles/video": queue_video, "/api/styles/video-cancel": cancel_video,
                   "/api/personas/draft": queue_draft, "/api/following/settings": save_follow_settings,
                   "/api/live/highlights": queue_highlights, "/api/live/delete": delete_room_video,
                   "/api/live/restore": restore_room_video, "/api/profile/link": save_link,
                   "/api/live/follow": follow_room, "/api/following/save": save_post, "/api/saved/import": import_saved,
                   "/api/dvr": dvr_action, "/api/signins": save_signin, "/api/browser/start": browser_start, "/api/e621/vote": e621_vote, "/api/profile/relink": relink}
        if path not in actions:
            return self.send(404, {"error": "not found"})
        # JSON only: a plain cross-site form post can't set this content type.
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self.send(415, {"error": "send JSON"})
        size = int(self.headers.get("Content-Length") or 0)
        if size > MAX_BODY:
            return self.send(413, {"error": "too much at once"})
        try:
            req = json.loads(self.rfile.read(size) or b"{}")
            if not isinstance(req, dict):
                raise ValueError("send a JSON object")
            self.send(200, actions[path](req))
        except LookupError as e:
            self.send(404, {"error": str(e)})
        except (ValueError, TypeError) as e:
            self.send(400, {"error": str(e) or "bad request"})

    def feedback(self, req: dict) -> dict:
        try:
            gid, action = int(req["id"]), req["action"]
        except (KeyError, TypeError, ValueError):
            raise ValueError('send {"id": number, "action": "like" | "skip" | "clear"}')
        if action not in ("like", "skip", "clear"):
            raise ValueError('action must be "like", "skip" or "clear"')
        return set_feedback(gid, action)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    LOGIN = formlogin.Login.from_env(   # password: python -m formlogin passwd (see README)
        "DREAMFEED", "dreamfeed", STATE, title="dreamfeed", accent=("#b4321f", "#e5604a"),
        icon="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'>"
             "<circle cx='8' cy='8' r='6' fill='%23e5604a'/></svg>")
    print(time.strftime("%F %T"), f"web: feed on :{PORT}", flush=True)
    threading.Thread(target=_link_sweep, daemon=True).start()
    threading.Thread(target=_dvr_once_watch, daemon=True).start()
    if BROWSER_POWER_DIR and BROWSER_PROFILE and BROWSER_SCREEN:
        threading.Thread(target=_browser_keeper, daemon=True).start()
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
