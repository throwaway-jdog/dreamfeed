"""e621 (e621.net), through its public API: tag searches for the live Feed (livefeeds) and
pools, its comics, for the Comics page's search (the web app). Standard library only, so the
web app uses it too.

A post with a tag dreamfeed never allows is left out (NEVER: the youth tags, feral,
bestiality); searches also ask e621 to leave those out (SEARCH_NOT).

Signed in (your username and API key: the Dashboard's Sign-ins, cookies.py), it reads as you
and can also: favorite and unfavorite (Save), vote, read your favorites (the Saved import, and
your taste: For you), and hide what your account's blacklist does. Your name goes in the user
agent, as e621 asks (E621_USERNAME too, when not signed in).
"""
import base64
import fnmatch
import datetime as dt
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from ..core import safety

API = "https://e621.net"
STATIC = ("static1.e621.net",)
GAP = 1.0                     # seconds between API requests (e621 allows about 2 a second)
NEVER = ({t.replace(" ", "_") for t in safety.YOUTH_TAGS | safety.FERAL_TAGS}
         | {"young", "cub", "child", "loli", "shota", "toddler", "baby", "infant", "teen", "adolescent",
            "feral", "bestiality", "zoophilia", "underage"})
SEARCH_NOT = "-young -feral -bestiality"
ARTIST = re.compile(r"^[a-z0-9_()\-.'!~]{1,100}$")     # an artist's tag
NOT_ARTISTS = ("conditional_dnp", "sound_warning", "unknown_artist", "anonymous_artist", "avoid_posting", "third-party_edit")
MAX_TERMS = 30                # e621 takes 40 tags a search; SEARCH_NOT and the date and order take some
_lock, _last = threading.Lock(), [0.0]


def creds() -> tuple[str, str] | None:
    """(username, API key) when signed in."""
    from ..core import cookies
    c = cookies.e621()
    return (c["username"], c["api_key"]) if c["from"] else None


def agent() -> str:
    user = (creds() or (os.environ.get("E621_USERNAME", "").strip(),))[0]
    return f"dreamfeed/1.0 (personal feed reader{f', by {user} on e621' if user else ''})"


def _wait(gap: float) -> None:
    with _lock:
        pause = _last[0] + gap - time.time()
        if pause > 0:
            time.sleep(pause)
        _last[0] = time.time()


def _headers() -> dict:
    h = {"User-Agent": agent()}
    c = creds()
    if c:
        h["Authorization"] = "Basic " + base64.b64encode(f"{c[0]}:{c[1]}".encode()).decode()
    return h


def get(path: str, params: dict):
    _wait(GAP)
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=_headers()), timeout=30) as r:
        return json.load(r)


def send(method: str, path: str, form: dict | None = None):
    """A change to your account (a favorite, a vote): only signed in."""
    if not creds():
        raise LookupError("e621 isn't signed in (the Dashboard: Sign-ins)")
    _wait(GAP)
    data = urllib.parse.urlencode(form or {}).encode() if method != "DELETE" else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise LookupError("e621 didn't take your username and API key") from e
        try:
            msg = json.loads(e.read() or b"{}").get("message") or e.code
        except ValueError:
            msg = e.code
        raise LookupError(f"e621 said: {msg}") from e
    return json.loads(body) if body.strip() else {}


def me() -> dict:
    """Your account as e621 shows it to you: {"name", "favorites", "blacklist" (its lines)}."""
    c = creds()
    if not c:
        raise LookupError("e621 isn't signed in")
    try:
        u = get(f"/users/{urllib.parse.quote(c[0])}.json", {})
    except urllib.error.HTTPError as e:
        raise LookupError("e621 didn't take your username and API key" if e.code in (401, 403, 404) else f"e621 said {e.code}") from e
    if "blacklisted_tags" not in u:           # (only shown to the account itself: the key isn't theirs)
        raise LookupError("e621 didn't take your username and API key")
    lines = [l.strip() for l in str(u.get("blacklisted_tags") or "").splitlines() if l.strip() and not l.strip().startswith("#")]
    return {"name": u.get("name") or c[0], "favorites": u.get("favorite_count"), "blacklist": lines}


# ---- your blacklist (as e621's own site applies it: a post is hidden when it matches every
# term of a line; -tag: without it; ~tag: any of those; rating:s/q/e; * in a tag)
BLACKLIST_TTL = 3600
_black = {"at": 0.0, "for": None, "lines": []}


