"""dreamfeed feed page. Everything except the sign-in page needs a signed-in session (formlogin).

GET  /                  the page
GET  /api/feed          ?view=feed|liked&medium=all|anime|furry&persona=HANDLE&offset=N
GET  /api/personas      the fictional posters, with post and like counts
GET  /avatar/<handle>   profile picture
GET  /api/summary       counts and the last run, for the header
GET  /thumb/<id>        small JPEG for the grid
GET  /img/<id>          full image for the viewer
GET  /api/dashboard     queue and recent runs
GET  /api/personas/edit every persona as stored in data/personas.json, plus the trained styles
POST /api/personas/save {"persona": {...}, "original": HANDLE|null} add or change one (checked first)
POST /api/personas/delete  {"handle": H} remove one; their posts leave the timeline
POST /api/personas/avatar  {"handle": H} new profile picture the next time they post
GET  /api/styles        trained and in-progress style LoRAs
POST /api/styles/train  {"name", "medium", "source", "limit", "steps"} download, check and train one
POST /api/styles/cancel {"name": N} stop a style job
POST /api/feedback      {"id": N, "action": "like"|"skip"|"clear"}
POST /api/generate      {"images": N, "keep": K, "mediums": [...], "personas": [...]} queue a generation run
POST /api/cancel        {"night": "..."} or {"job": N} stop a run or queued request
POST /api/animate       {"id": N, "prompt": "..."} or {"count": N} make Wan 2.2 clips from feed images
(POSTs are JSON only.)
"""
import json
import os
import re
import shutil
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import formlogin
import formlogin.httpserver

