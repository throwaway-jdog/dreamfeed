"""Live (Chaturbate): who you follow, Discover, a room's stream, your own videos of them and
their highlights, your recorder (streamonitor: dvr.py, and this stream only), profiles across
sites and linking their accounts.
"""
import json
import re
import sqlite3
import threading
import time
import urllib.parse
from pathlib import Path

import dvr
from dreamfeed.core import safety
from dreamfeed.feed import e621, livefeeds, savedposts
from dreamfeed.live import cbprofile, cbvideos, linking

from .common import DATA, FOLLOW, LIVE_DAYS, LIVE_INFO, REDDIT_USER, ROOM, X_HANDLE, _cached, _unix, db, read_json
from . import mutes, recordings
from .feed import _xuser


def following() -> dict:
    """The rooms you follow, live ones first (most watched first), each with its live times of
    the last LIVE_DAYS days as [start, end] Unix seconds (the page works out the usual hours in
    your own time)."""
    rooms, times = [], {}
    try:
        with db() as conn:
            for r in conn.execute("SELECT source, name, start_at, end_at FROM live_times"
                                  " WHERE end_at >= datetime('now', ?)", (f"-{LIVE_DAYS} days",)):
                times.setdefault((r["source"], r["name"]), []).append([_unix(r["start_at"]), _unix(r["end_at"])])
            follows = conn.execute("SELECT * FROM follows ORDER BY name").fetchall()
            videos = cbvideos.scan(r["name"] for r in follows if r["source"] == "chaturbate")
            for r in follows:
                thumb = FOLLOW / r["source"] / f"{r['name']}.jpg"
                rooms.append({"source": r["source"], "name": r["name"], "live": bool(r["live"]),
                              "info": json.loads(r["info"]) if r["info"] else {},
                              "last_live": _unix(r["last_live"]) if r["last_live"] else None,
                              "thumb": f"follow/thumb/{r['source']}/{r['name']}.jpg?t={int(thumb.stat().st_mtime)}"
                                       if thumb.is_file() else None,
                              "times": times.get((r["source"], r["name"]), []),
                              "videos": len(videos.get(r["name"], [])) if r["source"] == "chaturbate" else 0})
    except sqlite3.OperationalError:    # the follow service hasn't started yet
        pass
    rooms.sort(key=lambda r: (not r["live"], -(r["info"].get("viewers") or 0) if r["live"] else -(r["last_live"] or 0)))
    rec, once = _dvr(), _once_rooms()
    for r in rooms:
        r["dvr"] = _with_once(rec.get("rooms", {}).get(r["name"]), r["name"], once) if r["source"] == "chaturbate" else None
    return {"rooms": rooms, "status": read_json(FOLLOW / "status.json"), "feeds": read_json(FOLLOW / "feeds.json"),
            "dvr": {"on": dvr.enabled(), "free": rec.get("free"), "error": rec.get("error")}}


def _dvr() -> dict:
    """Your recorder's list (dvr.py), or {"error"} when it doesn't answer; {} when it's off."""
    try:
        return dvr.rooms()
    except (LookupError, ValueError) as e:
        return {"error": str(e)[:200]}


DVR_ONCE_POLL = 30        # seconds between looks at the rooms recorded for one stream
DVR_ONCE_GAP = 180        # seconds a once room's recording has stopped before its stream counts as over
                          # (a short drop and the recorder picking it up again isn't the end)


def _once_rooms() -> set:
    try:
        with db() as conn:
            return {r[0] for r in conn.execute("SELECT room FROM dvr_once")}
    except sqlite3.Error:
        return set()


def _with_once(st: dict | None, room: str, once: set) -> dict | None:
    return {**st, "once": room in once} if st else None


def _end_once(room: str, conn) -> dict:
    """A once room done (its stream over, or you stopped it): paused again if it was on the
    recorder's list before, else taken off it. Its recordings stay."""
    row = conn.execute("SELECT listed FROM dvr_once WHERE room = ?", (room,)).fetchone()
    out = dvr.act(room, "pause" if row and row["listed"] else "remove")     # (on failure: tried again)
    conn.execute("DELETE FROM dvr_once WHERE room = ?", (room,))
    conn.commit()
    return out