def _black_lines() -> list[list[str]]:
    c = creds()
    if not c:
        return []
    if _black["for"] != c or time.time() - _black["at"] > BLACKLIST_TTL:
        try:
            lines = me()["blacklist"]
        except (LookupError, OSError, ValueError):
            lines = _black["lines"] if _black["for"] == c else []
        _black.update(at=time.time(), **{"for": c}, lines=[l.lower().split() for l in lines])
    return _black["lines"]


def _line_hides(terms: list[str], tags: set[str], rating: str) -> bool:
    need, anyof = [], []
    for raw in terms:
        neg, alt = raw.startswith("-"), raw.startswith("~")
        t = raw[1:] if neg or alt else raw
        if not t:
            continue
        if ":" in t and not t.startswith("rating:"):
            return False                  # (a metatag dreamfeed doesn't read: that line's left to e621's own site)
        if t.startswith("rating:"):
            has = t[7:8] == rating[:1]
        elif "*" in t:
            has = any(fnmatch.fnmatchcase(x, t) for x in tags)
        else:
            has = t in tags
        if alt:
            anyof.append(has)
        else:
            need.append(not has if neg else has)
    if not need and not anyof:
        return False
    return all(need) and (any(anyof) if anyof else True)


def blacklisted(post: dict) -> bool:
    """Whether your e621 blacklist hides the post (signed in; else never)."""
    lines = _black_lines()
    if not lines:
        return False
    tags, rating = tags_of(post), str(post.get("rating") or "")
    return any(_line_hides(l, tags, rating) for l in lines)


def favorite(post_id: str, on: bool) -> None:
    if on:
        try:
            send("POST", "/favorites.json", {"post_id": post_id})
        except LookupError as e:
            if "already" not in str(e).lower():
                raise
    else:
        send("DELETE", f"/favorites/{post_id}.json")


def vote(post_id: str, score: int) -> dict:
    """Up (1) or down (-1); the same again takes it back. {"score", "up", "down", "ours"}."""
    d = send("POST", f"/posts/{post_id}/votes.json", {"score": score})
    return {"score": d.get("score"), "up": d.get("up"), "down": d.get("down"), "ours": d.get("our_score")}


def favorites(limit: int = 1000) -> list[dict]:
    """Your favorites, newest favorited first (e621's raw posts)."""
    c = creds()
    if not c:
        raise LookupError("e621 isn't signed in")
    out, page = [], 1
    while len(out) < limit:
        got = get("/favorites.json", {"limit": 320, "page": page}).get("posts") or []
        out += got
        if len(got) < 320:
            break
        page += 1
    return out[:limit]


# ---- your taste (For you): the artists and species most in what you favorited and voted up
TASTE_TTL = 6 * 3600
TASTE_ARTISTS, TASTE_SPECIES = 12, 6
COMMON_SPECIES = {"mammal", "canid", "canine", "felid", "feline", "anthro", "humanoid", "hybrid", "animal_humanoid"}
_taste = {"at": 0.0, "for": None, "value": None}


def taste() -> dict | None:
    """{"artists": [...], "species": [...], "name"} from your last few hundred favorites and up
    votes; None when not signed in or there's too little to go on."""
    c = creds()
    if not c:
        return None
    if _taste["for"] == c and time.time() - _taste["at"] < TASTE_TTL:
        return _taste["value"]
    posts = []
    try:
        posts = get("/favorites.json", {"limit": 320}).get("posts") or []
        posts += get("/posts.json", {"tags": f"votedup:{c[0]}", "limit": 160}).get("posts") or []
    except (OSError, ValueError):
        pass
    artists, species = {}, {}
    for p in posts:
        if blocked(p):
            continue
        g = p.get("tags") or {}
        for a in g.get("artist") or []:
            if a not in NOT_ARTISTS and ARTIST.match(a):
                artists[a] = artists.get(a, 0) + 1
        for s in g.get("species") or []:
            if s not in COMMON_SPECIES and s not in NEVER:
                species[s] = species.get(s, 0) + 1
    top = lambda d, n, least: [k for k, v in sorted(d.items(), key=lambda kv: -kv[1]) if v >= least][:n]
    value = {"name": c[0], "artists": top(artists, TASTE_ARTISTS, 2), "species": top(species, TASTE_SPECIES, 3)}
    value = value if value["artists"] or value["species"] else None
    _taste.update(at=time.time(), **{"for": c}, value=value)
    return value


