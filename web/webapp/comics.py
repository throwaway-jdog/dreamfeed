"""Comics: searching and importing them (multporn, e621's pools), making them, their pages and
animated panels.
"""
import json
import re
import shutil
import urllib.parse
from pathlib import Path

from dreamfeed.core import acts, cookies, personas as people, safety
from dreamfeed.feed import e621, livefeeds, savedposts

from .common import GENERATED, MEDIUMS, db, item, read_json
from .editor import read_personas
from .posts import _retried


MULTPORN = "https://multporn.net"
COMIC_PATHS = ("/comics/", "/hentai_manga/")
SEARCH_AGENT = {"User-Agent": "dreamfeed (comic search)"}
_covers: dict[str, bytes] = {}      # search covers already fetched (a few hundred at most)


def comic_search(q: str, page: int, site: str = "multporn") -> dict:
    """multporn's search for q: its comics and manga (not videos or games), each {"title", "url",
    "thumb"}. A search with words the dashboard never takes is refused, and so is a result
    whose title has them."""
    import html
    import urllib.parse
    import urllib.request
    if site == "e621":
        try:
            d = e621.pools(q, page)
        except OSError as e:
            raise LookupError(f"e621 didn't answer ({e})")
        d["results"] = [r for r in d["results"] if not safety.story_blocked(r["title"])]   # (what Import takes)
        for r in d["results"]:
            r["thumb"] = "comic-search/thumb?u=" + urllib.parse.quote(r.pop("cover") or "", safe="") if r.get("cover") else None
        return d
    if site != "multporn":
        raise ValueError("bad site")
    q = q.strip()
    if not 1 <= len(q) <= 100:
        raise ValueError("type what to look for (up to 100 characters)")
    bad = safety.request_blocked(q)
    if bad:
        raise ValueError(f"not something to look for: {', '.join(bad)}")
    url = f"{MULTPORN}/search?" + urllib.parse.urlencode({"search_api_views_fulltext": q, "page": page})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=SEARCH_AGENT), timeout=30) as r:
            page_html = r.read().decode("utf-8", "replace")
    except OSError as e:
        raise LookupError(f"multporn didn't answer ({e})")
    out = []
    for row in re.split(r'<div class="masonry-item views-row', page_html)[1:]:
        # the title's own link; its text can have the searched words in <strong>
        link = re.search(r'views-field-title">\s*<span class="field-content"><a href="([^"]+)">(.*?)</a>', row, re.S)
        img = re.search(r'<img[^>]+src="(https://multporn\.net/sites/default/files/[^"]+)"', row)
        if not link or not link.group(1).startswith(COMIC_PATHS):
            continue
        title = html.unescape(re.sub(r"<[^>]+>", "", link.group(2))).strip()
        if safety.story_blocked(title):     # what Import would refuse isn't offered
            continue
        out.append({"title": title, "url": MULTPORN + link.group(1),
                    "thumb": "comic-search/thumb?u=" + urllib.parse.quote(html.unescape(img.group(1)), safe="") if img else None})
    return {"results": out, "more": f"page={page + 1}" in page_html}


def comic_cover(u: str) -> bytes | None:
    """A search result's cover: multporn's, or the preview of an e621 pool's first post (whose
    tags e621.pools already checked)."""
    import urllib.request
    multporn, e6 = u.startswith(MULTPORN + "/sites/default/files/"), u.startswith("https://static1.e621.net/data/preview/")
    if not (multporn or e6) or ".." in u:
        return None
    if u not in _covers:
        try:
            if e6:
                data = e621.fetch(u, 4 << 20)
            else:
                with urllib.request.urlopen(urllib.request.Request(u, headers=SEARCH_AGENT), timeout=30) as r:
                    data = r.read(4 << 20)
        except (OSError, ValueError):
            return None
        if data[:3] != b"\xff\xd8\xff":     # covers are JPEGs
            return None
        if len(_covers) > 400:
            _covers.clear()
        _covers[u] = data
    return _covers[u]


COMIC_STORY = 600
COMIC_PAGES = 4
COMIC_TITLE = 100


def _comic_meta(file: str) -> dict:
    return read_json((GENERATED / file).parent / "comic.json")


