"""xvideos: a performer's videos (linked on their profile), and the Videos tab's: search, tags,
uploaders, a video's details and related videos. All played in dreamfeed's own player (each
video's own stream, read when it's opened: no xvideos page, no ads).

These are real people: nothing here goes to training, styles, comics or generation.
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from ..core import safety
from .common import _cached


# ---- xvideos: a performer's videos (linked on their profile) ----
XVIDEOS = "https://www.xvideos.com"
XVIDEOS_NAME = re.compile(r"^[a-z0-9_-]{2,60}$")


def xvideos_page(name: str, page: int) -> dict:
    """An xvideos profile's videos, newest first, 36 a page: {"videos": [{"id" (what its player
    takes), "title", "duration", "views", "thumb", "when"}], "total", "more"}. Played in dreamfeed's
    own player (xvideos_video); nothing is downloaded. Titles with words that only mean minors
    (youth()) are left out."""
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
            if not v.get("eid") or not re.fullmatch(r"[a-z0-9]{6,20}", str(v["eid"])) or youth(title):
                continue
            full = _from_json(v)                 # (its page's address: played and remembered like the Videos tab's)
            out.append({"id": v["eid"], "title": title, "duration": v.get("d"), "views": v.get("n"),
                        "thumb": thumb if thumb.startswith("https://") else None, "when": v.get("ut"),
                        "url": full["url"] if full else None})
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
        if youth(title):
            raise LookupError("dreamfeed leaves that video out")
        out = {"title": title, "hls": found("setVideoHLS"), "mp4": found("setVideoUrlHigh"),
               "mp4_low": found("setVideoUrlLow"), "poster": found("setThumbUrl169") or found("setThumbUrl")}
        if not (out["hls"] or out["mp4"] or out["mp4_low"]):
            raise LookupError("xvideos didn't give that video (gone, or private)")
        return out
    return _cached(f"xvideos:video:{vid}", fetch, 300)


# ---- the Videos tab: lists of xvideos' videos (search, a tag, an uploader), a video's details ----
# Every list gives each video as {"id", "url" (its page: /video.ID/title), "title", "duration"
# (seconds), "thumb", "uploader", "uploader_path", "channel", "views", "rating"}; titles and tags
# with words that only mean minors are left out (youth()). Real people: nothing goes to training.
XV_PATH = re.compile(r"^/video\.[a-z0-9]{6,20}/[A-Za-z0-9_-]{0,200}$")
# Words that only mean minors: a video whose title or tags have one is left out, and none is
# ever searched for (on top of dreamfeed's own word rules). Adult-site words like "teen" or
# "young" aren't among them: on xvideos nearly every title has one.
def youth(*texts) -> bool:
    return bool(safety.minors(*texts))
XV_UPLOADER = re.compile(r"^/[A-Za-z0-9_-]{2,80}$")
XV_LENGTHS = {"": "", "10": "10min_more", "20": "20min_more"}     # (minutes at least: xvideos' own length filter)
XV_SORTS = ("relevance", "uploaddate", "rating", "views")


def _seconds(text: str) -> int:
    """ "20 min", "1 h 5 min", "45 sec" as seconds."""
    total = 0
    for n, unit in re.findall(r"(\d+)\s*(h|min|sec|s)\b", str(text or "")):
        total += int(n) * {"h": 3600, "min": 60}.get(unit, 1)
    return total


AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"


def _signed_in_opener():
    """An opener with your xvideos cookies (the Dashboard's Sign-ins), or None when there are none."""
    import http.cookiejar
    from ..core import cookies
    file = cookies.path("xvideos")
    if not file:
        return None
    jar = http.cookiejar.MozillaCookieJar(str(file))
    jar.load(ignore_discard=True, ignore_expires=True)
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


LAST = {"at": None, "error": None}       # how the last request to xvideos went (the Dashboard's Health)


def _get(url: str, json_: bool = False, data: bytes | None = None, opener=None, headers: dict | None = None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0 (dreamfeed)" if not opener else AGENT,
                                                          "Accept": "application/json" if json_ else "text/html", **(headers or {})})
    try:
        with (opener.open(req, timeout=20) if opener else urllib.request.urlopen(req, timeout=20)) as r:
            raw = r.read(4 << 20)
    except OSError as e:
        LAST.update(at=time.time(), error=str(e)[:200])
        raise LookupError(f"xvideos didn't answer ({e})") from e
    LAST.update(at=time.time(), error=None)
    return json.loads(raw) if json_ else raw.decode("utf-8", "replace")


