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

Each site is its own module (common, x, reddit, redgifs, bsky, e621posts, xvideos);
this one mixes them into the Feed, finds one post and its comments, and passes on what the
rest of dreamfeed uses from them (the web app reads them all as livefeeds.*)."""
import itertools
from concurrent.futures import ThreadPoolExecutor
from . import e621

from .bsky import BSKY_DISCOVER, BSKY_HANDLE, BSKY_VIDEOS, _bsky, _bsky_comments, _bsky_json, _bsky_my_feeds, _bsky_post, _bsky_session, _bsky_uri, bsky_foryou, bsky_page, bsky_ready, bsky_user, bsky_videos  # noqa: F401
from .common import CACHE_TTL, MAX_GALLERY, POST_ID, SITES, SUBS_TTL, WHO_TTL, _cached, _merge, forget, place_blocked, text_blocked  # noqa: F401
from .e621posts import TOP_TODAY, _e621_comments, _e621_post, e621_artist, e621_favorites, e621_page, e621_taste_searches  # noqa: F401
from .reddit import MAX_USERS, REDDIT_AGENT, REDDIT_USER, _reddit, _reddit_comments, _reddit_listing, reddit_page, reddit_ready, reddit_save, reddit_saved, reddit_user, subscriptions, user_path  # noqa: F401
from .redgifs import redgifs_clip, redgifs_page  # noqa: F401
from .x import X_HOME, _x, _x_comments, _x_posts, x_bookmarks, x_cookies, x_page, x_related  # noqa: F401
from .xvideos import xvideos_page  # noqa: F401


def feed(mode: str, source: str, cursor: dict | None, follow: list[str], searches: list[str], tags: str = "") -> dict:
    """A page of the Feed. mode: following (your X Following, your subscriptions and the
    Dashboard's subreddits, its e621 searches, newest first) or foryou (X's For you, Reddit's
    Best, the best rated of the last 24 hours of the Dashboard's e621 searches). tags: e621
    shows only posts with these (instead of the Dashboard's searches).
    cursor: where each site's next page starts ({} for the first); None in it: that site's done.
    {"posts", "users", "cursor", "more", "errors"}."""
    wanted = set(source.split(","))           # (all, or the sites you picked: x,reddit)
    sources = [s for s in SITES if "all" in wanted or s in wanted]
    first = not cursor
    cursor = dict(cursor or {})
    def one(s: str) -> tuple[list[list[dict]], list[dict], object, str | None]:
        """(post lists, X users, where its next page starts, an error) of one site."""
        lists: list[list[dict]] = []
        try:
            if s == "x":
                page = x_page("home" if mode == "following" else "foryou", int(cursor.get("x") or 1))
                return [page["posts"]], page["users"], page["next"], None
            if s == "bsky":
                if not bsky_ready():
                    return [], [], None, None
                if mode == "following":
                    posts, after = bsky_page("home", cursor.get("bsky") or None)
                else:
                    c = cursor.get("bsky")
                    posts, after = bsky_foryou(c if isinstance(c, dict) else None)
                return [posts], [], after, None
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
            qs = [tags] if tags else list(searches)
            windows, labels = {}, {}
            if top and not tags:                # signed in: your taste too (the artists and species you like)
                try:
                    for q, window, label in e621_taste_searches():
                        qs.append(q); windows[q] = window; labels[q] = label
                except (LookupError, OSError, ValueError):
                    pass
            state = cursor.get("e621") or {q: None for q in qs}
            more, groups, refused = {}, [], []
            for q in qs:
                if not first and state.get(q) is None:
                    continue
                try:
                    posts, last = e621_page(q, state.get(q), top, windows.get(q, TOP_TODAY))
                except ValueError as e:         # a search dreamfeed won't run: the others still do
                    refused.append(f"{q}: {e}")
                    continue
                if q in labels:
                    posts = [{**p, "place": labels[q]} for p in posts]
                groups.append(posts)
                more[q] = last
            if top:                             # each search's best first, the searches taken in turns
                groups = [sorted(g, key=lambda p: p["score"], reverse=True) for g in groups]
                got = [p for row in itertools.zip_longest(*groups) for p in row if p]
            else:
                got = [p for g in groups for p in g]
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


# ---- one post, by its id (its own page) ----
def post(post_id: str) -> dict | None:
    """A post as the Feed shows it, live from its site; None when it's gone or left out."""
    m = POST_ID.fullmatch(post_id or "")
    if not m:
        raise ValueError("bad post")
    site, pid = m.groups()
    def fetch():
        if site == "reddit":
            if not reddit_ready():
                raise LookupError("Reddit isn't signed in")
            posts, _ = _reddit_listing(_reddit(f"/api/info?id=t3_{pid}&raw_json=1&sr_detail=1"), "post")
        elif site == "e621":
            found = (e621.get(f"/posts/{pid}.json", {}) or {}).get("post")
            posts = [x for x in [_e621_post(found, "")] if x] if found else []
        elif site == "bsky":
            got = _bsky("app.bsky.feed.getPosts", {"uris": [_bsky_uri(pid)]}).get("posts") or []
            posts = [x for x in (_bsky_post(p, "post") for p in got) if x]
        else:
            posts, _, _ = _x_posts(_x(f"https://x.com/i/web/status/{pid}", 1, 20), "post")
        return next((x for x in posts if x["id"] == post_id), None)
    return _cached(f"post:{post_id}", fetch)


def comments(post_id: str) -> list[dict]:
    """A post's comments, live from its site: [{"id", "author", "avatar", "text", "at", "score",
    "media" (X: pictures in a reply), "replies": [...]}]. Comments whose text has words
    dreamfeed never shows are left out (and their replies with them)."""
    m = POST_ID.fullmatch(post_id or "")
    if not m:
        raise ValueError("bad post")
    site, pid = m.groups()
    read = {"x": _x_comments, "reddit": _reddit_comments, "e621": _e621_comments, "bsky": _bsky_comments}[site]
    if site == "reddit" and not reddit_ready():
        raise LookupError("Reddit isn't signed in")
    return _cached(f"comments:{post_id}", lambda: read(pid))
