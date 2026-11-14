"""What the Feed's sites share: the page cache, the word rules, the limits.

These are real people: nothing here goes to training, styles, comics or generation.
"""
import datetime as dt
import re
import threading
import time
from ..core import safety


MAX_GALLERY = 20
SITES = ("x", "bsky", "reddit", "e621")        # the Feed's sites
POST_ID = re.compile(r"(x|reddit|e621|bsky):([A-Za-z0-9_]{1,60})")     # a post: its site and its id there


CACHE_TTL = 120        # seconds a page is reused (switching tabs, coming back)
_lock = threading.Lock()
_cache: dict[str, tuple[float, object, float]] = {}     # key: (when, value, seconds it's good for)
WHO_TTL = 86400        # who someone is (a Reddit user's picture, an e621 artist's links)


SUBS_TTL = 3600        # your Reddit subscriptions are asked for again after this


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
    """Text about minors (safety.minors)."""
    return bool(safety.minors(*texts))


def place_blocked(name: str) -> bool:
    return bool(safety.minors(name))


def _utc(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts or 0, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ---- the Feed ----
def _merge(lists: list[list[dict]], by_time: bool) -> list[dict]:
    if by_time:
        return sorted((p for l in lists for p in l), key=lambda p: p["posted_at"], reverse=True)
    out, i = [], 0               # each site's own order, taken in turns
    while any(i < len(l) for l in lists):
        out += [l[i] for l in lists if i < len(l)]
        i += 1
    return out


# ---- a post's comments ----
MAX_COMMENTS = 150      # read a post, at most
COMMENT_DEPTH = 4       # replies to replies ... (Reddit)


def _comment(cid, author, text, at, score=None, avatar=None, media=None) -> dict:
    return {"id": str(cid), "author": author or "", "text": text or "", "at": at or "", "score": score,
            "avatar": avatar if avatar and str(avatar).startswith("https://") else None, "media": media or [], "replies": []}
