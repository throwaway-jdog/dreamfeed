"""The persona posts: the persona feed, likes and skips, their pictures, the dashboard's summary,
and the generation jobs (posts, clips, scenes) asked for from it.
"""
import json
import shutil
import sqlite3
from pathlib import Path

from dreamfeed.core import acts, cookies, personas as people, safety

from .common import GENERATED, GENERATE_WINDOW, HANDLE, LIKED, MAX_IMAGES, MEDIUMS, PAGE_SIZE, db, item
from .feed import saved_view


def feed(view: str, medium: str, offset: int, persona: str = "", gid: int | None = None) -> dict:
    """A page of the persona feed; gid: just that post (its own page), unless you skipped it."""
    where, args = [], []
    if gid is not None:
        where.append("g.id = ? AND g.status = 'feed' AND (f.action IS NULL OR f.action = 'like')")
        args.append(gid)
        view, medium, persona = "item", "", ""
    if medium in MEDIUMS:
        where.append("g.medium = ?")
        args.append(medium)
    if persona:
        where.append("g.persona = ?")
        args.append(persona)
    if view == "liked":
        return saved_view(medium, offset)
    elif view == "item":
        order = "g.id"
    else:   # the timeline: persona posts only (v1 images stay reachable from Liked)
        where.append("g.status = 'feed' AND p.active = 1 AND (f.action IS NULL OR f.action = 'like')")
        order = "coalesce(g.posted_at, g.created_at) DESC, g.id DESC"
    sql = (f"SELECT g.id, g.night, g.medium, g.score, g.kind, g.caption, g.persona, g.posted_at, g.created_at,"
           f" g.checkpoint,"
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
    out = {"unrated": 0, "liked": 0, "last_run": None, "live": 0}
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
            out["live"] = conn.execute("SELECT count(*) FROM follows WHERE live = 1").fetchone()[0]
    except sqlite3.OperationalError:    # (follows: the follow service hasn't started yet)
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
                job = conn.execute("SELECT id, params, status, message FROM jobs WHERE night = ? ORDER BY id DESC LIMIT 1",
                                   (r["night"],)).fetchone()
                run["message"] = job["message"] if job else None   # why a job's run failed, what it made
                if job and job["status"] == "failed" and json.loads(job["params"]).get("kind") in RETRYABLE \
                        and not _retried(conn, job["id"], job["params"]):
                    run["retry"] = job["id"]
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
        params = {"images": images, "keep": keep, "mediums": mediums}
        if handles:
            params["personas"] = handles
        gid = conn.execute("INSERT INTO jobs(params, status) VALUES (?, 'queued')",
                           (json.dumps(params),)).lastrowid
    return {"job": gid}


MAX_PROMPT = 500


def scene_acts(req: dict) -> dict:
    """The acts a scene from this post can be made of, for the picker."""
    with db() as conn:
        row = conn.execute("SELECT prompt FROM generations WHERE id = ? AND kind = 'image'",
                           (int(req.get("id", 0)),)).fetchone()
    if not row:
        raise LookupError("no such image")
    k = acts.kind(row[0] or "")
    return {"kind": k, "slots": [{"slot": s, "label": label, "options": list(opts)} for s, label, opts in acts.SLOTS[k]]}


def request_animation(req: dict) -> dict:
    with db() as conn:
        if "id" in req:
            gid = int(req["id"])
            row = conn.execute("SELECT kind, status FROM generations WHERE id = ?", (gid,)).fetchone()
            if not row or row["kind"] != "image" or row["status"] != "feed":
                raise LookupError("only images in the feed can be animated")
            if req.get("scene"):
                tags = conn.execute("SELECT coalesce(tags, prompt) FROM generations WHERE id = ?", (gid,)).fetchone()[0]
                # POV pictures show only part of him: the tagger says 1boy or hetero, not duo.
                if not {"duo", "1boy", "hetero", "2girls", "yuri"} & {t.strip() for t in (tags or "").split(",")}:
                    raise ValueError("scenes need a post with two characters")
                prompt = conn.execute("SELECT prompt FROM generations WHERE id = ?", (gid,)).fetchone()[0] or ""
                picks = acts.checked(prompt, req.get("picks"))   # chosen acts; the rest random
                params = {"kind": "scene", "ids": [gid]} | ({"picks": picks} if picks else {})
                if conn.execute("SELECT count(*) FROM jobs WHERE status IN ('queued', 'running') AND params = ?",
                                (json.dumps(params),)).fetchone()[0]:
                    raise ValueError("a scene from this post is already waiting")
                jid = conn.execute("INSERT INTO jobs(params, status) VALUES (?, 'queued')",
                                   (json.dumps(params),)).lastrowid
                return {"job": jid}
            text = " ".join(str(req.get("prompt") or "").split())
            if len(text) > MAX_PROMPT:
                raise ValueError(f"keep the description under {MAX_PROMPT} characters")
            bad = safety.request_blocked(text)   # the worker checks every prompt again regardless
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


RETRYABLE = ("comic_animate", "comic_import", "comic", "animate", "scene")   # job kinds Try again can repeat


def _retried(conn, job: int, params: str) -> bool:
    """Whether the same request was queued again after job."""
    return bool(conn.execute("SELECT 1 FROM jobs WHERE id > ? AND params = ? LIMIT 1", (job, params)).fetchone())


def retry_job(req: dict) -> dict:
    """{"job"}: a failed request queued again exactly as it was asked (a panel's outline too)."""
    with db() as conn:
        row = conn.execute("SELECT params, status FROM jobs WHERE id = ?", (int(req.get("job", 0)),)).fetchone()
        if not row:
            raise LookupError("no such request")
        if row["status"] != "failed" or json.loads(row["params"]).get("kind") not in RETRYABLE:
            raise ValueError("only a failed animation, scene or comic can be tried again")
        if conn.execute("SELECT count(*) FROM jobs WHERE status IN ('queued', 'running') AND params = ?",
                        (row["params"],)).fetchone()[0]:
            raise ValueError("it's already waiting to be tried again")
        jid = conn.execute("INSERT INTO jobs(params, status) VALUES (?, 'queued')", (row["params"],)).lastrowid
    return {"job": jid}


def cancel(req: dict) -> dict:
    with db() as conn:
        if "job" in req:
            conn.execute("UPDATE jobs SET status = 'cancelled', finished_at = datetime('now')"
                         " WHERE id = ? AND status = 'queued'", (int(req["job"]),))
        if "night" in req:
            conn.execute("UPDATE runs SET cancel = 1 WHERE night = ? AND status = 'running'", (str(req["night"]),))
    return {"ok": True}
