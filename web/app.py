"""dreamfeed feed page. Everything except the sign-in page needs a signed-in session (formlogin).

GET  /                  the page
GET  /api/feed          ?view=liked&source=all|x|bsky|reddit|e621&offset=N  Saved (the persona posts are gone: other views are empty)
GET  /api/summary       how many of your rooms are live, for the header (and the iOS app's old fields, empty)
GET  /api/personas, /api/personas/edit, /api/styles, /api/dashboard, /api/personas/draft  empty: the personas and
                        the generation pipeline are retired (webapp/retired.py), these only so the iOS app shows nothing
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
GET  /api/health       whether each part is working (the Dashboard's Health): sign-ins, the Feed's sites, the recorder ...
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
GET  /api/videos/more  ?id=reddit:ID|e621:ID|bsky:ID&cursor=C  more videos after that one: its subreddit, your subscriptions (Reddit);
                        its search, yours (e621); theirs, Bluesky's Video feed, your timeline's (Bluesky)
GET  /api/x/related    ?id=TWEET&handle=H&cursor=C  the videos X shows after that one (its full-screen player's swipe-up feed)
GET  /api/redgifs      ?name=PROFILE&page=N  a RedGifs creator's clips (a room's linked one), live; /api/redgifs/clip?id=ID one
POST /api/profile/relink {"room"}  look for the room's accounts across sites again (linking.py)
GET  /api/xvideos      ?name=PROFILE&page=N  an xvideos profile's videos (a room's linked one), live
GET  /api/vids        ?length=|10|20&offset=N  the Videos tab: Continue watching, and For you (from what you watch here)
GET  /api/vids/search ?q=WORDS&page=N&length=&sort=relevance|uploaddate|rating|views  xvideos' search
GET  /api/vids/video  ?url=/video.ID/title  one to play: its stream, tags, related, where you left off, your vote
POST /api/vids/watch  {"id", "position", "duration", "delta"}  how far you are (the player says, as you watch)
GET  /api/vids/comments ?url=  a video's comments, top first
POST /api/vids/vote   {"id", "url", "vote": 1|-1|0}  more like this, less like this, or neither (on xvideos too, signed in there)
GET  /api/xvideos/video ?id=ID  one of them: its stream and files, for dreamfeed's own player (no xvideos page, no ads)
GET  /api/post         ?id=x:ID|reddit:ID|e621:ID  one post (its own page): your kept copy if you saved it, else live
GET  /api/post/comments ?id=x:ID|reddit:ID|e621:ID  a post's comments, live from its site
GET  /api/profile       ?room=ROOM | ?x=HANDLE | ?reddit=NAME | ?e621=ARTIST  one profile across sites
GET  /e621-media/data/...  one of e621's files, passed on (the page shows e621's pictures and videos through here)
GET  /vendor/hls.min.js the Live player's HLS library (hls.js, Apache 2.0)
GET  /api/comics/feed  ?offset=N  Comics: Updated (followed, with new pages), Continue reading, For you, your comics
GET  /api/comics/read  ?id=e621:POOL|mp:SLUG  one to read: its pages (straight from the site), where you left off
POST /api/comics/follow {"id", "follow": bool}; POST /api/comics/progress {"id", "page"}  (what For you learns from)
GET  /api/comics/search ?q=TEXT&page=N&site=multporn|e621  comics matching TEXT (title, cover)
GET  /comic-search/thumb ?u=URL  a search result's cover, fetched from multporn
GET  /api/following/settings  the subreddits and users read for the Feed, and how many top posts a day
POST /api/following/settings  {"reddit": {"follow": ["r/name", "u/name"], "top": N}} or
                        {"e621": {"searches": ["tag tag", ...], "top": N}} change them
GET  /api/following/posts  ?mode=following|foryou&source=all|x,bsky,reddit,e621&cursor=C&tags=T  the Feed, live from the sites
                        (source: all, or the sites you picked, with commas)
                           (tags: e621 only shows posts with them)
                        (its pictures and videos load from them); what you save is in Saved (/api/feed?view=liked)

POST /api/live/highlights {"name": ROOM, "path": P, "keep": 0.1-0.5} cut one of a room's videos down to its action
POST /api/live/delete   {"name": ROOM, "path": P} a room's video into the trash ({"undo": token})
POST /api/live/restore  {"undo": token} put it back
POST /api/profile/link  {"room", "source": "x"|"reddit", "handle", "remove": bool} link or unlink an account
POST /api/following/save {"post": {...}, "save": bool} keep a post in Saved, its files downloaded in full quality
                        (the follow service; and saved on Reddit too, for Reddit's)
GET  /saved-media/<source>/<post>/<file>  a saved post's kept picture or video
POST /api/saved/import  {"sites": ["x", "bsky", "reddit", "e621"]} bring what you saved there into Saved (in the background;
                        X's and Bluesky's bookmarks, Reddit's saved posts, e621's favorites; all when not given)
GET  /api/saved/import  how that went, and how many saved posts' files are kept
POST /api/live/follow   {"name": ROOM, "follow": bool} follow or unfollow it on Chaturbate
(POSTs are JSON only.)
"""
import json
import re
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import formlogin
import formlogin.httpserver
from dreamfeed.feed import e621, livefeeds, savedposts
from dreamfeed.live import cbprofile, cbvideos, linking