def comics() -> dict:
    """Finished comics (newest first), and the ones being made."""
    out = {"comics": [], "making": []}
    with db() as conn:
        for r in conn.execute("SELECT g.id, g.caption, g.persona, g.file, g.created_at, g.status, p.name FROM generations g"
                              " LEFT JOIN personas p ON p.handle = g.persona"
                              " WHERE g.kind = 'comic' AND g.status = 'comic'"
                              " ORDER BY g.id DESC LIMIT 100"):
            meta = _comic_meta(r["file"])
            out["comics"].append({"id": r["id"], "title": r["caption"] or "", "persona": r["persona"],
                                  "name": r["name"] or r["persona"], "pages": len(meta.get("pages") or [1]),
                                  "cast": meta.get("cast") or [], "story": meta.get("story", ""),
                                  "imported": bool(meta.get("imported")),
                                  "updated": meta.get("updated"),
                                  "panels": meta.get("panels") or {},
                                  "outlines": meta.get("outlines") or {},
                                  "animations": [{"page": a["page"], "box": a["box"], "name": Path(a["file"]).name,
                                                  "mask": Path(a["mask"]).name if a.get("mask") else None}
                                                 for a in meta.get("animations") or []],
                                  "created": r["created_at"]})
        # Comic jobs that failed in the last day, with why: they'd otherwise just vanish from "being made".
        out["failed"] = []
        for r in conn.execute("SELECT id, params, message, finished_at FROM jobs WHERE status = 'failed'"
                              " AND params LIKE '%\"kind\": \"comic%' AND finished_at >= datetime('now', '-1 day')"
                              " ORDER BY id DESC LIMIT 10"):
            if _retried(conn, r["id"], r["params"]):   # tried again since: that one shows instead
                continue
            params = json.loads(r["params"])
            what = {"comic": "Making a comic", "comic_import": "Importing a comic",
                    "comic_update": "Looking for new pages",
                    "comic_animate": f"Animating a panel on page {params.get('page')}"}.get(params.get("kind"))
            if not what:
                continue
            title = ""
            if params.get("id"):
                row = conn.execute("SELECT caption FROM generations WHERE id = ?", (params["id"],)).fetchone()
                title = row["caption"] if row else ""
            out["failed"].append({"job": r["id"], "what": what, "title": title or params.get("url", ""),
                                  "message": r["message"] or "", "finished": r["finished_at"]})
        for r in conn.execute("SELECT j.id, j.params, j.status, r.progress FROM jobs j LEFT JOIN runs r ON r.night = j.night"
                              " WHERE j.status IN ('queued', 'running') AND j.params LIKE '%\"kind\": \"comic%'"):
            params = json.loads(r["params"])
            if params.get("kind") not in ("comic", "comic_import", "comic_animate", "comic_update"):
                continue
            item = {"job": r["id"], "status": r["status"], "progress": json.loads(r["progress"]) if r["progress"] else None}
            if params["kind"] == "comic_import":
                item |= {"imported": True, "title": params.get("title") or "", "url": params["url"]}
            elif params["kind"] == "comic_update":
                title = conn.execute("SELECT caption FROM generations WHERE id = ?", (params["id"],)).fetchone() \
                    if params.get("id") else None
                item |= {"imported": True, "title": title["caption"] if title else "Every imported comic",
                         "url": "looking for new pages"}
            elif params["kind"] == "comic_animate":
                title = conn.execute("SELECT caption FROM generations WHERE id = ?", (params["id"],)).fetchone()
                item |= {"imported": True, "title": title["caption"] if title else "",
                         "url": f"animating a panel of page {params['page']}",
                         "comic": params["id"], "page": params["page"], "box": params["box"]}
            else:
                item |= {"cast": params["cast"], "story": params["story"], "pages": params["pages"]}
            out["making"].append(item)
    return out


def comic_page(gid: int, n: int, thumb: bool = False) -> Path | None:
    """Page n of a comic; thumb: its small copy (the page itself if there's none yet)."""
    with db() as conn:
        row = conn.execute("SELECT file FROM generations WHERE id = ? AND kind = 'comic'", (gid,)).fetchone()
    if not row:
        return None
    meta = _comic_meta(row["file"])
    pages = (meta.get("thumbs") if thumb else None) \
        or meta.get("pages") or [row["file"]]
    if not 1 <= n <= len(pages):
        return None
    path = (GENERATED / pages[n - 1]).resolve()
    return path if path.is_relative_to(GENERATED.resolve()) and path.is_file() else None


