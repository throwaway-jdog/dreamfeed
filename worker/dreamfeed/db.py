import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS bookmarks (
    id           INTEGER PRIMARY KEY,
    file         TEXT UNIQUE NOT NULL,
    tweet_id     TEXT,
    kind         TEXT NOT NULL,              -- image | video
    medium       TEXT NOT NULL,              -- photo | anime | furry
    medium_probs TEXT NOT NULL,              -- JSON
    rating       TEXT,                       -- general | sensitive | questionable | explicit
    embedding    BLOB NOT NULL,              -- CLIP, float16, normalized
    tagged_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS bookmark_tags (
    bookmark_id INTEGER NOT NULL REFERENCES bookmarks(id) ON DELETE CASCADE,
    tag         TEXT NOT NULL,
    score       REAL NOT NULL,
    PRIMARY KEY (bookmark_id, tag)
);
CREATE INDEX IF NOT EXISTS bookmark_tags_tag ON bookmark_tags(tag);
CREATE TABLE IF NOT EXISTS dropped (
    file     TEXT PRIMARY KEY,
    tweet_id TEXT,
    reason   TEXT NOT NULL,                  -- youth-tag | age-estimate | age-check | unreadable
    detail   TEXT,
    medium   TEXT,
    at       TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(dropped)")}
    if "medium" not in cols:   # added after the first release
        conn.execute("ALTER TABLE dropped ADD COLUMN medium TEXT")
    return conn
