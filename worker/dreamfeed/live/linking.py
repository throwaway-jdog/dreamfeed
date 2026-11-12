"""One creator across sites: the accounts a Chaturbate room's performer publishes, followed
further than their bio (the web app runs it: it has the Reddit and X sign-ins).

From what the room already links (their bio, or you):
1. Pages that list their accounts (Linktree, AllMyLinks) are read, and every account on them is
   linked ("their Linktree").
2. Each account's own profile is read for more: an X account's bio and website, a Reddit
   account's profile text, a RedGifs profile's text and links. Two steps out at most.
3. Their names (the room's, and the ones on OnlyFans, Fansly, X, Reddit) are looked for on
   RedGifs and Reddit. One whose profile links back to an account already known (a link to their
   room, their OnlyFans ...) is linked ("links back"); one that doesn't is only suggested, for
   you to confirm: a name alone isn't proof, others use the same names.

Only what creators publish themselves is used: nothing is guessed from faces or anything else.
OnlyFans and Fansly aren't read (they're paywalled); their names only help find the rest.
These are real people: nothing here goes to training, styles, comics or generation.
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import cbprofile

from ..feed import livefeeds

AGENT = "Mozilla/5.0 (dreamfeed: a creator's own links)"
MAX_FETCHES = 14          # pages read for one room
DEPTH = 2                 # steps out from what the room links
GAP = 1.0                 # seconds between pages read
NAME = re.compile(r"^[a-z0-9_.-]{3,40}$")
GROUP = 2                 # more accounts than this on one site, on one link page: a group's page


def _get(url: str, limit: int = 2 << 20) -> str:
    time.sleep(GAP)
    req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "text/html,application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read(limit).decode("utf-8", "replace")


def _link_page(url: str) -> str:
    """The addresses a Linktree or AllMyLinks page lists, as text to read links from."""
    page = _get(url)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)      # Linktree
    if m:
        try:
            acct = (json.loads(m.group(1)).get("props") or {}).get("pageProps", {}).get("account") or {}
            urls = [l.get("url") for l in (acct.get("links") or []) + (acct.get("socialLinks") or [])]
            return " ".join(u for u in urls if isinstance(u, str)) + " "
        except ValueError:
            pass
    return " ".join(urllib.parse.unquote(u) for u in re.findall(r"https?%3A%2F%2F[^\"'&<>\s]+|https?://[^\"'<>\s]+", page)) + " "


def redgifs_user(name: str) -> dict | None:
    """A RedGifs profile ({"name", "text": what it says and links, "gifs"}), or None."""
    try:
        d = json.loads(_get(f"https://api.redgifs.com/v1/users/{urllib.parse.quote(name)}"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    if d.get("status") not in (None, "active"):
        return None
    text = " ".join(str(x) for x in (d.get("description"), d.get("profileUrl")) if x) + " "
    return {"name": str(d.get("name") or name).lower(), "text": text, "gifs": d.get("publishedGifs") or d.get("gifs") or 0}


def reddit_text(name: str) -> str | None:
    """What a Reddit account's profile says (its description and title), or None when there's none."""
    if not livefeeds.reddit_ready():
        return None
    try:
        u = (livefeeds._reddit(f"/user/{name}/about?raw_json=1") or {}).get("data") or {}
    except LookupError:
        return None
    if u.get("is_suspended") or not u.get("name"):
        return None
    sub = u.get("subreddit") or {}
    return " ".join(str(x) for x in (sub.get("public_description"), sub.get("title")) if x) + " "


def x_text(handle: str) -> str | None:
    """An X account's bio and website (from its newest media post, as gallery-dl reads it)."""
    if not livefeeds.x_cookies():
        return None
    try:
        items = livefeeds._x(f"https://x.com/{handle}/media", 1, 1, timeout=60)
    except LookupError:
        return None
    for it in items:
        a = (it[-1] if isinstance(it, list) and it and isinstance(it[-1], dict) else {}).get("author") or {}
        if str(a.get("name", "")).lower() == handle.lower():
            return " ".join(str(x) for x in (a.get("description"), a.get("url")) if x) + " "
    return None


