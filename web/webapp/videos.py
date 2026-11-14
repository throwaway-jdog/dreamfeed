"""The Videos tab: long videos from xvideos, played in dreamfeed's own player, chosen from what you
watch. What you watch here (how far, whether you finish or skip, 👍 and "less like this") becomes
weights on tags and uploaders (older watching counts for less); For you is then drawn from the
related videos of what you liked, your uploaders, your tags (and, before there's much to go on,
your Chaturbate rooms' tags and their linked xvideos accounts), ranked by those weights, a few at
most from one uploader, each saying why it's there. Search, and Continue watching.

Real people: nothing here goes to training, styles, comics or generation.
"""
import json
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from dreamfeed.feed import xvideos as xv

from . import history, mutes
from .common import db
from .feed import _now_shown, _stale

LENGTHS = ("", "10", "20")        # minutes at least
PAGE = 24
PER_UPLOADER = 3                  # in a page of For you, at most
TASTE_DAYS = 30                   # watching this long ago counts half
SKIP_SECONDS = 30                 # left within this (and the first tenth): a skip
CONTINUE_FROM = 60                # watched past this, not finished: Continue watching
_ranked: dict[str, tuple[float, list]] = {}      # (length) -> (when, ranked For you), reused for its pages
_lock = threading.Lock()
RANKED_TTL = 600


