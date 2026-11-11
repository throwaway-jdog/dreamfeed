"""Who you follow on other sites, in one place: `python -m dreamfeed follow` (the follow service).

Posts from X, Reddit and e621 are read live by the web app (livefeeds.py), not here.

Every POLL seconds it asks Chaturbate which of the rooms you follow are live (signed in with
your cookies, the CHATURBATE_COOKIES_FILE mount) and keeps, in feed.db:
- follows: each room you follow, live or not, with what it's showing while live;
- live_times: when each one was live, for the "usually live" hours on the Following page.
A live room's thumbnail is saved in data/generated/follow/ (left out of the backup). The
Live tab plays a room in dreamfeed's own player; nothing of the stream is kept. Your own videos
of the rooms (CB_VIDEOS, see cbvideos.py) get their posters made here too, their highlights
cut (cbhighlights.py, one at a time, started within TICK seconds of being asked for) and the
trash emptied. It also reads a few rooms' bios each round (each once a day) for the X and
Reddit accounts they link for free (cbprofile.py: one profile across sites). Follows and
unfollows tapped in dreamfeed are sent to Chaturbate from here (signed in as you, one at a
time, within TICK seconds), and the list here changes with them.

These are real people: nothing here goes to training, styles, comics or generation. A room
Chaturbate doesn't list as age verified is left out.
"""
import datetime as dt
import http.cookiejar
import json
import os
import re
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import cbprofile, cbvideos
from .db import connect

POLL = 120                   # seconds between looks
TICK = 5                     # seconds between checks for highlight requests
HIGHLIGHT_LIMIT = 6 * 3600   # a cut taking longer than this is stopped
BIOS_PER_ROUND = 3           # rooms whose bios are read each round (each once a day)
EVERYONE = 3600              # seconds between listing every room followed (offline ones too)
GAP = 600                    # live again within this many seconds: the same session
PAGE = 90                    # rooms per request (the site's own page size)
MAX_ROOMS = 2000
SITE = "https://chaturbate.com"
ROOMS = SITE + "/api/ts/roomlist/room-list/"
THUMB_HOSTS = ("thumb.live.mmcdn.com",)
NAME = re.compile(r"^[a-z0-9_]{1,64}$")
COOKIES = Path("/config/chaturbate-cookies.txt")
AGENT = "dreamfeed (personal follow list)"


class SignedOut(RuntimeError):
    pass


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _opener():
    if not COOKIES.is_file():
        raise SignedOut("no Chaturbate cookies: set CHATURBATE_COOKIES_FILE in .env")
    jar = http.cookiejar.MozillaCookieJar(str(COOKIES))
    jar.load(ignore_discard=True, ignore_expires=True)    # read each time: a fresh export needs no restart
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def _get(opener, url: str, json_=True):
    req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "application/json" if json_ else "*/*",
                                               "Referer": SITE + "/"})
    with opener.open(req, timeout=30) as r:
        data = r.read()
    return json.loads(data) if json_ else data


def followed(opener, offline: bool) -> list[dict]:
    """The rooms you follow that are live (offline=False) or not live (offline=True)."""
    rooms = []
    while len(rooms) < MAX_ROOMS:
        q = {"follow": "true", "limit": PAGE, "offset": len(rooms)}
        if offline:
            q["offline"] = "true"
        page = _get(opener, ROOMS + "?" + urllib.parse.urlencode(q)).get("rooms") or []
        # Signed out, the site ignores follow=true and lists everyone's rooms instead.
        if any(not r.get("is_following") for r in page):
            raise SignedOut("Chaturbate isn't signed in: export your cookies again")
        rooms += page
        if len(page) < PAGE:
            break
    return [r for r in rooms if NAME.match(str(r.get("username", "")))]


def _info(r: dict) -> dict:
    return {"title": re.sub(r"<[^>]+>", "", r.get("subject") or r.get("room_subject") or "")[:300],
            "tags": [str(t)[:40] for t in (r.get("tags") or [])][:12], "viewers": int(r.get("num_users") or 0),
            "age": r.get("display_age"), "gender": r.get("gender"), "show": r.get("current_show"),
            "since": r.get("start_dt_utc")}


def _thumb(opener, r: dict, folder: Path) -> None:
    url = str(r.get("img") or "")
    if urllib.parse.urlparse(url).hostname not in THUMB_HOSTS:
        return
    try:
        data = _get(opener, url, json_=False)
    except OSError:
        return
    if data[:3] == b"\xff\xd8\xff":    # a JPEG
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / f".{r['username']}.jpg"
        tmp.write_bytes(data)
        tmp.replace(folder / f"{r['username']}.jpg")


