"""The Feed, live: posts read from X, Reddit and e621 when you look, shown straight from the
sites (their pictures and videos load from the sites' own servers; nothing is downloaded or
kept on disk). Used by the web app; standard library plus the gallery-dl command (for X).

- X: gallery-dl with your cookies (X_COOKIES, read-only), its metadata only (-j): your
  Following timeline, X's For you and anyone's media tab (their profile in dreamfeed).
- Reddit: its API as you (REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_REFRESH_TOKEN): your
  subscriptions and the Dashboard's extras as one listing (Following), your front page (Best,
  For you), any subreddit (Browse now) or user. Saving saves on Reddit.
- e621: the Dashboard's tag searches, newest first (Following), or their best rated of the last
  24 hours (For you); or, either way, only the tags you filter by. Pictures show e621's 850px
  copy; Save keeps the original.

What's still left out, by the rules alone (instant, no models): e621 posts with a tag dreamfeed
never allows (e621.NEVER: the youth tags, feral, bestiality; e621 hosts those, so they aren't
moderated away there), subreddits whose names have those words, and posts whose text does
(safety.request_blocked). Pictures aren't looked at.

These are real people: nothing here goes to training, styles, comics or generation.
"""
import base64
import datetime as dt
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import e621, safety

REDDIT_API = "https://oauth.reddit.com"
REDDIT_AGENT = "linux:dreamfeed:1.0 (personal feed reader)"
X_HOME = "https://x.com/home"         # your Following timeline; + "/for-you": X's For you
X_HANDLE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
SUBREDDIT = re.compile(r"^[A-Za-z0-9_]{2,21}$")
REDDIT_USER = re.compile(r"^[A-Za-z0-9_-]{3,20}$")
X_PAGE = 30            # media files read from X a page (a post can have several)
REDDIT_PAGE = 25
E621_PAGE = 20
MAX_GALLERY = 20
MAX_USERS = 10         # Reddit people (u/name) read for Following, each one's newest page
CACHE_TTL = 120        # seconds a page is reused (switching tabs, coming back)
_lock = threading.Lock()
_cache: dict[str, tuple[float, object, float]] = {}     # key: (when, value, seconds it's good for)
WHO_TTL = 86400        # who someone is (a Reddit user's picture, an e621 artist's links)
_token = {"value": "", "until": 0.0}
_redgifs = {"value": "", "until": 0.0}
_clips: dict[str, tuple[float, dict | None]] = {}
SUBS_TTL = 3600        # your Reddit subscriptions are asked for again after this


def x_cookies() -> str | None:
    path = os.environ.get("X_COOKIES", "").strip()
    return path if path and os.path.isfile(path) else None


def _cached(key: str, fetch, ttl: float = CACHE_TTL):
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < hit[2]:
            return hit[1]
    value = fetch()
    with _lock:
        for k in [k for k, (t, _, good) in _cache.items() if time.time() - t > good]:
            _cache.pop(k, None)
        _cache[key] = (time.time(), value, ttl)
    return value


def forget(prefix: str = "") -> None:
    with _lock:
        for k in [k for k in _cache if k.startswith(prefix)]:
            _cache.pop(k, None)


def text_blocked(*texts) -> bool:
    """Text with words dreamfeed never takes (young, feral and the like)."""
    t = " ".join(str(x) for x in texts if x).replace("_", " ")
    return bool(t and safety.request_blocked(t))


def place_blocked(name: str) -> bool:
    words = name.replace("_", " ").lower()
    return bool(safety.request_blocked(words) or safety.story_blocked(words)
                or any(w in words for w in e621.NEVER if len(w) > 3))