def dvr_action(req: dict) -> dict:
    """{"name": ROOM, "action"}: tell your recorder (streamonitor). record: all their streams;
    once: only this stream (or their next, when they're not live); stop: end either; pause, remove."""
    name, action = str(req.get("name", "")), str(req.get("action", ""))
    if not ROOM.match(name):
        raise ValueError("bad room")
    if action not in ("record", "once", "stop", "pause", "remove"):
        raise ValueError("bad action")
    with db() as conn:
        had = conn.execute("SELECT listed FROM dvr_once WHERE room = ?", (name,)).fetchone()
        if action == "once":
            listed = had["listed"] if had else int(dvr.rooms().get("rooms", {}).get(name) is not None)
            out = dvr.act(name, "record")
            conn.execute("INSERT OR REPLACE INTO dvr_once (room, listed, seen, quiet, at) VALUES (?, ?, 0, NULL, ?)",
                         (name, listed, time.time()))
            conn.commit()
        elif action == "stop" and had:
            out = _end_once(name, conn)
        else:
            conn.execute("DELETE FROM dvr_once WHERE room = ?", (name,))
            conn.commit()
            out = dvr.act(name, "pause" if action == "stop" else action)
    out["dvr"] = _with_once(out.get("dvr"), name, {name} if action == "once" else set())
    return out


def _dvr_once_watch() -> None:
    """Ends each once room's recording when its stream is over: it was recording, and has
    stopped for DVR_ONCE_GAP. One paused or taken off the list elsewhere is let go."""
    while True:
        time.sleep(DVR_ONCE_POLL)
        try:
            with db() as conn:
                rows = conn.execute("SELECT * FROM dvr_once").fetchall()
                if not rows:
                    continue
                rec = dvr.rooms().get("rooms", {})
                now = time.time()
                for r in rows:
                    st = rec.get(r["room"])
                    if st is None or not st["running"]:
                        conn.execute("DELETE FROM dvr_once WHERE room = ?", (r["room"],))
                    elif st["state"] == "recording":
                        conn.execute("UPDATE dvr_once SET seen = 1, quiet = NULL WHERE room = ?", (r["room"],))
                    elif r["seen"] and r["quiet"] is None:
                        conn.execute("UPDATE dvr_once SET quiet = ? WHERE room = ?", (now, r["room"]))
                    elif r["seen"] and now - r["quiet"] >= DVR_ONCE_GAP:
                        print(time.strftime("%F %T"), f"web: {r['room']}'s stream is over: recorder stops", flush=True)
                        _end_once(r["room"], conn)
                conn.commit()
        except (sqlite3.Error, LookupError, ValueError) as e:
            print(time.strftime("%F %T"), f"web: once recordings: {e}", flush=True)


def live_stream(name: str) -> dict:
    """{"status", "hls", "title", "viewers"}: hls is the room's video while it's a public show, else None."""
    import urllib.parse
    import urllib.request
    if not ROOM.match(name):     # any room (Discover too); only public, age-verified shows play
        raise ValueError("bad room")
    try:
        with urllib.request.urlopen(LIVE_INFO.format(name), timeout=20) as r:
            d = json.load(r)
    except (OSError, ValueError):
        return {"status": "unreachable", "hls": None}
    hls = str(d.get("hls_source") or "")
    u = urllib.parse.urlparse(hls)
    ok = (d.get("room_status") == "public" and d.get("is_age_verified") and u.scheme == "https"
          and (u.hostname or "").endswith(".live.mmcdn.com"))
    return {"status": d.get("room_status") or "offline", "hls": hls if ok else None,
            "title": str(d.get("room_title") or "")[:300], "viewers": d.get("num_viewers")}


def _followed() -> list[str]:
    with db() as conn:
        return [n for (n,) in conn.execute("SELECT name FROM follows WHERE source = 'chaturbate'")]


