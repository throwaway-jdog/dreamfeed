"""A Chaturbate room's public bio, and the X, Reddit and xvideos accounts its performer links there for
free (the follow service reads the rooms you follow once a day; the web app reads a room you
open from Discover). Links that cost tokens are left alone. Standard library only: the web app
uses it too.
"""
import json
import re
import time
import urllib.parse
import urllib.request

SITE = "https://chaturbate.com"
AGENT = "dreamfeed (personal follow list)"
ROOM = re.compile(r"^[a-z0-9_]{1,64}$")
X_LINK = re.compile(r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})(?:[/?\"'<\s]|$)")
# an xvideos profile (model, channel or amateur: they all list their videos at /profiles/NAME)
XVIDEOS_LINK = re.compile(r"https?://(?:[a-z]{2,3}\.|www\.)?xvideos\d*\.(?:com|red|es)/"
                          r"(?:profiles|models|pornstars|channels|amateur-channels|model-channels|pornstar-channels)/"
                          r"([A-Za-z0-9_-]{2,60})(?:[/?#\"'<\s]|$)")
REDGIFS_LINK = re.compile(r"https?://(?:www\.|v3\.)?redgifs\.com/users/([A-Za-z0-9_.-]{2,40})(?:[/?#\"'<\s]|$)")
ONLYFANS_LINK = re.compile(r"https?://(?:www\.)?onlyfans\.com/([A-Za-z0-9_.-]{3,40})(?:[/?#\"'<\s]|$)")
FANSLY_LINK = re.compile(r"https?://(?:www\.)?fansly\.com/([A-Za-z0-9_.-]{3,40})(?:[/?#\"'<\s]|$)")
# pages that list a creator's accounts (followed for more links: linking.py)
LINK_PAGE = re.compile(r"https?://(?:www\.)?(?:linktr\.ee|allmylinks\.com)/([A-Za-z0-9_.-]{2,40})(?:[/?#\"'<\s]|$)")
NOT_NAMES = {"my", "action", "api", "explore", "login", "signup", "terms", "privacy", "help", "search", "home", "about",
             "s", "admin", "settings", "legal", "dmca", "support", "features", "templates", "marketplace", "trial",
             "subscriptions", "live", "post", "posts", "messages", "notifications", "collections", "creators", "tos"}
REDDIT_LINK = re.compile(r"https?://(?:www\.|old\.)?reddit\.com/(?:u|user)/([A-Za-z0-9_-]{3,20})(?:[/?\"'<\s]|$)")
NOT_ACCOUNTS = {"chaturbate", "home", "intent", "share", "i", "search", "hashtag", "explore", "settings", "login"}
GAP = 1.5                     # seconds between requests


def _get(path: str, json_=True):
    time.sleep(GAP)
    req = urllib.request.Request(SITE + path, headers={"User-Agent": AGENT, "Accept": "application/json" if json_ else "text/html"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read(2 << 20)
    return json.loads(data) if json_ else data.decode("utf-8", "replace")


def _page_address(url: str) -> str:
    """A link page's address, one way: https, no www, lower case, nothing after the name."""
    u = urllib.parse.urlparse(url.rstrip("/?#\"'< \t\n"))
    return f"https://{(u.hostname or '').removeprefix('www.')}{u.path.rstrip('/')}".lower()


def _handles(text: str) -> list[tuple[str, str]]:
    found = [("x", h) for h in X_LINK.findall(text) if h.lower() not in NOT_ACCOUNTS]
    found += [("reddit", h) for h in REDDIT_LINK.findall(text)]
    found += [("xvideos", h.lower()) for h in XVIDEOS_LINK.findall(text)]
    found += [("redgifs", h.lower()) for h in REDGIFS_LINK.findall(text)]
    found += [("onlyfans", h.lower()) for h in ONLYFANS_LINK.findall(text) if h.lower() not in NOT_NAMES]
    found += [("fansly", h.lower()) for h in FANSLY_LINK.findall(text) if h.lower() not in NOT_NAMES]
    found += [("linkpage", _page_address(m.group(0))) for m in LINK_PAGE.finditer(text) if m.group(1).lower() not in NOT_NAMES]
    return found


def bio(name: str) -> dict:
    """{"about", "followers", "age", "location", "last_broadcast", "links": [(source, handle)]}."""
    if not ROOM.match(name):
        raise ValueError("bad room")
    d = _get(f"/api/biocontext/{name}/")
    links = _handles(d.get("about_me") or "")
    for s in d.get("social_medias") or []:
        title = str(s.get("title_name") or "").lower()
        link = str(s.get("link") or "")
        if not s.get("is_free") or not title.startswith(("x ", "twitter", "reddit", "xvideos", "onlyfans", "fansly", "redgifs",
                                                          "linktree", "allmylinks")):
            continue
        if link.startswith("/external_link/"):        # the address is in the link itself
            target = urllib.parse.parse_qs(urllib.parse.urlparse(link).query).get("url", [""])[0]
            links += _handles(target + " ")
            continue
        if not link.startswith("/socials/"):
            continue
        try:
            links += _handles(_get(link, json_=False))
        except OSError:
            continue
    seen, out = set(), []
    for src, h in links:
        if (src, h.lower()) not in seen:
            seen.add((src, h.lower()))
            out.append((src, h))
    about = re.sub(r"<[^>]+>", " ", d.get("about_me") or "")
    return {"about": re.sub(r"\s+", " ", about).strip()[:1000], "followers": d.get("follower_count"),
            "age": d.get("display_age"), "location": str(d.get("location") or "")[:100],
            "last_broadcast": d.get("last_broadcast"), "links": out}


ACCOUNTS = ("x", "reddit", "xvideos", "redgifs", "onlyfans", "fansly", "linkpage")     # what a room's links can be (linkpage: its address)


def save_links(conn, room: str, links, via: str = "their Chaturbate bio", state: str = "bio") -> None:
    """A room's links, added unless you removed (or confirmed) them: (source, handle) pairs, or
    (source, handle, via, state). state bio: they link it themselves (via says where); suggested:
    the same name, not linked back (you confirm it or not). A suggestion that turns out to be
    linked becomes bio."""
    for link in links:
        src, h, v, st = (link[0], link[1], via, state) if len(link) == 2 else link
        if src not in ACCOUNTS:
            continue
        row = conn.execute("SELECT state FROM links WHERE room = ? AND source = ? AND lower(handle) = lower(?)", (room, src, h)).fetchone()
        if not row:
            conn.execute("INSERT INTO links(room, source, handle, state, via) VALUES (?, ?, ?, ?, ?)", (room, src, h, st, v))
        elif row[0] == "suggested" and st == "bio":
            conn.execute("UPDATE links SET state = 'bio', via = ? WHERE room = ? AND source = ? AND lower(handle) = lower(?)",
                         (v, room, src, h))
