"""Comics: a feed like the rest, read live from e621's pools and multporn (feed/comics.py).

- **For you**: comics chosen from what you read here (how far you get, what you follow: their
  tags) and your e621 taste (the artists and species you favorite), from e621's comics with your
  kind of posts, its latest updated, multporn's newest and searches for your tags; ranked, each
  saying why, what you've finished or follow left out (they show above).
- **Updated**: comics you follow with new pages since you last read them (looked for every few
  hours). **Continue reading**: where you left off.
- **Your comics**: the ones kept here before (imported, or made), still readable; those imported
  from a site you can still read there are followed, so their new pages come in above.
- **Search** (multporn's, e621's pools).

Drawn work: comics with words dreamfeed never allows are left out (feed/comics.py); no picture is
looked at, and nothing is downloaded.
"""
import json
import math
import re
import shutil
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dreamfeed.feed import comics as live
from dreamfeed.feed import e621

from dreamfeed.core import notices

from . import history, mutes
from .common import GENERATED, db, read_json
from .feed import _now_shown, _stale

MULTPORN = "https://multporn.net"
COMIC_PATHS = ("/comics/", "/hentai_manga/")
SEARCH_AGENT = {"User-Agent": "dreamfeed (comic search)"}
COMIC_TITLE = 100
PAGE = 24
CHECK_EVERY = 6 * 3600     # followed comics: looked at for new pages this often
_covers: dict[str, bytes] = {}      # search covers already fetched (a few hundred at most)
_ranked: dict = {"at": 0.0, "list": []}
_lock = threading.Lock()


def _tables(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS comic_follows (id TEXT PRIMARY KEY, data TEXT NOT NULL, pages INTEGER NOT NULL DEFAULT 0,
        seen INTEGER NOT NULL DEFAULT 0, new_at REAL, checked_at REAL, at REAL NOT NULL)""")
    conn.execute("CREATE TABLE IF NOT EXISTS comic_refused (id TEXT PRIMARY KEY, at REAL NOT NULL)")   # (a page with a word never allowed: left out after)
    conn.execute("""CREATE TABLE IF NOT EXISTS comic_reads (id TEXT PRIMARY KEY, data TEXT NOT NULL, page INTEGER NOT NULL DEFAULT 1,
        furthest INTEGER NOT NULL DEFAULT 1, pages INTEGER NOT NULL DEFAULT 0, opened INTEGER NOT NULL DEFAULT 0,
        first_at REAL NOT NULL, last_at REAL NOT NULL)""")


def _conn():
    conn = db()
    _tables(conn)
    return conn


def _card(c: dict) -> dict:
    """What's kept of a comic for its card (and taste): no pages."""
    return {k: c.get(k) for k in ("id", "source", "title", "pages", "cover", "tags", "artists", "updated", "link")}


# ---- search (multporn's own, e621's pools by name) ----
def comic_search(q: str, page: int, site: str = "multporn") -> dict:
    """{"results": [comic cards ({"id", "title", "thumb", "url"} ...)], "more"}."""
    import html
    import urllib.request
    q = " ".join(str(q or "").split())
    if not 1 <= len(q) <= 100:
        raise ValueError("type what to look for (up to 100 characters)")
    if live.blocked(q):
        raise ValueError("not something to look for")
    if site == "e621":
        try:
            found = live.e621_pools(name=q, page=page + 1)
        except OSError as e:
            raise LookupError(f"e621 didn't answer ({e})")
        return {"results": [{**c, "url": c["link"], "thumb": "comic-search/thumb?u=" + urllib.parse.quote(c["cover"], safe="") if c.get("cover") else None}
                            for c in mutes.comics(found)], "more": len(found) >= live.PAGE - 6}
    if site != "multporn":
        raise ValueError("bad site")
    url = f"{MULTPORN}/search?" + urllib.parse.urlencode({"search_api_views_fulltext": q, "page": page})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=SEARCH_AGENT), timeout=30) as r:
            page_html = r.read().decode("utf-8", "replace")
    except OSError as e:
        raise LookupError(f"multporn didn't answer ({e})")
    out = []
    for row in re.split(r'<div class="masonry-item views-row', page_html)[1:]:
        link = re.search(r'views-field-title">\s*<span class="field-content"><a href="/comics/([a-z0-9_-]+)(?:\?[^"]*)?">(.*?)</a>', row, re.S)
        img = re.search(r'<img[^>]+src="(https://multporn\.net/sites/default/files/[^"]+)"', row)
        if not link:
            continue
        title = html.unescape(re.sub(r"<[^>]+>", "", link.group(2))).strip()
        if live.blocked(title):
            continue
        cover = html.unescape(img.group(1)) if img else None
        out.append({"id": f"mp:{link.group(1)}", "source": "multporn", "title": title, "cover": cover,
                    "thumb": "comic-search/thumb?u=" + urllib.parse.quote(cover, safe="") if cover else None,
                    "url": f"{MULTPORN}/comics/{link.group(1)}", "link": f"{MULTPORN}/comics/{link.group(1)}", "tags": []})
    return {"results": mutes.comics(out), "more": f"page={page + 1}" in page_html, "tags": tag_matches(q) if page == 0 else []}