def live_videos(name: str) -> dict:
    """A followed room's videos from your own folder, newest first, each with its poster and
    length (made by the follow service; until then none). Highlights come just before the video
    they're cut from, and each video has its latest highlights request (job)."""
    if not ROOM.match(name):
        raise ValueError("bad room")
    rooms = _followed()
    if name not in rooms:
        raise LookupError("you don't follow that room")
    index = read_json(cbvideos.posters(DATA) / "index.json") or {}
    with db() as conn:
        jobs = {}
        for r in conn.execute("SELECT path, status, progress, error FROM highlights WHERE room = ? ORDER BY id", (name,)):
            jobs[r["path"]] = {"status": r["status"], "error": r["error"],
                               **(json.loads(r["progress"]) if r["progress"] else {})}
    items = {}
    for v in cbvideos.scan(rooms).get(name, []):
        made = index.get(cbvideos.key(v)) or {}
        high = cbvideos.is_highlight(v["path"])
        title = Path(v["path"]).stem
        if high:
            title = re.sub(r" \[[0-9a-f]{6}\]\.highlights$", "", title, flags=re.I)
        items[v["path"]] = {"path": v["path"], "title": title.replace("_", " "), "size": v["size"], "mtime": v["mtime"],
                            "url": f"cb-videos/{name}/" + urllib.parse.quote(v["path"]),
                            "duration": made.get("duration") or None, "highlight": high,
                            "poster": f"cb-videos/poster/{cbvideos.key(v)}.jpg" if made.get("poster") else None}
    groups = []
    paired = set()
    for v in items.values():
        if v["highlight"]:
            continue
        group = [v]
        h = items.get(cbvideos.highlight_of(v["path"], name))
        if h:
            h["of"] = v["duration"]
            group.insert(0, h)
            paired.add(h["path"])
        v["has_highlight"] = bool(h)
        v["job"] = jobs.get(v["path"])
        groups.append((v["mtime"], group))
    groups += [(v["mtime"], [v]) for v in items.values() if v["highlight"] and v["path"] not in paired]
    groups.sort(key=lambda g: -g[0])
    return {"videos": [v for _, g in groups for v in g], "folder": cbvideos.root() is not None}


def _room_video(req: dict) -> tuple[str, str, Path]:
    name, rel = str(req.get("name", "")), str(req.get("path", ""))
    if not ROOM.match(name):
        raise ValueError("bad room")
    file = cbvideos.file(name, rel, _followed())
    if not file:
        raise LookupError("that video isn't there")
    return name, rel, file


def queue_highlights(req: dict) -> dict:
    """{"name", "path", "keep": 0.1-0.5}: cut the video's highlights (the follow service)."""
    name, rel, _ = _room_video(req)
    keep = float(req.get("keep", 0.25))
    if not 0.05 <= keep <= 0.5:
        raise ValueError("keep is 0.05 to 0.5")
    if cbvideos.is_highlight(rel):
        raise ValueError("that's already highlights")
    with db() as conn:
        if conn.execute("SELECT 1 FROM highlights WHERE path = ? AND status IN ('queued', 'running')", (rel,)).fetchone():
            raise ValueError("already being cut")
        conn.execute("INSERT INTO highlights(room, path, keep) VALUES (?, ?, ?)", (name, rel, keep))
    return {"ok": True}


def delete_room_video(req: dict) -> dict:
    """{"name", "path"}: into the trash (gone after a week); returns the token for Undo."""
    name, rel, file = _room_video(req)
    with db() as conn:
        conn.execute("DELETE FROM highlights WHERE path = ? AND status = 'queued'", (rel,))
        if conn.execute("SELECT 1 FROM highlights WHERE path = ? AND status = 'running'", (rel,)).fetchone():
            raise ValueError("its highlights are being cut: wait for them")
    return {"undo": cbvideos.trash(file)}


def restore_room_video(req: dict) -> dict:
    return {"path": cbvideos.restore(str(req.get("undo", "")))}


# ---- Discover and profiles (one profile across sites) ----
CB_LIST = "https://chaturbate.com/api/ts/roomlist/room-list/"
CB_AGENT = {"User-Agent": "dreamfeed (personal follow list)", "Accept": "application/json"}
GENDERS = ("f", "m", "c", "t")
DISCOVER_PAGE = 60
COMMON_TAGS = {"new", "18", "lovense", "lush", "ohmibod", "domi", "interactive", "interactivetoy", "private", "pvt",
               "goal", "tip", "tips", "c2c", "hd", "lovensetoy"}


_thumbs: dict[str, str] = {}                      # room -> its thumbnail's address (from a listing)


def _cb_list(params: dict) -> list[dict]:
    import urllib.request
    url = CB_LIST + "?" + urllib.parse.urlencode(params)

    def fetch():
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=CB_AGENT), timeout=30) as r:
                return json.load(r).get("rooms") or []
        except (OSError, ValueError) as e:
            raise LookupError(f"Chaturbate didn't answer ({e})")
    return _cached(url, 120, fetch)


