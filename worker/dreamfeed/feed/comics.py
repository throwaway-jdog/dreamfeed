"""Comics, live from the sites (the Comics tab: a feed like the rest): e621's pools (its comics)
and multporn's comics, with their pages, covers and tags, read when you look. Nothing is
downloaded: pages show straight from the sites (e621's own file server; multporn's, which only
sends its pictures to pages that don't name themselves, as dreamfeed's don't).

These are drawn: a comic is left out when its tags, categories or title are about minors
(safety.drawn_words: e621's tags for them, young, cub ..., and minors-only words), or your e621
blacklist hides its cover. No picture is looked at.

A comic: {"id" ("e621:POOL", "mp:SLUG", or "mpg:SLUG" for one of multporn's gay comics, which it
keeps apart), "source", "title", "pages", "cover", "tags", "artists", "updated" (when it last
changed, as the site says), "link"}. Read, a multporn comic also has its details as links to their
lists ("about": author, section, characters, tags, user tags), its rating, views, description,
translations, and its first page of comments.
"""
import datetime as dt
import html
import re
import urllib.parse
import urllib.request

from ..core import safety
from . import e621
from .common import _cached

MULTPORN = "https://multporn.net"
MP_AGENT = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"}   # (it turns away scripts' own)
MP_SLUG = re.compile(r"^[a-z0-9_-]{1,120}$")
POOL_ID = re.compile(r"^\d{1,9}$")
MAX_PAGES = 400
PAGE = 24


def blocked(*texts) -> bool:
    """Drawn work about minors (in a title, a tag or a category)."""
    return bool(safety.drawn_words(*texts))


def _iso(t: str) -> str:
    try:
        return dt.datetime.fromisoformat(str(t)).astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ""


# ---- e621's pools ----
def _covers(pools: list[dict]) -> dict:
    """Each pool's first post (its cover, and the tags it's judged by)."""
    firsts = [p["post_ids"][0] for p in pools if p.get("post_ids")]
    out = {}
    for i in range(0, len(firsts), 100):
        got = e621.get("/posts.json", {"tags": "id:" + ",".join(str(x) for x in firsts[i:i + 100]), "limit": 100}).get("posts") or []
        out.update({p["id"]: p for p in got})
    return out


def _pool(p: dict, cover: dict | None) -> dict | None:
    if not cover or e621.blocked(cover) or e621.blacklisted(cover) or blocked(p.get("name"), p.get("description", "")[:500]):
        return None
    g = cover.get("tags") or {}
    return {"id": f"e621:{p['id']}", "source": "e621", "title": str(p.get("name") or "").replace("_", " "), "pages": p.get("post_count") or 0,
            "cover": ((cover.get("sample") or {}).get("url") or (cover.get("preview") or {}).get("url")), "updated": _iso(p.get("updated_at")),
            "tags": [t for t in (g.get("artist") or []) + (g.get("species") or []) + (g.get("general") or [])[:20] if t not in e621.NOT_ARTISTS],
            "artists": [a for a in g.get("artist") or [] if a not in e621.NOT_ARTISTS], "link": f"{e621.API}/pools/{p['id']}"}


def e621_pools(order: str = "updated_at", page: int = 1, name: str = "", ids: list[int] | None = None) -> list[dict]:
    """e621's comics (series pools): the latest updated, or those whose name matches, or these."""
    if order not in ("updated_at", "created_at", "post_count") or not 1 <= page <= 50:
        raise ValueError("bad pools")
    params = {"search[category]": "series", "search[order]": order, "limit": PAGE, "page": page}
    if name:
        params["search[name_matches]"] = "*" + "*".join(name.split()) + "*"
    if ids:
        params = {"search[id]": ",".join(str(i) for i in ids[:100]), "limit": 100}
    def fetch():
        pools = [p for p in e621.get("/pools.json", params) if p.get("post_ids")]
        covers = _covers(pools)
        return [c for c in (_pool(p, covers.get(p["post_ids"][0])) for p in pools) if c]
    return _cached(f"comics:e621:{sorted(params.items())}", fetch, 900)


def e621_pools_like(tags: list[str]) -> list[dict]:
    """Comics with posts that have any of these tags (your taste: artists, species), best first."""
    q = " ".join("~" + t for t in tags[:12] if re.fullmatch(r"[a-z0-9_()\-.'!]{1,60}", t)) + " inpool:true order:score"
    def fetch():
        posts = e621.get("/posts.json", {"tags": e621.query(q), "limit": 100}).get("posts") or []
        ids = list(dict.fromkeys(i for p in posts for i in p.get("pools") or []))[:40]
        return e621_pools(ids=ids) if ids else []
    return _cached(f"comics:e621like:{q}", fetch, 3600)