# ---- browse: multporn's New and Updated comics, a tag's comics (multporn's or e621's) ----
LISTS = ("new", "updated", "tag")


def _refused() -> set:
    with _conn() as conn:
        return {r[0] for r in conn.execute("SELECT id FROM comic_refused")}


def browse(which: str, page: int, tag: str = "", sort: str = "new", site: str = "multporn") -> dict:
    """{"results": comic cards, "more", "tag"?}: one page of a list (two of multporn's, as its are short)."""
    if which not in LISTS or not 0 <= page < 200 or site not in ("multporn", "e621") or sort not in live.SORTS:
        raise ValueError("bad list")
    if which == "tag":
        tag = " ".join(str(tag or "").lower().split())
        if not tag:
            raise ValueError("pick a tag")
    if site == "e621":
        if which != "tag":
            raise ValueError("bad list")
        got = live.e621_pools_tagged(tag, page, sort)
        found, more = got["comics"], got["more"]
    else:
        slug = re.sub(r"[^a-z0-9]+", "_", tag).strip("_")
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.map(lambda n: live.multporn_list(which, n, slug, sort), (2 * page, 2 * page + 1))
        seen = set()
        found = [c for c in a["comics"] + (b["comics"] if a["more"] else []) if not (c["id"] in seen or seen.add(c["id"]))]
        more = a["more"] and b["more"]
        tag = slug
    skip = _refused()
    out = {"results": [{**c, "thumb": cover_thumb(c.get("cover"))} for c in mutes.comics(found) if c["id"] not in skip], "more": more}
    if which == "tag":
        names = {t["tag"]: t["name"] for t in _tags_or_none() or []} if site == "multporn" else {}
        out["tag"] = {"tag": tag, "name": names.get(tag) or tag.replace("_", " "), "site": site}
    return out


def _tags_or_none() -> list[dict] | None:
    try:
        return live.multporn_tags()
    except (LookupError, OSError):
        return None


def tags() -> dict:
    """{"tags": [{"tag", "name"}]}: multporn's tags for comics, A to Z (to browse one)."""
    got = _tags_or_none()
    if got is None:
        raise LookupError("multporn didn't answer")
    return {"tags": got}


def tag_matches(q: str) -> list[dict]:
    """multporn's tags that a search names (to browse one instead)."""
    words = " ".join(q.lower().replace("_", " ").split())
    found = [t for t in _tags_or_none() or [] if words and (t["name"].lower() == words or t["tag"].replace("_", " ") == words)]
    return found + [t for t in _tags_or_none() or [] if len(words) >= 3 and words in t["name"].lower() and t not in found][:5]


