"""The live Feed (livefeeds), Saved (and bringing in what you saved on the sites), More videos,
Browse now and the random subreddit, someone's latest posts, one post's own page.
"""
import base64
import json
import os
import random
import re
import shutil
import sqlite3
import threading
import time
import urllib.parse
from pathlib import Path

from dreamfeed.feed import e621, livefeeds, savedposts

from . import mutes
from .common import DATA, FEED_MODES, FEED_SOURCES, PAGE_SIZE, REDDIT_USER, X_HANDLE, _cached, db, read_json


SAVED_SOURCES = ("all", "x", "bsky", "reddit", "e621")


def saved_view(offset: int, source: str = "all") -> dict:
    """Saved: the Feed posts you saved (and brought in from the sites), newest first, as
    {"items": [{"post": a Feed post}], "more"}. source: all, or a site's."""
    if source not in SAVED_SOURCES:
        raise ValueError("bad source")
    where, args = "status != 'removed'", []
    if source != "all":
        where += " AND source = ?"
        args.append(source)
    try:
        with db() as conn:
            rows = conn.execute(f"SELECT * FROM saved_posts WHERE {where} ORDER BY saved_at DESC LIMIT ? OFFSET ?",
                                (*args, PAGE_SIZE + 1, offset)).fetchall()
    except sqlite3.OperationalError:   # (its table isn't there yet)
        return {"items": [], "more": False}
    return {"items": [{"post": _saved_json(r)} for r in rows[:PAGE_SIZE]], "more": len(rows) > PAGE_SIZE}


FOLLOWING = DATA / "following.json"     # read by the follow service on each round
MAX_FOLLOW = 50
REDDIT_NAME = re.compile(r"^(?:https?://(?:www\.|old\.)?reddit\.com)?/?(?:(r|u|user)/)?([A-Za-z0-9_-]{2,30})/?$")


def follow_settings(subscribed: bool = True) -> dict:
    """The Dashboard's subreddits and e621 searches, and the subscriptions you have on Reddit
    (when signed in as you; asked of Reddit, kept 10 minutes)."""
    d = read_json(FOLLOWING).get("reddit") or {}
    subs = []
    if subscribed and livefeeds.reddit_ready():
        try:
            subs = livefeeds.subscriptions()
        except (LookupError, OSError, ValueError):
            pass
    e = read_json(FOLLOWING).get("e621") or {}
    return {"reddit": {"follow": d.get("follow") or [], "top": d.get("top") or 10,
                       "subscribed": [s for s in subs if isinstance(s, str)] if isinstance(subs, list) else []},
            "e621": {"searches": e.get("searches") or [], "top": e.get("top") or 10}}


def _write_following(data: dict) -> None:
    tmp = FOLLOWING.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(FOLLOWING)


def save_follow_settings(req: dict) -> dict:
    if isinstance(req.get("e621"), dict):
        e = req["e621"]
        if not isinstance(e.get("searches"), list):
            raise ValueError('send {"e621": {"searches": [...], "top": N}}')
        searches = []
        for q in e["searches"]:
            q = " ".join(str(q).split())
            e621.query(q)           # refused: ValueError
            if q.lower() not in {x.lower() for x in searches}:
                searches.append(q)
        if len(searches) > MAX_FOLLOW:
            raise ValueError(f"at most {MAX_FOLLOW}")
        _write_following({**read_json(FOLLOWING), "e621": {"searches": searches,
                                                           "top": int(_num(e.get("top", 10), 1, 100, "top"))}})
        return follow_settings()
    r = req.get("reddit")
    if not isinstance(r, dict) or not isinstance(r.get("follow"), list):
        raise ValueError('send {"reddit": {"follow": [...], "top": N}} or {"e621": {...}}')
    out = []
    for item in r["follow"]:
        m = REDDIT_NAME.match(str(item).strip())
        if not m:
            raise ValueError(f"not a subreddit or user: {str(item)[:40]} (r/name or u/name)")
        name = f"{'u' if m.group(1) in ('u', 'user') else 'r'}/{m.group(2)}"
        if name.lower() not in {x.lower() for x in out}:
            out.append(name)
    if len(out) > MAX_FOLLOW:
        raise ValueError(f"at most {MAX_FOLLOW}")
    top = _num(r.get("top", 10), 1, 100, "top")
    _write_following({**read_json(FOLLOWING), "reddit": {"follow": out, "top": int(top)}})   # (subscribed isn't stored here)
    return follow_settings()