def _utc(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts or 0, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ---- Reddit ----
def _agent() -> str:
    user = os.environ.get("REDDIT_USERNAME", "").strip()
    return f"linux:dreamfeed:1.0 (by /u/{user})" if user else REDDIT_AGENT


def reddit_ready() -> bool:
    return all(os.environ.get(k, "").strip() for k in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_REFRESH_TOKEN"))


def _reddit_token() -> str:
    with _lock:
        if _token["value"] and time.time() < _token["until"]:
            return _token["value"]
    if not reddit_ready():
        raise LookupError("Reddit isn't signed in (REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_REFRESH_TOKEN)")
    creds = ":".join(os.environ[k].strip() for k in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"))
    form = {"grant_type": "refresh_token", "refresh_token": os.environ["REDDIT_REFRESH_TOKEN"].strip()}
    req = urllib.request.Request("https://www.reddit.com/api/v1/access_token", data=urllib.parse.urlencode(form).encode(),
                                 headers={"User-Agent": _agent(), "Authorization": "Basic " + base64.b64encode(creds.encode()).decode()})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    if not d.get("access_token"):
        raise LookupError(f"Reddit refused the sign-in: {d.get('error') or d}")
    with _lock:
        _token.update(value=d["access_token"], until=time.time() + int(d.get("expires_in") or 3600) - 120)
    return d["access_token"]


def _reddit(path: str, form: dict | None = None):
    url = REDDIT_API + path
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    for attempt in range(2):
        req = urllib.request.Request(url, data=data, headers={"User-Agent": _agent(), "Authorization": f"bearer {_reddit_token()}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 401 and not attempt:
                with _lock:
                    _token["until"] = 0
                continue
            if e.code == 403:
                raise LookupError("Reddit said no (private, banned or quarantined; or sign in again for this)") from e
            if e.code == 404:
                raise LookupError("Reddit has nothing there") from e
            raise LookupError(f"Reddit didn't answer ({e.code})") from e
        except (OSError, ValueError) as e:
            raise LookupError(f"Reddit didn't answer ({e})") from e


_redgifs_token_lock = threading.Lock()


def _new_redgifs_token() -> str:
    with urllib.request.urlopen(urllib.request.Request("https://api.redgifs.com/v2/auth/temporary",
                                                       headers={"User-Agent": _agent()}), timeout=20) as r:
        tok = json.load(r)["token"]
    with _lock:
        _redgifs.update(value=tok, until=time.time() + 12 * 3600)
    return tok


def _redgifs_clip(url: str) -> dict | None:
    """A redgifs link's clip, from redgifs' own API (a temporary token, as its site uses); kept
    an hour (its addresses are signed for longer)."""
    m = re.search(r"redgifs\.com/(?:watch|ifr|i)/([A-Za-z]+)", url)
    if not m:
        return None
    with _lock:
        hit = _clips.get(m.group(1).lower())
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    try:
        with _lock:
            tok = _redgifs["value"] if time.time() < _redgifs["until"] else ""
        if not tok:
            with _redgifs_token_lock:             # one new token, however many ask at once
                with _lock:
                    tok = _redgifs["value"] if time.time() < _redgifs["until"] else ""
                tok = tok or _new_redgifs_token()
        req = urllib.request.Request(f"https://api.redgifs.com/v2/gifs/{m.group(1).lower()}",
                                     headers={"User-Agent": _agent(), "Authorization": f"Bearer {tok}"})
        with urllib.request.urlopen(req, timeout=20) as r:
            g = json.load(r).get("gif") or {}
    except (OSError, ValueError, KeyError):
        return None
    urls = g.get("urls") or {}
    src = urls.get("hd") or urls.get("sd")
    clip = {"kind": "video", "url": src, "poster": urls.get("poster") or urls.get("thumbnail")} if src else None
    with _lock:
        if len(_clips) > 5000:
            _clips.clear()
        _clips[m.group(1).lower()] = (time.time(), clip)
    return clip


def _reddit_media(p: dict) -> list[dict]:
    """Every picture and video of a post (a crosspost's are the original's)."""
    src = (p.get("crosspost_parent_list") or [p])[0]
    prev = ((src.get("preview") or {}).get("images") or [{}])[0]
    poster = (prev.get("source") or {}).get("url")
    out = []
    if src.get("is_gallery"):
        meta = src.get("media_metadata") or {}
        for item in (src.get("gallery_data") or {}).get("items", [])[:MAX_GALLERY]:
            m = meta.get(item.get("media_id")) or {}
            big = m.get("s") or {}
            if m.get("status") != "valid":
                continue
            if big.get("mp4"):
                out.append({"kind": "video", "url": big["mp4"], "poster": big.get("u")})
            elif big.get("u") or big.get("gif"):
                out.append({"kind": "image", "url": big.get("u") or big.get("gif")})
        return out
    rv = (src.get("secure_media") or {}).get("reddit_video") or (src.get("preview") or {}).get("reddit_video_preview")
    url = src.get("url_overridden_by_dest") or src.get("url") or ""
    host = urllib.parse.urlparse(url).hostname or ""
    if "redgifs.com" in host:
        clip = _redgifs_clip(url)
        if clip:
            return [clip]
    if rv and (rv.get("hls_url") or rv.get("fallback_url")):
        return [{"kind": "hls" if rv.get("hls_url") else "video", "url": rv.get("hls_url") or rv["fallback_url"],
                 "fallback": rv.get("fallback_url"), "poster": poster}]
    if host == "i.imgur.com" and url.endswith(".gifv"):
        return [{"kind": "video", "url": url[:-5] + ".mp4", "poster": poster}]
    path = urllib.parse.urlparse(url).path.lower()
    if host in ("i.redd.it", "i.imgur.com") and path.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return [{"kind": "image", "url": url}]
    if host == "i.redd.it" and path.endswith(".gif"):
        mp4 = ((prev.get("variants") or {}).get("mp4") or {}).get("source", {}).get("url")
        return [{"kind": "video", "url": mp4, "poster": poster} if mp4 else {"kind": "image", "url": url}]
    return []


def _reddit_listing(d: dict, via: str) -> tuple[list[dict], str | None]:
    found = [c.get("data") or {} for c in (d.get("data") or {}).get("children") or [] if c.get("kind") == "t3"]
    found = [p for p in found if p.get("id") and not place_blocked(p.get("subreddit") or "")
             and not text_blocked(p.get("title"), p.get("link_flair_text"))]
    with ThreadPoolExecutor(max_workers=8) as pool:      # (redgifs links are each asked of redgifs)
        medias = list(pool.map(_reddit_media, found))
    posts = []
    for p, media in zip(found, medias):
        if not media:
            continue
        sr = p.get("sr_detail") or {}         # (sr_detail=1: the subreddit, with its icon)
        icon = sr.get("community_icon") or sr.get("icon_img") or None
        posts.append({"id": f"reddit:{p['id']}", "source": "reddit", "author": p.get("author") or "",
                      "avatar": icon if icon and icon.startswith("https://") else None,
                      "place": p.get("subreddit"), "text": p.get("title") or "", "posted_at": _utc(p.get("created_utc")),
                      "link": "https://www.reddit.com" + (p.get("permalink") or ""), "via": via,
                      "saved": bool(p.get("saved")), "media": media, "comments": p.get("num_comments")})
    return posts, (d.get("data") or {}).get("after")


def user_path(name: str) -> str:
    """A Reddit user's newest posts, as a listing path (Reddit's search by author: reading their
    profile itself needs a permission dreamfeed doesn't ask for)."""
    return f"/search?q=author%3A{name}&sort=new&type=link&include_over_18=on"


def reddit_page(path: str, after: str | None, via: str) -> tuple[list[dict], str | None]:
    """A Reddit listing (path like /best or /r/a+b/new), REDDIT_PAGE posts from `after`."""
    sep = "&" if "?" in path else "?"
    q = f"{path}{sep}limit={REDDIT_PAGE}&raw_json=1&sr_detail=1" + (f"&after={urllib.parse.quote(after)}" if after else "")
    return _cached("reddit:" + q, lambda: _reddit_listing(_reddit(q), via))


def reddit_user(name: str) -> dict:
    """Who a Reddit user is, for their profile: {"name", "avatar", "karma", "since"}."""
    if not REDDIT_USER.match(name):
        raise ValueError("bad Reddit username")
    def fetch():
        u = (_reddit(f"/user/{name}/about?raw_json=1") or {}).get("data") or {}
        icon = u.get("icon_img") or u.get("snoovatar_img") or ""     # (icon_img: the head shot)
        return {"name": u.get("name") or name, "avatar": icon if icon.startswith("https://") else None,
                "karma": u.get("total_karma"), "since": _utc(u["created_utc"]) if u.get("created_utc") else None}
    return _cached(f"reddit-user:{name.lower()}", fetch, WHO_TTL)


def subscriptions() -> list[str]:
    """The subreddits and profiles you're subscribed to ("r/name", "u/name"), kept SUBS_TTL."""
    def fetch():
        out, after = [], ""
        for _ in range(20):
            d = (_reddit(f"/subreddits/mine/subscriber?limit=100&raw_json=1&after={after}").get("data") or {})
            for c in d.get("children") or []:
                name = str((c.get("data") or {}).get("display_name") or "")
                out.append(f"u/{name[2:]}" if name.startswith("u_") else f"r/{name}")
            after = d.get("after") or ""
            if not after:
                break
        return sorted(set(out), key=str.lower)
    return _cached("subs", fetch, SUBS_TTL)


def reddit_save(post_id: str, save: bool) -> None:
    if not re.fullmatch(r"[a-z0-9]{3,12}", post_id):
        raise ValueError("bad post")
    _reddit("/api/save" if save else "/api/unsave", {"id": "t3_" + post_id})
    forget("reddit:")


# ---- X ----
# gallery-dl as the X reader, with each video's other sizes and its preview picture kept in the
# metadata too (gallery-dl itself names only the biggest file, up to 4K: slow on a phone).
X_RUNNER = """
import sys
from gallery_dl.extractor import twitter
_source = twitter.TwitterExtractor._extract_media_source
def _more(self, dest, media):
    _source(self, dest, media)
    info = media.get("video_info") or {}
    dest["variants"] = [{"url": v.get("url"), "bitrate": v.get("bitrate"), "type": v.get("content_type")}
                        for v in info.get("variants") or []]
    dest["poster_url"] = media.get("media_url_https")
twitter.TwitterExtractor._extract_media_source = _more
import gallery_dl
sys.argv = ["gallery-dl"] + sys.argv[1:]
sys.exit(gallery_dl.main())
"""
X_VIDEO_BITRATE = 2_500_000   # the biggest MP4 at or under this (about 720p); the smallest if none is


def _x_video(url: str, md: dict) -> str:
    mp4s = [v for v in md.get("variants") or [] if v.get("type") == "video/mp4" and v.get("url") and v.get("bitrate")]
    fits = [v for v in mp4s if v["bitrate"] <= X_VIDEO_BITRATE]
    pick = max(fits, key=lambda v: v["bitrate"]) if fits else min(mp4s, key=lambda v: v["bitrate"], default=None)
    return pick["url"] if pick else url


def _x(url: str, start: int, count: int, timeout: int = 90, options: tuple = ()) -> list:
    if not x_cookies():
        raise LookupError("X isn't signed in (X_COOKIES_FILE)")
    try:
        out = subprocess.run([sys.executable, "-c", X_RUNNER, "--config-ignore", "--cookies", x_cookies(), "-o", "cookies-update=false",
                              *[a for o in options for a in ("-o", o)],
                              "--range", f"{start}-{start + count - 1}", "-j", url],
                             capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise LookupError("X took too long") from e
    try:
        return json.loads(out.stdout or "[]")
    except ValueError as e:
        err = (out.stderr or "").strip().splitlines()
        raise LookupError(f"X didn't answer ({err[-1][:160] if err else 'nothing came back'})") from e


def _x_user(a: dict) -> dict:
    img = a.get("profile_image") or ""
    return {"handle": a.get("name") or "", "nick": a.get("nick"), "bio": a.get("description"), "location": a.get("location"),
            "followers": a.get("followers_count"), "following": a.get("friends_count"), "posts": a.get("statuses_count"),
            "image_url": img}


def _x_posts(items: list, via: str) -> tuple[list[dict], list[dict], int]:
    """(posts, users seen, files read) from gallery-dl's -j output."""
    posts: dict[str, dict] = {}
    users: dict[str, dict] = {}
    files = 0
    for it in items:
        if not isinstance(it, list) or len(it) < 3 or it[0] != 3:
            continue
        files += 1
        url, md = it[1], it[2]
        a = md.get("author") or {}
        tid = str(md.get("tweet_id") or "")
        if not tid or not a.get("name"):
            continue
        users[a["name"].lower()] = _x_user(a)
        p = posts.get(tid)
        if p is None:
            named = [m.get("name") for m in md.get("mentions") or []] + [md.get("reply_to")]
            p = posts[tid] = {"id": f"x:{tid}", "source": "x", "author": a["name"], "nick": a.get("nick"),
                              "avatar": a.get("profile_image") or None, "place": None, "text": md.get("content") or "",
                              "posted_at": str(md.get("date") or ""), "link": f"https://x.com/{a['name']}/status/{tid}",
                              "via": via, "saved": False, "media": [], "comments": md.get("reply_count"),
                              "mentions": sorted({n for n in named if n and n.lower() != a["name"].lower()})}
            if md.get("date_bookmarked"):           # your bookmarks: when you bookmarked it (UTC)
                p["saved_at"] = str(md["date_bookmarked"])[:19]
        ext = str(md.get("extension") or "").lower()
        if not str(url).startswith("https://"):
            continue
        if ext in ("mp4", "webm", "mov", "m4v"):
            p["media"].append({"kind": "video", "url": _x_video(url, md), "full": url, "poster": md.get("poster_url") or None})
        elif ext in ("jpg", "jpeg", "png", "webp", "gif"):
            p["media"].append({"kind": "image", "url": url.replace("name=orig", "name=large"), "full": url})
    kept = [p for p in posts.values() if p["media"] and not text_blocked(p["text"])]
    return kept, list(users.values()), files


def x_page(kind: str, start: int) -> dict:
    """X's Following ("home"), For you ("foryou") or a person's media ("@handle"), X_PAGE files
    from `start` (1-based). {"posts", "users", "next"}."""
    if kind == "home":
        url, via = X_HOME, "following"
    elif kind == "foryou":
        url, via = X_HOME + "/for-you", "foryou"
    elif kind.startswith("@") and X_HANDLE.match(kind[1:]):
        url, via = f"https://x.com/{kind[1:]}/media", "profile"
    else:
        raise ValueError("bad X timeline")

    def fetch():
        posts, users, files = _x_posts(_x(url, start, X_PAGE), via)
        return {"posts": posts, "users": users, "next": start + X_PAGE if files >= X_PAGE else None}
    return _cached(f"x:{kind}:{start}", fetch)


# ---- e621 ----
def _e621_full(p: dict, kind: str) -> str | None:
    """The original file (a video's full-size MP4 when e621 has one: originals are often WebM,
    which iPhones don't play)."""
    if kind == "video":
        mp4 = ((((p.get("sample") or {}).get("alternates") or {}).get("variants") or {}).get("mp4") or {}).get("url")
        if mp4:
            return mp4
    return (p.get("file") or {}).get("url")


TOP_TODAY = "order:score date:day"      # For you: the best rated of the last 24 hours


def e621_page(search: str, at: int | None, top: bool = False) -> tuple[list[dict], int | None]:
    """A page of an e621 tag search: the newest (at: the post id the page starts below), or
    with top, the best rated of the last 24 hours (at: the page number)."""
    def fetch():
        params = {"tags": e621.query(f"{search} {TOP_TODAY}" if top else search), "limit": E621_PAGE}
        if at:
            params["page"] = str(at) if top else f"b{at}"
        found = e621.get("/posts.json", params).get("posts") or []
        out = []
        for p in found:
            got = e621.media(p)
            if e621.blocked(p) or not got or text_blocked(p.get("description")):
                continue
            d = e621.details(p)
            kind = "video" if got[1] in ("mp4", "webm") else "image"
            sample = p.get("sample") or {}
            prev = sample.get("url") or (p.get("preview") or {}).get("url")
            # a picture shows e621's 850px copy (the original is often 5-20 MB): the original is
            # what Save keeps. A GIF's copy is a still, so it shows itself.
            shown = sample["url"] if kind == "image" and got[1] != "gif" and sample.get("has") and sample.get("url") else got[0]
            out.append({"id": f"e621:{d['id']}", "source": "e621", "author": d["author"], "artists": d["artists"],
                        "place": search, "text": d["title"], "posted_at": d["date"], "link": d["link"],
                        "via": "foryou" if top else "following", "saved": False,
                        "score": ((p.get("score") or {}).get("total") or 0), "comments": p.get("comment_count"),
                        "media": [{"kind": kind, "url": shown, "full": _e621_full(p, kind) or got[0],
                                   "poster": prev if kind == "video" else None}]})
        if len(found) < E621_PAGE:
            return out, None
        if top:
            return out, (at or 1) + 1
        return out, min((int(p["id"]) for p in found if str(p.get("id", "")).isdigit()), default=None)
    return _cached(f"e621:{top}:{search}:{at}", fetch)


def e621_artist(name: str) -> dict:
    """Who an e621 artist is, for their profile: {"name", "posts", "other_names", "links"
    (their pages elsewhere, as e621 lists them), "x" (their X handles among those)}."""
    name = name.strip().lower()
    if not e621.ARTIST.match(name):
        raise ValueError("bad e621 artist")
    def fetch():
        found = e621.get("/artists.json", {"search[name]": name, "limit": 1}) or []
        a = found[0] if isinstance(found, list) and found and found[0].get("name") == name else {}
        tag = e621.get("/tags.json", {"search[name]": name, "limit": 1}) or []
        links = [u["url"] for u in a.get("urls") or [] if u.get("is_active") and str(u.get("url", "")).startswith("https://")]
        xs = []
        for u in links:
            m = re.match(r"https://(?:www\.|mobile\.)?(?:twitter|x)\.com/([A-Za-z0-9_]{1,15})/?$", u)
            if m and m.group(1).lower() not in ("home", "i", "intent", "search") and m.group(1).lower() not in xs:
                xs.append(m.group(1).lower())
        return {"name": name, "posts": tag[0].get("post_count") if isinstance(tag, list) and tag else None,
                "other_names": (a.get("other_names") or [])[:10], "links": links[:20], "x": xs[:3]}
    return _cached(f"e621-artist:{name}", fetch, WHO_TTL)


# ---- the Feed ----
def _merge(lists: list[list[dict]], by_time: bool) -> list[dict]:
    if by_time:
        return sorted((p for l in lists for p in l), key=lambda p: p["posted_at"], reverse=True)
    out, i = [], 0               # each site's own order, taken in turns
    while any(i < len(l) for l in lists):
        out += [l[i] for l in lists if i < len(l)]
        i += 1
    return out


def feed(mode: str, source: str, cursor: dict | None, follow: list[str], searches: list[str], tags: str = "") -> dict:
    """A page of the Feed. mode: following (your X Following, your subscriptions and the
    Dashboard's subreddits, its e621 searches, newest first) or foryou (X's For you, Reddit's
    Best, the best rated of the last 24 hours of the Dashboard's e621 searches). tags: e621
    shows only posts with these (instead of the Dashboard's searches).
    cursor: where each site's next page starts ({} for the first); None in it: that site's done.
    {"posts", "users", "cursor", "more", "errors"}."""
    sources = [s for s in ("x", "reddit", "e621") if source in ("all", s)]
    first = not cursor
    cursor = dict(cursor or {})
    def one(s: str) -> tuple[list[list[dict]], list[dict], object, str | None]:
        """(post lists, X users, where its next page starts, an error) of one site."""
        lists: list[list[dict]] = []
        try:
            if s == "x":
                page = x_page("home" if mode == "following" else "foryou", int(cursor.get("x") or 1))
                return [page["posts"]], page["users"], page["next"], None
            if s == "reddit":
                if not reddit_ready():
                    return [], [], None, None
                people, error, after = [], None, None
                if mode == "foryou":
                    path = "/best"
                else:
                    subs = set(subscriptions()) | set(follow)
                    rs = sorted({w[2:] for w in subs if w.startswith("r/") and not place_blocked(w[2:])}, key=str.lower)
                    people = sorted({w[2:] for w in subs if w.startswith("u/") and REDDIT_USER.match(w[2:])}, key=str.lower)
                    path = "/r/" + "+".join(rs[:250]) + "/new" if rs else None
                # people (u/name) can't join one listing: each one's newest, with the first page
                pages = ([(path, cursor.get("reddit") or None)] if path else []) + \
                        ([(user_path(u), None) for u in people[:MAX_USERS]] if first else [])

                def get(page):
                    try:
                        return reddit_page(page[0], page[1], mode), None
                    except LookupError as e:
                        return ([], None), str(e)
                with ThreadPoolExecutor(max_workers=4) as pool:
                    for n, ((posts, nxt_after), err) in enumerate(pool.map(get, pages)):
                        lists.append(posts)
                        if n == 0 and path:
                            if err:
                                raise LookupError(err)
                            after = nxt_after
                        elif err:
                            error = err[:200]
                return lists, [], after, error
            top = mode == "foryou"
            qs = [tags] if tags else searches
            state = cursor.get("e621") or {q: None for q in qs}
            more, got, refused = {}, [], []
            for q in qs:
                if not first and state.get(q) is None:
                    continue
                try:
                    posts, last = e621_page(q, state.get(q), top)
                except ValueError as e:         # a search dreamfeed won't run: the others still do
                    refused.append(f"{q}: {e}")
                    continue
                got += posts
                more[q] = last
            if top:                             # your searches' best of the day, together
                got.sort(key=lambda p: p["score"], reverse=True)
            return ([got] if qs else [], [], more if any(v is not None for v in more.values()) else None,
                    "; ".join(refused)[:200] or None)
        except (LookupError, ValueError, OSError) as e:
            return lists, [], None, str(e)[:200]

    todo = [s for s in sources if first or cursor.get(s) is not None]
    lists, users, errors, nxt = [], [], {}, {}
    with ThreadPoolExecutor(max_workers=3) as pool:      # the sites at once
        for s, (got, people, after, error) in zip(todo, pool.map(one, todo)):
            lists += got; users += people; nxt[s] = after
            if error:
                errors[s] = error
    for s in sources:
        nxt.setdefault(s, None)
    posts = _merge(lists, by_time=mode == "following")
    seen, out = set(), []
    for p in posts:
        if p["id"] not in seen:
            seen.add(p["id"]); out.append(p)
    return {"posts": out, "users": users, "cursor": nxt, "more": any(v is not None for v in nxt.values()), "errors": errors}


# ---- xvideos: a performer's videos (linked on their profile) ----
XVIDEOS = "https://www.xvideos.com"
XVIDEOS_NAME = re.compile(r"^[a-z0-9_-]{2,60}$")


def xvideos_page(name: str, page: int) -> dict:
    """An xvideos profile's videos, newest first, 36 a page: {"videos": [{"id" (what its player
    takes), "title", "duration", "views", "thumb", "when"}], "total", "more"}. Watched in xvideos'
    own player (embedframe); nothing is downloaded. Titles with words dreamfeed never shows are
    left out."""
    name = name.strip().lower()
    if not XVIDEOS_NAME.match(name) or not 0 <= page < 200:
        raise ValueError("bad xvideos profile")
    def fetch():
        req = urllib.request.Request(f"{XVIDEOS}/profiles/{name}/videos/new/{page}",
                                     headers={"User-Agent": "Mozilla/5.0 (dreamfeed)", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.loads(r.read(4 << 20))
        except (OSError, ValueError) as e:
            raise LookupError(f"xvideos didn't answer ({e})") from e
        out = []
        for v in d.get("videos") or []:
            title = str(v.get("tf") or v.get("t") or "")
            thumb = str(v.get("i") or "")
            if not v.get("eid") or not re.fullmatch(r"[a-z0-9]{6,20}", str(v["eid"])) or text_blocked(title):
                continue
            out.append({"id": v["eid"], "title": title, "duration": v.get("d"), "views": v.get("n"),
                        "thumb": thumb if thumb.startswith("https://") else None, "when": v.get("ut")})
        total, per = int(d.get("nb_videos") or 0), int(d.get("nb_per_page") or 36)
        return {"videos": out, "total": total, "more": (page + 1) * per < total}
    return _cached(f"xvideos:{name}:{page}", fetch, 600)


# ---- a post's comments ----
MAX_COMMENTS = 150      # read a post, at most
COMMENT_DEPTH = 4       # replies to replies ... (Reddit)


def _comment(cid, author, text, at, score=None, avatar=None, media=None) -> dict:
    return {"id": str(cid), "author": author or "", "text": text or "", "at": at or "", "score": score,
            "avatar": avatar if avatar and str(avatar).startswith("https://") else None, "media": media or [], "replies": []}


def _reddit_comments(pid: str) -> list[dict]:
    d = _reddit(f"/comments/{pid}?raw_json=1&limit={MAX_COMMENTS}&depth={COMMENT_DEPTH}&sort=top")
    def walk(children) -> list[dict]:
        out = []
        for ch in children or []:
            c = ch.get("data") or {}
            if ch.get("kind") != "t1" or c.get("author") == "AutoModerator" or text_blocked(c.get("body")):
                continue
            item = _comment(c.get("id"), c.get("author"), c.get("body"), _utc(c.get("created_utc")), c.get("score"))
            replies = c.get("replies")
            item["replies"] = walk(((replies or {}).get("data") or {}).get("children")) if isinstance(replies, dict) else []
            out.append(item)
        return out
    return walk(((d[1] if isinstance(d, list) and len(d) > 1 else {}).get("data") or {}).get("children"))


def _e621_comments(pid: str) -> list[dict]:
    d = e621.get("/comments.json", {"group_by": "comment", "search[post_id]": pid, "limit": MAX_COMMENTS})
    rows = d if isinstance(d, list) else []          # (none: {"comments": []})
    rows = [c for c in rows if not c.get("is_hidden") and not text_blocked(c.get("body"))]
    rows.sort(key=lambda c: c.get("created_at") or "")
    out = []
    for c in rows:
        try:
            at = dt.datetime.fromisoformat(c["created_at"]).astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        except (KeyError, ValueError):
            at = ""
        out.append(_comment(c.get("id"), c.get("creator_name"), c.get("body"), at, c.get("score")))
    return out


def _x_comments(tid: str) -> list[dict]:
    """The replies under a post (gallery-dl's conversation of it), nested by what each answers."""
    items = _x(f"https://x.com/i/web/status/{tid}", 1, MAX_COMMENTS, timeout=60,
               options=("conversations=true", "text-tweets=true", "replies=true", "retweets=false", "quoted=false"))
    tweets: dict[str, dict] = {}
    parent: dict[str, str] = {}
    for it in items:
        if not isinstance(it, list) or len(it) < 2 or it[0] not in (2, 3):
            continue
        md = it[-1] if isinstance(it[-1], dict) else {}
        t = str(md.get("tweet_id") or "")
        a = md.get("author") or {}
        if not t or t == tid or not a.get("name"):
            continue
        if t not in tweets:
            if text_blocked(md.get("content")):
                tweets[t] = None
                continue
            text = re.sub(r"^(?:@\w{1,15}\s+)+", "", md.get("content") or "")     # (the @names it answers, as X hides them)
            tweets[t] = _comment(t, a["name"], text, str(md.get("date") or ""), md.get("favorite_count"),
                                 a.get("profile_image"))
            parent[t] = str(md.get("reply_id") or "")
        url = it[1] if it[0] == 3 else ""
        if tweets.get(t) is not None and isinstance(url, str) and url.startswith("https://pbs.twimg.com/"):
            tweets[t]["media"].append(url.replace("name=orig", "name=small"))
    top = []
    for t, c in tweets.items():
        if c is None:
            continue
        up = tweets.get(parent.get(t, ""))
        (up["replies"] if up else top).append(c)
    top.sort(key=lambda c: -(c["score"] or 0))
    return top


def comments(post_id: str) -> list[dict]:
    """A post's comments, live from its site: [{"id", "author", "avatar", "text", "at", "score",
    "media" (X: pictures in a reply), "replies": [...]}]. Comments whose text has words
    dreamfeed never shows are left out (and their replies with them)."""
    m = re.fullmatch(r"(x|reddit|e621):([A-Za-z0-9_]{1,30})", post_id or "")
    if not m:
        raise ValueError("bad post")
    site, pid = m.groups()
    read = {"x": _x_comments, "reddit": _reddit_comments, "e621": _e621_comments}[site]
    if site == "reddit" and not reddit_ready():
        raise LookupError("Reddit isn't signed in")
    return _cached(f"comments:{post_id}", lambda: read(pid))


# ---- what you saved on the sites (Saved's import) ----
def x_bookmarks() -> list[dict]:
    """Your X bookmarks with pictures or videos, newest first (all of them)."""
    posts, _, _ = _x_posts(_x("https://x.com/i/bookmarks", 1, 20000, timeout=1800), "saved")
    return posts


def reddit_saved() -> list[dict]:
    """The posts you saved on Reddit with pictures or videos, newest first (Reddit keeps the last
    1000). Needs the sign-in's history permission."""
    me = _reddit("/api/v1/me").get("name")
    if not me:
        raise LookupError("Reddit didn't say who you are")
    out, after = [], None
    for _ in range(10):
        q = f"/user/{me}/saved?type=links&limit=100&raw_json=1" + (f"&after={after}" if after else "")
        try:
            posts, after = _reddit_listing(_reddit(q), "saved")
        except LookupError as e:
            raise LookupError(f"{e}; Reddit's saved posts need the history permission: sign in again") from e
        out += posts
        if not after:
            break
    return out