def _backlinks(text: str, room: str, known: set) -> bool:
    """Does text link to the room or to an account already known to be theirs?"""
    low = text.lower()
    if f"chaturbate.com/{room}" in low:
        return True
    return any((src, h.lower()) in known for src, h in cbprofile._handles(text))


def find(room: str, known: list[tuple[str, str]]) -> list[tuple[str, str, str, str]]:
    """The room's accounts found from known [(source, handle)] (and its link pages): [(source,
    handle, via, state)], state bio (published by them) or suggested (the same name only)."""
    have = {(s, h.lower()) for s, h in known}
    out: dict[tuple[str, str], tuple[str, str]] = {}           # (source, handle) -> (via, state)
    fetches = 0
    todo = [(s, h, 0, "") for s, h in known]
    seen = set(have)

    def add(found: list, via: str, depth: int, from_page: bool = False) -> None:
        if from_page:
            # A link page is one person's. Link pages listed on it are other people's (a studio's
            # or a friend's), and several accounts on one site make it a group's page: neither
            # is taken from it.
            found = [(s, h) for s, h in found if s != "linkpage"]
            per = {}
            for s, h in dict.fromkeys((s, h.lower()) for s, h in found):
                per[s] = per.get(s, 0) + 1
            found = [(s, h) for s, h in found if per.get(s, 0) <= GROUP]
        for s, h in found:
            k = (s, h.lower())
            if k in seen:
                continue
            seen.add(k)
            if s in cbprofile.ACCOUNTS:
                out[k] = (via, "bio")
                have.add(k)
            todo.append((s, h, depth, via))

    while todo and fetches < MAX_FETCHES:
        s, h, depth, _ = todo.pop(0)
        if depth > DEPTH:
            continue
        try:
            if s == "linkpage":
                fetches += 1
                host = urllib.parse.urlparse(h).hostname or ""
                add(cbprofile._handles(_link_page(h)), "their Linktree" if "linktr" in host else "their AllMyLinks", depth + 1, True)
            elif s == "redgifs":
                fetches += 1
                u = redgifs_user(h)
                if u:
                    add(cbprofile._handles(u["text"]), "their RedGifs", depth + 1)
            elif s == "reddit":
                fetches += 1
                t = reddit_text(h)
                if t:
                    add(cbprofile._handles(t), "their Reddit profile", depth + 1)
            elif s == "x":
                fetches += 1
                t = x_text(h)
                if t:
                    add(cbprofile._handles(t), "their X bio", depth + 1)
        except (OSError, ValueError, LookupError):
            continue

    # their names elsewhere: linked when they link back, else only suggested
    names = [room] + [h.lower() for s, h in have if s in ("onlyfans", "fansly", "x", "reddit")]
    names = [n for n in dict.fromkeys(names) if NAME.match(n)][:4]
    for n in names:
        if fetches >= MAX_FETCHES + 6:
            break
        try:
            if ("redgifs", n) not in have:
                fetches += 1
                u = redgifs_user(n)
                if u and u["gifs"]:
                    linked = _backlinks(u["text"], room, have)
                    out[("redgifs", n)] = ("links back" if linked else "same name", "bio" if linked else "suggested")
                    if linked:
                        have.add(("redgifs", n))
            if ("reddit", n) not in have and not any(s == "reddit" for s, _ in have):
                fetches += 1
                t = reddit_text(n)
                if t is not None:
                    linked = _backlinks(t, room, have)
                    if linked:
                        out[("reddit", n)] = ("links back", "bio")
                        have.add(("reddit", n))
        except (OSError, ValueError, LookupError):
            continue
    return [(s, h, via, st) for (s, h), (via, st) in out.items()]
