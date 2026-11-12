"""X: gallery-dl with your cookies (the Dashboard's Sign-ins, or X_COOKIES), its metadata only
(-j): your Following, X's For you, anyone's media tab, replies, your bookmarks, and X's own
swipe-up video feed (ImmersiveMedia).

These are real people: nothing here goes to training, styles, comics or generation.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys

from .common import MAX_COMMENTS, _cached, _comment, text_blocked


X_HOME = "https://x.com/home"         # your Following timeline; + "/for-you": X's For you
X_HANDLE = re.compile(r"^[A-Za-z0-9_]{1,15}$")


X_PAGE = 30            # media files read from X a page (a post can have several)


def x_cookies() -> str | None:
    """Your X cookies: the dashboard's (Sign-ins), else the mounted X_COOKIES file."""
    from ..core import cookies
    p = cookies.path("x", os.environ.get("X_COOKIES", "").strip() or None)
    return str(p) if p else None


# ---- X ----
# gallery-dl as the X reader, with each video's other sizes and its preview picture kept in the
# metadata too (gallery-dl itself names only the biggest file, up to 4K: slow on a phone).
X_RUNNER = """
import sys
from gallery_dl.extractor import twitter
_source = twitter.TwitterExtractor._extract_media_source
def _more(self, dest, media):
    _source(self, dest, media)
    info = media.get("video_info") or {}
    dest["variants"] = [{"url": v.get("url"), "bitrate": v.get("bitrate"), "type": v.get("content_type")}
                        for v in info.get("variants") or []]
    dest["poster_url"] = media.get("media_url_https")
twitter.TwitterExtractor._extract_media_source = _more
import gallery_dl
sys.argv = ["gallery-dl"] + sys.argv[1:]
sys.exit(gallery_dl.main())
"""
X_VIDEO_BITRATE = 2_500_000   # the biggest MP4 at or under this (about 720p); the smallest if none is


def _x_video(url: str, md: dict) -> str:
    mp4s = [v for v in md.get("variants") or [] if v.get("type") == "video/mp4" and v.get("url") and v.get("bitrate")]
    fits = [v for v in mp4s if v["bitrate"] <= X_VIDEO_BITRATE]
    pick = max(fits, key=lambda v: v["bitrate"]) if fits else min(mp4s, key=lambda v: v["bitrate"], default=None)
    return pick["url"] if pick else url


def _x(url: str, start: int, count: int, timeout: int = 90, options: tuple = ()) -> list:
    if not x_cookies():
        raise LookupError("X isn't signed in (add your X cookies on the dashboard: Sign-ins)")
    try:
        out = subprocess.run([sys.executable, "-c", X_RUNNER, "--config-ignore", "--cookies", x_cookies(), "-o", "cookies-update=false",
                              *[a for o in options for a in ("-o", o)],
                              "--range", f"{start}-{start + count - 1}", "-j", url],
                             capture_output=True, text=True, timeout=timeout)
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
                              "via": via, "saved": False, "media": [], "comments": md.get("reply_count"),
                              "mentions": sorted({n for n in named if n and n.lower() != a["name"].lower()})}
            if md.get("date_bookmarked"):           # your bookmarks: when you bookmarked it (UTC)
                p["saved_at"] = str(md["date_bookmarked"])[:19]
        ext = str(md.get("extension") or "").lower()
        if not str(url).startswith("https://"):
            continue
        if ext in ("mp4", "webm", "mov", "m4v"):
            p["media"].append({"kind": "video", "url": _x_video(url, md), "full": url, "poster": md.get("poster_url") or None})
        elif ext in ("jpg", "jpeg", "png", "webp", "gif"):
            p["media"].append({"kind": "image", "url": url.replace("name=orig", "name=large"), "full": url})
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


# ---- X's "more videos" (its full-screen player's swipe-up feed) ----
# X's own web app asks this for the videos after one you watch full screen (its ImmersiveMedia
# call). Read as you, through gallery-dl's signed-in connection, like the rest of X here.
# X changes these ids now and then: X_RELATED_QUERY overrides the one known to work.
X_RELATED_QUERY = os.environ.get("X_RELATED_QUERY", "").strip() or "knKMRvWHvFkNPnuaEfjEvw"
X_RELATED_FEATURES = {
    "rweb_video_screen_enabled": False, "responsive_web_graphql_timeline_navigation_enabled": True,
    "view_counts_everywhere_api_enabled": True, "longform_notetweets_consumption_enabled": True,
    "creator_subscriptions_tweet_preview_api_enabled": True, "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True, "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True, "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True, "articles_preview_enabled": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True, "verified_phone_label_enabled": False,
    "responsive_web_twitter_article_tweet_consumption_enabled": True, "longform_notetweets_inline_media_enabled": False,
}
X_RELATED_RUNNER = """
import json, sys
from gallery_dl import config, extractor
cookies, query, tid, handle, cursor, feats = sys.argv[1:7]
config.set(("extractor",), "cookies", cookies)
config.set(("extractor",), "cookies-update", False)
ex = extractor.find(f"https://x.com/{handle or 'i'}/status/{tid}")
ex.initialize()
v = {"pinned_tweet_id": tid, "page_name": handle, "includePromotedContent": False}
if cursor:
    v["cursor"] = cursor
print(json.dumps(ex.api._call(f"/graphql/{query}/ImmersiveMedia", {"variables": json.dumps(v), "features": feats})))
"""