X_SEEN_DAYS = 30       # X accounts in your timelines are remembered this long (Discover)


def _cursor(raw: str) -> dict | None:
    if not raw:
        return None
    try:
        c = json.loads(base64.urlsafe_b64decode(raw.encode() + b"==").decode())
    except (ValueError, UnicodeDecodeError) as e:
        raise ValueError("bad cursor") from e
    if not isinstance(c, dict):
        raise ValueError("bad cursor")
    return c


def _seen(posts: list[dict], users: list[dict]) -> None:
    """Remember who's in your X timelines (Discover) and who they are (profiles)."""
    rows, mentions = [], []
    for p in posts:
        if p["source"] != "x" or p.get("via") not in ("following", "foryou"):
            continue
        tid = p["id"].split(":", 1)[1]
        rows.append((p["author"], p["via"], tid, None))
        if p["via"] == "following":
            mentions += [(h, "mention", tid, p["author"]) for h in p.get("mentions") or []]
    try:
        with db() as conn:
            conn.executemany("INSERT OR IGNORE INTO x_seen(handle, kind, post, by) VALUES (?, ?, ?, ?)", rows + mentions)
            for u in users:
                if u.get("handle"):
                    conn.execute("INSERT INTO x_users(handle, nick, bio, location, followers, following, posts, image_url, updated_at)"
                                 " VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now')) ON CONFLICT(handle) DO UPDATE SET"
                                 " nick = excluded.nick, bio = excluded.bio, location = excluded.location, followers = excluded.followers,"
                                 " following = excluded.following, posts = excluded.posts, image_url = excluded.image_url,"
                                 " updated_at = excluded.updated_at",
                                 (u["handle"], u.get("nick"), u.get("bio"), u.get("location"), u.get("followers"),
                                  u.get("following"), u.get("posts"), u.get("image_url")))
            conn.execute("DELETE FROM x_seen WHERE at < datetime('now', ?)", (f"-{X_SEEN_DAYS} days",))
    except sqlite3.OperationalError:     # the follow service hasn't made the tables yet
        pass


def _mark_saved(posts: list[dict]) -> list[dict]:
    if not posts:
        return posts
    try:
        with db() as conn:
            ids = {r[0] for r in conn.execute(f"SELECT id FROM saved_posts WHERE status != 'removed' AND id IN ({','.join('?' * len(posts))})",
                                              [p["id"] for p in posts])}
    except sqlite3.OperationalError:
        ids = set()
    for p in posts:
        p["saved"] = p["id"] in ids or (p["source"] == "reddit" and p.get("saved", False))
    return posts


SHOWN_AGAIN = 1800        # seconds a post can be shown again (paging back, reloading); after, it's passed over
SHOWN_DAYS = 14           # how long what you were shown is remembered
FRESH_MIN = 6             # For you reads further (FRESH_READS pages at most) until it has this many new posts
FRESH_READS = 3


def _stale(ids) -> set:
    """Those of ids shown to you more than SHOWN_AGAIN ago."""
    ids = list(dict.fromkeys(ids))
    if not ids:
        return set()
    with db() as conn:
        return {r[0] for r in conn.execute(f"SELECT id FROM shown WHERE at < ? AND id IN ({','.join('?' * len(ids))})",
                                           [time.time() - SHOWN_AGAIN, *ids])}


def _now_shown(posts: list[dict]) -> None:
    now = time.time()
    with db() as conn:
        conn.executemany("INSERT OR IGNORE INTO shown (id, at) VALUES (?, ?)", [(p["id"], now) for p in posts])
        conn.execute("DELETE FROM shown WHERE at < ?", (now - SHOWN_DAYS * 86400,))
        conn.commit()


def _unshown(posts: list[dict]) -> list[dict]:
    """posts without those you were shown before (more than SHOWN_AGAIN ago); the rest noted as shown."""
    old = _stale(p["id"] for p in posts)
    out = [p for p in posts if p["id"] not in old]
    _now_shown(out)
    return out



