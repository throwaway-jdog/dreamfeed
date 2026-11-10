"""e621 (e621.net), through its public API: tag searches for the Feed (followfeeds) and pools,
its comics, for the Comics page's search (the web app). Standard library only, so the web app
uses it too.

Before anything is downloaded or shown, a post with a tag dreamfeed never allows is left out
(NEVER: the youth tags, feral, bestiality); searches also ask e621 to leave those out
(SEARCH_NOT). What's downloaded then goes through the image checks like every feed's.
E621_USERNAME (optional) puts your name in the user agent, as e621 asks.
"""
import datetime as dt
import json
import os
import threading
import time
import urllib.parse
import urllib.request

from . import safety

API = "https://e621.net"
STATIC = ("static1.e621.net",)
GAP = 1.0                     # seconds between API requests (e621 allows about 2 a second)
NEVER = ({t.replace(" ", "_") for t in safety.YOUTH_TAGS | safety.FERAL_TAGS}
         | {"young", "cub", "child", "loli", "shota", "toddler", "baby", "infant", "teen", "adolescent",
            "feral", "bestiality", "zoophilia", "underage"})
SEARCH_NOT = "-young -feral -bestiality"
MAX_TERMS = 30                # e621 takes 40 tags a search; SEARCH_NOT and the date and order take some
_lock, _last = threading.Lock(), [0.0]


def agent() -> str:
    user = os.environ.get("E621_USERNAME", "").strip()
    return f"dreamfeed/1.0 (personal feed reader{f', by {user} on e621' if user else ''})"


def _wait(gap: float) -> None:
    with _lock:
        pause = _last[0] + gap - time.time()
        if pause > 0:
            time.sleep(pause)
        _last[0] = time.time()


def get(path: str, params: dict):
    _wait(GAP)
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": agent()}), timeout=30) as r:
        return json.load(r)


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
    """What the Feed shows of a post: who drew it, its description, when, the link."""
    artists = [a for a in (post.get("tags") or {}).get("artist") or []
               if a not in ("conditional_dnp", "sound_warning", "unknown_artist", "anonymous_artist")]
    try:
        when = dt.datetime.fromisoformat(post["created_at"]).astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except (KeyError, ValueError):
        when = ""
    return {"id": str(post["id"]), "author": ", ".join(artists[:3]).replace("_", " "),
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
