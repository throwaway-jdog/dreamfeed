"""Bluesky, read as you (your handle and an app password: the Dashboard's Sign-ins): your
Following, For you (your own feeds, mixed), someone's posts with media, More videos, replies.
Its pictures (cdn.bsky.app) and videos (HLS from video.bsky.app) play straight from it.

These are real people: nothing here goes to training, styles, comics or generation.
"""
import datetime as dt
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from .common import COMMENT_DEPTH, MAX_COMMENTS, MAX_GALLERY, SUBS_TTL, WHO_TTL, _cached, _comment, _merge, text_blocked


# ---- Bluesky ----
# Read as you (your handle and an app password, the Dashboard's Sign-ins): your Following, For
# you (your own feeds on Bluesky, the ones you pinned, else saved, mixed; else its Discover) and
# someone's posts with media. Its pictures (cdn.bsky.app) and videos (HLS from video.bsky.app) play here.
BSKY_ENTRY = "https://bsky.social"
BSKY_DISCOVER = "at://did:plc:z72i7hdynmk6r22z27h6tvur/app.bsky.feed.generator/whats-hot"
BSKY_PAGE = 40
BSKY_FEEDS = 10           # your feeds mixed into For you, at most
BSKY_FEED_PAGE = 20       # posts read from each a page
BSKY_ID = re.compile(r"^([a-z2-7]{24})_([a-z2-7]{13})$")          # a post: its account (did:plc:…) and its key
BSKY_HANDLE = re.compile(r"^(?:did:plc:[a-z2-7]{24}|[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)$")
_bsky_lock = threading.Lock()


def bsky_ready() -> bool:
    from ..core import cookies
    return bool(cookies.bsky()["from"])


def _bsky_json(url: str, data: dict | None = None, token: str | None = None, method: str | None = None):
    headers = {"User-Agent": "dreamfeed/1.0 (personal feed reader)", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data is not None else None
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method or ("POST" if body is not None else "GET"))
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    return json.loads(raw) if raw.strip() else {}


def _bsky_pds(sess: dict) -> str:
    for svc in ((sess.get("didDoc") or {}).get("service") or []):
        if svc.get("id") == "#atproto_pds" and str(svc.get("serviceEndpoint", "")).startswith("https://"):
            return svc["serviceEndpoint"].rstrip("/")
    return BSKY_ENTRY


def _bsky_session(fresh: bool = False) -> dict:
    """Your session (made once with the app password, kept, refreshed when it runs out)."""
    from ..core import cookies
    c = cookies.bsky()
    if not c["from"]:
        raise LookupError("Bluesky isn't signed in (the Dashboard: Sign-ins)")
    with _bsky_lock:
        sess = c["session"]
        if sess and not fresh:
            return sess
        try:
            if sess and sess.get("refreshJwt"):
                try:
                    new = _bsky_json(_bsky_pds(sess) + "/xrpc/com.atproto.server.refreshSession", None, sess["refreshJwt"], "POST")
                    sess = {**sess, **new}
                    cookies.save_bsky_session(sess)
                    return sess
                except urllib.error.HTTPError:
                    pass                      # (refresh too old: sign in again)
            sess = _bsky_json(BSKY_ENTRY + "/xrpc/com.atproto.server.createSession",
                              {"identifier": c["identifier"], "password": c["password"]})
        except urllib.error.HTTPError as e:
            if e.code in (400, 401):
                raise LookupError("Bluesky didn't take your handle and app password") from e
            raise LookupError(f"Bluesky said {e.code}") from e
        except OSError as e:
            raise LookupError(f"Bluesky didn't answer ({e})") from e
        cookies.save_bsky_session(sess)
        return sess


def _bsky(method: str, params: dict | None = None):
    """An app.bsky call as you (through your own server, as Bluesky's apps do)."""
    q = "?" + urllib.parse.urlencode([(k, x) for k, v in (params or {}).items() for x in (v if isinstance(v, list) else [v])
                                      if x is not None]) if params else ""
    for attempt in (0, 1):
        sess = _bsky_session(fresh=attempt == 1)
        try:
            return _bsky_json(f"{_bsky_pds(sess)}/xrpc/{method}{q}", token=sess["accessJwt"])
        except urllib.error.HTTPError as e:
            if e.code in (400, 401) and attempt == 0:
                try:
                    err = json.loads(e.read() or b"{}").get("error")
                except ValueError:
                    err = None
                if err in ("ExpiredToken", "InvalidToken") or e.code == 401:
                    continue                # (the session ran out: refreshed, once)
            raise LookupError(f"Bluesky said {e.code}") from e
        except OSError as e:
            raise LookupError(f"Bluesky didn't answer ({e})") from e