def _room_ok(r: dict) -> bool:
    """Shown in Discover: age verified, 18 or over, no password, and nothing dreamfeed never
    takes (minors) in its tags or title."""
    age = r.get("display_age")
    words = " ".join([str(t) for t in r.get("tags") or []] + [re.sub(r"<[^>]+>", " ", str(r.get("room_subject") or r.get("subject") or ""))])
    return (bool(r.get("is_age_verified")) and not (isinstance(age, int) and age < 18) and not r.get("has_password")
            and ROOM.match(str(r.get("username", ""))) is not None
            and not safety.minors(words))


def _room_card(r: dict, followed: set) -> dict:
    name = r["username"]
    img = str(r.get("img") or "")
    if urllib.parse.urlparse(img).hostname == "thumb.live.mmcdn.com":
        if len(_thumbs) > 3000:
            _thumbs.clear()
        _thumbs[name] = img
    return {"name": name, "live": True, "followed": name in followed, "discovered": True,
            "info": {"title": re.sub(r"<[^>]+>", "", str(r.get("room_subject") or r.get("subject") or ""))[:300],
                     "tags": [str(t)[:40] for t in (r.get("tags") or [])][:12], "viewers": int(r.get("num_users") or 0),
                     "age": r.get("display_age"), "gender": r.get("gender"), "show": r.get("current_show"),
                     "since": r.get("start_dt_utc")},
            "thumb": f"cb-thumb/{name}.jpg?t={int(time.time() // 60)}" if name in _thumbs else None, "times": []}


def discover_cb(mode: str, q: str, gender: str, offset: int) -> dict:
    """Live rooms you don't follow: for you (sharing the tags of the rooms you follow), top (most
    watched) or a search; only rooms _room_ok lets through."""
    if gender and gender not in GENDERS:
        raise ValueError("bad gender")
    with db() as conn:
        follows = conn.execute("SELECT name, info FROM follows WHERE source = 'chaturbate'").fetchall()
    followed = {r["name"] for r in follows}
    base = {"genders": gender} if gender else {}
    if mode == "foryou":
        counts: dict[str, int] = {}
        for r in follows:
            for t in (json.loads(r["info"]) if r["info"] else {}).get("tags") or []:
                t = str(t).lower()
                if t not in COMMON_TAGS and not safety.minors(t):
                    counts[t] = counts.get(t, 0) + 1
        tags = sorted(counts, key=lambda t: -counts[t])[:6]
        if not tags:
            return {"rooms": [], "more": False, "tags": [], "note": "Once the rooms you follow have been live a while, rooms with the same tags show here."}
        score: dict[str, list] = {}
        for t in tags:
            for r in _cb_list({**base, "hashtags": t, "limit": 90}):
                if r.get("username") in followed or not _room_ok(r):
                    continue
                entry = score.setdefault(r["username"], [0, r])
                entry[0] += counts[t]
        ranked = sorted(score.values(), key=lambda e: (-e[0], -int(e[1].get("num_users") or 0)))
        page = ranked[offset:offset + DISCOVER_PAGE]
        return {"rooms": mutes.rooms([_room_card(r, followed) for _, r in page]), "more": len(ranked) > offset + DISCOVER_PAGE, "tags": tags}
    if mode == "top":
        params = {**base, "limit": DISCOVER_PAGE, "offset": offset}
    elif mode == "search":
        q = q.strip().lower()
        if not 1 <= len(q) <= 60 or not re.fullmatch(r"[a-z0-9_ -]+", q):
            raise ValueError("type a tag or a few words (letters and numbers)")
        bad = safety.minors(q)
        if bad:
            raise ValueError(f"not something to look for: {', '.join(sorted(set(bad)))}")
        params = {**base, "keywords": q, "limit": DISCOVER_PAGE, "offset": offset}
    else:
        raise ValueError("bad mode")
    rooms = _cb_list(params)
    return {"rooms": mutes.rooms([_room_card(r, followed) for r in rooms if _room_ok(r) and r["username"] not in followed]),
            "more": len(rooms) >= DISCOVER_PAGE}     # (it sometimes gives one more than asked)


def cb_thumb(name: str) -> bytes | None:
    import urllib.request
    url = _thumbs.get(name)
    if not url:
        return None

    def fetch():
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=CB_AGENT), timeout=20) as r:
                data = r.read(2 << 20)
        except OSError:
            return None
        return data if data[:3] == b"\xff\xd8\xff" else None
    return _cached("thumb:" + name, 60, fetch)


