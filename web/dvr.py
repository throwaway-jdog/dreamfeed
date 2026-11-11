"""Your recorder (streamonitor), run from dreamfeed: which Chaturbate rooms it records and what
each is doing, and Record, Pause and Remove for a room. Off unless STREAMONITOR_URL is set (its
web address, e.g. http://streamonitor:5000 on a shared Docker network); STREAMONITOR_PASSWORD
when it has one (its admin password). Its recordings show on the room's profile through
CB_VIDEOS (cbvideos.py). Standard library only.
"""
import base64
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

SITE = "Chaturbate"          # (streamonitor's name for it; it lists it as CB)
TTL = 10                     # seconds its list is reused
_lock = threading.Lock()
_last: dict = {"at": 0.0, "value": None}


def url() -> str:
    return os.environ.get("STREAMONITOR_URL", "").strip().rstrip("/")


def enabled() -> bool:
    return bool(url())


def _request(method: str, path: str, form: dict | None = None):
    headers = {"Accept": "application/json"}
    password = os.environ.get("STREAMONITOR_PASSWORD", "")
    if password:
        headers["Authorization"] = "Basic " + base64.b64encode(f"admin:{password}".encode()).decode()
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url() + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5 if method == "GET" else 15) as r:   # (the Live tab waits on it)
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise LookupError("streamonitor wants its password (STREAMONITOR_PASSWORD)") from e
        return e.code, e.read()
    except OSError as e:
        raise LookupError(f"streamonitor didn't answer ({e})") from e


def _state(s: dict) -> str:
    """recording (now), waiting (for them to go live), paused, or problem (it says what)."""
    if s.get("recording"):
        return "recording"
    if s.get("sc") in (3, 400, 429, 1403):        # error, no such room, rate limited, restricted
        return "problem"
    return "waiting" if s.get("running") else "paused"


def rooms() -> dict:
    """{"rooms": {room: {"state", "status" (streamonitor's words), "running"}}, "free": "4.8 TiB"}; {} when off."""
    if not enabled():
        return {}
    with _lock:
        if _last["value"] is not None and time.time() - _last["at"] < TTL:
            return _last["value"]
    code, body = _request("GET", "/api/data")
    if code != 200:
        raise LookupError(f"streamonitor said {code}")
    d = json.loads(body)
    value = {"rooms": {str(s.get("username", "")).lower(): {"state": _state(s), "status": s.get("status") or "",
                                                           "running": bool(s.get("running"))}
                       for s in d.get("streamers") or [] if s.get("site") == "CB"},
             "free": (d.get("freeSpace") or {}).get("absolute")}
    with _lock:
        _last.update(at=time.time(), value=value)
    return value


def _forget() -> None:
    with _lock:
        _last["value"] = None


def act(room: str, action: str) -> dict:
    """record (add it, or start it again), pause (it stays on the list) or remove. The room's
    new {"state", "status"} (None: not on the list)."""
    if not enabled():
        raise ValueError("no recorder set up (STREAMONITOR_URL)")
    if action not in ("record", "pause", "remove"):
        raise ValueError("bad action")
    now = rooms()["rooms"].get(room)
    path = f"/{urllib.parse.quote(room)}/{SITE}"
    if action == "record" and now is None:
        code, body = _request("POST", "/add", {"username": room, "site": SITE})
    elif action == "record" and not now["running"] or action == "pause" and now and now["running"]:
        code, body = _request("PATCH", "/toggle" + path)
    elif action == "remove" and now is not None:
        code, body = _request("DELETE", "/remove" + path)
    else:
        code, body = 200, b""          # already so
    _forget()
    if code >= 400:
        raise LookupError(f"streamonitor didn't take it ({code})")
    return {"dvr": rooms()["rooms"].get(room)}