def e621_comic(pool_id: str) -> dict:
    """One e621 comic to read: its details and its pages ({"url" (e621's 850px copy), "full"}), in order."""
    if not POOL_ID.match(pool_id or ""):
        raise ValueError("bad comic")
    def fetch():
        p = e621.get(f"/pools/{pool_id}.json", {})
        ids = (p.get("post_ids") or [])[:MAX_PAGES]
        posts = {}
        for i in range(0, len(ids), 100):
            got = e621.get("/posts.json", {"tags": "id:" + ",".join(str(x) for x in ids[i:i + 100]), "limit": 100}).get("posts") or []
            posts.update({x["id"]: x for x in got})
        if any(e621.blocked(x) for x in posts.values()):
            raise LookupError("dreamfeed leaves that comic out")
        c = _pool(p, posts.get(ids[0]) if ids else None)
        if not c:
            raise LookupError("dreamfeed leaves that comic out")
        pages = []
        for i in ids:
            x = posts.get(i)
            if not x or e621.blacklisted(x):
                continue                           # (e621 hides some from visitors; your blacklist hides some)
            full = (x.get("file") or {}).get("url")
            sample = (x.get("sample") or {}).get("url") if (x.get("sample") or {}).get("has") else None
            if full or sample:
                pages.append({"url": sample or full, "full": full or sample})
        return {**c, "pages": len(ids), "images": pages, "description": str(p.get("description") or "")[:2000]}
    return _cached(f"comics:e621:pool:{pool_id}", fetch, 600)


# ---- multporn ----
def _mp_get(url: str) -> str:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=MP_AGENT), timeout=30) as r:
            return r.read(4 << 20).decode("utf-8", "replace")
    except OSError as e:
        raise LookupError(f"multporn didn't answer ({e})") from e


MP_TAG = re.compile(r"^[a-z0-9_]{1,60}$")
E6_TAG = re.compile(r"^[a-z0-9_()\-.'!]{1,60}$")
# how a tag's comics are ordered: multporn's own sorts, and e621's nearest
SORTS = {"new": (("created", "DESC"), "order:id"), "popular": (("totalcount", "DESC"), "order:score"),
         "top": (("value", "DESC"), "order:favcount")}


# multporn's two kinds of comic (its gay comics are kept apart, with their own sections and tags)
MP_KINDS = {"mp": "comics", "mpg": "gay_porn_comics"}
MP_PREFIX = {v: k for k, v in MP_KINDS.items()}
# multporn's lists, beyond New and Updated: what a comic's details link to (its own address there)
MP_LISTS = {"tag": "category", "gtag": "category_gay", "author": "authors_comics", "section": "comics",
            "gsection": "gay_porn_comics", "character": "characters", "usertag": "user_tags"}
MP_LINK = {v: k for k, v in MP_LISTS.items() if k not in ("section", "gsection")}


def _mp_cards(s: str) -> list[dict]:
    """The comics on one of multporn's lists (New, Updated comics, a tag's page), in order."""
    out = []
    s = s.split("More comics:", 1)[0]          # (not the random ones a page ends with)
    parts = re.split(r'views-field-title"> <strong class="field-content"><a href="/(comics|gay_porn_comics)/', s)
    for kind, row in zip(parts[1::2], parts[2::2]):
        t = re.match(r'([a-z0-9_-]+)(?:\?[^"]*)?">([^<]+)</a>', row)   # (some links carry a query: ?rule44=4)
        if not t:
            continue
        img = re.search(r'<img[^>]+src="(https://multporn\.net/sites/default/files/[^"]+)"[^>]*alt="([^"]*)"', row)
        about = html.unescape(img.group(2)) if img else ""
        title = html.unescape(t.group(2)).strip()
        if blocked(title, about):
            continue
        day = re.search(r"Date: </span> <span>(\d\d)/(\d\d)/(\d{4}) - (\d\d:\d\d)", row)
        by = re.search(r'views-field-field-author"> <h5 class="field-content">([^<]+)</h5>', row)
        out.append({"id": f"{MP_PREFIX[kind]}:{t.group(1)}", "source": "multporn", "title": title, "pages": None, "cover": img.group(1) if img else None,
                    "artists": [html.unescape(by.group(1)).strip()] if by else [],
                    "tags": [w.strip().lower() for w in re.split(r",| on ", about.split("comics", 1)[-1]) if w.strip()][:8],
                    "updated": None, "posted": f"{day[3]}-{day[2]}-{day[1]} {day[4]}:00" if day else None, "link": f"{MULTPORN}/{kind}/{t.group(1)}"})
    seen = set()
    return [c for c in out if not (c["id"] in seen or seen.add(c["id"]))]


