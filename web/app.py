"""dreamfeed feed page. Everything except the sign-in page needs a signed-in session (formlogin).

GET  /                  the page
GET  /api/feed          ?view=feed|liked&medium=all|photo|anime|furry&offset=N
GET  /api/summary       counts and the last run, for the header
GET  /thumb/<id>        small JPEG for the grid
GET  /img/<id>          full image for the viewer
POST /api/feedback      {"id": N, "action": "like"|"skip"|"clear"} (JSON only)
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
        if path != "/api/feedback":
            return self.send(404, {"error": "not found"})
        # JSON only: a plain cross-site form post can't set this content type.
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self.send(415, {"error": "send JSON"})
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            gid, action = int(req["id"]), req["action"]
            if action not in ("like", "skip", "clear"):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            return self.send(400, {"error": 'send {"id": number, "action": "like" | "skip" | "clear"}'})
        try:
            self.send(200, set_feedback(gid, action))
        except LookupError as e:
            self.send(404, {"error": str(e)})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    LOGIN = formlogin.Login.from_env(   # password: python -m formlogin passwd (see README)
        "DREAMFEED", "dreamfeed", STATE, title="dreamfeed", accent=("#b4321f", "#e5604a"),
        icon="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'>"
             "<circle cx='8' cy='8' r='6' fill='%23e5604a'/></svg>")
    print(time.strftime("%F %T"), f"web: feed on :{PORT}", flush=True)
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