def chaturbate(conn, thumbs: Path, everyone: bool) -> str:
    opener = _opener()
    live = followed(opener, offline=False)
    verified = [r for r in live if r.get("is_age_verified") and not (isinstance(r.get("display_age"), int) and r["display_age"] < 18)]
    names = {r["username"] for r in verified}
    now = _now()
    with conn:
        if everyone:
            others = followed(opener, offline=True)
            listed = names | {r["username"] for r in others}
            for n in listed:
                conn.execute("INSERT INTO follows(source, name, seen_at) VALUES ('chaturbate', ?, ?)"
                             " ON CONFLICT(source, name) DO UPDATE SET seen_at = excluded.seen_at", (n, now))
            # Unfollowed there: gone here too (their live times go with them).
            gone = [n for (n,) in conn.execute("SELECT name FROM follows WHERE source = 'chaturbate'") if n not in listed]
            for n in gone:
                conn.execute("DELETE FROM follows WHERE source = 'chaturbate' AND name = ?", (n,))
                conn.execute("DELETE FROM live_times WHERE source = 'chaturbate' AND name = ?", (n,))
        conn.execute("UPDATE follows SET live = 0 WHERE source = 'chaturbate'")
        for r in verified:
            conn.execute("INSERT INTO follows(source, name, live, info, last_live, seen_at) VALUES ('chaturbate', ?, 1, ?, ?, ?)"
                         " ON CONFLICT(source, name) DO UPDATE SET live = 1, info = excluded.info, last_live = excluded.last_live",
                         (r["username"], json.dumps(_info(r)), now, now))
            row = conn.execute("SELECT rowid FROM live_times WHERE source = 'chaturbate' AND name = ?"
                               " AND end_at >= datetime(?, ?) ORDER BY end_at DESC LIMIT 1",
                               (r["username"], now, f"-{GAP} seconds")).fetchone()
            if row:
                conn.execute("UPDATE live_times SET end_at = ? WHERE rowid = ?", (now, row[0]))
            else:
                conn.execute("INSERT INTO live_times(source, name, start_at, end_at) VALUES ('chaturbate', ?, ?, ?)",
                             (r["username"], now, now))
    for r in verified:
        _thumb(opener, r, thumbs / "chaturbate")
    hidden = len(live) - len(verified)
    return f"{len(verified)} live" + (f", {hidden} not age verified (hidden)" if hidden else "")


def main(argv: list[str]) -> None:
    if argv[:1] == ["highlight"] and len(argv) == 2:
        from .cbhighlights import run
        return run(int(argv[1]))
    if argv[:1] == ["reddit-login"]:
        from .redditlogin import login
        return login(argv[1:])
    data = os.environ.get("DATA_DIR", "").strip()
    if not data:
        sys.exit("follow: DATA_DIR is not set")
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))   # PID 1 in its container
    conn = connect(Path(data) / "feed.db")
    folder = Path(data) / "generated" / "follow"
    folder.mkdir(parents=True, exist_ok=True)
    status = folder / "status.json"
    last_everyone = 0.0
    cutting = None         # the highlights' child: (process, job, started)
    with conn:             # cut off by a restart: again from the start
        conn.execute("UPDATE highlights SET status = 'queued', progress = NULL WHERE status = 'running'")
    print("follow: watching the rooms you follow on Chaturbate", flush=True)
    next_look = 0.0
    while True:
        cutting = _highlights(conn, cutting)
        try:
            _cb_actions(conn)
        except SignedOut as e:
            print(f"follow: {e}", flush=True)
        if time.time() < next_look:
            time.sleep(TICK)
            continue
        next_look = time.time() + POLL
        everyone = time.time() - last_everyone >= EVERYONE
        st = {"at": _now(), "chaturbate": None, "error": None}
        try:
            st["chaturbate"] = chaturbate(conn, folder, everyone)
            if everyone:
                last_everyone = time.time()
        except SignedOut as e:
            st["error"] = str(e)
        except (OSError, ValueError) as e:     # network, a site hiccup, a bad answer: next time
            st["error"] = f"Chaturbate didn't answer ({e})"[:300]
        try:
            names = [n for (n,) in conn.execute("SELECT name FROM follows WHERE source = 'chaturbate'")]
            st["videos"] = cbvideos.make_posters(Path(data), names)
            if everyone:
                gone = cbvideos.empty_trash()
                if gone:
                    print(f"follow: emptied the videos' trash ({gone} over {cbvideos.TRASH_DAYS} days old)", flush=True)
        except OSError as e:
            print(f"follow: couldn't read the videos folder ({e})", flush=True)
        if st["error"]:
            print(f"follow: {st['error']}", flush=True)
        tmp = status.with_suffix(".tmp")
        tmp.write_text(json.dumps(st))
        tmp.replace(status)
        try:
            _bios(conn)
        except (OSError, ValueError) as e:
            print(f"follow: couldn't read a bio ({e})", flush=True)