from webapp import comics as comicfeed
from webapp.comics import comic_cover, comic_page, comic_search, comics, delete_comic, rename_comic
from webapp import health, retired, videos
from webapp.common import CSP, DATA, MAX_BODY, PAGE, PREFIX, ROOM, STATE, STATIC
from webapp.feed import FRESH_READS, _mark_saved, _seen, _unshown, browse, e621_vote, follow_posts, follow_settings, import_saved, import_status, more_videos, one_post, person_posts, random_subreddit, recent_browses, save_follow_settings, save_post, saved_file, saved_view
from webapp.live import _dvr_once_watch, _followed, _link_sweep, cb_thumb, delete_room_video, discover_cb, discover_x, dvr_action, follow_room, follow_thumb, following, live_stream, live_videos, profile, queue_highlights, relink, restore_room_video, save_link
from webapp.signins import BROWSER_POWER_DIR, BROWSER_PROFILE, BROWSER_SCREEN, _browser_keeper, browser_start, reddit_callback, reddit_login_url, save_signin, signins


# The page's script is kept in parts by what they do (static/js/NN-name.js) and served as one,
# static/app.js, joined in their order: one script, so a part can use what a later one defines.
_script = {"key": None, "body": b""}


def page_script() -> bytes:
    parts = sorted((STATIC / "js").glob("[0-9][0-9]-*.js"))
    key = tuple((p.name, p.stat().st_mtime_ns) for p in parts)
    if _script["key"] != key:
        _script.update(key=key, body=b"".join(p.read_bytes() for p in parts))
    return _script["body"]
# Each part of the page has its own address (the page reads it and opens that part):
PAGES = {"home", "feed", "saved", "live", "comics", "dashboard", "personas", "p", "item", "room", "watch",
         "x", "u", "r", "e621", "post", "xvideos", "redgifs", "videos", "bsky", "vids"}