def multporn_list(which: str, page: int = 0, tag: str = "", sort: str = "new") -> dict:
    """{"comics", "more", "name"?}: multporn's New comics, its Updated comics, or one of its lists
    (MP_LISTS: a tag's comics, an author's, a section's, a character's, a user tag's; with its name)."""
    if not 0 <= page < 500 or sort not in SORTS:
        raise ValueError("bad page")
    if which == "new":
        url, nxt = f"{MULTPORN}/new?type=1&page={page}", f"page={page + 1}&"
    elif which == "updated":
        url, nxt = f"{MULTPORN}/updated_comics?page={page}", f"page={page + 1}\""
    elif which in MP_LISTS and (MP_TAG if which == "tag" else MP_SLUG).match(tag or ""):
        if blocked(tag.replace("_", " ").replace("-", " ")):
            raise ValueError("not something to look for")
        by, order = SORTS[sort][0]
        url, nxt = f"{MULTPORN}/{MP_LISTS[which]}/{tag}?sort_by={by}&sort_order={order}&page=0%2C{page}", f"page=0%2C{page + 1}\""
    else:
        raise ValueError("bad list")
    what = {"tag": "tag", "gtag": "tag", "author": "author", "character": "character", "usertag": "user tag"}.get(which, "section")
    def fetch():
        try:
            s = re.sub(r"\s+", " ", _mp_get(url))
        except LookupError as e:
            if "404" in str(e):
                raise ValueError(f"multporn has no {what} “{tag.replace('_', ' ')}”") from e
            raise
        out = {"comics": _mp_cards(s), "more": nxt in s.replace("&amp;", "&")}
        if which in MP_LISTS:
            h1 = re.search(r"<h1[^>]*>([^<]+)</h1>", s)
            name = html.unescape(h1.group(1)).strip() if h1 else ""
            if which in ("section", "gsection") and 'field-name-field-com-pages' in s:
                raise ValueError(f"multporn has no section “{tag.replace('_', ' ')}”")   # (a comic's address, not a section's)
            if blocked(name):
                raise ValueError("not something to look for")
            out["name"] = name
        return out
    return _cached(f"comics:mp:list:{which}:{tag}:{sort}:{page}", fetch, 900)


def multporn_new(page: int = 0) -> list[dict]:
    """multporn's newest comics, with their covers (For you starts from these)."""
    return multporn_list("new", page)["comics"]


def multporn_tags() -> list[dict]:
    """multporn's tags (its categories for comics): [{"tag": slug, "name"}], A to Z."""
    def fetch():
        found = {}
        for n in range(12):
            s = re.sub(r"\s+", " ", _mp_get(f"{MULTPORN}/category_comic?page={n}"))
            got = re.findall(r'href="/category/([a-z0-9_]+)"[^>]*>([^<]+)<', s)
            for slug, name in got:
                name = html.unescape(name).strip()
                if name and not blocked(name, slug.replace("_", " ")):
                    found.setdefault(slug, name)
            if f"page={n + 1}&" not in s.replace("&amp;", "&") and f"page={n + 1}\"" not in s:
                break
        return [{"tag": k, "name": v} for k, v in sorted(found.items(), key=lambda kv: kv[1].lower())]
    return _cached("comics:mp:tags", fetch, 86400)


def e621_pools_tagged(tag: str, page: int = 0, sort: str = "new") -> dict:
    """{"comics", "more"}: e621's comics with posts that have this tag (one page of its posts, their pools)."""
    tag = tag.strip().lower().replace(" ", "_")
    if not E6_TAG.match(tag) or sort not in SORTS or not 0 <= page < 50:
        raise ValueError("bad tag")
    if blocked(tag.replace("_", " ")):
        raise ValueError("not something to look for")
    q = f"{tag} inpool:true {SORTS[sort][1]}"
    def fetch():
        posts = e621.get("/posts.json", {"tags": e621.query(q), "limit": 150, "page": page + 1}).get("posts") or []
        ids = list(dict.fromkeys(i for p in posts for i in p.get("pools") or []))[:60]
        found = e621_pools(ids=ids) if ids else []
        at = {i: n for n, i in enumerate(ids)}
        return {"comics": sorted(found, key=lambda c: at.get(int(c["id"].split(":")[1]), 99)), "more": len(posts) >= 150}
    return _cached(f"comics:e621tag:{q}:{page}", fetch, 1800)