def _bsky_media(embed: dict) -> list[dict]:
    t = str((embed or {}).get("$type") or "")
    if t.startswith("app.bsky.embed.recordWithMedia"):
        return _bsky_media(embed.get("media") or {})
    if t.startswith("app.bsky.embed.images"):
        return [{"kind": "image", "url": i.get("thumb") or i.get("fullsize"), "full": i.get("fullsize") or i.get("thumb")}
                for i in embed.get("images") or [] if str(i.get("fullsize") or i.get("thumb") or "").startswith("https://")][:MAX_GALLERY]
    if t.startswith("app.bsky.embed.video") and str(embed.get("playlist") or "").startswith("https://"):
        return [{"kind": "hls", "url": embed["playlist"], "poster": embed.get("thumbnail")}]
    return []


def _bsky_post(p: dict, via: str) -> dict | None:
    """One Bluesky post as the Feed shows it (pictures or a video), or None."""
    uri, a, rec = str(p.get("uri") or ""), p.get("author") or {}, p.get("record") or {}
    m = re.fullmatch(r"at://did:plc:([a-z2-7]{24})/app\.bsky\.feed\.post/([a-z2-7]{13})", uri)
    media = _bsky_media(p.get("embed") or {})
    labels = {str(l.get("val")) for l in p.get("labels") or []}
    if not m or not media or text_blocked(rec.get("text")) or labels & {"!hide", "!takedown", "gore"}:
        return None
    try:
        when = dt.datetime.fromisoformat(str(rec.get("createdAt") or p.get("indexedAt")).replace("Z", "+00:00")).astimezone(
            dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        when = ""
    handle = str(a.get("handle") or "")
    return {"id": f"bsky:{m.group(1)}_{m.group(2)}", "source": "bsky", "author": handle, "nick": a.get("displayName") or None,
            "avatar": a.get("avatar") if str(a.get("avatar") or "").startswith("https://") else None, "place": "",
            "text": rec.get("text") or "", "posted_at": when, "link": f"https://bsky.app/profile/{handle or 'did:plc:' + m.group(1)}/post/{m.group(2)}",
            "via": via, "saved": False, "media": media, "likes": p.get("likeCount"), "comments": p.get("replyCount"),
            "uri": uri}


def _bsky_list(items: list, via: str) -> list[dict]:
    out, seen = [], set()
    for it in items:
        p = _bsky_post(it.get("post") or {}, via)
        if p and p["id"] not in seen:
            seen.add(p["id"]); out.append(p)
    return out


def _bsky_my_feeds() -> list[dict]:
    """Your own feeds on Bluesky: those you pinned (in your order), else those you saved; else
    its Discover. [{"uri", "name"}]."""
    prefs = _bsky("app.bsky.actor.getPreferences").get("preferences") or []
    pinned, saved = [], []
    for pref in prefs:
        t = str(pref.get("$type", ""))
        if t.endswith("savedFeedsPrefV2"):
            for f in pref.get("items") or []:
                if f.get("type") == "feed" and str(f.get("value", "")).startswith("at://"):
                    (pinned if f.get("pinned") else saved).append(f["value"])
        elif t.endswith("savedFeedsPref"):       # (Bluesky's older form of the same)
            saved += [u for u in pref.get("saved") or [] if str(u).startswith("at://")]
            pinned += [u for u in pref.get("pinned") or [] if str(u).startswith("at://")]
    uris = list(dict.fromkeys(pinned or saved))[:BSKY_FEEDS] or [BSKY_DISCOVER]
    names = {}
    try:
        for g in _bsky("app.bsky.feed.getFeedGenerators", {"feeds": uris}).get("feeds") or []:
            names[g.get("uri")] = g.get("displayName")
    except LookupError:
        pass
    return [{"uri": u, "name": names.get(u) or "Discover" if u == BSKY_DISCOVER else names.get(u) or "a feed"} for u in uris]


def bsky_foryou(cursor: dict | None) -> tuple[list[dict], dict | None]:
    """For you: a page of each of your feeds, taken in turns (each its own cursor; one that's
    run out is left out of the next pages). (posts, cursor or None)."""
    feeds = _cached("bsky:my-feeds", _bsky_my_feeds, SUBS_TTL)
    first = not cursor
    cursor = {k: v for k, v in (cursor or {}).items() if isinstance(v, str) and len(v) < 1000}     # (from the page: only what Bluesky gave)
    todo = [f for f in feeds if first or cursor.get(f["uri"])]

    def one(f):
        def fetch():
            d = _bsky("app.bsky.feed.getFeed", {"feed": f["uri"], "limit": BSKY_FEED_PAGE, "cursor": cursor.get(f["uri"]) or None})
            return [{**p, "place": f["name"]} for p in _bsky_list(d.get("feed") or [], "foryou")], d.get("cursor") or None
        try:
            return _cached(f"bsky:feed:{f['uri']}:{cursor.get(f['uri'])}", fetch)
        except LookupError:
            return [], None                     # (a feed that's gone or failing: the others still come)
    with ThreadPoolExecutor(max_workers=4) as pool:
        got = list(pool.map(one, todo))
    nxt = {f["uri"]: after for f, (_, after) in zip(todo, got) if after}
    return _merge([posts for posts, _ in got], by_time=False), nxt or None


def bsky_page(kind: str, cursor: str | None) -> tuple[list[dict], str | None]:
    """Your Following ("home") or someone's posts with media ("@handle"). (For you: bsky_foryou.)"""
    def fetch():
        if kind == "home":
            d, via = _bsky("app.bsky.feed.getTimeline", {"limit": BSKY_PAGE, "cursor": cursor}), "following"
        elif kind.startswith("@") and BSKY_HANDLE.match(kind[1:]):
            d, via = _bsky("app.bsky.feed.getAuthorFeed", {"actor": kind[1:], "filter": "posts_with_media",
                                                          "limit": BSKY_PAGE, "cursor": cursor}), "profile"
        else:
            raise ValueError("bad Bluesky feed")
        return _bsky_list(d.get("feed") or [], via), d.get("cursor") or None
    return _cached(f"bsky:{kind}:{cursor}", fetch)


BSKY_VIDEOS = "at://did:plc:z72i7hdynmk6r22z27h6tvur/app.bsky.feed.generator/thevids"     # Bluesky's own "Video" feed


def bsky_videos(kind: str, where: str, cursor: str | None) -> tuple[list[dict], str | None]:
    """Bluesky videos for More videos: someone's ("author", their handle), its Video feed
    ("feed") or your timeline's ("home"), each with its next page."""
    def fetch():
        if kind == "author":
            if not BSKY_HANDLE.match(where):
                raise ValueError("bad Bluesky handle")
            d = _bsky("app.bsky.feed.getAuthorFeed", {"actor": where, "filter": "posts_with_video", "limit": BSKY_PAGE, "cursor": cursor})
        elif kind == "feed":
            d = _bsky("app.bsky.feed.getFeed", {"feed": BSKY_VIDEOS, "limit": BSKY_PAGE, "cursor": cursor})
        elif kind == "home":
            d = _bsky("app.bsky.feed.getTimeline", {"limit": BSKY_PAGE, "cursor": cursor})
        else:
            raise ValueError("bad Bluesky videos")
        return _bsky_list(d.get("feed") or [], "videos"), d.get("cursor") or None
    return _cached(f"bsky:videos:{kind}:{where}:{cursor}", fetch)


def bsky_user(handle: str) -> dict:
    """Who they are on Bluesky: {"handle", "nick", "bio", "avatar", "followers", "following", "posts"}."""
    if not BSKY_HANDLE.match(handle):
        raise ValueError("bad Bluesky handle")
    def fetch():
        u = _bsky("app.bsky.actor.getProfile", {"actor": handle})
        return {"handle": u.get("handle"), "nick": u.get("displayName"), "bio": u.get("description"),
                "avatar": u.get("avatar") if str(u.get("avatar") or "").startswith("https://") else None,
                "followers": u.get("followersCount"), "following": u.get("followsCount"), "posts": u.get("postsCount"),
                "you_follow": bool((u.get("viewer") or {}).get("following"))}
    return _cached(f"bsky:user:{handle.lower()}", fetch, WHO_TTL / 24)


def _bsky_uri(pid: str) -> str:
    m = BSKY_ID.match(pid)
    if not m:
        raise ValueError("bad post")
    return f"at://did:plc:{m.group(1)}/app.bsky.feed.post/{m.group(2)}"


def _bsky_comments(pid: str) -> list[dict]:
    d = _bsky("app.bsky.feed.getPostThread", {"uri": _bsky_uri(pid), "depth": COMMENT_DEPTH, "parentHeight": 0})
    def walk(node, depth=0) -> list[dict]:
        out = []
        for r in (node or {}).get("replies") or []:
            p = r.get("post") or {}
            rec, a = p.get("record") or {}, p.get("author") or {}
            if not p or text_blocked(rec.get("text")):
                continue
            c = _comment(p.get("uri"), a.get("handle"), rec.get("text"), str(rec.get("createdAt") or "")[:19].replace("T", " "),
                         p.get("likeCount"), a.get("avatar"), [m for m in _bsky_media(p.get("embed") or {}) if m["kind"] == "image"])
            if depth < COMMENT_DEPTH:
                c["replies"] = walk(r, depth + 1)
            out.append(c)
        return out[:MAX_COMMENTS]
    return walk(d.get("thread") or {})