def _cb_actions(conn) -> None:
    """Follows and unfollows asked for in dreamfeed, sent to Chaturbate as the site's own
    buttons send them (your session, its CSRF token), each checked against its answer."""
    rows = conn.execute("SELECT id, room, action FROM cb_actions WHERE status = 'queued' ORDER BY id").fetchall()
    if not rows:
        return
    opener = _opener()
    jar = next(h.cookiejar for h in opener.handlers if hasattr(h, "cookiejar"))
    token = next((c.value for c in jar if c.name == "csrftoken"), None)
    for job, room, action in rows:
        error = None
        try:
            if not token:
                raise SignedOut("Chaturbate isn't signed in: export your cookies again")
            req = urllib.request.Request(f"{SITE}/follow/{action}/{room}/", data=b"", method="POST", headers={
                "User-Agent": AGENT, "Accept": "application/json", "X-CSRFToken": token,
                "X-Requested-With": "XMLHttpRequest", "Referer": f"{SITE}/{room}/"})
            with opener.open(req, timeout=30) as r:
                answer = json.loads(r.read() or b"{}")
            if answer.get("following") is not (action == "follow"):
                raise ValueError(f"Chaturbate said {answer}"[:200])
        except (OSError, ValueError, SignedOut) as e:
            error = str(e)[:300]
        with conn:
            conn.execute("UPDATE cb_actions SET status = ?, error = ? WHERE id = ?", ("failed" if error else "done", error, job))
            if not error and action == "follow":
                conn.execute("INSERT INTO follows(source, name, seen_at) VALUES ('chaturbate', ?, ?)"
                             " ON CONFLICT(source, name) DO NOTHING", (room, _now()))
            elif not error:
                conn.execute("DELETE FROM follows WHERE source = 'chaturbate' AND name = ?", (room,))
                conn.execute("DELETE FROM live_times WHERE source = 'chaturbate' AND name = ?", (room,))
        print(f"follow: {action} {room} on Chaturbate: {error or 'done'}", flush=True)
        time.sleep(1)


def _bios(conn) -> None:
    """The next few followed rooms' bio links (each once a day)."""
    for (name,) in conn.execute("SELECT name FROM follows WHERE source = 'chaturbate' AND"
                                " (bio_at IS NULL OR bio_at < datetime('now', '-1 day')) ORDER BY bio_at LIMIT ?",
                                (BIOS_PER_ROUND,)).fetchall():
        try:
            links = cbprofile.bio(name)["links"]
        except urllib.error.HTTPError as e:
            if e.code == 429:                    # too many: the rest next round
                return
            print(f"follow: couldn't read {name}'s bio ({e})", flush=True)
            links = []
        except (OSError, ValueError) as e:     # gone, or a hiccup: tomorrow
            print(f"follow: couldn't read {name}'s bio ({e})", flush=True)
            links = []
        with conn:
            cbprofile.save_links(conn, name, links)
            conn.execute("UPDATE follows SET bio_at = datetime('now') WHERE source = 'chaturbate' AND name = ?", (name,))


def _highlights(conn, cutting):
    """Starts the next highlights request when none is being cut; notices when one ends."""
    import subprocess
    if cutting:
        proc, job, started = cutting
        if proc.poll() is None:
            if time.time() - started < HIGHLIGHT_LIMIT:
                return cutting
            os.killpg(proc.pid, signal.SIGKILL)     # its ffmpeg too
            proc.wait()
        with conn:     # it died without saying why
            conn.execute("UPDATE highlights SET status = 'failed', progress = NULL,"
                         " error = coalesce(error, 'stopped (took too long or crashed)') WHERE id = ? AND status = 'running'", (job,))
    row = conn.execute("SELECT id FROM highlights WHERE status = 'queued' ORDER BY id LIMIT 1").fetchone()
    if not row:
        return None
    with conn:
        conn.execute("UPDATE highlights SET status = 'running' WHERE id = ?", (row[0],))
    proc = subprocess.Popen([sys.executable, "-m", "dreamfeed", "follow", "highlight", str(row[0])], start_new_session=True)
    return proc, row[0], time.time()
