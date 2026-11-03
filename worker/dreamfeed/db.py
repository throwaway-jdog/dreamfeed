import sqlite3
from pathlib import Path

SCHEMA = """
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
    source_bookmark INTEGER,                 -- unused since v2 (bookmarks were removed)
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
CREATE TABLE IF NOT EXISTS personas (      -- fictional posters, mirrored from data/personas.json
    handle      TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    medium      TEXT NOT NULL,               -- anime | furry
    bio         TEXT NOT NULL DEFAULT '',
    strict      INTEGER NOT NULL DEFAULT 0,  -- stricter adult prompts and age check
    video_share REAL NOT NULL DEFAULT 0.2,   -- share of nightly clips that should be theirs
    avatar      TEXT,                        -- relative to data/generated
    active      INTEGER NOT NULL DEFAULT 1,  -- 0 once removed from the file
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
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
    # Bookmarks were removed in v2: personas replaced them as the source of posts.
    conn.executescript("DROP TABLE IF EXISTS bookmark_tags; DROP TABLE IF EXISTS bookmarks;"
                       " DROP TABLE IF EXISTS dropped;")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(generations)")}
    if "embedding" not in cols:   # added with the feed
        conn.execute("ALTER TABLE generations ADD COLUMN embedding BLOB")
        conn.execute("ALTER TABLE generations ADD COLUMN thumb TEXT")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(generations)")}
    if "kind" not in cols:        # added with video
        conn.execute("ALTER TABLE generations ADD COLUMN kind TEXT NOT NULL DEFAULT 'image'")   # image | video
        conn.execute("ALTER TABLE generations ADD COLUMN source_generation INTEGER")           # image a video animates
    cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
    if "progress" not in cols:    # added with the dashboard
        conn.execute("ALTER TABLE runs ADD COLUMN progress TEXT")
        conn.execute("ALTER TABLE runs ADD COLUMN cancel INTEGER NOT NULL DEFAULT 0")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(generations)")}
    if "persona" not in cols:     # added with v2 personas
        conn.execute("ALTER TABLE generations ADD COLUMN persona TEXT")      # personas.handle
        conn.execute("ALTER TABLE generations ADD COLUMN caption TEXT")
        conn.execute("ALTER TABLE generations ADD COLUMN posted_at TEXT")    # when it appears in the timeline
        conn.execute("CREATE INDEX IF NOT EXISTS generations_persona ON generations(persona, status)")
    return conn