def _mp_html(kind: str, slug: str, query: str = "") -> str:
    """A multporn comic's own page (one of its comment pages, with a query), its spaces made single."""
    if kind not in MP_PREFIX or not MP_SLUG.match(slug or ""):
        raise ValueError("bad comic")
    return _cached(f"comics:mp:html:{kind}:{slug}:{query}", lambda: re.sub(r"\s+", " ", _mp_get(f"{MULTPORN}/{kind}/{slug}{query}")), 600)


def _text(h: str) -> str:
    """Some of multporn's HTML as plain text (its lines kept)."""
    h = re.sub(r"(?i)<br\s*/?>|</p>\s*<p[^>]*>", "\n", h)
    return "\n".join(" ".join(x.split()) for x in html.unescape(re.sub(r"<[^>]+>", " ", h)).split("\n")).strip()


def _mp_about(s: str) -> dict:
    """A comic's details, each a link to its list here: {"author", "section", "characters", "tags", "usertags": [{"list", "slug", "name"}]}."""
    out = {"author": [], "section": [], "characters": [], "tags": [], "usertags": []}
    field = {"author": "author", "com-group": "section", "gay-com-group": "section", "characters": "characters",
             "category": "tags", "gay-tags": "tags", "user-tags": "usertags"}
    for m in re.finditer(r'<div class="field field-name-field-([a-z-]+) [^"]*field-type-taxonomy-term-reference[^"]*">(.*?)</ul>', s):
        key = field.get(m.group(1))
        if not key:
            continue
        for path, slug, name in re.findall(r'<a href="/([a-z_]+)/([a-z0-9_-]+)"[^>]*>([^<]+)</a>', m.group(2)):
            lst = {"comics": "section", "gay_porn_comics": "gsection"}.get(path) or MP_LINK.get(path)
            if lst and MP_SLUG.match(slug):
                out[key].append({"list": lst, "slug": slug, "name": html.unescape(name).strip()})
    return out


def _mp_comments(s: str) -> dict:
    """{"comments": [{"id", "user", "at", "text", "score", "depth"}], "more"}: one page of a comic's
    comments, in multporn's order (a reply under the one it answers, a step in); one about minors left out."""
    out = []
    start = s.find('<a id="comment-')
    if start >= 0:
        end = s.find('id="comment-form"', start)
        body = s[start:end if end > 0 else len(s)]
        stack, depth_at = [], {}
        for m in re.finditer(r'<div( class="indented")?[^>]*>|</div>|<a id="comment-(\d+)"></a>', body):
            if m.group(2):
                depth_at[m.group(2)] = sum(stack)
            elif m.group(0) == "</div>":
                if stack:
                    stack.pop()
            else:
                stack.append(1 if m.group(1) else 0)
        for m in re.finditer(r'<a id="comment-(\d+)"></a>(.*?)(?=<a id="comment-\d+"></a>|$)', body):
            row = m.group(2)
            text = re.search(r'field-name-comment-body.*?<div class="field-item even">(.*?)</div></div></div>', row)
            text = _text(text.group(1)) if text else ""
            if not text or blocked(text):
                continue
            who = re.search(r'class="username">([^<]+)<', row)
            at = re.search(r'forum-posted-on[^>]*> (?:\w+, )?(\d\d)/(\d\d)/(\d{4}) - (\d\d:\d\d)', row)
            score = re.search(r'rate-number-up-down-rating[^>]*>\s*(-?[\d.]+)', row)
            out.append({"id": m.group(1), "user": html.unescape(who.group(1)).strip() if who else "Anonymous",
                        "at": f"{at[3]}-{at[2]}-{at[1]} {at[4]}:00" if at else None, "text": text[:4000],
                        "score": float(score.group(1)) if score else None, "depth": min(depth_at.get(m.group(1), 0), 6)})
    return {"comments": out, "more": 'class="pager-next' in s}