PORT = 8000


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

    E621_FILE = re.compile(r"data/(?:sample/|preview/)?[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{32}(?:_[a-z0-9]{1,12})?\.(?:jpe?g|png|gif|webp|webm|mp4)")

    def send_e621(self, rest: str) -> None:
        """One of e621's files, passed on (by ranges too, for its videos). e621 now turns away
        pictures a browser shows on another site; the page asks here instead (the iOS app, which
        doesn't say so, still loads them from e621 itself). Only e621's own file paths."""
        import urllib.error
        import urllib.request
        if not self.E621_FILE.fullmatch(rest):
            return self.send(404, {"error": "not an e621 file"})
        headers = {"User-Agent": e621.agent()}
        rng = self.headers.get("Range", "")
        if re.fullmatch(r"bytes=\d*-\d*", rng):
            headers["Range"] = rng
        try:
            r = urllib.request.urlopen(urllib.request.Request(f"https://static1.e621.net/{rest}", headers=headers), timeout=30)
        except urllib.error.HTTPError as e:
            return self.send(e.code if e.code in (404, 416) else 502, {"error": f"e621 said {e.code}"})
        except OSError as e:
            return self.send(502, {"error": f"e621 didn't answer ({e})"})
        with r:
            self.send_response(r.status)
            for h in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "Last-Modified", "ETag"):
                if r.headers.get(h):
                    self.send_header(h, r.headers[h])
            self.send_header("Cache-Control", "private, max-age=2592000")      # (its files never change: named by what's in them)
            for k, v in formlogin.SECURITY_HEADERS:
                self.send_header(k, v)
            self.end_headers()
            try:
                while chunk := r.read(1 << 16):
                    self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

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
            if q.get("view") == "liked":
                return self.send(200, saved_view(offset, q.get("source", "all")))
            return self.send(200, {"items": [], "more": False})        # (the persona posts are gone)
        if path == "/api/personas":
            return self.send(200, retired.personas())
        if path == "/api/personas/edit":
            return self.send(200, retired.persona_config())
        if path == "/api/styles":
            return self.send(200, retired.styles())
        if path == "/api/personas/draft":
            return self.send(200, retired.draft_status(0))
        if path == "/api/comics":
            return self.send(200, comics())
        if path in ("/api/comics/feed", "/api/comics/read"):
            q = self.query()
            try:
                if path == "/api/comics/feed":
                    return self.send(200, comicfeed.feed(int(q.get("offset", "0") or 0)))
                return self.send(200, comicfeed.read(q.get("id", "")))
            except ValueError as e:
                return self.send(400, {"error": str(e)})
            except (LookupError, OSError) as e:
                return self.send(502, {"error": str(e)[:200]})
        if path.startswith("/comic/"):
            parts = path.split("/")
            if len(parts) in (4, 5) and parts[2].isdigit() and parts[3].isdigit() and parts[4:] in ([], ["thumb"]):
                file = comic_page(int(parts[2]), int(parts[3]), thumb=parts[4:] == ["thumb"])
                if file:
                    return self.send_file(file)
            return self.send(404, {"error": "page not found"})
        if path == "/api/summary":
            return self.send(200, retired.summary())
        if path == "/api/dashboard":
            return self.send(200, retired.dashboard())
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
        if path in ("/api/vids", "/api/vids/search", "/api/vids/video", "/api/vids/comments"):
            q = self.query()
            try:
                if path == "/api/vids":
                    return self.send(200, videos.home(q.get("length", ""), int(q.get("offset", "0") or 0)))
                if path == "/api/vids/search":
                    return self.send(200, videos.search(q.get("q", ""), int(q.get("page", "0") or 0), q.get("length", ""), q.get("sort", "")))
                if path == "/api/vids/comments":
                    return self.send(200, videos.comments(q.get("url", "")))
                return self.send(200, videos.video(q.get("url", "")))
            except ValueError as e:
                return self.send(400, {"error": str(e)})
            except LookupError as e:
                return self.send(502, {"error": str(e)})
        if path == "/api/xvideos/video":
            try:
                return self.send(200, livefeeds.xvideos_video(self.query().get("id", "")))
            except ValueError as e:
                return self.send(400, {"error": str(e)})
            except LookupError as e:
                return self.send(502, {"error": str(e)})
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
        if path == "/api/health":
            return self.send(200, health.health(self.headers))
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
        if path == "/static/app.js":
            return self.send(200, page_script(), "text/javascript; charset=utf-8", cache="no-cache")
        if path.startswith("/static/"):          # the page's style (static/app.css)
            file = (STATIC / path[len("/static/"):]).resolve()
            ctype = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8"}.get(file.suffix)
            if not ctype or not file.is_relative_to(STATIC) or not file.is_file():
                return self.send(404, {"error": "not found"})
            return self.send(200, file.read_bytes(), ctype, cache="no-cache")
        if path.startswith("/e621-media/"):
            return self.send_e621(path[len("/e621-media/"):])
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
        self.send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        if formlogin.httpserver.handle(self, LOGIN, path):
            return
        actions = {"/api/comics/delete": delete_comic, "/api/comics/rename": rename_comic,
                   "/api/comics/follow": comicfeed.follow, "/api/comics/progress": comicfeed.progress,
                   "/api/following/settings": save_follow_settings,
                   "/api/live/highlights": queue_highlights, "/api/live/delete": delete_room_video,
                   "/api/live/restore": restore_room_video, "/api/profile/link": save_link,
                   "/api/live/follow": follow_room, "/api/following/save": save_post, "/api/saved/import": import_saved,
                   "/api/dvr": dvr_action, "/api/signins": save_signin, "/api/browser/start": browser_start, "/api/e621/vote": e621_vote,
                   "/api/vids/watch": videos.watch, "/api/vids/vote": videos.vote, "/api/profile/relink": relink}
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

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    LOGIN = formlogin.Login.from_env(   # password: python -m formlogin passwd (see README)
        "DREAMFEED", "dreamfeed", STATE, title="dreamfeed", accent=("#b4321f", "#e5604a"),
        icon="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'>"
             "<circle cx='8' cy='8' r='6' fill='%23e5604a'/></svg>")
    print(time.strftime("%F %T"), f"web: feed on :{PORT}", flush=True)
    threading.Thread(target=comicfeed.watch_follows, daemon=True).start()
    threading.Thread(target=_link_sweep, daemon=True).start()
    threading.Thread(target=_dvr_once_watch, daemon=True).start()
    if BROWSER_POWER_DIR and BROWSER_PROFILE and BROWSER_SCREEN:
        threading.Thread(target=_browser_keeper, daemon=True).start()
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