def signed_in() -> str | None:
    """None when xvideos sees you signed in with your cookies, else what's wrong."""
    opener = _signed_in_opener()
    if not opener:
        return "no xvideos cookies set"
    page = _get(f"{XVIDEOS}/account", opener=opener)
    return None if re.search(r'"is_logged":\s*true', page) else "xvideos doesn't see you signed in with these"


def _num(text: str) -> int | None:
    """ "1,234" or "1.1k" or "2M" as a number (the short ones, about)."""
    m = re.fullmatch(r"([\d.]+)\s*([kKmM]?)", str(text or "").replace(",", "").strip())
    if not m:
        return None
    try:
        return int(float(m.group(1)) * {"k": 1_000, "m": 1_000_000}.get(m.group(2).lower(), 1))
    except ValueError:
        return None


def _ok(v: dict) -> dict | None:
    if (not XVIDEOS_ID.match(v.get("id") or "") or not XV_PATH.match(v.get("url") or "")
            or youth(v.get("title"), v.get("url"), *(v.get("tags") or []))):
        return None
    if v.get("thumb") and not XVIDEOS_CDN.match(v["thumb"]):
        v["thumb"] = None
    if v.get("uploader_path") and not XV_UPLOADER.match(v["uploader_path"]):
        v["uploader_path"] = None
    return v


def _from_json(it: dict) -> dict | None:
    """A video as xvideos' own lists give it (an uploader's, a video's related)."""
    import html as html_
    url = str(it.get("u") or "")
    m = re.fullmatch(r"/prof-video-click/[a-z]+/[A-Za-z0-9_-]+/([a-z0-9]{6,20})/([A-Za-z0-9_-]{0,200})", url)
    if m:                                       # (an uploader's list: its click-counting address, as the video's own)
        url = f"/video.{m.group(1)}/{m.group(2)}"
    return _ok({"id": str(it.get("eid") or ""), "url": url, "title": html_.unescape(str(it.get("tf") or it.get("t") or "")),
                "duration": _seconds(it.get("d")), "thumb": str(it.get("i") or "") or None,
                "uploader": html_.unescape(str(it.get("pn") or "")) or None, "uploader_path": str(it.get("pu") or "") or None,
                "channel": str(it.get("ch")) in ("True", "true", "1"), "views": str(it.get("n") or "") or None, "rating": str(it.get("r") or "") or None})


def _from_html(page: str) -> list[dict]:
    """The videos on one of xvideos' list pages (search, a tag)."""
    import html as html_
    out = []
    for blk in page.split('<div id="video_')[1:]:
        eid = re.match(r"([a-z0-9]{6,20})\"", blk)
        t = re.search(r'<p class="title"><a href="(/video[^"]+)" title="([^"]*)"', blk)
        if not eid or not t:
            continue
        up = re.search(r'<a href="(/[A-Za-z0-9_-]+)"><span class="name">([^<]+)</span>', blk)
        thumb = re.search(r'data-src="(https://[^"]+)"', blk)
        views = re.search(r'<span>([\d.,]+[kM]?) Views</span>', blk)
        v = _ok({"id": eid.group(1), "url": html_.unescape(t.group(1)), "title": html_.unescape(t.group(2)),
                 "duration": _seconds((re.search(r'<span class="duration">([^<]+)</span>', blk) or [0, ""])[1]),
                 "thumb": thumb.group(1) if thumb else None, "uploader": html_.unescape(up.group(2)) if up else None,
                 "uploader_path": up.group(1) if up else None, "channel": 'data-is-channel="1"' in blk[:400],
                 "views": views.group(1) if views else None, "rating": None})
        if v:
            out.append(v)
    return out


