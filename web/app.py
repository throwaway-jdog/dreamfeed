"""dreamfeed feed page. Everything except the sign-in page needs a signed-in session (formlogin).

GET  /                  the page
GET  /api/feed          ?view=feed|liked&medium=all|photo|anime|furry&offset=N
GET  /api/summary       counts and the last run, for the header
GET  /thumb/<id>        small JPEG for the grid
GET  /img/<id>          full image for the viewer
GET  /api/dashboard     scan state, profile, queue, recent runs
POST /api/feedback      {"id": N, "action": "like"|"skip"|"clear"}
POST /api/scan          ask the sync container to fetch bookmarks now
POST /api/generate      {"images": N, "keep": K, "mediums": [...]} queue a generation run
POST /api/cancel        {"night": "..."} or {"job": N} stop a run or queued request
(POSTs are JSON only.)
"""
import json
import os
import shutil
import sqlite3
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import formlogin
import formlogin.httpserver


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"web: {name} is not set")
    return value


DATA = Path(required("DATA_DIR"))
STATE = required("STATE_DIR")
GENERATED = DATA / "generated"
LIKED = DATA / "liked"
DB_PATH = DATA / "feed.db"
PAGE = Path(__file__).with_name("index.html")
SYNC = DATA / "sync"
BOOKMARKS_IN = DATA / "bookmarks"
GENERATE_WINDOW = required("GENERATE_WINDOW")
MAX_IMAGES = 400
PORT = 8000
PAGE_SIZE = 30
MEDIUMS = ("photo", "anime", "furry")
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
       "script-src 'self' 'unsafe-inline'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    # The worker owns the schema; this one table is created here too so likes work
    # even before the worker's next start.
    conn.execute("""CREATE TABLE IF NOT EXISTS feedback (
        generation_id INTEGER PRIMARY KEY REFERENCES generations(id),
        action TEXT NOT NULL, liked_file TEXT,
        at TEXT NOT NULL DEFAULT (datetime('now')))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY, params TEXT NOT NULL, status TEXT NOT NULL, night TEXT, message TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')), finished_at TEXT)""")
    return conn


def item(row) -> dict:
    return {"id": row["id"], "night": row["night"], "medium": row["medium"],
            "score": round(row["score"] or 0, 3), "liked": row["action"] == "like"}


def feed(view: str, medium: str, offset: int) -> dict:
    where, args = [], []
    if medium in MEDIUMS:
        where.append("g.medium = ?")
        args.append(medium)
    if view == "liked":
        where.append("f.action = 'like'")
        order = "f.at DESC"
    else:
        where.append("g.status = 'feed' AND (f.action IS NULL OR f.action = 'like')")
        order = "g.night DESC, g.score DESC"
    sql = (f"SELECT g.id, g.night, g.medium, g.score, f.action FROM generations g"
           f" LEFT JOIN feedback f ON f.generation_id = g.id WHERE {' AND '.join(where)}"
           f" ORDER BY {order} LIMIT ? OFFSET ?")
    try:
        with db() as conn:
            rows = conn.execute(sql, (*args, PAGE_SIZE + 1, offset)).fetchall()
    except sqlite3.OperationalError:   # worker hasn't created its tables yet
        return {"items": [], "more": False}
    return {"items": [item(r) for r in rows[:PAGE_SIZE]], "more": len(rows) > PAGE_SIZE}


def summary() -> dict:
    out = {"unrated": 0, "liked": 0, "bookmarks": {}, "last_run": None}
    try:
        with db() as conn:
            out["unrated"] = conn.execute(
                "SELECT count(*) FROM generations g LEFT JOIN feedback f ON f.generation_id = g.id"
                " WHERE g.status = 'feed' AND f.action IS NULL").fetchone()[0]
            out["liked"] = conn.execute("SELECT count(*) FROM feedback WHERE action = 'like'").fetchone()[0]
            out["bookmarks"] = dict(conn.execute(
                "SELECT medium, count(*) FROM bookmarks GROUP BY medium").fetchall())
            run = conn.execute("SELECT night, status, finished_at FROM runs WHERE night NOT LIKE 'test-%'"
                               " ORDER BY started_at DESC LIMIT 1").fetchone()
            if run:
                out["last_run"] = dict(run)
    except sqlite3.OperationalError:
        pass
    return out