def fetch(url: str, limit: int = 200 << 20) -> bytes:
    """A file from e621's file server (pictures, videos, previews)."""
    if urllib.parse.urlparse(url).hostname not in STATIC:
        raise ValueError("not an e621 file")
    _wait(GAP / 2)
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": agent()}), timeout=120) as r:
        return r.read(limit)


def tags_of(post: dict) -> set[str]:
    return {t.lower() for group in (post.get("tags") or {}).values() for t in group}


def blocked(post: dict) -> list[str]:
    """The tags on a post that dreamfeed never allows (empty: it may be downloaded)."""
    return sorted(tags_of(post) & NEVER)


def query(search: str) -> str:
    """A tag search as typed, checked (raises ValueError), with SEARCH_NOT added."""
    terms = search.split()
    if not terms or len(terms) > MAX_TERMS or len(search) > 300 or any(not t.isprintable() for t in terms):
        raise ValueError(f"a search is 1 to {MAX_TERMS} tags")
    bad = safety.request_blocked(search.replace("_", " ")) + [t for t in terms if t.lower().lstrip("~") in NEVER]
    if bad:
        raise ValueError(f"not something to look for: {', '.join(sorted(set(bad)))}")
    return f"{' '.join(terms)} {SEARCH_NOT}"


def media(post: dict) -> tuple[str, str] | None:
    """(address, extension) of what to download: a video's 720p (or 480p) MP4 rather than the
    original, a picture's own file unless it's huge (then the sample)."""
    f, sample = post.get("file") or {}, post.get("sample") or {}
    ext = (f.get("ext") or "").lower()
    if ext in ("webm", "mp4"):
        alt = sample.get("alternates") or {}
        for q in ("720p", "480p"):
            u = ((alt.get("samples") or {}).get(q) or {}).get("url")
            if u:
                return u, "mp4"
        mp4 = ((alt.get("variants") or {}).get("mp4") or {}).get("url")
        if mp4:
            return mp4, "mp4"
        return (f["url"], ext) if f.get("url") else None
    if ext in ("jpg", "jpeg", "png", "gif", "webp") and f.get("url"):
        if (f.get("size") or 0) > 25 << 20 and sample.get("url"):
            return sample["url"], "jpg"
        return f["url"], ext
    return None


def details(post: dict) -> dict:
    """What the Feed shows of a post: who drew it (artists: their tags), its description, when, the link."""
    artists = [a for a in (post.get("tags") or {}).get("artist") or [] if a not in NOT_ARTISTS]
    try:
        when = dt.datetime.fromisoformat(post["created_at"]).astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except (KeyError, ValueError):
        when = ""
    return {"id": str(post["id"]), "author": ", ".join(artists[:3]).replace("_", " "), "artists": artists[:3],
            "title": (post.get("description") or "")[:500], "date": when, "link": f"{API}/posts/{post['id']}"}


def pools(q: str, page: int) -> dict:
    """e621's comics (pools of the "series" kind) whose name matches q, each {"title", "url",
    "pages", "thumb"}: the cover is the first post's preview, and a pool whose cover has a tag
    dreamfeed never allows is left out."""
    q = q.strip()
    if not 1 <= len(q) <= 100:
        raise ValueError("type what to look for (up to 100 characters)")
    bad = safety.request_blocked(q)
    if bad:
        raise ValueError(f"not something to look for: {', '.join(bad)}")
    found = get("/pools.json", {"search[name_matches]": "*" + "*".join(q.split()) + "*", "search[category]": "series",
                                "limit": 24, "page": page + 1})
    more = len(found) == 24
    found = [p for p in found if p.get("post_ids") and not safety.request_blocked(p.get("name", "").replace("_", " "))]
    covers = {}
    if found:
        posts = get("/posts.json", {"tags": "id:" + ",".join(str(p["post_ids"][0]) for p in found), "limit": 100})
        covers = {p["id"]: p for p in posts.get("posts") or []}
    out = []
    for p in found:
        cover = covers.get(p["post_ids"][0])
        if not cover or blocked(cover):      # e621 hides some covers from visitors; those are left out too
            continue
        out.append({"title": p["name"].replace("_", " "), "url": f"{API}/pools/{p['id']}", "pages": p.get("post_count"),
                    "cover": (cover.get("preview") or {}).get("url")})
    return {"results": out, "more": more}