def xv_search(q: str, page: int = 0, length: str = "", sort: str = "relevance") -> dict:
    """xvideos' search: {"videos", "more"}. length: "" | "10" | "20" (minutes at least)."""
    q = " ".join(str(q or "").split())
    if not 1 <= len(q) <= 100 or not 0 <= page < 50 or length not in XV_LENGTHS or sort not in XV_SORTS:
        raise ValueError("bad search")
    if youth(q):
        raise ValueError("not something to look for")
    params = {"k": q, "p": page, **({"durf": XV_LENGTHS[length]} if length else {}), **({"sort": sort} if sort != "relevance" else {})}
    def fetch():
        found = _from_html(_get(f"{XVIDEOS}/?{urllib.parse.urlencode(params)}"))
        least = int(length or 0) * 60          # (its filter isn't exact: checked here too)
        return {"videos": [v for v in found if v["duration"] >= least], "more": len(found) >= 10}
    return _cached(f"xvideos:search:{urllib.parse.urlencode(params)}", fetch, 900)


def xv_tag(tag: str, page: int = 0) -> list[dict]:
    """A tag's videos (xvideos' own tag page)."""
    tag = str(tag or "").strip().lower().replace(" ", "-")
    if not re.fullmatch(r"[a-z0-9-]{2,40}", tag) or not 0 <= page < 50 or youth(tag):
        raise ValueError("bad tag")
    return _cached(f"xvideos:tag:{tag}:{page}", lambda: _from_html(_get(f"{XVIDEOS}/tags/{tag}" + (f"/{page + 1}" if page else ""))), 1800)


def xv_uploader(path: str, channel: bool | None = None, page: int = 0) -> list[dict]:
    """An uploader's videos, newest first (a channel's or a profile's; unknown: either)."""
    if not XV_UPLOADER.match(path or "") or not 0 <= page < 50:
        raise ValueError("bad uploader")
    kinds = ["channels"] if channel else ["profiles"] if channel is False else ["channels", "profiles"]
    def fetch():
        for kind in kinds:
            try:
                d = _get(f"{XVIDEOS}/{kind}{path}/videos/new/{page}", json_=True)
            except (LookupError, ValueError):
                continue
            vids = [v for v in (_from_json(it) for it in d.get("videos") or []) if v]
            if vids:
                return vids
        return []
    return _cached(f"xvideos:up:{channel}{path}:{page}", fetch, 1800)