def _x_related_post(r: dict) -> dict | None:
    """One post of X's related feed, as the Feed shows it (videos only), or None."""
    r = r.get("tweet") or r                       # (TweetWithVisibilityResults)
    leg, user = r.get("legacy") or {}, ((r.get("core") or {}).get("user_results") or {}).get("result") or {}
    handle = (user.get("core") or {}).get("screen_name") or (user.get("legacy") or {}).get("screen_name")
    tid = r.get("rest_id")
    if not tid or not handle or text_blocked(leg.get("full_text")):
        return None
    media = []
    for m in (leg.get("extended_entities") or {}).get("media") or []:
        if m.get("type") not in ("video", "animated_gif"):
            continue
        variants = [{"url": v.get("url"), "bitrate": v.get("bitrate"), "type": v.get("content_type")}
                    for v in (m.get("video_info") or {}).get("variants") or []]
        best = max((v for v in variants if v["type"] == "video/mp4" and v["url"]), key=lambda v: v.get("bitrate") or 0, default=None)
        if best:
            media.append({"kind": "video", "url": _x_video(best["url"], {"variants": variants}), "full": best["url"],
                          "poster": m.get("media_url_https")})
    if not media:
        return None
    try:
        when = dt.datetime.strptime(leg.get("created_at", ""), "%a %b %d %H:%M:%S %z %Y").astimezone(dt.timezone.utc)
        when = when.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        when = ""
    text = re.sub(r"\s*https://t\.co/\w+$", "", leg.get("full_text") or "")
    return {"id": f"x:{tid}", "source": "x", "author": handle, "nick": (user.get("core") or {}).get("name"),
            "avatar": (user.get("avatar") or {}).get("image_url"), "place": None, "text": text, "posted_at": when,
            "link": f"https://x.com/{handle}/status/{tid}", "via": "related", "saved": False, "media": media,
            "comments": leg.get("reply_count"), "likes": leg.get("favorite_count"),
            "views": int((r.get("views") or {}).get("count") or 0) or None}


def x_related(tid: str, handle: str, cursor: str = "") -> dict:
    """The videos X shows after this one in its full-screen player: {"posts", "cursor"}."""
    if not re.fullmatch(r"\d{5,25}", tid or "") or (handle and not X_HANDLE.match(handle)) or len(cursor) > 2000:
        raise ValueError("bad post")
    if not x_cookies():
        raise LookupError("X isn't signed in (add your X cookies on the dashboard: Sign-ins)")
    def fetch():
        try:
            out = subprocess.run([sys.executable, "-c", X_RELATED_RUNNER, x_cookies(), X_RELATED_QUERY, tid, handle, cursor,
                                  json.dumps(X_RELATED_FEATURES)], capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired as e:
            raise LookupError("X took too long") from e
        try:
            d = json.loads(out.stdout)
        except ValueError as e:
            err = (out.stderr or "").strip().splitlines()
            raise LookupError(f"X didn't give its video feed ({err[-1][:160] if err else 'nothing came back'})") from e
        posts, nxt, seen = [], None, set()
        def walk(o, depth=0):
            nonlocal nxt
            if depth > 40:
                return
            if isinstance(o, dict):
                if "tweet_results" in o:
                    p = _x_related_post((o["tweet_results"] or {}).get("result") or {})
                    if p and p["id"] not in seen and p["id"] != f"x:{tid}":
                        seen.add(p["id"]); posts.append(p)
                    return
                if o.get("cursorType") == "Bottom" and o.get("value"):
                    nxt = o["value"]
                for v in o.values():
                    walk(v, depth + 1)
            elif isinstance(o, list):
                for v in o:
                    walk(v, depth + 1)
        walk(d.get("data") or {})
        if not posts and d.get("errors"):
            raise LookupError(f"X said: {str(d['errors'][0].get('message'))[:160]}")
        return {"posts": posts, "cursor": nxt if posts else None}
    return _cached(f"x-related:{tid}:{cursor}", fetch)


def _x_comments(tid: str) -> list[dict]:
    """The replies under a post (gallery-dl's conversation of it), nested by what each answers."""
    items = _x(f"https://x.com/i/web/status/{tid}", 1, MAX_COMMENTS, timeout=60,
               options=("conversations=true", "text-tweets=true", "replies=true", "retweets=false", "quoted=false"))
    tweets: dict[str, dict] = {}
    parent: dict[str, str] = {}
    for it in items:
        if not isinstance(it, list) or len(it) < 2 or it[0] not in (2, 3):
            continue
        md = it[-1] if isinstance(it[-1], dict) else {}
        t = str(md.get("tweet_id") or "")
        a = md.get("author") or {}
        if not t or t == tid or not a.get("name"):
            continue
        if t not in tweets:
            if text_blocked(md.get("content")):
                tweets[t] = None
                continue
            text = re.sub(r"^(?:@\w{1,15}\s+)+", "", md.get("content") or "")     # (the @names it answers, as X hides them)
            tweets[t] = _comment(t, a["name"], text, str(md.get("date") or ""), md.get("favorite_count"),
                                 a.get("profile_image"))
            parent[t] = str(md.get("reply_id") or "")
        url = it[1] if it[0] == 3 else ""
        if tweets.get(t) is not None and isinstance(url, str) and url.startswith("https://pbs.twimg.com/"):
            tweets[t]["media"].append(url.replace("name=orig", "name=small"))
    top = []
    for t, c in tweets.items():
        if c is None:
            continue
        up = tweets.get(parent.get(t, ""))
        (up["replies"] if up else top).append(c)
    top.sort(key=lambda c: -(c["score"] or 0))
    return top


# ---- what you saved on the sites (Saved's import) ----
def x_bookmarks() -> list[dict]:
    """Your X bookmarks with pictures or videos, newest first (all of them)."""
    posts, _, _ = _x_posts(_x("https://x.com/i/bookmarks", 1, 20000, timeout=1800), "saved")
    return posts