def multporn_comic(slug: str, kind: str = "comics") -> dict:
    """One multporn comic to read: its details (its categories as tags) and pages, in order."""
    if not MP_SLUG.match(slug or "") or kind not in MP_PREFIX:
        raise ValueError("bad comic")
    def fetch():
        url = f"{MULTPORN}/{kind}/{slug}"
        s = _mp_html(kind, slug)
        title = html.unescape((re.search(r"<h1[^>]*>([^<]+)</h1>", s) or [0, slug])[1]).strip()
        about = _mp_about(s)
        if 'field-name-field-com-pages' not in s:
            raise LookupError("multporn has no such comic")
        tags = [x["name"].lower() for x in about["tags"] + about["characters"]]
        if blocked(title, *tags, *(x["name"] for k in ("section", "usertags", "author") for x in about[k])):
            raise LookupError("dreamfeed leaves that comic out")
        cover = re.search(r'<meta property="og:image" content="([^"]+)"', s)
        cfg = re.search(r'configUrl":"([^"]+)"', s)
        images = []
        if cfg:
            xml = _mp_get(urllib.parse.urljoin(url, cfg.group(1).replace("\\/", "/")))
            for prev in [html.unescape(u) for u in re.findall(r'imageURL="([^"]+)"', xml)][:MAX_PAGES]:
                full = re.sub(r"/styles/[^/]+/public/", "/", prev.split("?")[0])
                if full.startswith(MULTPORN + "/"):
                    images.append({"url": prev if prev.startswith(MULTPORN + "/") else full, "full": full})
        votes = re.search(r"Average:\s*([\d.]+)\s*\(\s*(\d+)\s*votes?", " ".join(re.sub(r"<[^>]+>", " ", s).split()))
        views = re.search(r'statistics_counter[^>]*><span>(\d+) views', s)
        said = [_text(d) for d in re.findall(r"<div class='usr-dis-text'> <h3>(.*?)</h3>", s)]
        trans = [{"id": f"{MP_PREFIX[k]}:{t}", "lang": html.unescape(n).strip()}
                 for k, t, n in re.findall(r'href=" ?https://multporn\.net/(comics|gay_porn_comics)/([a-z0-9_-]+)" ?>([^<]+)</a>',
                                           (re.search(r'field-translate.*?</div>', s) or [""])[0])]
        return {"id": f"{MP_PREFIX[kind]}:{slug}", "source": "multporn", "title": title, "pages": len(images), "images": images,
                "cover": cover.group(1) if cover and cover.group(1).startswith(MULTPORN + "/") else (images[0]["url"] if images else None),
                "tags": tags[:40], "artists": [x["name"] for x in about["author"]], "updated": None, "link": url,
                "about": about, "rating": {"average": float(votes.group(1)), "votes": int(votes.group(2))} if votes else None,
                "views": int(views.group(1)) if views else None,
                "description": next((d for d in said if d and not blocked(d)), "")[:2000],
                "translations": trans, "comments": _mp_comments(s)}
    return _cached(f"comics:mp:{kind}:{slug}", fetch, 600)


def multporn_comments(cid: str, page: int) -> dict:
    """{"comments", "more"}: a page of a multporn comic's comments (multporn's pager: page=0,0,0,N)."""
    src, _, slug = str(cid or "").partition(":")
    if src not in MP_KINDS or not MP_SLUG.match(slug) or not 0 <= int(page) < 500:
        raise ValueError("bad comic")
    multporn_comic(slug, MP_KINDS[src])          # (one dreamfeed leaves out has no comments here either)
    first = _mp_html(MP_KINDS[src], slug)
    if page == 0:
        return _mp_comments(first)
    pager = re.search(rf'href="/{MP_KINDS[src]}/{slug}\?page=((?:\d+%2C)*)\d+"', first)
    if not pager:
        return {"comments": [], "more": False}
    return _mp_comments(_mp_html(MP_KINDS[src], slug, f"?page={pager.group(1)}{page}"))


def comic(cid: str) -> dict:
    """A comic to read, by its id."""
    src, _, key = str(cid or "").partition(":")
    if src == "e621":
        return e621_comic(key)
    if src in MP_KINDS:
        return multporn_comic(key, MP_KINDS[src])
    raise ValueError("bad comic")


def page_count(cid: str) -> int:
    """How many pages a comic has now (for following it: new pages)."""
    src, _, key = str(cid or "").partition(":")
    if src == "e621":
        if not POOL_ID.match(key):
            raise ValueError("bad comic")
        return int((e621.get(f"/pools/{key}.json", {}) or {}).get("post_count") or 0)
    if src not in MP_KINDS:
        raise ValueError("bad comic")
    return int(multporn_comic(key, MP_KINDS[src])["pages"] or 0)
