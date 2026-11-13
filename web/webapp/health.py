"""Health (the Dashboard): whether each part of dreamfeed is working, in one list, so what has
quietly stopped (a sign-in run out, the recorder not answering, a site's searches refused, the
disk filling) shows instead of hiding in logs. Each: {"part", "state": ok | warn | bad | off,
"says", "at" (when it was last seen working or failing, unix)}. Read from what's already kept;
the only thing asked of anything here is the recorder's list.
"""
import os
import shutil
import time
from pathlib import Path

from dreamfeed.core import cookies
from dreamfeed.feed import xvideos

from .common import DATA, FOLLOW, db, read_json
from .feed import SITE_STATE
from .live import _dvr
from .signins import BROWSER_POWER_DIR, MOUNTED_COOKIES, _bsky_status, _browser, _e621_status, _reddit_status

WEEK = 7 * 86400
FREE_WARN = 20 << 30          # disk space under this: warn
_saved_size = {"at": 0.0, "bytes": 0}


def _row(part: str, state: str, says: str, at: float | None = None) -> dict:
    return {"part": part, "state": state, "says": says, "at": at}


def _ago(t: float | None) -> str:
    if not t:
        return ""
    s = time.time() - t
    return "just now" if s < 90 else f"{int(s // 60)} min ago" if s < 5400 else f"{int(s // 3600)} h ago" if s < 2 * 86400 else f"{int(s // 86400)} days ago"


def _size(path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def health(headers=None) -> dict:
    rows, now = [], time.time()

    # sign-ins
    for site in cookies.SITES:
        st = cookies.status(site, MOUNTED_COOKIES.get(site))
        name, rf = st["name"], _browser["refresh"].get(site)
        if not st["set"]:
            rows.append(_row(f"{name} sign-in", "off", "not set"))
        elif st["missing"]:
            rows.append(_row(f"{name} sign-in", "bad", f"missing {', '.join(st['missing'])}"))
        elif st["expires"] and st["expires"] < now:
            rows.append(_row(f"{name} sign-in", "bad", "run out: set it again"))
        elif rf and rf.get("error"):
            rows.append(_row(f"{name} sign-in", "warn", f"the daily refresh failed: {rf['error']}", rf["at"]))
        elif st["expires"] and st["expires"] < now + WEEK:
            rows.append(_row(f"{name} sign-in", "warn", f"runs out within a week"))
        else:
            rows.append(_row(f"{name} sign-in", "ok", "set" + (f", refreshed {_ago(rf['at'])}" if rf else ""), st.get("updated")))
    for st in (_reddit_status(headers or {}), _bsky_status(), _e621_status()):
        name = st["name"]
        if not st.get("from") and not st.get("app"):
            rows.append(_row(f"{name} sign-in", "off", "not set"))
        else:
            rows.append(_row(f"{name} sign-in", "ok" if st["signed_in"] else "bad", "signed in" if st["signed_in"] else st.get("error") or "not signed in"))

    # the Feed's sites, as they last answered
    for site, name in (("x", "X"), ("bsky", "Bluesky"), ("reddit", "Reddit"), ("e621", "e621")):
        s = SITE_STATE.get(site)
        if not s:
            rows.append(_row(f"{name} in the Feed", "off", "not read since the web app started"))
        else:
            rows.append(_row(f"{name} in the Feed", "warn" if s["error"] else "ok", s["error"] or f"read {_ago(s['at'])}", s["at"]))
    last = xvideos.LAST
    rows.append(_row("xvideos (Videos)", "off" if not last["at"] else "warn" if last["error"] else "ok",
                     "not asked since the web app started" if not last["at"] else last["error"] or f"answered {_ago(last['at'])}", last["at"]))

    # Live: the follow service, the recorder, the server's browser
    fs = read_json(FOLLOW / "status.json") or {}
    at = fs.get("at")
    try:
        at = time.mktime(time.strptime(str(at)[:19], "%Y-%m-%d %H:%M:%S")) - time.timezone if at else None
    except ValueError:
        at = None
    rows.append(_row("Chaturbate follow list", "bad" if fs.get("error") else "warn" if not at or now - at > 1800 else "ok",
                     fs.get("error") or (f"read {_ago(at)}" if at else "not read yet"), at))
    rec = _dvr()
    if not rec:
        rows.append(_row("Recorder", "off", "not set up (STREAMONITOR_URL)"))
    elif rec.get("error"):
        rows.append(_row("Recorder", "bad", rec["error"]))
    else:
        rooms = rec.get("rooms") or {}
        problem = [r for r, s in rooms.items() if s.get("state") == "problem"]
        rows.append(_row("Recorder", "warn" if problem else "ok",
                         f"{len(rooms)} rooms, {sum(1 for s in rooms.values() if s.get('state') == 'recording')} recording, {rec.get('free') or '?'} free"
                         + (f"; trouble with {', '.join(problem[:3])}" if problem else "")))
    if BROWSER_POWER_DIR:
        st = read_json(Path(BROWSER_POWER_DIR) / "status.json") or {}
        fresh = st.get("at") and now - float(st["at"]) < 180
        rows.append(_row("Server browser", "ok" if fresh else "bad",
                         ("running" if st.get("running") else "stopped (starts when needed)") if fresh
                         else "not looked after: is browserpower installed? (sudo browserpower/install.sh)", st.get("at")))

    # linking, disk
    with db() as conn:
        checked = conn.execute("SELECT max(at) FROM link_checks").fetchone()[0]
    rows.append(_row("Linking accounts", "ok" if checked else "off", f"last looked {checked} (UTC)" if checked else "not run yet"))
    if now - _saved_size["at"] > 3600:
        _saved_size.update(at=now, bytes=_size(DATA / "saved"))
    disk = shutil.disk_usage(DATA)
    rows.append(_row("Disk", "warn" if disk.free < FREE_WARN else "ok",
                     f"{disk.free / 2**30:.0f} GB free; Saved's copies {_saved_size['bytes'] / 2**30:.1f} GB"))
    order = {"bad": 0, "warn": 1, "ok": 2, "off": 3}
    return {"parts": rows, "worst": min((r["state"] for r in rows), key=lambda s: order[s], default="ok"), "at": now}