def _num(v, lo: float, hi: float, what: str) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number")
    if not lo <= x <= hi:
        raise ValueError(f"{what} must be between {lo:g} and {hi:g}")
    return round(x, 3)


SITE_STATE: dict[str, dict] = {}     # site -> {"at", "error"}: how its last reading went (Health)


def follow_posts(source: str, cursor: str, mode: str = "following", tags: str = "") -> dict:
    """A page of the Feed, live from the sites (livefeeds). tags: e621 only shows posts with
    these tags (e.g. "anal" or "anal canine")."""
    picked = source.split(",")
    if not (source == "all" or picked and all(s in FEED_SOURCES for s in picked)) or mode not in FEED_MODES:
        raise ValueError("bad source")
    tags = " ".join(tags.split())
    if tags:
        e621.query(tags)            # a search e621 and dreamfeed take (raises ValueError)
    s = follow_settings(subscribed=False)
    d = livefeeds.feed(mode, source, _cursor(cursor), s["reddit"]["follow"], s["e621"]["searches"], tags)
    for site in (FEED_SOURCES if source == "all" else picked):     # (Health: each site's last answer)
        SITE_STATE[site] = {"at": time.time(), "error": d["errors"].get(site)}
    _seen(d["posts"], d["users"])
    d = {**d, "posts": mutes.posts(d["posts"])}        # (your mute list)
    if mode == "foryou":            # something new each time: what you were shown before is passed over
        posts, reads = _unshown(d["posts"]), 1
        while len(posts) < FRESH_MIN and d["more"] and reads < FRESH_READS:
            more = livefeeds.feed(mode, source, d["cursor"], s["reddit"]["follow"], s["e621"]["searches"], tags)
            _seen(more["posts"], more["users"])
            have = {p["id"] for p in posts}
            posts += [p for p in _unshown(mutes.posts(more["posts"])) if p["id"] not in have]
            d = {**more, "errors": {**d["errors"], **more["errors"]}}
            reads += 1
        d = {**d, "posts": posts}
    nxt = base64.urlsafe_b64encode(json.dumps(d["cursor"]).encode()).decode().rstrip("=") if d["more"] else None
    return {"posts": _mark_saved(d["posts"]), "more": d["more"], "cursor": nxt, "errors": d["errors"]}


SUBREDDIT = re.compile(r"^(?:/?r/)?([A-Za-z0-9_]{2,21})/?$")
BROWSE_SORTS = {"hot": "/hot", "new": "/new", "top": "/top?t=day"}


# A random subreddit (Browse's 🎲): from a list of names, one a line (RANDOM_SUBREDDITS_URL, an
# https address of a text file; read again each day). Off when it's not set.
RANDOM_SUBS_URL = os.environ.get("RANDOM_SUBREDDITS_URL", "").strip()
RANDOM_TRIES = 6           # banned, private or empty ones are passed over