def cover_thumb(cover: str | None) -> str | None:
    """A cover's address for the page: e621's through dreamfeed, multporn's fetched here."""
    if not cover:
        return None
    if cover.startswith("https://static1.e621.net/data/"):
        return "e621-media/" + cover[len("https://static1.e621.net/"):]
    return "comic-search/thumb?u=" + urllib.parse.quote(cover, safe="")


def comic_cover(u: str) -> bytes | None:
    """A cover, fetched here (for the iOS app, which can't load multporn's pictures itself)."""
    import urllib.request
    multporn, e6 = u.startswith(MULTPORN + "/sites/default/files/"), u.startswith("https://static1.e621.net/data/")
    if not (multporn or e6) or ".." in u:
        return None
    if u not in _covers:
        try:
            if e6:
                data = e621.fetch(u, 4 << 20)
            else:
                with urllib.request.urlopen(urllib.request.Request(u, headers=live.MP_AGENT), timeout=30) as r:
                    data = r.read(4 << 20)
        except (OSError, ValueError):
            return None
        if data[:3] != b"\xff\xd8\xff" and data[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        if len(_covers) > 400:
            _covers.clear()
        _covers[u] = data
    return _covers[u]


# ---- reading one, following ----
def read(cid: str) -> dict:
    """A comic to read: its pages (straight from the site), where you left off, whether you follow it.
    One with a page dreamfeed never allows (only seen once it's opened: lists judge by covers) is
    refused, and left out of For you from then on."""
    try:
        c = live.comic(cid)
    except LookupError as e:
        if "leaves that comic out" in str(e):
            with _conn() as conn:
                conn.execute("INSERT OR REPLACE INTO comic_refused (id, at) VALUES (?, ?)", (str(cid), time.time()))
            with _lock:
                _ranked["at"] = 0
        raise
    now = time.time()
    with _conn() as conn:
        conn.execute("INSERT INTO comic_reads (id, data, pages, opened, first_at, last_at) VALUES (?, ?, ?, 1, ?, ?)"
                     " ON CONFLICT(id) DO UPDATE SET data = excluded.data, pages = excluded.pages, opened = opened + 1, last_at = excluded.last_at",
                     (c["id"], json.dumps(_card(c)), len(c["images"]), now, now))
        r = conn.execute("SELECT page FROM comic_reads WHERE id = ?", (c["id"],)).fetchone()
        f = conn.execute("SELECT seen FROM comic_follows WHERE id = ?", (c["id"],)).fetchone()
    history.note("comic", c["id"], c.get("title") or "", "comics/" + c["id"].replace(":", "/", 1), cover_thumb(c.get("cover")), _card(c))
    return {**c, "page": r["page"] if r else 1, "followed": bool(f), "new_from": (f["seen"] + 1) if f and f["seen"] else None}


def progress(req: dict) -> dict:
    """{"id", "page"}: where you are in it."""
    cid = str(req.get("id", ""))
    try:
        page = int(req.get("page"))
    except (TypeError, ValueError):
        raise ValueError("bad page")
    if not re.fullmatch(r"(?:e621:\d{1,9}|mp:[a-z0-9_-]{1,120})", cid) or not 1 <= page <= 1000:
        raise ValueError("bad page")
    with _conn() as conn:
        conn.execute("UPDATE comic_reads SET page = ?, furthest = max(furthest, ?), last_at = ? WHERE id = ?", (page, page, time.time(), cid))
        conn.execute("UPDATE comic_follows SET seen = max(seen, ?) WHERE id = ?", (page, cid))
    return {"ok": True}


def follow(req: dict) -> dict:
    """{"id", "follow": bool}: its new pages come in Updated."""
    cid = str(req.get("id", ""))
    if not re.fullmatch(r"(?:e621:\d{1,9}|mp:[a-z0-9_-]{1,120})", cid):
        raise ValueError("bad comic")
    with _conn() as conn:
        if req.get("follow"):
            c = live.comic(cid)
            r = conn.execute("SELECT furthest FROM comic_reads WHERE id = ?", (cid,)).fetchone()
            conn.execute("INSERT OR REPLACE INTO comic_follows (id, data, pages, seen, checked_at, at) VALUES (?, ?, ?, ?, ?, ?)",
                         (cid, json.dumps(_card(c)), len(c["images"]), r["furthest"] if r else 0, time.time(), time.time()))
        else:
            conn.execute("DELETE FROM comic_follows WHERE id = ?", (cid,))
    with _lock:
        _ranked["at"] = 0
    return {"followed": bool(req.get("follow"))}


def _check_follows() -> None:
    """New pages of the comics you follow (each looked at every CHECK_EVERY)."""
    with _conn() as conn:
        rows = conn.execute("SELECT id, pages, seen, data FROM comic_follows WHERE checked_at IS NULL OR checked_at < ?",
                            (time.time() - CHECK_EVERY,)).fetchall()
    for r in rows:
        try:
            n = live.page_count(r["id"])
        except (LookupError, ValueError, OSError):
            n = None
        with _conn() as conn:
            if n and n > r["pages"]:
                conn.execute("UPDATE comic_follows SET pages = ?, new_at = ?, checked_at = ? WHERE id = ?", (n, time.time(), time.time(), r["id"]))
                c = json.loads(r["data"])
                new = n - max(r["seen"], r["pages"])
                notices.add(conn, "comics", f"comic:{r['id']}:{n}", f"{c.get('title') or 'A comic you follow'}: "
                            f"{new} new page{'s' if new != 1 else ''}", f"{n} pages now", "comics/" + r["id"].replace(":", "/", 1),
                            cover_thumb(c.get("cover")))
            else:
                conn.execute("UPDATE comic_follows SET checked_at = ? WHERE id = ?", (time.time(), r["id"]))
        time.sleep(2)


def watch_follows() -> None:
    """The web app's thread: followed comics looked at for new pages; your kept comics imported
    from a site followed there (once)."""
    time.sleep(60)
    try:
        _follow_library()
    except Exception as e:                       # (it's only a convenience: logged, not fatal)
        print(time.strftime("%F %T"), f"web: following your imported comics: {e}", flush=True)
    while True:
        try:
            _check_follows()
        except Exception as e:
            print(time.strftime("%F %T"), f"web: followed comics: {e}", flush=True)
        time.sleep(1800)


def _follow_library() -> None:
    with _conn() as conn:
        done = conn.execute("SELECT count(*) FROM comic_follows WHERE json_extract(data, '$.from_library')").fetchone()[0]
        if done:
            return
        for lib in library():
            m = re.match(r"https://multporn\.net/comics/([a-z0-9_-]+)", lib.get("source") or "")
            if not m:
                continue
            cid = f"mp:{m.group(1)}"
            if conn.execute("SELECT 1 FROM comic_follows WHERE id = ?", (cid,)).fetchone():
                continue
            card = {"id": cid, "source": "multporn", "title": lib["title"], "pages": lib["pages"], "cover": None, "tags": [],
                    "link": lib["source"], "from_library": True}
            conn.execute("INSERT INTO comic_follows (id, data, pages, seen, checked_at, at) VALUES (?, ?, ?, ?, NULL, ?)",
                         (cid, json.dumps(card), lib["pages"], lib["pages"], time.time()))


# ---- your taste, and For you ----
def taste() -> dict:
    """{"tags": {tag: weight}, "n"}: from how far you read comics here, and what you follow."""
    tags, n, now = {}, 0, time.time()
    with _conn() as conn:
        reads = conn.execute("SELECT data, furthest, pages, opened, last_at FROM comic_reads").fetchall()
        follows = conn.execute("SELECT data, at FROM comic_follows").fetchall()
    for r in reads:
        d, pages = json.loads(r["data"]), max(1, r["pages"])
        share = r["furthest"] / pages
        s = 1.0 if share >= 0.9 else 0.6 if share >= 0.3 else -0.3 if r["furthest"] <= 2 and pages > 5 else 0.2
        s *= 0.5 ** ((now - r["last_at"]) / 86400 / 30)
        vt = d.get("tags") or []
        for t in vt:
            tags[t] = tags.get(t, 0.0) + s / math.sqrt(len(vt))
        n += 1
    for f in follows:
        vt = json.loads(f["data"]).get("tags") or []
        for t in vt:
            tags[t] = tags.get(t, 0.0) + 1.5 / math.sqrt(len(vt))
        n += 1
    return {"tags": tags, "n": n}


def _candidates(t: dict) -> list[tuple[dict, float, str]]:
    top = [g for g, w in sorted(t["tags"].items(), key=lambda kv: -kv[1]) if w > 0.3][:6]
    jobs = [(0.5, "Just updated on e621", lambda: live.e621_pools()),
            (0.45, "New on multporn", lambda: live.multporn_new()),
            (0.4, "New on multporn", lambda: live.multporn_new(1))]
    mine = e621.taste() if e621.creds() else None
    if mine and (mine["artists"] or mine["species"]):
        jobs.append((0.9, "Artists you favorite on e621", lambda: live.e621_pools_like(mine["artists"] or mine["species"])))
    if top:
        jobs.append((0.8, f"Because you read {', '.join(top[:3])}", lambda: live.e621_pools_like([g.replace(" ", "_") for g in top])))
        for g in top[:2]:
            jobs.append((0.7, f"You like {g}", lambda g=g: comic_search(g, 0)["results"]))

    def run(job):
        prior, why, read_ = job
        try:
            return [(c, prior, why) for c in read_()]
        except (LookupError, ValueError, OSError):
            return []
    with ThreadPoolExecutor(max_workers=4) as pool:
        return [c for got in pool.map(run, jobs) for c in got]


def _rank() -> list[dict]:
    t = taste()
    with _conn() as conn:
        skip = {r[0] for r in conn.execute("SELECT id FROM comic_follows")} | {r[0] for r in conn.execute("SELECT id FROM comic_refused")} | \
               {r[0] for r in conn.execute("SELECT id FROM comic_reads WHERE furthest * 10 >= pages * 9 AND pages > 0")}
    best, mr = {}, mutes.rules()
    for c, prior, why in _candidates(t):
        if c["id"] in skip or mutes.comic_muted(c, mr):
            continue
        tags = {x.replace("_", " ") for x in c.get("tags") or []}
        s = prior + 0.25 * sum(w for g, w in t["tags"].items() if g.replace("_", " ") in tags)
        if c["id"] not in best or best[c["id"]][0] < s:
            best[c["id"]] = (s, c, why)
    return [{**_card(c), "why": why} for s, c, why in sorted(best.values(), key=lambda x: -x[0])]


def feed(offset: int) -> dict:
    """{"updated", "continue", "comics": a page of For you, "more", "library" (first page only)}."""
    if not 0 <= offset < 2000:
        raise ValueError("bad page")
    with _lock:
        fresh = time.time() - _ranked["at"] < 600 and offset > 0
        ranked = _ranked["list"] if fresh else None
    if ranked is None:
        ranked = _rank()
        old = _stale(f"comic:{c['id']}" for c in ranked)
        ranked = [c for c in ranked if f"comic:{c['id']}" not in old] + [c for c in ranked if f"comic:{c['id']}" in old]
        with _lock:
            _ranked.update(at=time.time(), list=ranked)
    page = ranked[offset:offset + PAGE]
    _now_shown([{"id": f"comic:{c['id']}"} for c in page])
    out = {"comics": page, "more": offset + PAGE < len(ranked)}
    if offset == 0:
        with _conn() as conn:
            out["updated"] = [{**json.loads(r["data"]), "pages": r["pages"], "new": r["pages"] - r["seen"]}
                              for r in conn.execute("SELECT * FROM comic_follows WHERE pages > seen ORDER BY coalesce(new_at, at) DESC LIMIT 20")]
            out["following"] = [{**json.loads(r["data"]), "pages": r["pages"]}
                                for r in conn.execute("SELECT * FROM comic_follows WHERE pages <= seen ORDER BY at DESC LIMIT 40")]
            out["continue"] = [{**json.loads(r["data"]), "page": r["page"], "pages": r["pages"]}
                               for r in conn.execute("SELECT * FROM comic_reads WHERE furthest * 10 < pages * 9 AND furthest > 1"
                                                     " AND id NOT IN (SELECT id FROM comic_follows) ORDER BY last_at DESC LIMIT 12")]
        out["library"] = library()
        t = taste()
        out["taste"] = {"tags": [g for g, w in sorted(t["tags"].items(), key=lambda kv: -kv[1]) if w > 0.3][:8], "n": t["n"]}
    return out


# ---- your comics (kept here before: imported, or made) ----
def _comic_meta(file: str) -> dict:
    return read_json((GENERATED / file).parent / "comic.json")


def library() -> list[dict]:
    out = []
    with db() as conn:
        for r in conn.execute("SELECT g.id, g.caption, g.file, g.created_at FROM generations g"
                              " WHERE g.kind = 'comic' AND g.status = 'comic' ORDER BY g.id DESC LIMIT 200"):
            meta = _comic_meta(r["file"])
            out.append({"id": r["id"], "title": r["caption"] or meta.get("title") or "", "pages": len(meta.get("pages") or [1]),
                        "imported": bool(meta.get("imported")), "source": meta.get("source"), "created": r["created_at"]})
    return out


def comics() -> dict:
    """Your comics (the iOS app's list: they're its library now)."""
    return {"comics": [{**c, "cast": [], "story": "", "animations": [], "panels": {}, "outlines": {}} for c in library()],
            "making": [], "failed": []}


def comic_page(gid: int, n: int, thumb: bool = False) -> Path | None:
    """Page n of one of your comics; thumb: its small copy (the page itself if there's none)."""
    with db() as conn:
        row = conn.execute("SELECT file FROM generations WHERE id = ? AND kind = 'comic'", (gid,)).fetchone()
    if not row:
        return None
    meta = _comic_meta(row["file"])
    pages = (meta.get("thumbs") if thumb else None) or meta.get("pages") or [row["file"]]
    if not 1 <= n <= len(pages):
        return None
    path = (GENERATED / pages[n - 1]).resolve()
    return path if path.is_relative_to(GENERATED.resolve()) and path.is_file() else None


def _finished_comic(gid: int) -> tuple[Path, dict]:
    with db() as conn:
        row = conn.execute("SELECT file FROM generations WHERE id = ? AND kind = 'comic' AND status = 'comic'", (gid,)).fetchone()
    if not row:
        raise LookupError("no such comic")
    folder = (GENERATED / row["file"]).parent.resolve()
    if not folder.is_relative_to(GENERATED.resolve()):
        raise LookupError("no such comic")
    return folder, read_json(folder / "comic.json")


def rename_comic(req: dict) -> dict:
    """{"id", "title"}"""
    gid = int(req.get("id", 0))
    title = " ".join(str(req.get("title") or "").split())[:COMIC_TITLE]
    if not title:
        raise ValueError("give it a title")
    folder, meta = _finished_comic(gid)
    (folder / "comic.json").write_text(json.dumps(meta | {"title": title}, ensure_ascii=False, indent=1))
    with db() as conn:
        conn.execute("UPDATE generations SET caption = ? WHERE id = ?", (title, gid))
    return {"ok": True, "title": title}


def delete_comic(req: dict) -> dict:
    gid = int(req.get("id", 0))
    with db() as conn:
        row = conn.execute("SELECT file FROM generations WHERE id = ? AND kind = 'comic'", (gid,)).fetchone()
        if not row:
            raise LookupError("no such comic")
        folder = (GENERATED / row["file"]).parent.resolve()
        if folder.is_relative_to(GENERATED.resolve()) and folder != GENERATED.resolve():
            shutil.rmtree(folder, ignore_errors=True)
        conn.execute("UPDATE generations SET status = 'deleted' WHERE id = ?", (gid,))
    return {"ok": True}