def _bio(name: str) -> dict:
    def fetch():
        try:
            return cbprofile.bio(name)
        except (OSError, ValueError):
            return None
    return _cached("bio:" + name, 3600, fetch) or {}


LINK_DAYS = 7              # a room's links are looked for again after this
LINK_SWEEP = 1800          # seconds between looks at the rooms you follow (a few each time)
_linking: set = set()
_linking_lock = threading.Lock()


def start_linking(room: str) -> bool:
    """Look for the room's accounts across sites (linking.py), in the background, one room at a time."""
    with _linking_lock:
        if room in _linking or len(_linking) >= 2:
            return False
        _linking.add(room)
    threading.Thread(target=_run_linking, args=(room,), daemon=True).start()
    return True


def _run_linking(room: str) -> None:
    try:
        with db() as conn:
            known = [(l["source"], l["handle"]) for l in conn.execute(
                "SELECT source, handle FROM links WHERE room = ? AND state IN ('bio', 'yours')", (room,))]
            removed = {(l["source"], l["handle"].lower()) for l in conn.execute(
                "SELECT source, handle FROM links WHERE room = ? AND state = 'removed'", (room,))}
        try:
            bio = cbprofile.bio(room)["links"]          # (with their link pages, which aren't kept)
        except (OSError, ValueError):
            bio = []
        start = list(dict.fromkeys(known + [(s, h) for s, h in bio if (s, h.lower()) not in removed]))
        found = [f for f in linking.find(room, start) if (f[0], f[1].lower()) not in removed]
        with db() as conn:
            cbprofile.save_links(conn, room, [(s, h) for s, h in bio if s in cbprofile.ACCOUNTS])
            cbprofile.save_links(conn, room, found)
            conn.execute("INSERT INTO link_checks(room, at, found) VALUES (?, datetime('now'), ?)"
                         " ON CONFLICT(room) DO UPDATE SET at = excluded.at, found = excluded.found",
                         (room, json.dumps(found)))
        if found:
            print(time.strftime("%F %T"), f"web: {room}: {len(found)} account(s) found across sites", flush=True)
    except Exception as e:      # (the profile just shows what it had)
        print(time.strftime("%F %T"), f"web: looking for {room}'s accounts failed: {e}", flush=True)
    finally:
        with _linking_lock:
            _linking.discard(room)


def _link_sweep() -> None:
    """The rooms you follow, a few each half hour, each again after LINK_DAYS."""
    while True:
        time.sleep(LINK_SWEEP)
        try:
            with db() as conn:
                rooms = [r[0] for r in conn.execute(
                    "SELECT f.name FROM follows f LEFT JOIN link_checks c ON c.room = f.name WHERE f.source = 'chaturbate'"
                    " AND (c.at IS NULL OR c.at < datetime('now', ?)) ORDER BY c.at LIMIT 3", (f"-{LINK_DAYS} days",))]
            for r in rooms:
                while _linking:
                    time.sleep(5)
                start_linking(r)
        except sqlite3.Error:
            pass


def relink(req: dict) -> dict:
    """{"room"}: look for the room's accounts again now."""
    room = str(req.get("room", ""))
    if not ROOM.match(room):
        raise ValueError("bad room")
    return {"running": start_linking(room) or room in _linking}


