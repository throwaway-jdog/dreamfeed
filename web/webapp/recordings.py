"""After a recording: each new video in your videos folder (CB_VIDEOS) of a room you follow is told
on Updates once it's done, and, for a room set so (its profile: After a recording), its highlights
are cut, keeping the original or then moving it to the trash (cbhighlights; gone after
cbvideos.TRASH_DAYS, Undo on the profile until then).

Done means it has stopped changing: the same size and time as the last look, nothing written for
QUIET seconds, and your recorder isn't recording that room into it (its newest file). Only
recordings done after a room was set are cut; those already there are left as they are.
"""
import time

import dvr
from dreamfeed.core import notices
from dreamfeed.live import cbvideos

from .common import DATA, ROOM, db, read_json

LOOK_EVERY = 300
QUIET = 900                # seconds without a change before a recording counts as done
SHORTEST = 120             # seconds: shorter ones are told, not cut
MODES = ("off", "keep", "delete")


def _tables(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS auto_highlights (room TEXT PRIMARY KEY, mode TEXT NOT NULL, keep REAL NOT NULL,
        since REAL NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS rec_files (path TEXT PRIMARY KEY, room TEXT NOT NULL, size INTEGER NOT NULL,
        mtime INTEGER NOT NULL, done INTEGER NOT NULL DEFAULT 0, first_at REAL NOT NULL)""")
    conn.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(highlights)")}
    if cols and "then_delete" not in cols:      # (as the follow service's db.py makes it)
        conn.execute("ALTER TABLE highlights ADD COLUMN then_delete INTEGER NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE highlights ADD COLUMN auto INTEGER NOT NULL DEFAULT 0")


def _conn():
    conn = db()
    _tables(conn)
    return conn


def setting(room: str) -> dict:
    with _conn() as conn:
        r = conn.execute("SELECT mode, keep, since FROM auto_highlights WHERE room = ?", (room,)).fetchone()
    return {"mode": r["mode"], "keep": r["keep"], "since": r["since"]} if r else {"mode": "off", "keep": 0.25, "since": None}


def set_auto(req: dict) -> dict:
    """{"name", "mode": off | keep (highlights, the original kept) | delete (highlights, then the
    original into the trash), "keep": 0.1-0.5}."""
    name, mode = str(req.get("name", "")), str(req.get("mode", ""))
    if not ROOM.match(name) or mode not in MODES:
        raise ValueError("bad room or mode")
    try:
        keep = float(req.get("keep", 0.25))
    except (TypeError, ValueError):
        raise ValueError("keep is 0.1 to 0.5")
    if not 0.1 <= keep <= 0.5:
        raise ValueError("keep is 0.1 to 0.5")
    with _conn() as conn:
        if not conn.execute("SELECT 1 FROM follows WHERE source = 'chaturbate' AND name = ?", (name,)).fetchone():
            raise LookupError("you don't follow that room")
        if mode == "off":
            conn.execute("DELETE FROM auto_highlights WHERE room = ?", (name,))
        else:
            old = conn.execute("SELECT since FROM auto_highlights WHERE room = ?", (name,)).fetchone()
            conn.execute("INSERT OR REPLACE INTO auto_highlights (room, mode, keep, since) VALUES (?, ?, ?, ?)",
                         (name, mode, keep, old["since"] if old else time.time()))
    return setting(name)


def _recording_now() -> set:
    try:
        return {r for r, s in (dvr.rooms().get("rooms") or {}).items() if s.get("state") == "recording"}
    except (LookupError, ValueError):
        return set()


def look() -> None:
    """One look at the folder (the thread's, every LOOK_EVERY)."""
    if not cbvideos.root():
        return
    now = time.time()
    with _conn() as conn:
        rooms = [n for (n,) in conn.execute("SELECT name FROM follows WHERE source = 'chaturbate'")]
        found = cbvideos.scan(rooms)
        files = {v["path"]: (room, v) for room, vids in found.items() for v in vids if not cbvideos.is_highlight(v["path"])}
        known = {r["path"]: r for r in conn.execute("SELECT * FROM rec_files")}
        if not conn.execute("SELECT 1 FROM kv WHERE key = 'rec_started'").fetchone():
            # the first look: what's already there is known, not new
            conn.executemany("INSERT OR IGNORE INTO rec_files (path, room, size, mtime, done, first_at) VALUES (?, ?, ?, ?, 1, ?)",
                             [(p, room, v["size"], v["mtime"], now) for p, (room, v) in files.items()])
            conn.execute("INSERT INTO kv (key, value) VALUES ('rec_started', ?)", (str(now),))
            return
        auto = {r["room"]: r for r in conn.execute("SELECT * FROM auto_highlights")}
        newest = {room: vids[0]["path"] for room, vids in found.items() if vids}
        busy = _recording_now()
        index = read_json(cbvideos.posters(DATA) / "index.json") or {}
        for path in [p for p in known if p not in files]:          # (deleted, or moved to the trash)
            conn.execute("DELETE FROM rec_files WHERE path = ?", (path,))
        for path, (room, v) in files.items():
            k = known.get(path)
            if not k:
                conn.execute("INSERT INTO rec_files (path, room, size, mtime, first_at) VALUES (?, ?, ?, ?, ?)",
                             (path, room, v["size"], v["mtime"], now))
                continue
            if k["done"]:
                continue
            if (k["size"], k["mtime"]) != (v["size"], v["mtime"]):
                conn.execute("UPDATE rec_files SET size = ?, mtime = ? WHERE path = ?", (v["size"], v["mtime"], path))
                continue
            if now - v["mtime"] < QUIET or (room in busy and newest.get(room) == path):
                continue
            conn.execute("UPDATE rec_files SET done = 1 WHERE path = ?", (path,))
            seconds = (index.get(cbvideos.key(v)) or {}).get("duration") or 0
            a = auto.get(room)
            cut = a and v["mtime"] >= a["since"] and (not seconds or seconds >= SHORTEST) and not conn.execute(
                "SELECT 1 FROM highlights WHERE path = ?", (path,)).fetchone()
            if cut:
                conn.execute("INSERT INTO highlights (room, path, keep, then_delete, auto) VALUES (?, ?, ?, ?, 1)",
                             (room, path, a["keep"], int(a["mode"] == "delete")))
            length = f"{seconds // 3600} h {seconds % 3600 // 60} min" if seconds >= 3600 else f"{seconds // 60} min" if seconds else ""
            notices.add(conn, "recordings", f"rec:{path}", f"New recording of {room}" + (f" ({length})" if length else ""),
                        " · ".join(x for x in (f"{v['size'] / 1e9:.1f} GB", "cutting its highlights" + (", then the original goes to the trash"
                                                                                               if a["mode"] == "delete" else "") if cut else "")
                                   if x), f"room/{room}", f"cb-videos/poster/{cbvideos.key(v)}.jpg"
                        if (index.get(cbvideos.key(v)) or {}).get("poster") else None)


def watch() -> None:
    """The web app's thread."""
    time.sleep(120)
    while True:
        try:
            look()
        except Exception as e:      # (logged; tried again next time)
            print(time.strftime("%F %T"), f"web: watching recordings: {e}", flush=True)
        time.sleep(LOOK_EVERY)
