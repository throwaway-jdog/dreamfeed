"""Updates: what happened while you weren't looking (a room you follow went live, a recording or
its highlights are done, a comic you follow has new pages, something stopped working), shown on
the page's Updates, by topic. Nothing is pushed anywhere. Written by the web app and the follow
service alike (standard library only); each is kept KEEP_DAYS, at most KEEP_MAX.
"""
import time

TOPICS = ("live", "recordings", "comics", "health")
KEEP_DAYS = 30
KEEP_MAX = 1000
TABLE = """CREATE TABLE IF NOT EXISTS notices (
    id      INTEGER PRIMARY KEY,
    topic   TEXT NOT NULL,               -- live | recordings | comics | health
    key     TEXT NOT NULL UNIQUE,        -- what it's about, so the same thing is told once
    title   TEXT NOT NULL,
    body    TEXT NOT NULL DEFAULT '',
    link    TEXT,                        -- the page's address that opens it (relative: room/NAME/watch ...)
    thumb   TEXT,                        -- a picture's address, relative to the page
    at      REAL NOT NULL,
    read    INTEGER NOT NULL DEFAULT 0
)"""


def table(conn) -> None:
    conn.execute(TABLE)


def add(conn, topic: str, key: str, title: str, body: str = "", link: str | None = None, thumb: str | None = None) -> bool:
    """Tells it once (by key; the same key again is left as it was). True when it's new."""
    if topic not in TOPICS:
        raise ValueError("bad topic")
    table(conn)
    cur = conn.execute("INSERT OR IGNORE INTO notices (topic, key, title, body, link, thumb, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (topic, key[:300], title[:300], body[:600], link, thumb, time.time()))
    if cur.rowcount:
        conn.execute("DELETE FROM notices WHERE at < ? OR id NOT IN (SELECT id FROM notices ORDER BY id DESC LIMIT ?)",
                     (time.time() - KEEP_DAYS * 86400, KEEP_MAX))
    return bool(cur.rowcount)