def profile(room: str = "", x: str = "", reddit: str = "", e621_artist: str = "", bsky: str = "") -> dict:
    """One profile across sites: a Chaturbate room (or the room an X or Reddit account is linked
    to), its linked accounts (who they are on X and Reddit) and your videos of it; or an e621
    artist (their pages elsewhere, and their X account's posts when e621 lists one). Their
    posts are read live (person_posts)."""
    artist = None
    if e621_artist:
        try:
            artist = livefeeds.e621_artist(e621_artist)
        except OSError as e:
            raise LookupError(f"e621 didn't answer ({e})")
    with db() as conn:
        if not room and (x or reddit):
            src, h = ("x", x) if x else ("reddit", reddit)
            hit = conn.execute("SELECT room FROM links WHERE source = ? AND lower(handle) = lower(?) AND state != 'removed'"
                               " ORDER BY state = 'yours' DESC LIMIT 1", (src, h)).fetchone()
            room = hit["room"] if hit else ""
        if room and not ROOM.match(room):
            raise ValueError("bad room")
        out = {"room": room or None, "followed": False, "bio": {}, "links": [], "xusers": {}, "following_x": [], "videos": 0,
               "e621": [artist["name"]] if artist else [], "artist": artist, "reddituser": None, "bsky": [], "bskyuser": None}
        if bsky:                             # a Bluesky account on its own
            h = bsky.strip().lstrip("@")
            if not livefeeds.BSKY_HANDLE.match(h):
                raise ValueError("bad Bluesky handle")
            out["bsky"] = [h.lower()]
            try:
                out["bskyuser"] = livefeeds.bsky_user(h)
            except LookupError:
                pass
        if room:
            bio = _bio(room)
            if bio.get("links"):
                with conn:
                    cbprofile.save_links(conn, room, bio["links"])
            out["bio"] = {k: bio.get(k) for k in ("about", "followers", "age", "location", "last_broadcast")}
            r = conn.execute("SELECT * FROM follows WHERE source = 'chaturbate' AND name = ?", (room,)).fetchone()
            if r:
                out.update(followed=True, live=bool(r["live"]), info=json.loads(r["info"]) if r["info"] else {},
                           last_live=_unix(r["last_live"]) if r["last_live"] else None)
                out["times"] = [[_unix(t["start_at"]), _unix(t["end_at"])] for t in conn.execute(
                    "SELECT start_at, end_at FROM live_times WHERE source = 'chaturbate' AND name = ? AND end_at >= datetime('now', ?)",
                    (room, f"-{LIVE_DAYS} days"))]
                out["videos"] = len(cbvideos.scan(_followed()).get(room, []))
                out["auto"] = {**recordings.setting(room), "folder": cbvideos.root() is not None}
            act = conn.execute("SELECT action, status, error FROM cb_actions WHERE room = ? AND created_at >= datetime('now', '-10 minutes')"
                               " ORDER BY id DESC LIMIT 1", (room,)).fetchone()
            out["action"] = dict(act) if act else None
            rec = _dvr()
            out["dvr"] = {"on": dvr.enabled(), "room": _with_once(rec.get("rooms", {}).get(room), room, _once_rooms()), "free": rec.get("free"),
                          "error": rec.get("error")}
            out["links"] = [{"source": l["source"], "handle": l["handle"], "state": l["state"],
                             "via": l["via"] or ("their Chaturbate bio" if l["state"] == "bio" else None)} for l in conn.execute(
                "SELECT * FROM links WHERE room = ? AND state != 'removed' ORDER BY state = 'suggested', source, handle", (room,))]
            chk = conn.execute("SELECT at, at < datetime('now', ?) AS old FROM link_checks WHERE room = ?",
                               (f"-{LINK_DAYS} days", room)).fetchone()
            out["linking"] = {"running": room in _linking, "at": chk["at"] if chk else None}
            if not chk or chk["old"]:
                start_linking(room)                  # (in the background: the profile shows them when done)
                out["linking"]["running"] = True
        mine = [l for l in out["links"] if l["state"] != "suggested"]        # (a suggestion is only shown)
        xs = ({l["handle"].lower() for l in mine if l["source"] == "x"} | ({x.lower()} if x else set())
              | set(artist["x"] if artist else []))
        rs = {l["handle"].lower() for l in mine if l["source"] == "reddit"} | ({reddit.lower()} if reddit else set())
        out["x"], out["reddit"] = sorted(xs), sorted(rs)
        out["xvideos"] = sorted({l["handle"].lower() for l in mine if l["source"] == "xvideos"})
        out["redgifs"] = sorted({l["handle"].lower() for l in mine if l["source"] == "redgifs"})
        if rs and not xs and livefeeds.reddit_ready():      # their picture (X's own is in xusers)
            try:
                out["reddituser"] = livefeeds.reddit_user(sorted(rs)[0])
            except (LookupError, ValueError, OSError):
                pass
        if xs:
            marks = ",".join("?" * len(xs))
            following = {h.lower() for (h,) in conn.execute(
                f"SELECT DISTINCT handle FROM x_seen WHERE kind = 'following' AND lower(handle) IN ({marks})", [*xs])}
            out["following_x"] = sorted(following)
            out["xusers"] = {u["handle"].lower(): _xuser(u) for u in conn.execute(
                f"SELECT * FROM x_users WHERE lower(handle) IN ({marks})", [*xs])}
    return out