def _random_names() -> list[str]:
    def fetch():
        import urllib.request
        if not RANDOM_SUBS_URL.startswith("https://"):
            raise ValueError("RANDOM_SUBREDDITS_URL isn't an https address")
        req = urllib.request.Request(RANDOM_SUBS_URL, headers={"User-Agent": "dreamfeed (random subreddit list)"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                text = r.read(4 << 20).decode("utf-8", "replace")
        except OSError as e:
            raise LookupError(f"the subreddit list didn't load ({e})")
        names = {}
        for line in text.splitlines():
            n = line.strip().removeprefix("r/").removeprefix("/r/").strip("/")
            if SUBREDDIT.match(n) and not livefeeds.place_blocked(n):      # (the usual rules still apply)
                names.setdefault(n.lower(), n)
        return list(names.values())
    return _cached("random-subs", 86400, fetch)


def random_subreddit(avoid: str = "") -> dict:
    """{"sub"}: a random one from the list that has posts to show now."""
    import random
    if not RANDOM_SUBS_URL:
        raise ValueError("no subreddit list set up (RANDOM_SUBREDDITS_URL)")
    names = [n for n in _random_names() if n.lower() != avoid.lower()]
    if not names:
        raise LookupError("the subreddit list is empty")
    for name in random.sample(names, min(RANDOM_TRIES, len(names))):
        try:
            posts, _ = livefeeds.reddit_page(f"/r/{name}/hot", None, "browse")   # (kept: Browse shows it at once)
        except LookupError:
            continue
        if posts:
            return {"sub": name}
    raise LookupError("no luck this time: try again")


def browse(sub: str, sort: str, after: str) -> dict:
    """Browse now: a subreddit as it is now, REDDIT_PAGE posts at a time (live)."""
    m = SUBREDDIT.match(sub.strip())
    if not m or sort not in BROWSE_SORTS:
        raise ValueError("a subreddit's name, like r/yiff")
    sub = m.group(1)
    if livefeeds.place_blocked(sub):
        raise ValueError("not a subreddit dreamfeed reads")
    posts, nxt = livefeeds.reddit_page(f"/r/{sub}{BROWSE_SORTS[sort]}", after or None, "browse")
    r = mutes.rules()             # (your mute list: its people and words; a muted subreddit you open still shows)
    posts = [p for p in posts if not mutes.post_muted(p, {**r, "subs": set()})]
    if not after:
        with db() as conn:
            conn.execute("DELETE FROM browses WHERE lower(sub) = lower(?) AND sort = ?", (sub, sort))
            conn.execute("INSERT INTO browses(sub, sort, status) VALUES (?, ?, 'done')", (sub, sort))
            conn.execute("DELETE FROM browses WHERE id NOT IN (SELECT id FROM browses ORDER BY id DESC LIMIT 30)")
    return {"sub": sub, "sort": sort, "posts": _mark_saved(posts), "after": nxt}


def recent_browses() -> dict:
    with db() as conn:
        rows = conn.execute("SELECT sub, sort, id, created_at AS at FROM browses WHERE status != 'failed'"
                            " ORDER BY id DESC LIMIT 8").fetchall()
    return {"browses": [dict(r) for r in rows]}


def person_posts(source: str, handle: str, cursor: str) -> dict:
    """An X account's latest media, a Reddit user's latest posts or an e621 artist's, live (their profile)."""
    if source == "x":
        m = X_HANDLE.match(handle.strip())
        if not m:
            raise ValueError("bad X handle")
        page = livefeeds.x_page("@" + m.group(1), int(cursor or 1))
        _seen([], [u for u in page["users"] if u["handle"].lower() == m.group(1).lower()])
        posts = [p for p in page["posts"] if p["author"].lower() == m.group(1).lower()]
        nxt = page["next"]
    elif source == "reddit":
        m = REDDIT_USER.match(handle.strip())
        if not m:
            raise ValueError("bad Reddit username")
        posts, nxt = livefeeds.reddit_page(livefeeds.user_path(m.group(1)), cursor or None, "profile")
    elif source == "e621":
        name = handle.strip().lower()
        if not e621.ARTIST.match(name):
            raise ValueError("bad e621 artist")
        try:
            posts, nxt = livefeeds.e621_page(name, int(cursor) if cursor.isdigit() else None)
        except OSError as e:
            raise LookupError(f"e621 didn't answer ({e})")
    elif source == "bsky":
        h = handle.strip().lstrip("@")
        if not livefeeds.BSKY_HANDLE.match(h):
            raise ValueError("bad Bluesky handle")
        posts, nxt = livefeeds.bsky_page("@" + h, cursor or None)
    else:
        raise ValueError("bad source")
    return {"posts": _mark_saved(posts), "cursor": str(nxt) if nxt else None}


def save_post(req: dict) -> dict:
    """{"post": {...}, "save": bool}: keep a post in Saved (as it was shown); a Reddit post is
    saved on Reddit too, an e621 one favorited (signed in)."""
    p, save = req.get("post") or {}, bool(req.get("save"))
    pid = str(p.get("id") or "")
    m = livefeeds.POST_ID.fullmatch(pid)
    if not m or p.get("source") != m.group(1) or not isinstance(p.get("media"), list):
        raise ValueError("bad post")
    sync = None
    if m.group(1) == "reddit":
        try:
            livefeeds.reddit_save(m.group(2), save)
            sync = {"status": "done"}
        except (LookupError, ValueError) as e:
            sync = {"status": "failed", "error": str(e)}
    elif m.group(1) == "e621" and e621.creds() and m.group(2).isdigit():
        try:
            e621.favorite(m.group(2), save)
            sync = {"status": "done"}
        except (LookupError, OSError) as e:
            sync = {"status": "failed", "error": str(e)[:200]}
    media = []
    for x in p["media"][:livefeeds.MAX_GALLERY]:
        if not isinstance(x, dict) or x.get("kind") not in ("image", "video", "hls"):
            raise ValueError("bad post")
        item = {k: x[k] for k in ("kind", "url", "full", "poster", "fallback") if isinstance(x.get(k), str) and x[k]}
        if any(not savedposts.allowed(item[k]) for k in ("url", "full", "poster", "fallback") if k in item) or "url" not in item:
            raise ValueError("not a site's media address")
        media.append(item)
    keep = {k: p.get(k) for k in ("id", "source", "author", "nick", "avatar", "place", "text", "posted_at", "link")}
    keep["media"] = media
    with db() as conn:
        if save:      # (saved again while kept: left as it is)
            conn.execute("INSERT INTO saved_posts(id, source, data) VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET"
                         " data = excluded.data, status = 'queued', error = NULL, files = NULL, saved_at = datetime('now')"
                         " WHERE saved_posts.status = 'removed'", (pid, m.group(1), json.dumps(keep)[:200_000]))
        else:         # kept as removed, so an import of what you saved on the site doesn't bring it back
            conn.execute("UPDATE saved_posts SET status = 'removed', files = NULL, error = NULL WHERE id = ?", (pid,))
            shutil.rmtree(savedposts.folder(DATA, pid), ignore_errors=True)
        r = conn.execute("SELECT status, error FROM saved_posts WHERE id = ? AND status != 'removed'", (pid,)).fetchone()
    return {"saved": save, "sync": sync, "keep": dict(r) if r else None}


_import = {"running": False, "at": None, "x": None, "bsky": None, "reddit": None, "e621": None}
_import_lock = threading.Lock()
IMPORT_SITES = ("x", "bsky", "reddit", "e621")      # (what Saved's import can read)


def e621_vote(req: dict) -> dict:
    """{"id": "e621:ID", "score": 1 | -1}: vote on it as you (the same again takes it back)."""
    m = re.fullmatch(r"e621:(\d{1,12})", str(req.get("id", "")))
    score = req.get("score")
    if not m or score not in (1, -1):
        raise ValueError("bad vote")
    return e621.vote(m.group(1), score)


def import_saved(req: dict) -> dict:
    """{"sites": ["x", "bsky", "reddit", "e621"] (those to read; all when not given)}: bring what
    you saved on them into Saved: your X and Bluesky bookmarks, your Reddit saved posts and your
    e621 favorites (with pictures or videos), their files then kept like any you save here. Ones
    you unsaved here stay out. In the background; GET /api/saved/import says how it went."""
    sites = req.get("sites", list(IMPORT_SITES))
    if not isinstance(sites, list) or not sites or any(s not in IMPORT_SITES for s in sites):
        raise ValueError("pick the sites to bring in")
    with _import_lock:
        if _import["running"]:
            return dict(_import)
        _import.update(running=True, **{s: None for s in IMPORT_SITES})
    threading.Thread(target=_run_import, args=([s for s in IMPORT_SITES if s in sites],), daemon=True).start()
    return dict(_import)


def _run_import(sites: list[str]) -> None:
    readers = {"x": livefeeds.x_bookmarks, "bsky": livefeeds.bsky_saved, "reddit": livefeeds.reddit_saved,
               "e621": livefeeds.e621_favorites}
    try:
        for source in sites:
            read = readers[source]
            if source == "bsky" and not livefeeds.bsky_ready():
                _import["bsky"] = {"error": "Bluesky isn't signed in"}
                continue
            if source == "reddit" and not livefeeds.reddit_ready():
                _import["reddit"] = {"error": "Reddit isn't signed in"}
                continue
            if source == "e621" and not e621.creds():
                _import["e621"] = {"error": "e621 isn't signed in"}
                continue
            try:
                posts = read()
            except (LookupError, OSError, ValueError) as e:
                _import[source] = {"error": str(e)[:300]}
                continue
            added = 0
            with db() as conn:
                # saved when you saved it on the site (X's and Bluesky's bookmarks say when); else now,
                # each a second older than the one before, so they keep the site's order
                for n, p in enumerate(posts):
                    keep = {k: p.get(k) for k in ("id", "source", "author", "nick", "avatar", "place", "text", "posted_at", "link", "media")}
                    when = p.get("saved_at") if re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", str(p.get("saved_at") or "")) else None
                    added += conn.execute("INSERT INTO saved_posts(id, source, data, saved_at) VALUES (?, ?, ?, coalesce(?, datetime('now', ?)))"
                                          " ON CONFLICT(id) DO NOTHING", (p["id"], source, json.dumps(keep)[:200_000], when, f"-{n} seconds")).rowcount
            _import[source] = {"found": len(posts), "added": added}
    finally:
        _import.update(running=False, at=time.strftime("%Y-%m-%d %H:%M:%S"))


def import_status() -> dict:
    with db() as conn:
        counts = {r["status"]: r["n"] for r in conn.execute("SELECT status, count(*) AS n FROM saved_posts GROUP BY status")}
    return {**_import, "files": counts}


def _saved_json(r) -> dict:
    """A saved post as Saved shows it: from its kept files once they're downloaded."""
    p = {**json.loads(r["data"]), "saved": True, "keep": {"status": r["status"], "error": r["error"]}}
    if r["status"] == "done" and r["files"]:
        base = "saved-media/" + "/".join(savedposts.folder(Path("."), r["id"]).parts[1:]) + "/"
        p["media"] = [{"kind": f["kind"], "url": base + f["file"], "poster": base + f["poster"] if f.get("poster") else None}
                      for f in json.loads(r["files"])]
    return p


VIDEO_KINDS = ("video", "hls")
MORE_VIDEOS = 8            # videos a page of More videos (several listing pages read for them, at most MORE_READS)
MORE_READS = 4


def more_videos(post_id: str, cursor: str) -> dict:
    """More videos after a Reddit or e621 post (the Reddit app's swipe-up feed, rebuilt from the
    public API): Reddit, more from its subreddit (hot, then the week's top), then from your
    subscriptions and the Dashboard's subreddits, newest first; e621, more of the search it came
    from (or its artist), then the Dashboard's searches. Videos only. {"posts", "cursor"}."""
    m = re.fullmatch(r"(reddit|e621|bsky):([A-Za-z0-9_]{1,60})", post_id or "")
    if not m:
        raise ValueError("bad post")
    site = m.group(1)
    c = _cursor(cursor) or {}
    if not c:                                  # the first page: what the post itself says where to look
        p = one_post(post_id)["post"]
        if site == "bsky":           # theirs, then Bluesky's own Video feed, then your timeline's
            who = p.get("author") or ""
            stages = ([["bsky-author", who]] if livefeeds.BSKY_HANDLE.match(who) else []) + [["bsky-feed", ""], ["bsky-home", ""]]
        elif site == "reddit":
            sub = p.get("place") or ""
            # its subreddit's listings in a different order each time (hot, new, the week's and month's top)
            lists = [f"/r/{sub}/{x}" for x in random.sample(["hot", "new", "top?t=week", "top?t=month"], 4)]
            stages = ([["sub", x] for x in lists] if SUBREDDIT.match(sub) else []) + [["subs", ""]]
        else:
            first = p.get("place") or ((p.get("artists") or [""])[0])
            stages = [["e621", q] for q in dict.fromkeys([first] + follow_settings(subscribed=False)["e621"]["searches"]) if q]
        c = {"stages": stages, "i": 0, "at": None, "seen": [post_id]}
    stages = c.get("stages") or []
    ok = {"bsky-author": livefeeds.BSKY_HANDLE, "bsky-feed": re.compile(r"^$"), "bsky-home": re.compile(r"^$"),
          "sub": re.compile(r"^/r/[A-Za-z0-9_]{2,21}/(?:hot|new|top\?t=week|top\?t=month)$"), "subs": re.compile(r"^$"), "e621": re.compile(r"^.{1,300}$")}
    if (not isinstance(stages, list) or len(stages) > 40 or not isinstance(c.get("i"), int)
            or any(not (isinstance(x, list) and len(x) == 2 and x[0] in ok and isinstance(x[1], str) and ok[x[0]].match(x[1]))
                   for x in stages)
            or (site == "e621") != all(x[0] == "e621" for x in stages)
            or (site == "bsky") != all(x[0].startswith("bsky-") for x in stages)):
        raise ValueError("bad cursor")      # (it comes back from the page: only what this made)
    at = c.get("at")
    if at is not None and not (isinstance(at, int) if site == "e621" else isinstance(at, str) and len(at) < 1000 if site == "bsky"
                               else isinstance(at, str) and re.fullmatch(r"t3_\w{1,20}", at)):
        raise ValueError("bad cursor")
    out, reads, seen = [], 0, set(str(x) for x in (c.get("seen") or [])[:300])
    while c["i"] < len(stages) and len(out) < MORE_VIDEOS and reads < MORE_READS:
        kind, where = stages[c["i"]]
        reads += 1
        try:
            if kind == "e621":
                posts, nxt = livefeeds.e621_page(f"{where} ~type:webm ~type:mp4", c["at"])
            elif kind.startswith("bsky-"):
                try:
                    posts, nxt = livefeeds.bsky_videos(kind[5:], where, c["at"])
                except LookupError:      # (a feed that won't load: on to the next)
                    posts, nxt = [], None
            else:
                if kind == "subs":
                    s = follow_settings()
                    subs = set(s["reddit"]["subscribed"]) | set(s["reddit"]["follow"])
                    rs = sorted({w[2:] for w in subs if w.startswith("r/") and not livefeeds.place_blocked(w[2:])}, key=str.lower)
                    if not rs:
                        c.update(i=c["i"] + 1, at=None); continue
                    where = "/r/" + "+".join(rs[:250]) + "/new"
                posts, nxt = livefeeds.reddit_page(where, c["at"], "videos")
        except ValueError:               # (a search dreamfeed won't run)
            posts, nxt = [], None
        old = _stale(p["id"] for p in posts)          # (shown to you before: passed over)
        for p in posts:
            if (p["id"] not in seen and p["id"] not in old and any(x.get("kind") in VIDEO_KINDS for x in p["media"])
                    and not mutes.post_muted(p)):
                if kind == "e621":
                    p = {**p, "place": where}
                seen.add(p["id"]); out.append(p)
        if nxt:
            c["at"] = nxt
        else:
            c.update(i=c["i"] + 1, at=None)
    c["seen"] = list(seen)[-300:]
    _now_shown(out)
    more = c["i"] < len(stages)
    return {"posts": _mark_saved(out), "cursor": base64.urlsafe_b64encode(json.dumps(c).encode()).decode().rstrip("=") if more else None}


def one_post(post_id: str) -> dict:
    """A post's own page: a post you saved (from its kept copy), else live from its site."""
    with db() as conn:
        r = conn.execute("SELECT * FROM saved_posts WHERE id = ? AND status != 'removed'", (post_id,)).fetchone()
    if r:
        return {"post": _saved_json(r)}
    try:
        found = livefeeds.post(post_id)
    except OSError as e:
        raise LookupError(f"the site didn't answer ({e})")
    if not found:
        raise LookupError("that post isn't there any more (or dreamfeed leaves it out)")
    return {"post": _mark_saved([found])[0]}


def saved_file(rel: str) -> Path | None:
    from urllib.parse import unquote
    root = (DATA / "saved").resolve()
    path = (root / unquote(rel)).resolve()
    return path if path.is_relative_to(root) and path.is_file() and not path.name.startswith(".") else None


def _xuser(u) -> dict:
    return {"handle": u["handle"], "nick": u["nick"], "bio": u["bio"], "location": u["location"], "followers": u["followers"],
            "following": u["following"], "posts": u["posts"], "avatar": u["image_url"] or None}