def _tables(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS xv_videos (id TEXT PRIMARY KEY, data TEXT NOT NULL, at REAL NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS xv_watch (id TEXT PRIMARY KEY, position REAL NOT NULL DEFAULT 0,
        duration REAL NOT NULL DEFAULT 0, watched REAL NOT NULL DEFAULT 0, finished INTEGER NOT NULL DEFAULT 0,
        opened INTEGER NOT NULL DEFAULT 0, first_at REAL NOT NULL, last_at REAL NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS xv_votes (id TEXT PRIMARY KEY, vote INTEGER NOT NULL, at REAL NOT NULL)""")


def _conn():
    conn = db()
    _tables(conn)
    return conn


def _keep(conn, v: dict) -> None:
    """What a video is (title, uploader, tags once known), for Continue watching and your taste."""
    old = conn.execute("SELECT data FROM xv_videos WHERE id = ?", (v["id"],)).fetchone()
    data = {**(json.loads(old["data"]) if old else {}), **{k: v[k] for k in ("id", "url", "title", "duration", "thumb", "uploader",
                                                                             "uploader_path", "channel", "tags", "poster") if v.get(k)}}
    conn.execute("INSERT OR REPLACE INTO xv_videos (id, data, at) VALUES (?, ?, ?)", (v["id"], json.dumps(data), time.time()))


# ---- what you watch ----
def video(url: str) -> dict:
    """A video to play: its details and files (xvideos.xv_details), where you left off, your vote."""
    d = xv.xv_details(url)
    with _conn() as conn:
        _keep(conn, d)
        conn.execute("INSERT INTO xv_watch (id, opened, first_at, last_at) VALUES (?, 1, ?, ?) ON CONFLICT(id) DO UPDATE SET"
                     " opened = opened + 1, last_at = excluded.last_at", (d["id"], time.time(), time.time()))
        w = conn.execute("SELECT position, finished FROM xv_watch WHERE id = ?", (d["id"],)).fetchone()
        v = conn.execute("SELECT vote FROM xv_votes WHERE id = ?", (d["id"],)).fetchone()
    history.note("video", d["id"], d.get("title") or "", f"xvideos/{d['id']}", d.get("thumb") or d.get("poster"),
                 {k: d.get(k) for k in ("id", "url", "title", "duration", "thumb", "uploader", "uploader_path")} | {"url": url})
    seen = _watched_ids()
    related = [r for r in mutes.videos(d["related"]) if r["id"] not in seen]
    return {**d, "related": related[:20], "resume": w["position"] if w and not w["finished"] and w["position"] > CONTINUE_FROM else 0,
            "vote": v["vote"] if v else 0}


def watch(req: dict) -> dict:
    """{"id", "position", "duration", "delta" (seconds watched since the last)}: how far you are."""
    vid = str(req.get("id", ""))
    if not xv.XVIDEOS_ID.match(vid):
        raise ValueError("bad video")
    try:
        pos, dur, delta = (max(0.0, float(req.get(k) or 0)) for k in ("position", "duration", "delta"))
    except (TypeError, ValueError):
        raise ValueError("bad numbers")
    delta = min(delta, 60.0)                         # (one report: a minute at most)
    finished = 1 if dur and pos >= dur * 0.9 else 0
    with _conn() as conn:
        conn.execute("INSERT INTO xv_watch (id, position, duration, watched, finished, first_at, last_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
                     " ON CONFLICT(id) DO UPDATE SET position = excluded.position, duration = max(duration, excluded.duration),"
                     " watched = watched + excluded.watched, finished = max(finished, excluded.finished), last_at = excluded.last_at",
                     (vid, pos, dur, delta, finished, time.time(), time.time()))
    return {"ok": True, "finished": bool(finished)}


def vote(req: dict) -> dict:
    """{"id", "vote": 1 (more like this) | -1 (less) | 0 (take it back), "url"}: here, and on
    xvideos too when you're signed in there (👍 / 👎 as you; taking it back stays here)."""
    vid, v, url = str(req.get("id", "")), req.get("vote"), str(req.get("url") or "")
    if not xv.XVIDEOS_ID.match(vid) or v not in (1, -1, 0) or (url and not xv.XV_PATH.match(url)):
        raise ValueError("bad vote")
    site = None
    if v and url:
        from dreamfeed.core import cookies
        if cookies.path("xvideos"):
            try:
                xv.xv_vote(url, v == 1)
                site = {"status": "done"}
            except (LookupError, OSError) as e:
                site = {"status": "failed", "error": str(e)[:200]}
    with _conn() as conn:
        if v:
            conn.execute("INSERT OR REPLACE INTO xv_votes (id, vote, at) VALUES (?, ?, ?)", (vid, v, time.time()))
        else:
            conn.execute("DELETE FROM xv_votes WHERE id = ?", (vid,))
    with _lock:
        _ranked.clear()                            # (For you, ranked again with it)
    return {"vote": v, "site": site}


def comments(url: str) -> dict:
    return {"comments": xv.xv_comments(url)}


def _watched_ids() -> set:
    with _conn() as conn:
        return {r[0] for r in conn.execute("SELECT id FROM xv_watch WHERE finished = 1 OR watched > 120")} | \
               {r[0] for r in conn.execute("SELECT id FROM xv_votes WHERE vote < 0")}


# ---- your taste ----
def taste() -> dict:
    """{"tags": {tag: weight}, "uploaders": {path: weight}, "liked": [videos you liked most, newest
    first], "n": videos it's from}."""
    tags, ups, liked = {}, {}, []
    now = time.time()
    with _conn() as conn:
        rows = conn.execute("SELECT w.*, v.data, b.vote FROM xv_watch w JOIN xv_videos v ON v.id = w.id"
                            " LEFT JOIN xv_votes b ON b.id = w.id").fetchall()
        rows += conn.execute("SELECT NULL AS position, NULL AS duration, 0 AS watched, 0 AS finished, b.at AS last_at, v.data, b.vote"
                             " FROM xv_votes b JOIN xv_videos v ON v.id = b.id WHERE b.id NOT IN (SELECT id FROM xv_watch)").fetchall()
    for r in rows:
        d = json.loads(r["data"])
        dur, pos, watched = r["duration"] or d.get("duration") or 0, r["position"] or 0, r["watched"] or 0
        if r["finished"] or (dur and watched >= dur * 0.8):
            s = 1.0
        elif watched >= 120:
            s = 0.5 + 0.5 * min(1.0, watched / dur) if dur else 0.6
        elif r["position"] is not None and watched < SKIP_SECONDS and (not dur or pos < dur * 0.1):
            s = -0.6
        else:
            s = 0.1
        s += {1: 2.0, -1: -2.0}.get(r["vote"] or 0, 0.0)
        s *= 0.5 ** ((now - (r["last_at"] or now)) / 86400 / TASTE_DAYS)
        vt = d.get("tags") or []
        for t in vt:
            tags[t] = tags.get(t, 0.0) + s / math.sqrt(len(vt))
        if d.get("uploader_path"):
            ups[d["uploader_path"]] = ups.get(d["uploader_path"], 0.0) + s
        if s > 0.5 and d.get("url"):
            liked.append((s, r["last_at"] or 0, d))
    liked.sort(key=lambda x: (-x[0], -x[1]))
    return {"tags": tags, "uploaders": ups, "liked": [d for _, _, d in liked[:6]], "n": len(rows)}


def _room_seeds() -> tuple[list[str], list[str]]:
    """Before there's much to go on: the tags of your Chaturbate rooms (most common first) and the
    xvideos accounts linked to them."""
    counts = {}
    with _conn() as conn:
        for (info,) in conn.execute("SELECT info FROM follows WHERE source = 'chaturbate' AND info IS NOT NULL"):
            for t in (json.loads(info) or {}).get("tags") or []:
                t = str(t).lower().strip("#")
                if (re.fullmatch(r"[a-z0-9]{3,30}", t) and t not in ("new", "hd", "18", "lovense", "ohmibod", "lush", "cam")
                        and not xv.youth(t)):
                    counts[t] = counts.get(t, 0) + 1
        linked = [r[0] for r in conn.execute("SELECT DISTINCT handle FROM links WHERE source = 'xvideos' AND state != 'removed'")]
    return [t for t, _ in sorted(counts.items(), key=lambda kv: -kv[1])][:6], linked


def _candidates(t: dict, length: str) -> list[tuple[dict, float, str]]:
    """(video, how much its source says, why) from each source, read at once."""
    jobs = []
    for d in t["liked"][:4]:
        jobs.append((1.0, f"Because you watched “{d.get('title', '')[:60]}”", lambda d=d: xv.xv_details(d["url"])["related"]))
    top_ups = [p for p, w in sorted(t["uploaders"].items(), key=lambda kv: -kv[1]) if w > 0.4][:3]
    names = {}
    for d in t["liked"]:
        names[d.get("uploader_path")] = d.get("uploader")
    for p in top_ups:
        jobs.append((0.8, f"From {names.get(p) or p.strip('/')}, whom you watch", lambda p=p: xv.xv_uploader(p)))
    top_tags = [g for g, w in sorted(t["tags"].items(), key=lambda kv: -kv[1]) if w > 0.3][:3]
    for g in top_tags:
        jobs.append((0.6, f"You like {g}", lambda g=g: xv.xv_search(g, 0, length, "rating")["videos"]))
    if t["n"] < 8:                                  # (little to go on yet: your rooms)
        seeds, linked = _room_seeds()
        for g in seeds[:4]:
            jobs.append((0.5, f"Like your rooms (#{g})", lambda g=g: xv.xv_search(g, 0, length, "rating")["videos"]))
        for name in linked[:3]:
            jobs.append((0.55, "From a room you follow", lambda name=name: xv.xv_uploader("/" + name, False)))
        if not seeds and not linked:
            jobs.append((0.4, "Top rated", lambda: xv.xv_search("amateur", 0, length, "rating")["videos"]))

    def run(job):
        prior, why, read = job
        try:
            return [(v, prior, why) for v in read()]
        except (LookupError, ValueError, OSError):
            return []
    with ThreadPoolExecutor(max_workers=4) as pool:
        return [c for got in pool.map(run, jobs) for c in got]


def _rank(length: str) -> list[dict]:
    t = taste()
    least = int(length or 0) * 60
    skip = _watched_ids()
    best: dict[str, tuple[float, dict, str]] = {}
    mr = mutes.rules()
    for v, prior, why in _candidates(t, length):
        if v["id"] in skip or (least and v["duration"] < least) or mutes.video_muted(v, mr):
            continue
        words = set(re.findall(r"[a-z0-9]+", v["title"].lower()))
        s = prior + 0.3 * sum(w for g, w in t["tags"].items() if g in words) + 0.5 * t["uploaders"].get(v.get("uploader_path"), 0.0)
        r = re.match(r"(\d+)%", v.get("rating") or "")
        s += 0.3 * int(r.group(1)) / 100 if r else 0.0
        if v["id"] not in best or best[v["id"]][0] < s:
            best[v["id"]] = (s, v, why)
    ranked, per = [], {}
    for s, v, why in sorted(best.values(), key=lambda x: -x[0]):
        up = v.get("uploader_path") or v["id"]
        if per.get(up, 0) >= PER_UPLOADER:
            continue
        per[up] = per.get(up, 0) + 1
        ranked.append({**v, "why": why})
    return ranked


def home(length: str, offset: int) -> dict:
    """{"continue": [...], "videos": a page of For you, "more", "taste": what it's going on}."""
    if length not in LENGTHS or not 0 <= offset < 2000:
        raise ValueError("bad page")
    with _lock:
        hit = _ranked.get(length)
    if offset == 0 or not hit or time.time() - hit[0] > RANKED_TTL:
        ranked = _rank(length)
        with _lock:
            _ranked[length] = (time.time(), ranked)
    else:
        ranked = hit[1]
    old = _stale(f"xv:{v['id']}" for v in ranked) if offset == 0 else set()   # (shown before: further down)
    if old:
        ranked = [v for v in ranked if f"xv:{v['id']}" not in old] + [v for v in ranked if f"xv:{v['id']}" in old]
        with _lock:
            _ranked[length] = (time.time(), ranked)
    page = ranked[offset:offset + PAGE]
    _now_shown([{"id": f"xv:{v['id']}"} for v in page])
    t = taste()
    out = {"videos": page, "more": offset + PAGE < len(ranked),
           "taste": {"tags": [g for g, w in sorted(t["tags"].items(), key=lambda kv: -kv[1]) if w > 0.3][:8], "n": t["n"]}}
    if offset == 0:
        out["continue"] = continue_watching()
    return out


def continue_watching() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT w.position, w.duration, v.data FROM xv_watch w JOIN xv_videos v ON v.id = w.id"
                            " WHERE w.finished = 0 AND w.position > ? AND w.id NOT IN (SELECT id FROM xv_votes WHERE vote < 0)"
                            " ORDER BY w.last_at DESC LIMIT 12", (CONTINUE_FROM,)).fetchall()
    return [{**json.loads(r["data"]), "resume": r["position"], "duration": r["duration"] or json.loads(r["data"]).get("duration")}
            for r in rows]


def search(q: str, page: int, length: str, sort: str) -> dict:
    d = xv.xv_search(q, page, length, sort or "relevance")
    skip = {r for r in _watched_ids()}
    return {"videos": [{**v, "seen": v["id"] in skip} for v in mutes.videos(d["videos"])], "more": d["more"]}
