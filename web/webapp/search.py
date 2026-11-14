"""Search (the page's 🔍): one search across dreamfeed. The page asks each part at once:
- posts: X, Bluesky, Reddit and e621 (its tags), read live and mixed, here;
- subreddits: Reddit's, by name and description, here;
- yours: what you saved, rooms you follow, comics you follow and your history, here;
- and, through their own searches: Videos (/api/vids/search), Comics (/api/comics/search), Live
  rooms (/api/discover/cb?mode=search).
Your mute list applies; what dreamfeed leaves out (minors) is left out of searches too.
"""
import base64
import itertools
import json
import re
from concurrent.futures import ThreadPoolExecutor

from dreamfeed.core import safety
from dreamfeed.feed import livefeeds

from . import history, mutes
from .common import FEED_SOURCES, db
from .feed import _mark_saved, _saved_json


def _q(q: str) -> str:
    q = " ".join(str(q or "").split())
    if not 1 <= len(q) <= 100:
        raise ValueError("type what to look for (up to 100 characters)")
    if safety.minors(q):
        raise ValueError("not something to look for")
    return q


def _like(q: str) -> str:
    return "%" + re.sub(r"([%_\\])", r"\\\1", q) + "%"


def posts(q: str, source: str, cursor: str) -> dict:
    """{"posts", "cursor", "errors"}: each site's matches, mixed in turns."""
    q = _q(q)
    picked = FEED_SOURCES if source == "all" else tuple(s for s in source.split(","))
    if not picked or any(s not in FEED_SOURCES for s in picked):
        raise ValueError("bad source")
    try:
        at = json.loads(base64.urlsafe_b64decode(cursor.encode() + b"==").decode()) if cursor else {}
    except ValueError as e:
        raise ValueError("bad cursor") from e
    if not isinstance(at, dict):
        raise ValueError("bad cursor")
    todo = [s for s in picked if not cursor or at.get(s) is not None]

    def one(site):
        c = at.get(site)
        try:
            if site == "x":
                if not livefeeds.x_cookies():
                    return [], None, None
                d = livefeeds.x_search(q, int(c or 1))
                return d["posts"], d["next"], None
            if site == "bsky":
                if not livefeeds.bsky_ready():
                    return [], None, None
                return (*livefeeds.bsky_search(q, c), None)
            if site == "reddit":
                if not livefeeds.reddit_ready():
                    return [], None, None
                return (*livefeeds.reddit_search(q, c), None)
            tags = " ".join(w.replace(" ", "_") for w in q.lower().split())
            return (*livefeeds.e621_page(tags, int(c) if c else None), None)
        except (LookupError, ValueError, OSError) as e:
            return [], None, str(e)[:200]
    lists, nxt, errors = [], {}, {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for site, (got, after, err) in zip(todo, pool.map(one, todo)):
            lists.append(mutes.posts(got))
            nxt[site] = after
            if err:
                errors[site] = err
    mixed = [p for row in itertools.zip_longest(*lists) for p in row if p]
    more = any(v is not None for v in nxt.values())
    return {"posts": _mark_saved(mixed), "errors": errors,
            "cursor": base64.urlsafe_b64encode(json.dumps(nxt).encode()).decode().rstrip("=") if more else None}


def subreddits(q: str) -> dict:
    q = _q(q)
    if not livefeeds.reddit_ready():
        return {"subreddits": [], "note": "Reddit isn't signed in"}
    try:
        found = livefeeds.subreddit_search(q)
    except LookupError as e:
        return {"subreddits": [], "note": str(e)[:200]}
    r = mutes.rules()
    return {"subreddits": [s for s in found if s["name"].lower() not in r["subs"]]}


def yours(q: str) -> dict:
    """What matches among what's yours: saved posts, rooms and comics you follow, your history."""
    q = _q(q)
    like = _like(q)
    with db() as conn:
        saved = [_saved_json(r) for r in conn.execute(
            "SELECT * FROM saved_posts WHERE status != 'removed' AND (json_extract(data, '$.text') LIKE ? ESCAPE '\\'"
            " OR json_extract(data, '$.author') LIKE ? ESCAPE '\\' OR json_extract(data, '$.place') LIKE ? ESCAPE '\\')"
            " ORDER BY saved_at DESC LIMIT 12", (like, like, like))]
        rooms = [{"name": r["name"], "live": bool(r["live"]), "info": json.loads(r["info"]) if r["info"] else {}}
                 for r in conn.execute("SELECT * FROM follows WHERE source = 'chaturbate' AND name LIKE ? ESCAPE '\\'"
                                       " ORDER BY live DESC, name LIMIT 12", (like.replace(" ", "_"),))]
        try:
            comics = [json.loads(r["data"]) for r in conn.execute(
                "SELECT data FROM comic_follows WHERE json_extract(data, '$.title') LIKE ? ESCAPE '\\' ORDER BY at DESC LIMIT 12", (like,))]
        except Exception:          # (no comics followed yet)
            comics = []
    return {"saved": saved, "rooms": rooms, "comics": comics, "history": history.listing("", 0, q)["items"][:12]}
