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
CREATE TABLE IF NOT EXISTS runs (
    night       TEXT PRIMARY KEY,            -- local date the window started
    attempts    INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL,               -- running | done | failed | cancelled
    stats       TEXT,                        -- JSON
    started_at  TEXT,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS generations (
    id          INTEGER PRIMARY KEY,
    night       TEXT NOT NULL,
    medium      TEXT NOT NULL,
    checkpoint  TEXT NOT NULL,
    prompt      TEXT NOT NULL,
    seed        INTEGER NOT NULL,
    source_bookmark INTEGER,                 -- bookmark whose tags seeded the prompt
    file        TEXT,                        -- relative to data/generated
    status      TEXT NOT NULL,               -- queued | generated | dropped | scored | ranked-out | feed | expired
    reason      TEXT,                        -- why it was dropped
    score       REAL,                        -- taste score, higher is better
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS generations_night ON generations(night, status);
CREATE TABLE IF NOT EXISTS jobs (           -- generation requests from the dashboard
    id          INTEGER PRIMARY KEY,
    params      TEXT NOT NULL,               -- JSON: images, keep, mediums
    status      TEXT NOT NULL,               -- queued | running | done | failed | cancelled
    night       TEXT,                        -- the run it became (runs.night)
    message     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS feedback (
    generation_id INTEGER PRIMARY KEY REFERENCES generations(id),
    action        TEXT NOT NULL,             -- like | skip
    liked_file    TEXT,                      -- copy in data/liked, kept when the feed expires
    at            TEXT NOT NULL DEFAULT (datetime('now'))
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
    cols = {r[1] for r in conn.execute("PRAGMA table_info(generations)")}
    if "embedding" not in cols:   # added with the feed
        conn.execute("ALTER TABLE generations ADD COLUMN embedding BLOB")
        conn.execute("ALTER TABLE generations ADD COLUMN thumb TEXT")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
    if "progress" not in cols:    # added with the dashboard
        conn.execute("ALTER TABLE runs ADD COLUMN progress TEXT")
        conn.execute("ALTER TABLE runs ADD COLUMN cancel INTEGER NOT NULL DEFAULT 0")
    return conn
