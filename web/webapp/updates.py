"""Updates (the page's 🔔): what happened, by topic (dreamfeed.core.notices: written here and by the
follow service). Live: a room you follow went live. Recordings: a new recording is done, its
highlights are ready (or failed). Comics: one you follow has new pages. Health: a part stopped
working, or a sign-in is about to run out (looked at every HEALTH_EVERY). Nothing is pushed.
"""
import time

from dreamfeed.core import notices

from .common import db

HEALTH_EVERY = 1800
PAGE = 60


def _conn():
    conn = db()
    notices.table(conn)
    return conn


def unread() -> int:
    try:
        with _conn() as conn:
            return conn.execute("SELECT count(*) FROM notices WHERE read = 0").fetchone()[0]
    except Exception:          # (Updates is extra: the header still shows)
        return 0


def listing(topic: str, offset: int) -> dict:
    """{"notices": newest first, "more", "counts": {topic: unread}}."""
    if topic and topic not in notices.TOPICS or not 0 <= offset < 5000:
        raise ValueError("bad topic")
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM notices" + (" WHERE topic = ?" if topic else "") + " ORDER BY at DESC, id DESC LIMIT ? OFFSET ?",
                            ([topic] if topic else []) + [PAGE + 1, offset]).fetchall()
        counts = {r[0]: r[1] for r in conn.execute("SELECT topic, count(*) FROM notices WHERE read = 0 GROUP BY topic")}
        live = {r[0] for r in conn.execute("SELECT name FROM follows WHERE source = 'chaturbate' AND live = 1")}
    out = []
    for r in rows[:PAGE]:
        n = {k: r[k] for k in ("id", "topic", "title", "body", "link", "thumb", "at")} | {"read": bool(r["read"])}
        if r["topic"] == "live":           # (whether they still are)
            n["live_now"] = r["key"].split(":")[1] in live
        out.append(n)
    return {"notices": out, "more": len(rows) > PAGE, "counts": counts, "topics": list(notices.TOPICS)}


def mark_read(req: dict) -> dict:
    """{"topic"?}: all read (of that topic)."""
    topic = str(req.get("topic") or "")
    if topic and topic not in notices.TOPICS:
        raise ValueError("bad topic")
    with _conn() as conn:
        conn.execute("UPDATE notices SET read = 1 WHERE read = 0" + (" AND topic = ?" if topic else ""), [topic] if topic else [])
    return {"ok": True}


def clear(req: dict) -> dict:
    """{"topic"?} all gone (of that topic); {"id"} that one."""
    topic, nid = str(req.get("topic") or ""), req.get("id")
    if topic and topic not in notices.TOPICS:
        raise ValueError("bad topic")
    with _conn() as conn:
        if nid is not None:
            conn.execute("DELETE FROM notices WHERE id = ?", (int(nid),))
        else:
            conn.execute("DELETE FROM notices" + (" WHERE topic = ?" if topic else ""), [topic] if topic else [])
    return {"ok": True}


def watch_health() -> None:
    """The web app's thread: a part of Health that's broken (bad), or a sign-in that runs out soon,
    told once a day while it lasts."""
    from . import health
    time.sleep(300)
    while True:
        try:
            parts = health.health()["parts"]
            day = time.strftime("%Y-%m-%d")
            with _conn() as conn:
                for p in parts:
                    if p["state"] == "bad" or (p["state"] == "warn" and "runs out" in p["says"]):
                        notices.add(conn, "health", f"health:{p['part']}:{p['says']}:{day}", f"{p['part']}: "
                                    + ("not working" if p["state"] == "bad" else "needs a look"), p["says"], "dashboard")
        except Exception as e:      # (logged; tried again next time)
            print(time.strftime("%F %T"), f"web: watching health: {e}", flush=True)
        time.sleep(HEALTH_EVERY)
