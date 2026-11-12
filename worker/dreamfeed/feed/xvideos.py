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
    takes), "title", "duration", "views", "thumb", "when"}], "total", "more"}. Watched in xvideos'
    own player (embedframe); nothing is downloaded. Titles with words dreamfeed never shows are
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
