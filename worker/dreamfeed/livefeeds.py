"""The Feed, live: posts read from X, Reddit and e621 when you look, shown straight from the
sites (their pictures and videos load from the sites' own servers; nothing is downloaded or
kept on disk). Used by the web app; standard library plus the gallery-dl command (for X).

- X: gallery-dl with your cookies (X_COOKIES, read-only), its metadata only (-j): your
  Following timeline, X's For you and anyone's media tab (their profile in dreamfeed).
- Reddit: its API as you (REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_REFRESH_TOKEN): your
  subscriptions and the Dashboard's extras as one listing (Following), your front page (Best,
  For you), any subreddit (Browse now) or user. Saving saves on Reddit.
- e621: the Dashboard's tag searches.

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
_cache: dict[str, tuple[float, object]] = {}
_token = {"value": "", "until": 0.0}
_redgifs = {"value": "", "until": 0.0}
_clips: dict[str, tuple[float, dict | None]] = {}
SUBS_TTL = 3600        # your Reddit subscriptions are asked for again after this


def x_cookies() -> str | None:
    path = os.environ.get("X_COOKIES", "").strip()
    return path if path and os.path.isfile(path) else None


def _cached(key: str, fetch):
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL:
            return hit[1]
    value = fetch()
    with _lock:
        for k in [k for k, (t, _) in _cache.items() if time.time() - t > CACHE_TTL]:
            _cache.pop(k, None)
        _cache[key] = (time.time(), value)
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
        posts.append({"id": f"reddit:{p['id']}", "source": "reddit", "author": p.get("author") or "",
                      "place": p.get("subreddit"), "text": p.get("title") or "", "posted_at": _utc(p.get("created_utc")),
                      "link": "https://www.reddit.com" + (p.get("permalink") or ""), "via": via,
                      "saved": bool(p.get("saved")), "media": media})
    return posts, (d.get("data") or {}).get("after")


def user_path(name: str) -> str:
    """A Reddit user's newest posts, as a listing path (Reddit's search by author: reading their
    profile itself needs a permission dreamfeed doesn't ask for)."""
    return f"/search?q=author%3A{name}&sort=new&type=link&include_over_18=on"


def reddit_page(path: str, after: str | None, via: str) -> tuple[list[dict], str | None]:
    """A Reddit listing (path like /best or /r/a+b/new), REDDIT_PAGE posts from `after`."""
    sep = "&" if "?" in path else "?"
    q = f"{path}{sep}limit={REDDIT_PAGE}&raw_json=1" + (f"&after={urllib.parse.quote(after)}" if after else "")
    return _cached("reddit:" + q, lambda: _reddit_listing(_reddit(q), via))


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
    with _lock:
        hit = _cache.get("subs")
        if hit and time.time() - hit[0] < SUBS_TTL:
            return hit[1]
    subs = fetch()
    with _lock:
        _cache["subs"] = (time.time(), subs)
    return subs


def reddit_save(post_id: str, save: bool) -> None:
    if not re.fullmatch(r"[a-z0-9]{3,12}", post_id):
        raise ValueError("bad post")
    _reddit("/api/save" if save else "/api/unsave", {"id": "t3_" + post_id})
    forget("reddit:")


# ---- X ----
def _x(url: str, start: int, count: int) -> list:
    if not x_cookies():
        raise LookupError("X isn't signed in (X_COOKIES_FILE)")
    try:
        out = subprocess.run(["gallery-dl", "--config-ignore", "--cookies", x_cookies(), "-o", "cookies-update=false",
                              "--range", f"{start}-{start + count - 1}", "-j", url],
                             capture_output=True, text=True, timeout=90)
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
                              "via": via, "saved": False, "media": [],
                              "mentions": sorted({n for n in named if n and n.lower() != a["name"].lower()})}
        ext = str(md.get("extension") or "").lower()
        if not str(url).startswith("https://"):
            continue
        if ext in ("mp4", "webm", "mov", "m4v"):
            p["media"].append({"kind": "video", "url": url, "poster": md.get("image") or None})
        elif ext in ("jpg", "jpeg", "png", "webp", "gif"):
            p["media"].append({"kind": "image", "url": url.replace("name=orig", "name=large")})
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
def e621_page(search: str, before: int | None) -> tuple[list[dict], int | None]:
    def fetch():
        params = {"tags": e621.query(search), "limit": E621_PAGE}
        if before:
            params["page"] = f"b{before}"
        found = e621.get("/posts.json", params).get("posts") or []
        out = []
        for p in found:
            got = e621.media(p)
            if e621.blocked(p) or not got or text_blocked(p.get("description")):
                continue
            d = e621.details(p)
            kind = "video" if got[1] in ("mp4", "webm") else "image"
            prev = (p.get("sample") or {}).get("url") or (p.get("preview") or {}).get("url")
            out.append({"id": f"e621:{d['id']}", "source": "e621", "author": d["author"], "place": search,
                        "text": d["title"], "posted_at": d["date"], "link": d["link"], "via": "following", "saved": False,
                        "media": [{"kind": kind, "url": got[0], "poster": prev if kind == "video" else None}]})
        last = min((int(p["id"]) for p in found if str(p.get("id", "")).isdigit()), default=None)
        return out, last if len(found) >= E621_PAGE else None
    return _cached(f"e621:{search}:{before}", fetch)


# ---- the Feed ----
def _merge(lists: list[list[dict]], by_time: bool) -> list[dict]:
    if by_time:
        return sorted((p for l in lists for p in l), key=lambda p: p["posted_at"], reverse=True)
    out, i = [], 0               # each site's own order, taken in turns
    while any(i < len(l) for l in lists):
        out += [l[i] for l in lists if i < len(l)]
        i += 1
    return out


def feed(mode: str, source: str, cursor: dict | None, follow: list[str], searches: list[str]) -> dict:
    """A page of the Feed. mode: following (your X Following, your subscriptions and the
    Dashboard's subreddits, its e621 searches) or foryou (X's For you, Reddit's Best).
    cursor: where each site's next page starts ({} for the first); None in it: that site's done.
    {"posts", "users", "cursor", "more", "errors"}."""
    sources = [s for s in (("x", "reddit", "e621") if mode == "following" else ("x", "reddit")) if source in ("all", s)]
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
            state = cursor.get("e621") or {q: None for q in searches}
            more, got = {}, []
            for q in searches:
                if not first and state.get(q) is None:
                    continue
                posts, last = e621_page(q, state.get(q))
                got += posts
                more[q] = last
            return [got] if searches else [], [], more if any(v is not None for v in more.values()) else None, None
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