def queue_comic(req: dict) -> dict:
    """{"cast": [persona, persona | "partner"], "story", "pages"}: checked here as the worker checks it."""
    cast = req.get("cast")
    if not isinstance(cast, list) or len(cast) != 2:
        raise ValueError("pick two characters")
    every = {p.handle: p for p in people.parse(read_personas())}
    a = every.get(str(cast[0]))
    if not a or not a.lora:
        raise ValueError("the first character must be a persona with a trained style")
    if cast[1] != "partner":
        b = every.get(str(cast[1]))
        if not b or b.handle == a.handle:
            raise ValueError("pick a second persona, or her partner")
        if b.medium != a.medium:
            raise ValueError(f"@{a.handle} is {a.medium} and @{b.handle} is {b.medium}")
        if a.strict or b.strict:
            raise ValueError("personas using the strict checks can't be in a comic together")
    story = " ".join(str(req.get("story") or "").split())
    if not story:
        raise ValueError("write a few words of story")
    if len(story) > COMIC_STORY:
        raise ValueError(f"keep the story under {COMIC_STORY} characters")
    bad = safety.story_blocked(story)
    if bad:
        raise ValueError(f"the story can't include: {', '.join(bad)}")
    try:
        pages = int(req.get("pages", 1))
    except (TypeError, ValueError):
        raise ValueError("bad page count")
    if not 1 <= pages <= COMIC_PAGES:
        raise ValueError(f"1 to {COMIC_PAGES} pages")
    with db() as conn:
        jid = conn.execute("INSERT INTO jobs(params, status) VALUES (?, 'queued')", (json.dumps(
            {"kind": "comic", "cast": [a.handle, str(cast[1])], "story": story, "pages": pages}),)).lastrowid
    return {"job": jid}


def queue_comic_import(req: dict) -> dict:
    """{"url", "title", "medium"}: a comic from its gallery's link, kept as drawn."""
    url = str(req.get("url") or "").strip()
    if not re.match(r"https?://[^\s/]+\.[^\s/]+/\S*$", url):
        raise ValueError("paste a link to the comic's gallery")
    if re.match(r"https?://(www\.)?multporn\.net/sites/", url):
        raise ValueError("that's multporn's full-screen viewer, which doesn't say which comic it shows: "
                         "paste the comic's own page instead (multporn.net/comics/...)")
    title = " ".join(str(req.get("title") or "").split())[:COMIC_TITLE]
    medium = req.get("medium")
    if medium not in MEDIUMS:
        raise ValueError("pick furry or anime")
    bad = safety.story_blocked(f"{title} {url}")
    if bad:
        raise ValueError(f"the comic can't include: {', '.join(bad)}")
    with db() as conn:
        jid = conn.execute("INSERT INTO jobs(params, status) VALUES (?, 'queued')", (json.dumps(
            {"kind": "comic_import", "url": url, "title": title, "medium": medium}),)).lastrowid
    return {"job": jid}


def queue_comic_update(req: dict) -> dict:
    """{"id": N}: look for new pages of that imported comic now (they're looked for daily anyway)."""
    try:
        gid = int(req["id"])
    except (KeyError, TypeError, ValueError):
        raise ValueError('send {"id": number}')
    _, meta = _finished_comic(gid)
    if not meta.get("imported"):
        raise ValueError("only imported comics have a source to look at")
    with db() as conn:
        if conn.execute("SELECT 1 FROM jobs WHERE status IN ('queued', 'running') AND params = ?",
                        (json.dumps({"kind": "comic_update", "id": gid}),)).fetchone():
            raise ValueError("already looking")
        jid = conn.execute("INSERT INTO jobs(params, status) VALUES (?, 'queued')",
                           (json.dumps({"kind": "comic_update", "id": gid}),)).lastrowid
    return {"job": jid}


ANIMATE_MOTION = 200      # characters of "what moves"
ANIMATE_CASTS = ("woman", "women", "woman and man", "man", "men")   # comicanim.CASTS
OUTLINE_LOOPS = 8         # loops drawn around what moves, per panel
OUTLINE_POINTS = 2000     # per loop


def _finished_comic(gid: int) -> tuple[Path, dict]:
    with db() as conn:
        row = conn.execute("SELECT file FROM generations WHERE id = ? AND kind = 'comic' AND status = 'comic'",
                           (gid,)).fetchone()
    if not row:
        raise LookupError("no such comic")
    folder = (GENERATED / row["file"]).parent.resolve()
    if not folder.is_relative_to(GENERATED.resolve()):
        raise LookupError("no such comic")
    return folder, read_json(folder / "comic.json")