def xv_details(url: str) -> dict:
    """A video's page: {"id", "title", "duration", "tags", "uploader", "uploader_path", "related"
    (its related videos, as xvideos shows them), and its files: "hls", "mp4", "mp4_low", "poster"}."""
    if not XV_PATH.match(url or ""):
        raise ValueError("bad xvideos video")
    import html as html_
    def fetch():
        page = _get(f"{XVIDEOS}{url}")
        def call(name):
            m = re.search(r"html5player\." + name + r"\('([^']*)'\)", page)
            return m.group(1) if m else ""
        cdn = lambda u: u if XVIDEOS_CDN.match(u) else None
        title = html_.unescape(call("setVideoTitle"))
        tags = [html_.unescape(t).strip().lower() for t in re.findall(r'<a[^>]+class="[^"]*is-keyword[^"]*"[^>]*>([^<]+)</a>', page)]
        if youth(title, url, *tags):
            raise LookupError("dreamfeed leaves that video out")
        rel = re.search(r"var video_related=(\[.*?\]);", page, re.S)
        try:
            related = [v for v in (_from_json(it) for it in json.loads(rel.group(1))) if v] if rel else []
        except ValueError:
            related = []
        up = re.search(r'<a href="(/[A-Za-z0-9_-]+)" class="[^"]*uploader-tag[^"]*"><span class="name">(?:<span[^>]*></span>)?\s*([^<]+)</span>', page)
        dur = re.search(r'<meta property="og:duration" content="(\d+)"', page)
        num = re.search(r'"id_video":\s*(\d+)', page)
        views = re.search(r'id="v-views">(?:<[^>]+>)*\s*([\d,]+)', page)
        good, bad = (re.search(r'class="rating-' + k + r'-nbr"[^>]*>([\d,.]+[kKmM]?)<', page) for k in ("good", "bad"))
        com = re.search(r'"pub_comments":\s*(\d+)', page)
        return {"id": url.split("/")[1][6:], "url": url, "title": title, "duration": int(dur.group(1)) if dur else 0,
                "num": num.group(1) if num else None, "views": _num(views.group(1)) if views else None,
                "likes": _num(good.group(1)) if good else None, "dislikes": _num(bad.group(1)) if bad else None,
                "comments": int(com.group(1)) if com else None,
                "tags": [t for t in dict.fromkeys(tags) if t][:40], "uploader": html_.unescape(up.group(2)) if up else None,
                "uploader_path": up.group(1) if up and XV_UPLOADER.match(up.group(1)) else None,
                "related": related, "hls": cdn(call("setVideoHLS")), "mp4": cdn(call("setVideoUrlHigh")),
                "mp4_low": cdn(call("setVideoUrlLow")), "poster": cdn(call("setThumbUrl169")) or cdn(call("setThumbUrl"))}
    return _cached(f"xvideos:details:{url}", fetch, 300)


def xv_comments(url: str) -> list[dict]:
    """A video's top comments (its first page: 10), top first: [{"id", "author", "text", "at" (as
    xvideos says it: "2 years ago"), "up", "down"}]. Their text is plain (xvideos' markup taken out)."""
    import html as html_
    num = xv_details(url).get("num")
    if not num:
        return []
    def fetch():
        d = _get(f"{XVIDEOS}/threads/video-comments/get-posts/top/{num}/0/0", json_=True, data=b"",
                 headers={"X-Requested-With": "XMLHttpRequest"})
        posts = ((d.get("posts") or {}).get("posts") or {}) if isinstance(d.get("posts"), dict) else {}
        out = []
        for p in posts.values():
            text = html_.unescape(re.sub(r"<br\s*/?>", "\n", str(p.get("message") or "")))
            text = re.sub(r"<[^>]+>", "", text).strip()
            if not text or youth(text):
                continue
            votes = p.get("votes") if isinstance(p.get("votes"), dict) else {}
            out.append({"id": str(p.get("id")), "author": html_.unescape(str(p.get("name") or "")), "text": text[:2000],
                        "at": str(p.get("time_diff") or p.get("date") or ""), "up": votes.get("nb"), "down": votes.get("nbb")})
        return out
    return _cached(f"xvideos:comments:{num}", fetch, 600)


def xv_vote(url: str, good: bool) -> None:
    """👍 (good) or 👎 on xvideos as you: your page's own vote address (it's tied to your session),
    sent with your cookies."""
    if not XV_PATH.match(url or ""):
        raise ValueError("bad xvideos video")
    opener = _signed_in_opener()
    if not opener:
        raise LookupError("xvideos isn't signed in (the Dashboard: Sign-ins)")
    page = _get(f"{XVIDEOS}{url}", opener=opener)
    m = re.search(r'"vote_' + ("good" if good else "bad") + r'":"((?:\\/|[A-Za-z0-9_=+-])+)"', page)
    if not m:
        raise LookupError("xvideos didn't offer a vote on that video")
    path = m.group(1).replace("\\/", "/")
    if not re.fullmatch(r"/video-vote/\d+/(?:GOOD|BAD)/[A-Za-z0-9_=+/-]+", path):
        raise LookupError("xvideos' vote address looks wrong")
    _get(f"{XVIDEOS}{path}", data=b"", opener=opener, headers={"X-Requested-With": "XMLHttpRequest", "Referer": f"{XVIDEOS}{url}"})
