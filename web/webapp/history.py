"""History (the ⋮ menu): what you've opened here, newest first, by kind: posts (opened on their own
page), videos (xvideos, in the player), comics (in the reader), live rooms (watched) and your
recordings (played). Each is kept once (opening it again moves it to the top), KEEP_DAYS at most.
Clearing it here doesn't change what For you has learned, or Continue watching and reading.
"""
import json
import re
import time

from .common import ROOM, db

KINDS = ("post", "video", "comic", "room", "recording")
KEEP_DAYS = 180
PAGE = 50
MAX_DATA = 20000           # bytes of what's kept to open it again


def _tables(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS history (kind TEXT NOT NULL, key TEXT NOT NULL, title TEXT NOT NULL,
        thumb TEXT, link TEXT NOT NULL, data TEXT, at REAL NOT NULL, PRIMARY KEY (kind, key))""")
    conn.execute("CREATE INDEX IF NOT EXISTS history_at ON history(at)")


def _conn():
    conn = db()
    _tables(conn)
    return conn


def _link_ok(link: str, query: bool = False) -> bool:
    """One of the page's own addresses (relative; a picture's may have a query)."""
    chars = r"[A-Za-z0-9_./%+:~?=&-]" if query else r"[A-Za-z0-9_./%+:~-]"
    return bool(re.fullmatch(chars + "{1,600}", link)) and not link.startswith(("/", "http")) and ".." not in link


def note(kind: str, key: str, title: str, link: str, thumb: str | None = None, data: dict | None = None) -> None:
    """One thing opened (kept once: again, it moves to the top)."""
    raw = json.dumps(data) if data else None
    with _conn() as conn:
        conn.execute("INSERT OR REPLACE INTO history (kind, key, title, thumb, link, data, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (kind, key[:300], (title or "").strip()[:300] or kind, thumb, link, raw if raw and len(raw) <= MAX_DATA else None,
                      time.time()))
        conn.execute("DELETE FROM history WHERE at < ?", (time.time() - KEEP_DAYS * 86400,))


def add(req: dict) -> dict:
    """{"kind": post | recording | room, "key", "title", "link", "thumb"?, "data"?}: from the page, for
    what the server doesn't see opened itself (videos and comics are noted where they load)."""
    kind, key, link = str(req.get("kind", "")), str(req.get("key", "")), str(req.get("link", ""))
    thumb = req.get("thumb")
    if kind not in ("post", "recording", "room") or not 1 <= len(key) <= 300 or not _link_ok(link):
        raise ValueError("bad history entry")
    if thumb is not None and not (isinstance(thumb, str) and (thumb.startswith("https://") or _link_ok(thumb, True)) and len(thumb) < 1000):
        raise ValueError("bad thumb")
    if kind == "room" and not ROOM.match(key):
        raise ValueError("bad room")
    data = req.get("data") if isinstance(req.get("data"), dict) else None
    note(kind, key, str(req.get("title") or ""), link, thumb, data)
    return {"ok": True}


def listing(kind: str, offset: int, q: str = "") -> dict:
    if kind and kind not in KINDS or not 0 <= offset < 10000:
        raise ValueError("bad kind")
    where, args = [], []
    if kind:
        where.append("kind = ?"); args.append(kind)
    if q:
        where.append("title LIKE ? ESCAPE '\\'"); args.append("%" + re.sub(r"([%_\\])", r"\\\1", q.strip()[:100]) + "%")
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM history" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY at DESC LIMIT ? OFFSET ?",
                            args + [PAGE + 1, offset]).fetchall()
    return {"items": [{"kind": r["kind"], "key": r["key"], "title": r["title"], "thumb": r["thumb"], "link": r["link"],
                       "data": json.loads(r["data"]) if r["data"] else None, "at": r["at"]} for r in rows[:PAGE]],
            "more": len(rows) > PAGE, "kinds": list(KINDS)}


def remove(req: dict) -> dict:
    """{"kind", "key"}: that one; {"all": true, "kind"?}: everything (of that kind)."""
    kind = str(req.get("kind") or "")
    if kind and kind not in KINDS:
        raise ValueError("bad kind")
    with _conn() as conn:
        if req.get("all"):
            conn.execute("DELETE FROM history" + (" WHERE kind = ?" if kind else ""), [kind] if kind else [])
        else:
            conn.execute("DELETE FROM history WHERE kind = ? AND key = ?", (kind, str(req.get("key", ""))))
    return {"ok": True}