def image_path(gid: int, thumb: bool) -> Path | None:
    with db() as conn:
        row = conn.execute("SELECT g.file, g.thumb, f.liked_file FROM generations g"
                           " LEFT JOIN feedback f ON f.generation_id = g.id WHERE g.id = ?", (gid,)).fetchone()
    if not row:
        return None
    candidates = [(GENERATED, row["thumb"] if thumb else None), (GENERATED, row["file"]),
                  (LIKED, row["liked_file"])]
    for base, rel in candidates:
        if rel:
            path = (base / rel).resolve()
            if path.is_relative_to(base.resolve()) and path.is_file():
                return path
    return None


def set_feedback(gid: int, action: str) -> dict:
    with db() as conn:
        row = conn.execute("SELECT g.id, g.night, g.medium, g.score, g.file, g.status, f.action, f.liked_file"
                           " FROM generations g LEFT JOIN feedback f ON f.generation_id = g.id"
                           " WHERE g.id = ?", (gid,)).fetchone()
        if not row or row["status"] not in ("feed", "expired"):
            raise LookupError("no such image")
        old_copy = row["liked_file"]
        if action == "like":
            copy = old_copy
            if not copy:
                src = GENERATED / row["file"]
                if not src.is_file():
                    raise LookupError("this image has expired")
                copy =f"{row['night']}-{row['medium']}-{gid}{src.suffix}"
                LIKED.mkdir(exist_ok=True)
                shutil.copy2(src, LIKED / copy)
            conn.execute("INSERT INTO feedback(generation_id, action, liked_file) VALUES (?, 'like', ?)"
                         " ON CONFLICT(generation_id) DO UPDATE SET action = 'like', liked_file = ?,"
                         " at = datetime('now')", (gid, copy, copy))
        else:
            if old_copy:
                (LIKED / old_copy).unlink(missing_ok=True)
            if action == "skip":
                conn.execute("INSERT INTO feedback(generation_id, action) VALUES (?, 'skip')"
                             " ON CONFLICT(generation_id) DO UPDATE SET action = 'skip', liked_file = NULL,"
                             " at = datetime('now')", (gid,))
            else:
                conn.execute("DELETE FROM feedback WHERE generation_id = ?", (gid,))
    return {"id": gid, "action": None if action == "clear" else action}


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def dashboard() -> dict:
    sync = read_json(SYNC / "status.json")
    sync["requested"] = (SYNC / "scan-now").exists()
    waiting = sum(1 for p in BOOKMARKS_IN.iterdir() if p.is_file()) if BOOKMARKS_IN.is_dir() else 0
    out = {"sync": sync, "waiting": waiting, "window": GENERATE_WINDOW, "bookmarks": {}, "dropped": {},
           "runs": [], "jobs": [], "liked": 0}
    try:
        with db() as conn:
            out["bookmarks"] = dict(conn.execute("SELECT medium, count(*) FROM bookmarks GROUP BY medium").fetchall())
            out["dropped"] = dict(conn.execute("SELECT reason, count(*) FROM dropped GROUP BY reason").fetchall())
            out["liked"] = conn.execute("SELECT count(*) FROM feedback WHERE action = 'like'").fetchone()[0]
            for r in conn.execute("SELECT night, status, stats, progress, started_at, finished_at FROM runs"
                                  " WHERE night NOT LIKE 'test-%' ORDER BY started_at DESC LIMIT 8"):
                run = dict(r)
                run["stats"] = json.loads(run["stats"]) if run["stats"] else {}
                run["progress"] = json.loads(run["progress"]) if run["progress"] else None
                out["runs"].append(run)
            out["jobs"] = [dict(r) | {"params": json.loads(r["params"])} for r in conn.execute(
                "SELECT id, params, status, night, message, created_at FROM jobs"
                " WHERE status IN ('queued', 'running') ORDER BY id")]
    except sqlite3.OperationalError:
        pass
    return out


def request_scan() -> dict:
    status = read_json(SYNC / "status.json")
    if status.get("state") != "running":
        SYNC.mkdir(exist_ok=True)
        (SYNC / "scan-now").touch()
    return {"ok": True}


