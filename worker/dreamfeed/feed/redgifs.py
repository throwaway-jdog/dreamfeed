"""redgifs: the clips Reddit posts link to, and a creator's clips (their profile's RedGifs tab),
through its API with a temporary token.

These are real people: nothing here goes to training, styles, comics or generation.
"""
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .common import _cached, _lock, text_blocked


def _agent() -> str:
    """Reddit's user agent (it names you), asked for when used: reddit.py needs this module too."""
    from .reddit import _agent as reddit_agent
    return reddit_agent()


_redgifs = {"value": "", "until": 0.0}
_clips: dict[str, tuple[float, dict | None]] = {}


_redgifs_token_lock = threading.Lock()


def _new_redgifs_token() -> str:
    with urllib.request.urlopen(urllib.request.Request("https://api.redgifs.com/v2/auth/temporary",
                                                       headers={"User-Agent": _agent()}), timeout=20) as r:
        tok = json.load(r)["token"]
    with _lock:
        _redgifs.update(value=tok, until=time.time() + 12 * 3600)
    return tok


def _redgifs_get(path: str):
    """redgifs' API with a temporary token (as its own site uses); a new token when it's refused."""
    for attempt in (0, 1):
        with _lock:
            tok = _redgifs["value"] if time.time() < _redgifs["until"] else ""
        if not tok or attempt:
            with _redgifs_token_lock:
                with _lock:
                    tok = _redgifs["value"] if time.time() < _redgifs["until"] and not attempt else ""
                tok = tok or _new_redgifs_token()
        req = urllib.request.Request("https://api.redgifs.com" + path,
                                     headers={"User-Agent": _agent(), "Authorization": f"Bearer {tok}"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 401 or attempt:
                raise


REDGIFS_NAME = re.compile(r"^[a-z0-9_.-]{2,40}$")


def redgifs_page(name: str, page: int) -> dict:
    """A RedGifs creator's clips, newest first, 40 a page: {"clips": [{"id", "url", "poster",
    "duration", "views", "tags"}], "total", "more"}. Played from redgifs' own servers."""
    name = name.strip().lower()
    if not REDGIFS_NAME.match(name) or not 1 <= page <= 200:
        raise ValueError("bad RedGifs profile")
    def fetch():
        try:
            d = _redgifs_get(f"/v2/users/{urllib.parse.quote(name)}/search?order=new&count=40&page={page}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"clips": [], "total": 0, "more": False}
            raise LookupError(f"RedGifs didn't answer ({e})") from e
        except (OSError, ValueError) as e:
            raise LookupError(f"RedGifs didn't answer ({e})") from e
        out = []
        for g in d.get("gifs") or []:
            urls = g.get("urls") or {}
            src = urls.get("hd") or urls.get("sd")
            if not g.get("id") or not src or text_blocked(g.get("description"), " ".join(g.get("tags") or [])):
                continue
            out.append({"id": g["id"], "url": src, "poster": urls.get("poster") or urls.get("thumbnail"),
                        "duration": round(g.get("duration") or 0), "views": g.get("views"), "tags": (g.get("tags") or [])[:6],
                        "has_audio": bool(g.get("hasAudio"))})
        return {"clips": out, "total": d.get("total") or 0, "more": page < (d.get("pages") or 0)}
    return _cached(f"redgifs:{name}:{page}", fetch, 600)


def redgifs_clip(cid: str) -> dict | None:
    """One RedGifs clip by its id (its own page)."""
    if not re.fullmatch(r"[a-z]{3,80}", cid or ""):
        raise ValueError("bad clip")
    return _redgifs_clip(f"https://www.redgifs.com/watch/{cid}")


def _redgifs_clip(url: str) -> dict | None:
    """A redgifs link's clip, from redgifs' own API (a temporary token, as its site uses); kept
    an hour (its addresses are signed for longer)."""
    m = re.search(r"redgifs\.com/(?:watch|ifr|i)/([A-Za-z]+)", url)
    if not m:
        return None
    with _lock:
        hit = _clips.get(m.group(1).lower())
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    try:
        with _lock:
            tok = _redgifs["value"] if time.time() < _redgifs["until"] else ""
        if not tok:
            with _redgifs_token_lock:             # one new token, however many ask at once
                with _lock:
                    tok = _redgifs["value"] if time.time() < _redgifs["until"] else ""
                tok = tok or _new_redgifs_token()
        req = urllib.request.Request(f"https://api.redgifs.com/v2/gifs/{m.group(1).lower()}",
                                     headers={"User-Agent": _agent(), "Authorization": f"Bearer {tok}"})
        with urllib.request.urlopen(req, timeout=20) as r:
            g = json.load(r).get("gif") or {}
    except (OSError, ValueError, KeyError):
        return None
    urls = g.get("urls") or {}
    src = urls.get("hd") or urls.get("sd")
    clip = {"kind": "video", "url": src, "poster": urls.get("poster") or urls.get("thumbnail")} if src else None
    with _lock:
        if len(_clips) > 5000:
            _clips.clear()
        _clips[m.group(1).lower()] = (time.time(), clip)
    return clip
