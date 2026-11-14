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
FEED_STALE = 6 * 3600  # a Feed page older than its TTL is still shown this long, while it's read again
                       # (the page then offers what's new: New posts)
_lock = threading.Lock()
_cache: dict[str, tuple[float, object, float, float]] = {}   # key: (when, value, seconds it's good for, then shown while read again)
_reading: dict[str, threading.Event] = {}                     # key: being read now (one reading at a time; others wait for it)
_failed: dict[str, BaseException] = {}
WHO_TTL = 86400        # who someone is (a Reddit user's picture, an e621 artist's links)


SUBS_TTL = 3600        # your Reddit subscriptions are asked for again after this


def _store(key: str, value, ttl: float, stale: float) -> None:
    with _lock:
        now = time.time()
        for k in [k for k, (t, _, good, more) in _cache.items() if now - t > good + more]:
            _cache.pop(k, None)
        _cache[key] = (now, value, ttl, stale)


def _read(key: str, fetch, ttl: float, stale: float):
    """Read it (this thread is the one reading key); anyone waiting gets the answer too."""
    try:
        value = fetch()
    except BaseException as e:
        with _lock:
            _failed[key] = e
        raise
    else:
        _store(key, value, ttl, stale)
        with _lock:
            _failed.pop(key, None)
        return value
    finally:
        with _lock:
            done = _reading.pop(key, None)
        if done:
            done.set()


def _cached(key: str, fetch, ttl: float = CACHE_TTL, stale: float = 0):
    """fetch()'s answer, kept ttl seconds. stale: after that, the old answer is still given (this
    long) while it's read again in the background. The same key is only read once at a time."""
    while True:
        with _lock:
            hit, now = _cache.get(key), time.time()
            if hit and now - hit[0] < hit[2]:
                return hit[1]
            busy = _reading.get(key)
            if hit and now - hit[0] < hit[2] + hit[3]:          # old but still shown: read again behind it
                if not busy:
                    _reading[key] = threading.Event()
                    threading.Thread(target=lambda: _quiet(key, fetch, ttl, stale), daemon=True).start()
                return hit[1]
            if not busy:
                _reading[key] = threading.Event()
                break
        busy.wait(120)
        with _lock:
            hit, err = _cache.get(key), _failed.get(key)
        if hit and time.time() - hit[0] < hit[2] + hit[3]:
            return hit[1]
        if err is not None:
            raise err
    return _read(key, fetch, ttl, stale)


def _quiet(key: str, fetch, ttl: float, stale: float) -> None:
    try:
        _read(key, fetch, ttl, stale)
    except Exception:          # (the old answer stays; the next ask tries again)
        pass


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