from dreamfeed import personas as people   # the worker's own persona rules (see Dockerfile)


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
PERSONAS = DATA / "personas.json"
LORA_DIR = Path(required("LORA_DIR"))
GENERATE_WINDOW = required("GENERATE_WINDOW")
MAX_IMAGES = 400
PORT = 8000
PAGE_SIZE = 30
MEDIUMS = ("anime", "furry")
HANDLE = re.compile(r"^[a-z0-9_]{2,20}$")
CSP = ("default-src 'self'; img-src 'self' data:; media-src 'self'; style-src 'self' 'unsafe-inline'; "
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
    return {"id": row["id"], "night": row["night"], "medium": row["medium"], "kind": row["kind"],
            "score": round(row["score"] or 0, 3), "liked": row["action"] == "like",
            "animated": bool(row["animated"]), "caption": row["caption"] or "",
            "posted": row["posted_at"] or row["created_at"],
            "persona": {"handle": row["persona"], "name": row["name"] or row["persona"],
                        "avatar": bool(row["avatar"])} if row["persona"] else None}


def feed(view: str, medium: str, offset: int, persona: str = "") -> dict:
    where, args = [], []
    if medium in MEDIUMS:
        where.append("g.medium = ?")
        args.append(medium)
    if persona:
        where.append("g.persona = ?")
        args.append(persona)
    if view == "liked":
        where.append("f.action = 'like'")
        order = "f.at DESC"
    else:   # the timeline: persona posts only (v1 images stay reachable from Liked)
        where.append("g.status = 'feed' AND p.active = 1 AND (f.action IS NULL OR f.action = 'like')")
        order = "coalesce(g.posted_at, g.created_at) DESC, g.id DESC"
    sql = (f"SELECT g.id, g.night, g.medium, g.score, g.kind, g.caption, g.persona, g.posted_at, g.created_at,"
           f" f.action, p.name, p.avatar,"
           f" EXISTS(SELECT 1 FROM generations v WHERE v.source_generation = g.id AND v.kind = 'video'"
           f"        AND v.status IN ('queued', 'generated', 'feed')) AS animated FROM generations g"
           f" LEFT JOIN feedback f ON f.generation_id = g.id LEFT JOIN personas p ON p.handle = g.persona"
           f" WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ? OFFSET ?")
    try:
        with db() as conn:
            rows = conn.execute(sql, (*args, PAGE_SIZE + 1, offset)).fetchall()
    except sqlite3.OperationalError:   # worker hasn't created its tables yet
        return {"items": [], "more": False}
    return {"items": [item(r) for r in rows[:PAGE_SIZE]], "more": len(rows) > PAGE_SIZE}


def personas() -> dict:
    try:
        with db() as conn:
            rows = conn.execute(
                "SELECT p.handle, p.name, p.medium, p.bio, p.avatar IS NOT NULL AS avatar,"
                " (SELECT count(*) FROM generations g WHERE g.persona = p.handle AND g.status = 'feed') AS posts,"
                " (SELECT count(*) FROM generations g JOIN feedback f ON f.generation_id = g.id"
                "  WHERE g.persona = p.handle AND f.action = 'like') AS likes"
                " FROM personas p WHERE p.active = 1 ORDER BY p.name").fetchall()
    except sqlite3.OperationalError:   # worker hasn't created its tables yet
        return {"personas": []}
    return {"personas": [dict(r) | {"avatar": bool(r["avatar"])} for r in rows]}


def avatar_path(handle: str) -> Path | None:
    if not HANDLE.match(handle):
        return None
    with db() as conn:
        row = conn.execute("SELECT avatar FROM personas WHERE handle = ?", (handle,)).fetchone()
    if not row or not row["avatar"]:
        return None
    path = (GENERATED / row["avatar"]).resolve()
    return path if path.is_relative_to(GENERATED.resolve()) and path.is_file() else None


def summary() -> dict:
    out = {"unrated": 0, "liked": 0, "last_run": None}
    try:
        with db() as conn:
            out["unrated"] = conn.execute(
                "SELECT count(*) FROM generations g LEFT JOIN feedback f ON f.generation_id = g.id"
                " JOIN personas p ON p.handle = g.persona"
                " WHERE g.status = 'feed' AND p.active = 1 AND f.action IS NULL").fetchone()[0]
            out["liked"] = conn.execute("SELECT count(*) FROM feedback WHERE action = 'like'").fetchone()[0]
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
        row = conn.execute("SELECT g.id, g.night, g.medium, g.score, g.file, g.status, g.persona, f.action, f.liked_file"
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
                copy = f"{row['night']}-{row['persona'] or row['medium']}-{gid}{src.suffix}"
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
    out = {"window": GENERATE_WINDOW, "runs": [], "jobs": [], "liked": 0}
    try:
        with db() as conn:
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


def queue_generation(req: dict) -> dict:
    images, keep = int(req.get("images", 0)), int(req.get("keep", 0))
    mediums = [m for m in req.get("mediums") or [] if m in MEDIUMS]
    handles = [str(h) for h in req.get("personas") or [] if HANDLE.match(str(h))]
    if not 1 <= images <= MAX_IMAGES:
        raise ValueError(f"images must be between 1 and {MAX_IMAGES}")
    if not 1 <= keep <= images:
        raise ValueError("keep must be between 1 and the number of images")
    if req.get("mediums") and not mediums:
        raise ValueError("pick at least one style")
    with db() as conn:
        if handles:
            known = {r[0] for r in conn.execute("SELECT handle FROM personas WHERE active = 1")}
            if not set(handles) <= known:
                raise ValueError("unknown persona")
        busy = conn.execute("SELECT count(*) FROM jobs WHERE status IN ('queued', 'running')").fetchone()[0]
        if busy >= 3:
            raise ValueError("three requests are already waiting; let one finish first")
        params = {"images": images, "keep": keep, "mediums": mediums}
        if handles:
            params["personas"] = handles
        gid = conn.execute("INSERT INTO jobs(params, status) VALUES (?, 'queued')",
                           (json.dumps(params),)).lastrowid
    return {"job": gid}


MAX_PROMPT = 500
# Quick check so a refused prompt fails here, visibly. The worker enforces the full list
# (worker/dreamfeed/safety.py) on every prompt regardless.
BLOCKED_WORDS = re.compile(r"\b(child|children|kid|kids|toddler|baby|babies|loli|lolicon|shota|shotacon|teen|"
                           r"teens|teenage|teenager|underage|minor|minors|young|cub|preteen|schoolgirl|"
                           r"schoolboy|school uniform|petite|flat chest)\b", re.I)


def request_animation(req: dict) -> dict:
    with db() as conn:
        busy = conn.execute("SELECT count(*) FROM jobs WHERE status IN ('queued', 'running')").fetchone()[0]
        if busy >= 3:
            raise ValueError("three requests are already waiting; let one finish first")
        if "id" in req:
            gid = int(req["id"])
            row = conn.execute("SELECT kind, status FROM generations WHERE id = ?", (gid,)).fetchone()
            if not row or row["kind"] != "image" or row["status"] != "feed":
                raise LookupError("only images in the feed can be animated")
            text = " ".join(str(req.get("prompt") or "").split())
            if len(text) > MAX_PROMPT:
                raise ValueError(f"keep the description under {MAX_PROMPT} characters")
            bad = sorted({m.group(0).lower() for m in BLOCKED_WORDS.finditer(text)})
            if bad:
                raise ValueError(f"the description can't include: {', '.join(bad)}")
            params = {"kind": "animate", "ids": [gid]}
            if text:
                params["prompt"] = text
            # Same image with a new description is fine; the identical request twice is a double tap.
            dup = conn.execute("SELECT count(*) FROM jobs WHERE status IN ('queued', 'running') AND params = ?",
                               (json.dumps(params),)).fetchone()[0]
            if dup:
                raise ValueError("this exact animation is already waiting")
        else:
            count = int(req.get("count", 0))
            if not 1 <= count <= 50:
                raise ValueError("count must be between 1 and 50")
            params = {"kind": "animate", "count": count}
        jid = conn.execute("INSERT INTO jobs(params, status) VALUES (?, 'queued')", (json.dumps(params),)).lastrowid
    return {"job": jid}


def cancel(req: dict) -> dict:
    with db() as conn:
        if "job" in req:
            conn.execute("UPDATE jobs SET status = 'cancelled', finished_at = datetime('now')"
                         " WHERE id = ? AND status = 'queued'", (int(req["job"]),))
        if "night" in req:
            conn.execute("UPDATE runs SET cancel = 1 WHERE night = ? AND status = 'running'", (str(req["night"]),))
    return {"ok": True}


# ---------- persona editor ----------
# Edits go to data/personas.json, the same file the worker reads every run. Each save is
# checked with the worker's own rules (blocked tags, placeholders, strict mode) before it is
# written, so a bad edit is refused here instead of breaking the nightly run.
EDIT_LOCK = threading.Lock()
TEXT_FIELDS = {"name": 60, "bio": 300, "look": 1000, "avatar": 500, "negative": 500, "based_on": 200}
LIST_FIELDS = {"characters": (30, 300), "outfits": (40, 200), "settings": (40, 200), "emoji": (10, 16),
               "hashtags": (10, 40)}
MAX_POST_KINDS = 12
NEW_FILE = {"_note": "Private. Fictional posters for the dreamfeed timeline, edited from the dashboard or by hand. "
                     "based_on is a private reminder only; it is never shown or used in prompts.", "personas": []}


def read_personas() -> dict:
    if not PERSONAS.is_file():
        return json.loads(json.dumps(NEW_FILE))
    raw = json.loads(PERSONAS.read_text())
    raw.setdefault("personas", [])
    return raw


def write_personas(raw: dict) -> None:
    tmp = PERSONAS.with_name(PERSONAS.name + ".tmp")
    tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
    if PERSONAS.is_file():
        shutil.copy2(PERSONAS, PERSONAS.with_name(PERSONAS.name + ".bak"))   # one step of undo
    os.replace(tmp, PERSONAS)


def styles() -> list[dict]:
    """Trained style LoRAs: a prep.json from lora-prep and the trainer's output file."""
    out = []
    for prep in sorted((DATA / "lora").glob("*/prep.json")):
        info, name = read_json(prep), prep.parent.name
        file = f"style-{name}.safetensors"
        if info.get("trigger") and info.get("medium") in MEDIUMS and (LORA_DIR / file).is_file():
            out.append({"name": name, "medium": info["medium"], "trigger": info["trigger"], "file": file})
    return out


def voices() -> dict[str, int]:
    """Styles whose artist's post texts were saved (voice.json): name -> how many posts."""
    out = {}
    for f in sorted((DATA / "lora").glob("*/voice.json")):
        n = len(read_json(f).get("posts") or [])
        if n:
            out[f.parent.name] = n
    return out


def persona_config() -> dict:
    out = {"personas": [], "styles": styles(), "voices": voices(), "error": None,
           "ratings": list(people.RATINGS), "mediums": list(MEDIUMS)}
    try:
        raw = read_personas()
    except ValueError as e:
        out["error"] = f"data/personas.json is not valid JSON: {e}"
        return out
    try:
        checked = {p.handle: p for p in people.parse(raw)}
    except (ValueError, TypeError) as e:
        checked, out["error"] = {}, str(e)
    with db() as conn:
        avatars = {r[0] for r in conn.execute("SELECT handle FROM personas WHERE avatar IS NOT NULL")}
    for entry in raw["personas"]:
        p = checked.get(entry.get("handle"))
        lo = entry.get("lora") or None
        out["personas"].append(entry | {
            "strict": bool(p and p.strict), "has_avatar": entry.get("handle") in avatars,
            "lora": lo and {"style": str(lo.get("file", "")).removeprefix("style-").removesuffix(".safetensors"),
                            "strength": lo.get("strength", 0.8), "female_only": bool(lo.get("female_only")),
                            "enabled": lo.get("enabled", True) is not False}})
    return out


def _text(v, limit: int, what: str) -> str:
    v = " ".join(str(v or "").split())
    if len(v) > limit:
        raise ValueError(f"{what} is too long (at most {limit} characters)")
    return v


def _list(v, n: int, limit: int, what: str) -> list[str]:
    items = [_text(x, limit, what) for x in (v or []) if str(x).strip()]
    if len(items) > n:
        raise ValueError(f"at most {n} {what}")
    return items


def _num(v, lo: float, hi: float, what: str) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number")
    if not lo <= x <= hi:
        raise ValueError(f"{what} must be between {lo:g} and {hi:g}")
    return round(x, 3)


def _apply(entry: dict, src: dict) -> dict:
    """The editable fields from the dashboard onto the stored entry (other keys are kept)."""
    if not isinstance(src, dict):
        raise ValueError("send the persona as an object")
    entry = dict(entry)
    for k, limit in TEXT_FIELDS.items():
        if k in src:
            entry[k] = _text(src[k], limit, k)
            if not entry[k] and k != "name":
                entry.pop(k)
    for k, (n, limit) in LIST_FIELDS.items():
        if k in src:
            entry[k] = _list(src[k], n, limit, k)
            if not entry[k]:
                entry.pop(k)
    if "medium" in src:
        entry["medium"] = src["medium"]
    if "weight" in src:
        entry["weight"] = _num(src["weight"], 0.1, 5, "how often they post")
    if "video_share" in src:
        entry["video_share"] = _num(src["video_share"], 0, 1, "video share")
    if "paused" in src:
        entry["paused"] = bool(src["paused"])
        if not entry["paused"]:
            entry.pop("paused")
    if "posts" in src:
        if not isinstance(src["posts"], list) or len(src["posts"]) > MAX_POST_KINDS:
            raise ValueError(f"at most {MAX_POST_KINDS} kinds of post")
        entry["posts"] = [{"kind": _text(k.get("kind") or "post", 40, "kind"),
                           "weight": _num(k.get("weight", 1), 0.1, 10, "post weight"),
                           "rating": k.get("rating") if k.get("rating") in people.RATINGS else "explicit",
                           "prompt": _text(k.get("prompt"), 1000, "prompt"),
                           "captions": _list(k.get("captions"), 30, 280, "captions")}
                          for k in src["posts"] if isinstance(k, dict)]
    if "voice" in src:
        v = str(src["voice"] or "")
        if v and v != entry.get("voice") and v not in voices():
            raise ValueError("pick a style that has saved posts for captions")
        entry["voice"] = v
        if not v:
            entry.pop("voice")
    if "lora" in src:
        entry["lora"] = _lora(entry.get("lora"), src["lora"], entry.get("medium"))
        if not entry["lora"]:
            entry.pop("lora")
    return entry


def _lora(old: dict | None, want, medium: str | None) -> dict | None:
    if not want:
        return None
    if not isinstance(want, dict):
        raise ValueError("bad style settings")
    name = str(want.get("style", ""))
    style = next((s for s in styles() if s["name"] == name), None)
    if style:
        if style["medium"] != medium:
            raise ValueError(f"the {name} style is trained for {style['medium']}, not {medium}")
        out = {"file": style["file"], "trigger": style["trigger"]}
    elif old and str(old.get("file", "")) == f"style-{name}.safetensors":
        out = {"file": old["file"], "trigger": old.get("trigger", "")}   # file missing for now; keep it
    else:
        raise ValueError("pick a trained style")
    out["strength"] = _num(want.get("strength", 0.8), 0.2, 1.2, "style strength")
    if want.get("female_only"):
        out["female_only"] = True
    if want.get("enabled", True) is False:
        out["enabled"] = False
    return out


def _commit(raw: dict) -> list:
    checked = people.parse(raw)   # people.Invalid (a ValueError) becomes a 400 with its message
    write_personas(raw)
    with db() as conn:
        people.sync(conn, checked)
    return checked


def save_persona(req: dict) -> dict:
    original = req.get("original")
    with EDIT_LOCK:
        raw = read_personas()
        handles = [p.get("handle") for p in raw["personas"]]
        if original:
            if original not in handles:
                raise LookupError("that persona no longer exists; reload the page")
            i = handles.index(original)
            raw["personas"][i] = _apply(raw["personas"][i], req.get("persona")) | {"handle": original}
        else:
            handle = str((req.get("persona") or {}).get("handle", "")).strip().lower()
            if not HANDLE.match(handle):
                raise ValueError("handle must be 2-20 of a-z 0-9 _")
            if handle in handles:
                raise ValueError(f"@{handle} is taken")
            with db() as conn:   # a removed persona's old posts would come back under the new one
                if conn.execute("SELECT 1 FROM personas WHERE handle = ?", (handle,)).fetchone():
                    raise ValueError(f"@{handle} was used before; pick another handle")
            raw["personas"].append(_apply({"handle": handle}, req.get("persona")) | {"handle": handle})
        _commit(raw)
    return {"ok": True}


def delete_persona(req: dict) -> dict:
    handle = str(req.get("handle", ""))
    with EDIT_LOCK:
        raw = read_personas()
        keep = [p for p in raw["personas"] if p.get("handle") != handle]
        if len(keep) == len(raw["personas"]):
            raise LookupError("no such persona")
        raw["personas"] = keep
        _commit(raw)
    return {"ok": True}


def new_avatar(req: dict) -> dict:
    handle = str(req.get("handle", ""))
    if not HANDLE.match(handle):
        raise ValueError("bad handle")
    with db() as conn:
        row = conn.execute("SELECT avatar FROM personas WHERE handle = ? AND active = 1", (handle,)).fetchone()
        if not row:
            raise LookupError("no such persona")
        conn.execute("UPDATE personas SET avatar = NULL WHERE handle = ?", (handle,))
    if row["avatar"]:
        old = (GENERATED / row["avatar"]).resolve()
        if old.is_relative_to(GENERATED.resolve()):
            old.unlink(missing_ok=True)
    return {"ok": True}


# ---------- style training ----------
# A "style" job for the worker: download the source's images, check them (photos and
# anything the adults-only checks flag are dropped), then the trainer service trains.
STYLE_LIMITS = (100, 300, 600)
STYLE_STEPS = (1000, 2000, 3000)


def style_list() -> dict:
    lora = DATA / "lora"
    with db() as conn:
        jobs = {json.loads(r["params"]).get("name"): dict(r) for r in conn.execute(
            "SELECT id, params, status FROM jobs WHERE status IN ('queued', 'running')"
            " AND params LIKE '%\"kind\": \"style\"%'")}
    try:
        users = {}
        for p in read_personas()["personas"]:
            f = str((p.get("lora") or {}).get("file", ""))
            if f and (p.get("lora") or {}).get("enabled", True) is not False:
                users.setdefault(f, []).append(p.get("name") or p.get("handle"))
    except ValueError:
        users = {}
    out = []
    for d in sorted(x for x in lora.iterdir() if x.is_dir() and not x.name.startswith(".")) if lora.is_dir() else []:
        prep, src, st = read_json(d / "prep.json"), read_json(d / "source.json"), read_json(d / "status.json")
        file = LORA_DIR / f"style-{d.name}.safetensors"
        job = jobs.get(d.name)
        out.append({"name": d.name, "medium": src.get("medium") or prep.get("medium"), "kept": prep.get("kept"),
                    "voice": len(read_json(d / "voice.json").get("posts") or []),
                    "source": src.get("source"), "limit": src.get("limit"), "steps": src.get("steps"),
                    "trained": int(file.stat().st_mtime) if file.is_file() else None,
                    "used_by": users.get(file.name, []),
                    "job": job and {"status": job["status"]},
                    # status.json is only live while a job runs; otherwise it is the last result
                    "status": st if job or st.get("phase") in ("failed", "cancelled") else None})
    return {"styles": out, "limits": STYLE_LIMITS, "steps": STYLE_STEPS}


def queue_style(req: dict) -> dict:
    name = str(req.get("name", "")).strip().lower()
    medium, source = req.get("medium"), str(req.get("source", "")).strip()
    if not HANDLE.match(name):
        raise ValueError("name must be 2-20 of a-z 0-9 _")
    if medium not in MEDIUMS:
        raise ValueError("pick anime or furry")
    if not re.match(r"^https://[^\s/]+\.[^\s/]+/\S*$", source) or len(source) > 300:
        raise ValueError("the source must be an https:// link to the artist's page")
    try:
        limit, steps = int(req.get("limit", 300)), int(req.get("steps", 2000))
    except (TypeError, ValueError):
        raise ValueError("bad numbers")
    if limit not in STYLE_LIMITS or steps not in STYLE_STEPS:
        raise ValueError("pick one of the offered sizes")
    known = next((s for s in style_list()["styles"] if s["name"] == name), None)
    if known and known["medium"] and known["medium"] != medium:
        raise ValueError(f"the {name} style is {known['medium']}; use another name for {medium}")
    with db() as conn:
        if conn.execute("SELECT count(*) FROM jobs WHERE status IN ('queued', 'running')"
                        " AND params LIKE '%\"kind\": \"style\"%'").fetchone()[0]:
            raise ValueError("a style is already being trained; one at a time")
        jid = conn.execute("INSERT INTO jobs(params, status) VALUES (?, 'queued')", (json.dumps(
            {"kind": "style", "name": name, "medium": medium, "source": source, "limit": limit,
             "steps": steps}),)).lastrowid
    return {"job": jid}


def cancel_style(req: dict) -> dict:
    name = str(req.get("name", ""))
    if not HANDLE.match(name):
        raise ValueError("bad name")
    with db() as conn:
        for r in conn.execute("SELECT id, params, status FROM jobs WHERE status IN ('queued', 'running')"
                              " AND params LIKE '%\"kind\": \"style\"%'").fetchall():
            if json.loads(r["params"]).get("name") != name:
                continue
            if r["status"] == "queued":
                conn.execute("UPDATE jobs SET status = 'cancelled', finished_at = datetime('now') WHERE id = ?",
                             (r["id"],))
            else:
                (DATA / "lora" / name / "cancel").touch()   # the worker and trainer watch for this
            return {"ok": True}
    raise LookupError("nothing is running for that style")


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

    def send_file(self, file: Path) -> None:
        """Images whole; videos also in byte ranges, which phones need to play them."""
        ctype = {".png": "image/png", ".mp4": "video/mp4"}.get(file.suffix, "image/jpeg")
        size = file.stat().st_size
        start, end = 0, size - 1
        rng = self.headers.get("Range", "")
        partial = rng.startswith("bytes=") and "," not in rng
        if partial:
            a, _, b = rng[6:].partition("-")
            try:
                if a:
                    start, end = int(a), min(int(b) if b else size - 1, size - 1)
                else:
                    start = max(0, size - int(b))
            except ValueError:
                partial = False
            if partial and start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "private, max-age=604800, immutable")
        self.send_header("Content-Security-Policy", CSP)
        for k, v in formlogin.SECURITY_HEADERS:
            self.send_header(k, v)
        self.end_headers()
        with file.open("rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = f.read(min(1 << 20, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

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
            persona = q.get("persona", "")
            if persona and not HANDLE.match(persona):
                return self.send(400, {"error": "bad persona"})
            return self.send(200, feed(q.get("view", "feed"), q.get("medium", "all"), offset, persona))
        if path == "/api/personas":
            return self.send(200, personas())
        if path == "/api/personas/edit":
            return self.send(200, persona_config())
        if path == "/api/styles":
            return self.send(200, style_list())
        if path.startswith("/avatar/"):
            file = avatar_path(path[len("/avatar/"):])
            if not file:
                return self.send(404, {"error": "no profile picture yet"})
            return self.send_file(file)
        if path == "/api/summary":
            return self.send(200, summary())
        if path == "/api/dashboard":
            return self.send(200, dashboard())
        for prefix, thumb in (("/thumb/", True), ("/img/", False)):
            if path.startswith(prefix) and path[len(prefix):].isdigit():
                file = image_path(int(path[len(prefix):]), thumb)
                if not file:
                    return self.send(404, {"error": "image not found"})
                return self.send_file(file)
        self.send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        if formlogin.httpserver.handle(self, LOGIN, path):
            return
        actions = {"/api/feedback": self.feedback, "/api/generate": queue_generation, "/api/cancel": cancel,
                   "/api/animate": request_animation, "/api/personas/save": save_persona,
                   "/api/personas/delete": delete_persona, "/api/personas/avatar": new_avatar,
                   "/api/styles/train": queue_style, "/api/styles/cancel": cancel_style}
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