def queue_generation(req: dict) -> dict:
    images, keep = int(req.get("images", 0)), int(req.get("keep", 0))
    mediums = [m for m in req.get("mediums") or [] if m in MEDIUMS]
    if not 1 <= images <= MAX_IMAGES:
        raise ValueError(f"images must be between 1 and {MAX_IMAGES}")
    if not 1 <= keep <= images:
        raise ValueError("keep must be between 1 and the number of images")
    if req.get("mediums") and not mediums:
        raise ValueError("pick at least one style")
    with db() as conn:
        busy = conn.execute("SELECT count(*) FROM jobs WHERE status IN ('queued', 'running')").fetchone()[0]
        if busy >= 3:
            raise ValueError("three requests are already waiting; let one finish first")
        gid = conn.execute("INSERT INTO jobs(params, status) VALUES (?, 'queued')",
                           (json.dumps({"images": images, "keep": keep, "mediums": mediums}),)).lastrowid
    return {"job": gid}


def cancel(req: dict) -> dict:
    with db() as conn:
        if "job" in req:
            conn.execute("UPDATE jobs SET status = 'cancelled', finished_at = datetime('now')"
                         " WHERE id = ? AND status = 'queued'", (int(req["job"]),))
        if "night" in req:
            conn.execute("UPDATE runs SET cancel = 1 WHERE night = ? AND status = 'running'", (str(req["night"]),))
    return {"ok": True}


class Handler(BaseHTTPRequestHandler):
    def send(self, code: int, body, ctype="application/json", cache="no-store"):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Security-Policy", CSP)
        for k, v in formlogin.SECURITY_HEADERS:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def query(self) -> dict:
        from urllib.parse import parse_qs, urlsplit
        return {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}

    def do_GET(self):
        path = self.path.split("?")[0]
        if formlogin.httpserver.handle(self, LOGIN, path):
            return
        if path in ("/", "/index.html"):
            return self.send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        if path == "/api/feed":
            q = self.query()
            try:
                offset = max(0, int(q.get("offset", "0")))
            except ValueError:
                return self.send(400, {"error": "offset must be a number"})
            return self.send(200, feed(q.get("view", "feed"), q.get("medium", "all"), offset))
        if path == "/api/summary":
            return self.send(200, summary())
        if path == "/api/dashboard":
            return self.send(200, dashboard())
        for prefix, thumb in (("/thumb/", True), ("/img/", False)):
            if path.startswith(prefix) and path[len(prefix):].isdigit():
                file = image_path(int(path[len(prefix):]), thumb)
                if not file:
                    return self.send(404, {"error": "image not found"})
                ctype = "image/png" if file.suffix == ".png" else "image/jpeg"
                return self.send(200, file.read_bytes(), ctype, "private, max-age=604800, immutable")
        self.send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        if formlogin.httpserver.handle(self, LOGIN, path):
            return
        actions = {"/api/feedback": self.feedback, "/api/scan": lambda r: request_scan(),
                   "/api/generate": queue_generation, "/api/cancel": cancel}
        if path not in actions:
            return self.send(404, {"error": "not found"})
        # JSON only: a plain cross-site form post can't set this content type.
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self.send(415, {"error": "send JSON"})
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            if not isinstance(req, dict):
                raise ValueError("send a JSON object")
            self.send(200, actions[path](req))
        except LookupError as e:
            self.send(404, {"error": str(e)})
        except (ValueError, TypeError) as e:
            self.send(400, {"error": str(e) or "bad request"})

    def feedback(self, req: dict) -> dict:
        try:
            gid, action = int(req["id"]), req["action"]
        except (KeyError, TypeError, ValueError):
            raise ValueError('send {"id": number, "action": "like" | "skip" | "clear"}')
        if action not in ("like", "skip", "clear"):
            raise ValueError('action must be "like", "skip" or "clear"')
        return set_feedback(gid, action)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    LOGIN = formlogin.Login.from_env(   # password: python -m formlogin passwd (see README)
        "DREAMFEED", "dreamfeed", STATE, title="dreamfeed", accent=("#b4321f", "#e5604a"),
        icon="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'>"
             "<circle cx='8' cy='8' r='6' fill='%23e5604a'/></svg>")
    print(time.strftime("%F %T"), f"web: feed on :{PORT}", flush=True)
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
