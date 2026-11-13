"""xvideos: a performer's videos (linked on their profile), played in xvideos' own player.

These are real people: nothing here goes to training, styles, comics or generation.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from .common import _cached, text_blocked


# ---- xvideos: a performer's videos (linked on their profile) ----
XVIDEOS = "https://www.xvideos.com"
XVIDEOS_NAME = re.compile(r"^[a-z0-9_-]{2,60}$")


def xvideos_page(name: str, page: int) -> dict:
    """An xvideos profile's videos, newest first, 36 a page: {"videos": [{"id" (what its player
    takes), "title", "duration", "views", "thumb", "when"}], "total", "more"}. Played in dreamfeed's
    own player (xvideos_video); nothing is downloaded. Titles with words dreamfeed never shows are
    left out."""
    name = name.strip().lower()
    if not XVIDEOS_NAME.match(name) or not 0 <= page < 200:
        raise ValueError("bad xvideos profile")
    def fetch():
        req = urllib.request.Request(f"{XVIDEOS}/profiles/{name}/videos/new/{page}",
                                     headers={"User-Agent": "Mozilla/5.0 (dreamfeed)", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.loads(r.read(4 << 20))
        except (OSError, ValueError) as e:
            raise LookupError(f"xvideos didn't answer ({e})") from e
        out = []
        for v in d.get("videos") or []:
            title = str(v.get("tf") or v.get("t") or "")
            thumb = str(v.get("i") or "")
            if not v.get("eid") or not re.fullmatch(r"[a-z0-9]{6,20}", str(v["eid"])) or text_blocked(title):
                continue
            out.append({"id": v["eid"], "title": title, "duration": v.get("d"), "views": v.get("n"),
                        "thumb": thumb if thumb.startswith("https://") else None, "when": v.get("ut")})
        total, per = int(d.get("nb_videos") or 0), int(d.get("nb_per_page") or 36)
        return {"videos": out, "total": total, "more": (page + 1) * per < total}
    return _cached(f"xvideos:{name}:{page}", fetch, 600)


XVIDEOS_ID = re.compile(r"^[a-z0-9]{6,20}$")
XVIDEOS_CDN = re.compile(r"^https://[a-z0-9-]+\.xvideos-cdn\.com/")     # (its video and picture servers)


def xvideos_video(vid: str) -> dict:
    """One video's own files, to play in dreamfeed's player instead of xvideos' (no ads): {"title",
    "hls" (its stream, up to 1080p), "mp4" (and "mp4_low": where HLS doesn't play), "poster"}.
    Read from its embed page each time (the addresses carry a short-lived token)."""
    if not XVIDEOS_ID.match(vid or ""):
        raise ValueError("bad xvideos video")
    def fetch():
        req = urllib.request.Request(f"{XVIDEOS}/embedframe/{vid}", headers={"User-Agent": "Mozilla/5.0 (dreamfeed)"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                page = r.read(2 << 20).decode("utf-8", "replace")
        except OSError as e:
            raise LookupError(f"xvideos didn't answer ({e})") from e
        def found(call):
            m = re.search(r"html5player\." + call + r"\('([^']*)'\)", page)
            u = m.group(1) if m else ""
            return u if XVIDEOS_CDN.match(u) else None
        title = (re.search(r"html5player\.setVideoTitle\('([^']*)'\)", page) or [None, ""])[1]
        if text_blocked(title):
            raise LookupError("dreamfeed leaves that video out")
        out = {"title": title, "hls": found("setVideoHLS"), "mp4": found("setVideoUrlHigh"),
               "mp4_low": found("setVideoUrlLow"), "poster": found("setThumbUrl169") or found("setThumbUrl")}
        if not (out["hls"] or out["mp4"] or out["mp4_low"]):
            raise LookupError("xvideos didn't give that video (gone, or private)")
        return out
    return _cached(f"xvideos:video:{vid}", fetch, 300)