def queue_comic_animation(req: dict) -> dict:
    """{"id", "page" (from 1), "box": [x0, y0, x1, y1] shares of the page, "motion", "cast",
    "outline": [[[x, y], ...], ...] loops drawn around what moves, shares of the page (optional;
    they may reach past the panel)}: one panel animated into a short loop."""
    gid = int(req.get("id", 0))
    folder, meta = _finished_comic(gid)
    try:
        page = int(req.get("page", 0))
    except (TypeError, ValueError):
        raise ValueError("bad page")
    if not 1 <= page <= len(meta.get("pages") or []):
        raise ValueError("bad page")
    box = req.get("box")
    if not isinstance(box, list) or len(box) != 4 or not all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in box):
        raise ValueError("bad panel")
    x0, y0, x1, y1 = (round(float(v), 4) for v in box)
    if x1 - x0 < 0.05 or y1 - y0 < 0.05:
        raise ValueError("that panel is too small")
    motion = " ".join(str(req.get("motion") or "").split())
    if len(motion) > ANIMATE_MOTION:
        raise ValueError(f"keep it under {ANIMATE_MOTION} characters")
    bad = safety.request_blocked(motion)
    if bad:
        raise ValueError(f"can't include: {', '.join(bad)}")
    cast = str(req.get("cast") or "")
    if cast and cast not in ANIMATE_CASTS:
        raise ValueError("bad choice of who's in it")
    outline = req.get("outline") or []
    if not isinstance(outline, list) or len(outline) > OUTLINE_LOOPS:
        raise ValueError(f"at most {OUTLINE_LOOPS} outlines")
    loops = []
    for loop in outline:
        if not isinstance(loop, list) or not 3 <= len(loop) <= OUTLINE_POINTS or not all(
                isinstance(q, list) and len(q) == 2 and all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in q) for q in loop):
            raise ValueError("bad outline")
        loops.append([[round(float(x), 4), round(float(y), 4)] for x, y in loop])
    params = {"kind": "comic_animate", "id": gid, "page": page, "box": [x0, y0, x1, y1], "motion": motion, "cast": cast}
    if loops:
        params["outline"] = loops
    with db() as conn:
        if conn.execute("SELECT count(*) FROM jobs WHERE status IN ('queued', 'running') AND params = ?",
                        (json.dumps(params),)).fetchone()[0]:
            raise ValueError("this exact animation is already waiting")
        jid = conn.execute("INSERT INTO jobs(params, status) VALUES (?, 'queued')", (json.dumps(params),)).lastrowid
    return {"job": jid}


def delete_comic_animation(req: dict) -> dict:
    """{"id", "index"}: an animated panel back to the still page."""
    gid, index = int(req.get("id", 0)), int(req.get("index", -1))
    folder, meta = _finished_comic(gid)
    anims = meta.get("animations") or []
    if not 0 <= index < len(anims):
        raise LookupError("no such animation")
    gone = anims.pop(index)
    for file in (gone["file"], gone.get("mask")):
        path = (GENERATED / file).resolve() if file else None
        if path and path.is_relative_to(folder):
            path.unlink(missing_ok=True)
    (folder / "comic.json").write_text(json.dumps(meta | {"animations": anims}, ensure_ascii=False, indent=1))
    return {"ok": True}


def comic_animation(gid: int, name: str) -> Path | None:
    """A comic's clip, or the mask of what moves in it, by its file name (names are never
    reused, so a cached copy is the right one)."""
    try:
        folder, meta = _finished_comic(gid)
    except LookupError:
        return None
    for a in meta.get("animations") or []:
        for file in (a["file"], a.get("mask")):
            if file and Path(file).name == name:
                path = (GENERATED / file).resolve()
                return path if path.is_relative_to(folder) and path.is_file() else None
    return None


def rename_comic(req: dict) -> dict:
    """{"id", "title"}"""
    gid = int(req.get("id", 0))
    title = " ".join(str(req.get("title") or "").split())[:COMIC_TITLE]
    if not title:
        raise ValueError("give it a title")
    bad = safety.story_blocked(title)
    if bad:
        raise ValueError(f"the title can't include: {', '.join(bad)}")
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
