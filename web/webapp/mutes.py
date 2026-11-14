"""Your mute list (the Dashboard's Mute): what you'd rather not see, left out of the Feed (Following,
For you, Browse, More videos), Videos, Comics, Live's Discover and Search. What you open yourself (a
profile, a post's own page, Saved, rooms you follow) still shows.

- word: a word or a few, anywhere in a post's text, a title, tags, a subreddit's or room's name
  (whole words, case and _ - ignored: "feet" leaves out "Feet pics" and "feet_focus", not "feetish");
- account: someone on a site (x, bsky, reddit, e621: an artist, xvideos: an uploader, chaturbate:
  a room, comics: an artist), or on any of them;
- subreddit: a subreddit's posts.
"""
import re
import threading
import time

from .common import db

KINDS = ("word", "account", "subreddit")
SITES = ("", "x", "bsky", "reddit", "e621", "xvideos", "chaturbate", "comics")
MAX = 500
_rules: dict = {"at": 0.0, "value": None}
_lock = threading.Lock()


def _tables(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS mutes (kind TEXT NOT NULL, value TEXT NOT NULL, site TEXT NOT NULL DEFAULT '',
        at REAL NOT NULL, PRIMARY KEY (kind, value, site))""")


def _conn():
    conn = db()
    _tables(conn)
    return conn


def _norm(kind: str, value: str) -> str:
    v = " ".join(str(value or "").replace("_", " ").split()).lower() if kind == "word" else str(value or "").strip().lower()
    if kind == "account":
        v = re.sub(r"^(?:@|/?u/|https?://(?:www\.)?xvideos\.com/)", "", v).strip("/")
    if kind == "subreddit":
        v = re.sub(r"^/?r/", "", v).strip("/")
    return v


def listing() -> dict:
    with _conn() as conn:
        rows = conn.execute("SELECT kind, value, site, at FROM mutes ORDER BY kind, value").fetchall()
    return {"mutes": [dict(r) for r in rows], "kinds": list(KINDS), "sites": list(SITES)}


def change(req: dict) -> dict:
    """{"kind", "value", "site"?, "remove"?: bool}"""
    kind, site = str(req.get("kind", "")), str(req.get("site") or "")
    if kind not in KINDS or site not in SITES:
        raise ValueError("bad kind or site")
    if kind != "account":
        site = ""
    value = _norm(kind, req.get("value"))
    ok = {"word": r"[^\W_][\w '&.+-]{0,59}", "account": r"[\w.()'!~-]{1,100}", "subreddit": r"[a-z0-9_]{2,21}"}[kind]
    if not re.fullmatch(ok, value):
        raise ValueError({"word": "a word or a few (up to 60 letters)", "account": "a name, like someone or @someone",
                          "subreddit": "a subreddit's name, like r/pics"}[kind])
    with _conn() as conn:
        if req.get("remove"):
            conn.execute("DELETE FROM mutes WHERE kind = ? AND value = ? AND site = ?", (kind, value, site))
        else:
            if conn.execute("SELECT count(*) FROM mutes").fetchone()[0] >= MAX:
                raise ValueError(f"the mute list is full ({MAX})")
            conn.execute("INSERT OR REPLACE INTO mutes (kind, value, site, at) VALUES (?, ?, ?, ?)", (kind, value, site, time.time()))
    with _lock:
        _rules["value"] = None
    return listing()


def rules() -> dict:
    """{"words": a pattern or None, "accounts": {(site, name)}, "anywhere": {name}, "subs": {name}}."""
    with _lock:
        if _rules["value"] is not None and time.time() - _rules["at"] < 60:
            return _rules["value"]
    try:
        with _conn() as conn:
            rows = conn.execute("SELECT kind, value, site FROM mutes").fetchall()
    except Exception:              # (a mute list that won't read leaves nothing out)
        rows = []
    words = [r["value"] for r in rows if r["kind"] == "word"]
    value = {"words": re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(w).replace(r"\ ", r"[\s_-]+") for w in
                                                                 sorted(words, key=len, reverse=True)) + r")(?![a-z0-9])", re.I)
             if words else None,
             "accounts": {(r["site"], r["value"]) for r in rows if r["kind"] == "account" and r["site"]},
             "anywhere": {r["value"] for r in rows if r["kind"] == "account" and not r["site"]},
             "subs": {r["value"] for r in rows if r["kind"] == "subreddit"}}
    with _lock:
        _rules.update(at=time.time(), value=value)
    return value


def _hit(r: dict, texts, people) -> bool:
    """people: (site, name) pairs."""
    for site, name in people:
        name = str(name or "").lower().strip("/")
        if name and ((site, name) in r["accounts"] or name in r["anywhere"]):
            return True
    if r["words"]:
        t = " ".join(str(x) for x in texts if x)
        if t and r["words"].search(t.replace("_", " ")):
            return True
    return False


def post_muted(p: dict, r: dict | None = None) -> bool:
    r = r or rules()
    src = p.get("source")
    if src == "reddit" and str(p.get("place") or "").lower() in r["subs"]:
        return True
    people = [(src, p.get("author"))] + [("e621", a) for a in p.get("artists") or []]
    return _hit(r, [p.get("text"), p.get("place"), " ".join(p.get("tags") or [])], people)


def video_muted(v: dict, r: dict | None = None) -> bool:
    r = r or rules()
    return _hit(r, [v.get("title"), " ".join(v.get("tags") or [])],
                [("xvideos", v.get("uploader_path")), ("xvideos", v.get("uploader"))])


def comic_muted(c: dict, r: dict | None = None) -> bool:
    r = r or rules()
    artists = c.get("artists") or []
    return _hit(r, [c.get("title"), " ".join(c.get("tags") or [])], [("comics", a) for a in artists] + [("e621", a) for a in artists])


def room_muted(room: dict, r: dict | None = None) -> bool:
    r = r or rules()
    info = room.get("info") or {}
    return _hit(r, [info.get("title"), " ".join(info.get("tags") or [])], [("chaturbate", room.get("name"))])


def posts(items: list[dict]) -> list[dict]:
    r = rules()
    return [p for p in items if not post_muted(p, r)] if r["words"] or r["accounts"] or r["anywhere"] or r["subs"] else items


def videos(items: list[dict]) -> list[dict]:
    r = rules()
    return [v for v in items if not video_muted(v, r)] if r["words"] or r["accounts"] or r["anywhere"] else items


def comics(items: list[dict]) -> list[dict]:
    r = rules()
    return [c for c in items if not comic_muted(c, r)] if r["words"] or r["accounts"] or r["anywhere"] else items


def rooms(items: list[dict]) -> list[dict]:
    r = rules()
    return [x for x in items if not room_muted(x, r)] if r["words"] or r["accounts"] or r["anywhere"] else items
