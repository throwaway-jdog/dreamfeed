"""Reddit, through its API as you (your own app and sign-in: the Dashboard's Sign-ins, or
REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_REFRESH_TOKEN): listings, users, your
subscriptions, Save, your saved posts, comments.

These are real people: nothing here goes to training, styles, comics or generation.
"""
import base64
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from .common import COMMENT_DEPTH, MAX_COMMENTS, MAX_GALLERY, SUBS_TTL, WHO_TTL, _cached, _comment, _lock, _utc, forget, place_blocked, text_blocked
from .redgifs import _redgifs_clip


REDDIT_API = "https://oauth.reddit.com"


REDDIT_AGENT = "linux:dreamfeed:1.0 (personal feed reader)"


SUBREDDIT = re.compile(r"^[A-Za-z0-9_]{2,21}$")


REDDIT_USER = re.compile(r"^[A-Za-z0-9_-]{3,20}$")


REDDIT_PAGE = 25


MAX_USERS = 10         # Reddit people (u/name) read for Following, each one's newest page


_token = {"value": "", "until": 0.0}


# ---- Reddit ----
def _creds() -> dict:
    """Your Reddit app and sign-in: the dashboard's, else the environment's (cookies.py)."""
    from ..core import cookies
    return cookies.reddit()


def _agent() -> str:
    user = _creds()["username"]
    return f"linux:dreamfeed:1.0 (by /u/{user})" if user else REDDIT_AGENT


def reddit_ready() -> bool:
    c = _creds()
    return all(c[k] for k in ("client_id", "client_secret", "refresh_token"))


def _reddit_token() -> str:
    c = _creds()
    with _lock:      # (a new sign-in: a new token)
        if _token["value"] and time.time() < _token["until"] and _token.get("for") == c["refresh_token"]:
            return _token["value"]
    if not reddit_ready():
        raise LookupError("Reddit isn't signed in (the dashboard: Sign-ins)")
    creds = f"{c['client_id']}:{c['client_secret']}"
    form = {"grant_type": "refresh_token", "refresh_token": c["refresh_token"]}
    req = urllib.request.Request("https://www.reddit.com/api/v1/access_token", data=urllib.parse.urlencode(form).encode(),
                                 headers={"User-Agent": _agent(), "Authorization": "Basic " + base64.b64encode(creds.encode()).decode()})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    if not d.get("access_token"):
        raise LookupError(f"Reddit refused the sign-in: {d.get('error') or d}")
    with _lock:
        _token.update(value=d["access_token"], until=time.time() + int(d.get("expires_in") or 3600) - 120, **{"for": c["refresh_token"]})
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
