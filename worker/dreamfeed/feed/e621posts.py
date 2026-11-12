"""e621's posts as the Feed shows them (the API itself: e621.py): the Dashboard's searches,
their best of the day, your taste, your favorites, an artist's page, comments.

These are real people: nothing here goes to training, styles, comics or generation.
"""
import datetime as dt
import re
from . import e621

from .common import MAX_COMMENTS, WHO_TTL, _cached, _comment, text_blocked


E621_PAGE = 20


# ---- e621 ----
def _e621_full(p: dict, kind: str) -> str | None:
    """The original file (a video's full-size MP4 when e621 has one: originals are often WebM,
    which iPhones don't play)."""
    if kind == "video":
        mp4 = ((((p.get("sample") or {}).get("alternates") or {}).get("variants") or {}).get("mp4") or {}).get("url")
        if mp4:
            return mp4
    return (p.get("file") or {}).get("url")


TOP_TODAY = "order:score date:day"      # For you: the best rated of the last 24 hours
TOP_WEEK = "order:score date:week"      # (your taste's artists: the week's, as they post less often)


def _e621_post(p: dict, place: str, top: bool = False) -> dict | None:
    """One e621 post as the Feed shows it, or None when it's left out."""
    got = e621.media(p)
    if e621.blocked(p) or not got or text_blocked(p.get("description")) or e621.blacklisted(p):    # (and your own blacklist)
        return None
    d = e621.details(p)
    kind = "video" if got[1] in ("mp4", "webm") else "image"
    sample = p.get("sample") or {}
    prev = sample.get("url") or (p.get("preview") or {}).get("url")
    # a picture shows e621's 850px copy (the original is often 5-20 MB): the original is
    # what Save keeps. A GIF's copy is a still, so it shows itself.
    shown = sample["url"] if kind == "image" and got[1] != "gif" and sample.get("has") and sample.get("url") else got[0]
    return {"id": f"e621:{d['id']}", "source": "e621", "author": d["author"], "artists": d["artists"],
            "place": place, "text": d["title"], "posted_at": d["date"], "link": d["link"],
            "via": "foryou" if top else "following", "saved": False,
            "score": ((p.get("score") or {}).get("total") or 0), "comments": p.get("comment_count"),
            "votable": bool(e621.creds()),
            "media": [{"kind": kind, "url": shown, "full": _e621_full(p, kind) or got[0],
                       "poster": prev if kind == "video" else None}]}


def e621_page(search: str, at: int | None, top: bool = False, window: str = TOP_TODAY) -> tuple[list[dict], int | None]:
    """A page of an e621 tag search: the newest (at: the post id the page starts below), or
    with top, the best rated in window (the last 24 hours; at: the page number)."""
    def fetch():
        params = {"tags": e621.query(f"{search} {window}" if top else search), "limit": E621_PAGE}
        if at:
            params["page"] = str(at) if top else f"b{at}"
        found = e621.get("/posts.json", params).get("posts") or []
        out = [x for x in (_e621_post(p, search, top) for p in found) if x]
        if len(found) < E621_PAGE:
            return out, None
        if top:
            return out, (at or 1) + 1
        return out, min((int(p["id"]) for p in found if str(p.get("id", "")).isdigit()), default=None)
    return _cached(f"e621:{top}:{window}:{search}:{at}", fetch)


def e621_taste_searches() -> list[tuple[str, str, str]]:
    """For you's searches from your taste (signed in): [(search, window, what it's called)]: the
    artists you favorite and vote up most (the week's best), the species (today's), without
    what you've already favorited."""
    t = e621.taste()
    if not t:
        return []
    out, mine = [], f"-fav:{t['name']}"
    if t["artists"]:
        out.append((" ".join("~" + a for a in t["artists"]) + " " + mine, TOP_WEEK, "artists you like"))
    if t["species"]:
        out.append((" ".join("~" + x for x in t["species"]) + " " + mine, TOP_TODAY, "what you like"))
    return out


def e621_favorites(limit: int = 1000) -> list[dict]:
    """Your e621 favorites as Feed posts (the Saved import), newest favorited first."""
    return [x for x in (_e621_post(p, "your favorites") for p in e621.favorites(limit)) if x]


def e621_artist(name: str) -> dict:
    """Who an e621 artist is, for their profile: {"name", "posts", "other_names", "links"
    (their pages elsewhere, as e621 lists them), "x" (their X handles among those)}."""
    name = name.strip().lower()
    if not e621.ARTIST.match(name):
        raise ValueError("bad e621 artist")
    def fetch():
        found = e621.get("/artists.json", {"search[name]": name, "limit": 1}) or []
        a = found[0] if isinstance(found, list) and found and found[0].get("name") == name else {}
        tag = e621.get("/tags.json", {"search[name]": name, "limit": 1}) or []
        links = [u["url"] for u in a.get("urls") or [] if u.get("is_active") and str(u.get("url", "")).startswith("https://")]
        xs = []
        for u in links:
            m = re.match(r"https://(?:www\.|mobile\.)?(?:twitter|x)\.com/([A-Za-z0-9_]{1,15})/?$", u)
            if m and m.group(1).lower() not in ("home", "i", "intent", "search") and m.group(1).lower() not in xs:
                xs.append(m.group(1).lower())
        return {"name": name, "posts": tag[0].get("post_count") if isinstance(tag, list) and tag else None,
                "other_names": (a.get("other_names") or [])[:10], "links": links[:20], "x": xs[:3]}
    return _cached(f"e621-artist:{name}", fetch, WHO_TTL)


def _e621_comments(pid: str) -> list[dict]:
    d = e621.get("/comments.json", {"group_by": "comment", "search[post_id]": pid, "limit": MAX_COMMENTS})
    rows = d if isinstance(d, list) else []          # (none: {"comments": []})
    rows = [c for c in rows if not c.get("is_hidden") and not text_blocked(c.get("body"))]
    rows.sort(key=lambda c: c.get("created_at") or "")
    out = []
    for c in rows:
        try:
            at = dt.datetime.fromisoformat(c["created_at"]).astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        except (KeyError, ValueError):
            at = ""
        out.append(_comment(c.get("id"), c.get("creator_name"), c.get("body"), at, c.get("score")))
    return out
