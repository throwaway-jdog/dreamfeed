"""A Chaturbate room's public bio, and the X and Reddit accounts its performer links there for
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
REDDIT_LINK = re.compile(r"https?://(?:www\.|old\.)?reddit\.com/(?:u|user)/([A-Za-z0-9_-]{3,20})(?:[/?\"'<\s]|$)")
NOT_ACCOUNTS = {"chaturbate", "home", "intent", "share", "i", "search", "hashtag", "explore", "settings", "login"}
GAP = 1.5                     # seconds between requests


def _get(path: str, json_=True):
    time.sleep(GAP)
    req = urllib.request.Request(SITE + path, headers={"User-Agent": AGENT, "Accept": "application/json" if json_ else "text/html"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read(2 << 20)
    return json.loads(data) if json_ else data.decode("utf-8", "replace")


def _handles(text: str) -> list[tuple[str, str]]:
    found = [("x", h) for h in X_LINK.findall(text) if h.lower() not in NOT_ACCOUNTS]
    found += [("reddit", h) for h in REDDIT_LINK.findall(text)]
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
        if not s.get("is_free") or not title.startswith(("x ", "twitter", "reddit")):
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


def save_links(conn, room: str, links) -> None:
    """A room's bio links, added unless you removed them (yours and removed ones stay as they are)."""
    for src, h in links:
        if not conn.execute("SELECT 1 FROM links WHERE room = ? AND source = ? AND lower(handle) = lower(?)", (room, src, h)).fetchone():
            conn.execute("INSERT INTO links(room, source, handle, state) VALUES (?, ?, ?, 'bio')", (room, src, h))