def follow_room(req: dict) -> dict:
    """{"name", "follow": bool}: follow or unfollow a room on Chaturbate (sent by the follow service)."""
    name = str(req.get("name", ""))
    if not ROOM.match(name):
        raise ValueError("bad room")
    with db() as conn:
        if conn.execute("SELECT 1 FROM cb_actions WHERE room = ? AND status = 'queued'", (name,)).fetchone():
            raise ValueError("already on its way")
        conn.execute("INSERT INTO cb_actions(room, action) VALUES (?, ?)", (name, "follow" if req.get("follow") else "unfollow"))
    return {"ok": True}


def save_link(req: dict) -> dict:
    """{"room", "source": "x"|"reddit"|"xvideos"|"redgifs"|"onlyfans"|"fansly", "handle", "remove": bool}:
    link an account to a room (or confirm a suggested one), or unlink it. A profile can be given as
    its address."""
    room, source, handle = str(req.get("room", "")), str(req.get("source", "")), str(req.get("handle", "")).strip()
    if not ROOM.match(room):
        raise ValueError("bad room")
    pattern = {"xvideos": cbprofile.XVIDEOS_LINK, "redgifs": cbprofile.REDGIFS_LINK, "onlyfans": cbprofile.ONLYFANS_LINK,
               "fansly": cbprofile.FANSLY_LINK}.get(source)
    if pattern:
        found = pattern.findall(handle + " ")
        handle = (found[0] if found else handle.lstrip("@")).lower()
        if not re.fullmatch(r"[a-z0-9_.-]{2,60}", handle):
            raise ValueError(f"a {source} name or address")
    else:
        m = (X_HANDLE if source == "x" else REDDIT_USER if source == "reddit" else None)
        m = m.match(handle) if m else None
        if not m:
            raise ValueError("an X handle (letters, numbers, _) or a Reddit username")
        handle = m.group(1)
    with db() as conn:
        conn.execute("DELETE FROM links WHERE room = ? AND source = ? AND lower(handle) = lower(?)", (room, source, handle))
        conn.execute("INSERT INTO links(room, source, handle, state) VALUES (?, ?, ?, ?)",
                     (room, source, handle, "removed" if req.get("remove") else "yours"))
    return {"ok": True}


def discover_x() -> dict:
    """X accounts you might like and don't follow: those the rooms you follow link to, those the
    people you follow mention (twice or more) and those in X's For you (twice or more), from the
    last X_SEEN_DAYS of your timelines."""
    with db() as conn:
        following = {h.lower() for (h,) in conn.execute("SELECT DISTINCT handle FROM x_seen WHERE kind = 'following'")}
        people: dict[str, dict] = {}

        def person(h: str) -> dict:
            return people.setdefault(h.lower(), {"handle": h, "rooms": [], "mentions": 0, "by": set(), "foryou": 0})
        for l in conn.execute("SELECT l.room, l.handle FROM links l JOIN follows f ON f.source = 'chaturbate' AND f.name = l.room"
                              " WHERE l.source = 'x' AND l.state != 'removed'"):
            if l["handle"].lower() not in following:
                person(l["handle"])["rooms"].append(l["room"])
        for r in conn.execute("SELECT handle, by FROM x_seen WHERE kind = 'mention'"):
            if r["handle"].lower() not in following and X_HANDLE.match(r["handle"]):
                p = person(r["handle"])
                p["mentions"] += 1
                p["by"].add(r["by"])
        for r in conn.execute("SELECT handle, count(*) AS n FROM x_seen WHERE kind = 'foryou' GROUP BY lower(handle)"):
            if r["handle"].lower() not in following:
                person(r["handle"])["foryou"] = r["n"]
        users = {u["handle"].lower(): u for u in conn.execute("SELECT handle, image_url FROM x_users")}
        out = []
        for key, p in people.items():
            if not p["rooms"] and p["mentions"] < 2 and p["foryou"] < 2:
                continue
            u = users.get(key)
            out.append({"handle": p["handle"], "rooms": p["rooms"], "mentions": p["mentions"], "by": sorted(p["by"])[:3],
                        "foryou": p["foryou"], "thumb": (u["image_url"] if u else None) or None})
    out.sort(key=lambda p: (-len(p["rooms"]), -(p["mentions"] + p["foryou"]), p["handle"].lower()))
    return {"people": out[:80]}


def follow_thumb(source: str, file: str) -> Path | None:
    name = file.removesuffix(".jpg")
    if source != "chaturbate" or not file.endswith(".jpg") or not ROOM.match(name):
        return None
    path = FOLLOW / source / file
    return path if path.is_file() else None
