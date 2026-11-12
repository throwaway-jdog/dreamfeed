"""The persona editor, trained styles and video LoRAs (training them), and persona drafts.
"""
import json
import os
import re
import shutil
import threading
from pathlib import Path

from dreamfeed.core import acts, cookies, personas as people, safety

from .common import DATA, GENERATED, HANDLE, LORA_DIR, MEDIUMS, PERSONAS, db, read_json


# ---------- persona editor ----------
# Edits go to data/personas.json, the same file the worker reads every run. Each save is
# checked with the worker's own rules (blocked tags, placeholders, strict mode) before it is
# written, so a bad edit is refused here instead of breaking the nightly run.
EDIT_LOCK = threading.Lock()
TEXT_FIELDS = {"name": 60, "bio": 300, "look": 1000, "avatar": 500, "negative": 500, "based_on": 200}
LIST_FIELDS = {"characters": (30, 300), "outfits": (40, 200), "partners": (30, 200), "girlfriends": (30, 200), "friends": (10, 20), "must_not_show": (12, 60), "settings": (40, 200), "emoji": (10, 16),
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
    """Styles with a saved voice (voice.json): name -> how many lines, the character's
    speech-bubble lines when there are any (what captions use), else the artist's posts."""
    out = {}
    for f in sorted((DATA / "lora").glob("*/voice.json")):
        d = read_json(f)
        n = len(d.get("speech") or d.get("posts") or [])
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
        art = entry.get("art") or None
        out["personas"].append(entry | {
            "art": art and {"style": str(art.get("file", "")).removeprefix("style-").removesuffix(".safetensors"),
                            "strength": art.get("strength", 0.5), "enabled": art.get("enabled", True) is not False},
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
    if "must_show" in src:   # traits, each a list of tags any of which counts
        groups = [_list(g, 6, 60, "must show") for g in (src["must_show"] or [])[:8] if isinstance(g, list)]
        entry["must_show"] = [g for g in groups if g]
        if not entry["must_show"]:
            entry.pop("must_show")
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
    if "art" in src:   # the artist's style, with a character LoRA in "lora"
        entry["art"] = _lora(entry.get("art"), src["art"], entry.get("medium"))
        if entry["art"]:
            entry["art"].pop("female_only", None)
        else:
            entry.pop("art")
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
VIDEO_LIMITS = (100, 300, 600)        # videos to download from the artist's page
VIDEO_STEPS = (1000, 1500, 2000)      # per half of Wan 2.2


def _jobs(kind: str) -> dict[str, dict]:
    """Queued and running jobs of one kind, by style name."""
    with db() as conn:
        return {json.loads(r["params"]).get("name"): dict(r) for r in conn.execute(
            "SELECT id, params, status FROM jobs WHERE status IN ('queued', 'running')"
            " AND params LIKE ?", (f'%"kind": "{kind}"%',))}


def _video(d: Path, st: dict, job: dict | None) -> dict:
    """A style's video LoRA: when both halves were trained, the clips, and progress."""
    halves = [LORA_DIR / f"video-{d.name}-{part}.safetensors" for part in ("high", "low")]
    prep = read_json(d / "video-prep.json")
    live = {k.removeprefix("video_"): v for k, v in st.items() if k.startswith("video_")}
    return {"trained": int(min(f.stat().st_mtime for f in halves)) if all(f.is_file() for f in halves) else None,
            "clips": prep.get("kept"), "limit": live.get("limit"), "steps": live.get("steps"),
            "job": job and {"status": job["status"]},
            "status": live if job or live.get("phase") in ("failed", "cancelled") else None}


def style_list() -> dict:
    lora = DATA / "lora"
    jobs, video_jobs = _jobs("style"), _jobs("video_style")
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
                    "status": st if job or st.get("phase") in ("failed", "cancelled") else None,
                    "video": _video(d, st, video_jobs.get(d.name))})
    return {"styles": out, "limits": STYLE_LIMITS, "steps": STYLE_STEPS,
            "video_limits": VIDEO_LIMITS, "video_steps": VIDEO_STEPS}


MAX_DESCRIPTION = 2000


def queue_draft(req: dict) -> dict:
    """Have the worker draft a persona from a description (worker/dreamfeed/builder.py)."""
    text = " ".join(str(req.get("description") or "").split())
    if len(text) < 10:
        raise ValueError("describe them in a few words: who they are and what they post")
    if len(text) > MAX_DESCRIPTION:
        raise ValueError(f"keep the description under {MAX_DESCRIPTION} characters")
    with db() as conn:
        if conn.execute("SELECT count(*) FROM jobs WHERE status IN ('queued', 'running')"
                        " AND params LIKE '%\"kind\": \"persona_draft\"%'").fetchone()[0]:
            raise ValueError("a persona is already being drafted; one at a time")
        jid = conn.execute("INSERT INTO jobs(params, status) VALUES (?, 'queued')",
                           (json.dumps({"kind": "persona_draft", "description": text}),)).lastrowid
    return {"job": jid}


def draft_status(job: int) -> dict:
    with db() as conn:
        row = conn.execute("SELECT params, status, message FROM jobs WHERE id = ?", (job,)).fetchone()
        if not row or json.loads(row["params"]).get("kind") != "persona_draft":
            raise LookupError("no such draft")
        ahead = conn.execute("SELECT count(*) FROM jobs WHERE status IN ('queued', 'running') AND id < ?",
                             (job,)).fetchone()[0]
        night = conn.execute("SELECT count(*) FROM runs WHERE status = 'running' AND night GLOB '[0-9]*'"
                             ).fetchone()[0]
    out = {"status": row["status"], "message": row["message"], "ahead": ahead, "night_running": bool(night)}
    if row["status"] == "done":
        out["draft"] = read_json(DATA / "drafts" / f"{job}.json") or None
    return out


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
             "steps": steps, "videos": bool(req.get("videos"))}),)).lastrowid
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


def queue_video(req: dict) -> dict:
    """Train a video LoRA for a trained style from the artist's own animations."""
    name = str(req.get("name", ""))
    if not HANDLE.match(name):
        raise ValueError("bad name")
    try:
        limit, steps = int(req.get("limit", 300)), int(req.get("steps", 1500))
    except (TypeError, ValueError):
        raise ValueError("bad numbers")
    if limit not in VIDEO_LIMITS or steps not in VIDEO_STEPS:
        raise ValueError("pick one of the offered sizes")
    style = next((s for s in style_list()["styles"] if s["name"] == name), None)
    if not style or not style["trained"] or not style["source"]:
        raise ValueError("train the style first: video training uses its artist's page")
    if style["job"]:
        raise ValueError("wait for the style's own training to finish")
    if _jobs("video_style"):
        raise ValueError("a video LoRA is already being trained; one at a time")
    with db() as conn:
        jid = conn.execute("INSERT INTO jobs(params, status) VALUES (?, 'queued')", (json.dumps(
            {"kind": "video_style", "name": name, "limit": limit, "steps": steps}),)).lastrowid
    return {"job": jid}


def cancel_video(req: dict) -> dict:
    name = str(req.get("name", ""))
    if not HANDLE.match(name):
        raise ValueError("bad name")
    job = _jobs("video_style").get(name)
    if not job:
        raise LookupError("no video training is running for that style")
    if job["status"] == "queued":
        with db() as conn:
            conn.execute("UPDATE jobs SET status = 'cancelled', finished_at = datetime('now') WHERE id = ?",
                         (job["id"],))
    else:
        (DATA / "lora" / name / "video-cancel").touch()   # the worker and video trainer watch for this
    return {"ok": True}
