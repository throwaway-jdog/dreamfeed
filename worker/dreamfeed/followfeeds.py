"""Posts from who you follow on X and Reddit, checked before they show: `python -m dreamfeed
follow feeds` (the follow service runs it every FEEDS_EVERY seconds, as a child that exits
when done, so the checking models' memory is given back).

1. New posts are downloaded (e621: the Dashboard's tag searches, through e621.py, their
   top-scored posts of each day, those with tags dreamfeed never allows left out first): X with gallery-dl and your cookies (the Following timeline,
   x.com/home); Reddit for the subreddits and users on the Dashboard (data/following.json),
   once a day each, the top `top` posts of the last day: through Reddit's API with your own
   app (REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET; app-only, no account), pictures, galleries,
   Reddit's own videos and redgifs (gallery-dl); without the app, from their public RSS feeds,
   pictures and redgifs only. What's been read is remembered (gallery-dl's archive; reddit.seen).
2. Every file goes through the adults-only checks (checks.problem, strict), a video's
   VIDEO_FRAMES frames spread over it, and a face in a drawing gets the age estimate too. A
   post with any file that fails is deleted, all of it.
3. Posts that pass are kept KEEP_DAYS days in data/generated/follow/media (left out of the
   backup) and listed in follow_posts for the Following page.

These are real people: nothing here goes to training, styles, comics or generation.
"""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

KEEP_DAYS = 14
MAX_FILES = 150            # files read from a feed at a time
STOP_AFTER_SEEN = 10       # a feed is read up to this many files in a row it already has
VIDEO_FRAMES = 4
CHECK_SIDE = 1536          # pictures are checked at most this big
MAX_SIZE = "200M"
IMAGES = {".jpg", ".jpeg", ".png", ".webp"}
VIDEOS = {".mp4", ".webm", ".mov", ".m4v", ".gif"}
X_HOME = "https://x.com/home"     # your Following timeline; + "/for-you": X's For you
FEEDS = {
    "x": {"url": X_HOME, "cookies": Path("/config/x-cookies.txt"), "name": "X"},
    # X's own For you timeline: mostly people you don't follow, kept apart from your Following
    # posts (the Feed's For you), and fewer at a time (they all go through the checks).
    "foryou": {"url": X_HOME + "/for-you", "cookies": Path("/config/x-cookies.txt"), "name": "X For you",
               "as": "x", "via": "foryou", "max": 60},
    "reddit": {"name": "Reddit"},
    "e621": {"name": "e621"},
}
E621_EVERY = 24 * 3600     # each search is read once a day: its top-scored posts of that day
# Reddit's rules for scripts: a user agent that says what it is.
REDDIT_AGENT = "linux:dreamfeed:1.0 (personal feed reader)"
REDDIT_RSS = {"r": "https://www.reddit.com/r/{}/top/.rss?t=day&limit={}",
              "u": "https://www.reddit.com/user/{}/submitted/.rss?sort=top&t=day&limit={}"}
REDDIT_EVERY = 24 * 3600   # each one is read once a day: its top posts of that day
REDDIT_GAP = 11            # seconds between Reddit requests (unsigned readers get about one per 10 s)
REDDIT_IMAGES = ("i.redd.it", "preview.redd.it")
REDDIT_API = "https://oauth.reddit.com"
FRONT_PAGE = 50           # posts of your front page looked at each round (only new ones are fetched)
API_GAP = 1                # seconds between API requests (it allows about 100 a minute)
MAX_GALLERY = 20           # pictures kept from one gallery
VIDEO_MAX_BYTES = 200 << 20
REDDIT_LINKED = ("redgifs.com", "www.redgifs.com", "v3.redgifs.com")
SEEN_KEEP = 5000
ATOM = {"a": "http://www.w3.org/2005/Atom"}


def settings() -> dict:
    """What the Dashboard set (data/following.json, written by the web app):
    {"reddit": {"follow": ["r/name", "u/name"], "top": N}}."""
    try:
        d = json.loads((Path(os.environ["DATA_DIR"]) / "following.json").read_text())
    except (OSError, ValueError, KeyError):
        d = {}
    r, e = d.get("reddit") or {}, d.get("e621") or {}
    return {"follow": [w for w in r.get("follow") or [] if isinstance(w, str) and w[:2] in ("r/", "u/")],
            "top": max(1, min(100, int(r.get("top") or 10))),
            "e621": {"searches": [q for q in e.get("searches") or [] if isinstance(q, str) and q.strip()],
                     "top": max(1, min(100, int(e.get("top") or 10)))}}


def reddit_follow() -> list[str]:
    return settings()["follow"]


def _signed_in(source: str) -> str | None:
    """Why this feed can't be read, or None."""
    if source == "e621":
        return None if settings()["e621"]["searches"] else "no e621 searches yet (add them on the Dashboard)"
    if source == "reddit":
        return None if reddit_follow() or (_api_creds() and _signed_in_as_you()) else \
            "no subreddits or users yet (sign in to Reddit, or add them on the Dashboard)"
    cookies = FEEDS[source]["cookies"]
    if not cookies.is_file() or not any(line.strip() and not line.startswith("# ") for line in cookies.open()):
        return f"no {FEEDS[source]['name']} cookies yet"
    return None


def download(source: str, incoming: Path, archive: Path) -> str | None:
    """The feed's new files into incoming, each with its post's details (FILE.json); an error, or None."""
    incoming.mkdir(parents=True, exist_ok=True)
    if source == "reddit":
        return _reddit(incoming, archive.with_suffix(".seen"))
    if source == "e621":
        return _e621(incoming, archive.with_suffix(".seen"))
    conf = {"extractor": {
        "base-directory": str(incoming), "directory": [], "archive": str(archive), "cookies-update": False,
        "filename": "{category}_{filename}.{extension}",
        "twitter": {"text-tweets": False, "retweets": False, "quoted": False, "filename": "{tweet_id}_{num}.{extension}"},
    }, "downloader": {"part-directory": str(incoming / ".part"), "filesize-max": MAX_SIZE}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(conf, f)
    try:
        r = subprocess.run(["gallery-dl", "--config-ignore", "--config", f.name, "--cookies", str(FEEDS[source]["cookies"]),
                            "--range", f"1-{FEEDS[source].get('max', MAX_FILES)}", "--abort", str(STOP_AFTER_SEEN), "--write-metadata",
                            FEEDS[source]["url"]], capture_output=True, text=True, timeout=1800)
    finally:
        Path(f.name).unlink(missing_ok=True)
        shutil.rmtree(incoming / ".part", ignore_errors=True)
    errors = [line for line in r.stderr.splitlines() if "][error]" in line]
    if r.returncode and errors and not any(incoming.iterdir()):
        return errors[-1].split("][error]", 1)[1].strip()[:200]
    return None


def _fetch(url: str, headers: dict | None = None, gap: float | None = None) -> bytes:
    """Reddit, politely: one request at a time, gap apart (REDDIT_GAP without the API), once
    more after a 429."""
    import time
    import urllib.error
    import urllib.request
    for attempt in range(2):
        time.sleep(REDDIT_GAP if gap is None else gap)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _agent(), **(headers or {})})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read(200 << 20)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt:
                raise
            time.sleep(min(60, float(e.headers.get("x-ratelimit-reset") or 30)))
    raise OSError("rate limited")


def _agent() -> str:
    user = os.environ.get("REDDIT_USERNAME", "").strip()
    return f"linux:dreamfeed:1.0 (by /u/{user})" if user else REDDIT_AGENT


def _api_creds() -> tuple[str, str] | None:
    """Your own Reddit app (a "personal use script"): REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET."""
    cid, secret = (os.environ.get(k, "").strip() for k in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"))
    return (cid, secret) if cid and secret else None


def _token_request(creds: tuple[str, str], form: dict) -> dict:
    import base64
    import urllib.parse
    import urllib.request
    req = urllib.request.Request("https://www.reddit.com/api/v1/access_token", data=urllib.parse.urlencode(form).encode(),
                                 headers={"User-Agent": _agent(),
                                          "Authorization": "Basic " + base64.b64encode(":".join(creds).encode()).decode()})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _signed_in_as_you() -> str:
    return os.environ.get("REDDIT_REFRESH_TOKEN", "").strip()


def _api_token(creds: tuple[str, str]) -> str:
    """A token good for an hour: as you, if you've signed in (REDDIT_REFRESH_TOKEN, from
    `follow reddit-login`), else the app reading public posts as itself."""
    refresh = _signed_in_as_you()
    d = _token_request(creds, {"grant_type": "refresh_token", "refresh_token": refresh} if refresh
                       else {"grant_type": "client_credentials"})
    if not d.get("access_token"):
        raise OSError(f"Reddit refused the app: {d.get('error') or d}")
    return d["access_token"]


def subscriptions(token: str) -> list[str]:
    """The subreddits (and people's profiles) you're subscribed to, as "r/name" and "u/name"."""
    out, after = [], ""
    for _ in range(20):                         # up to 2000
        d = json.loads(_fetch(f"{REDDIT_API}/subreddits/mine/subscriber?limit=100&raw_json=1&after={after}",
                              {"Authorization": f"bearer {token}"}, gap=API_GAP)).get("data") or {}
        for c in d.get("children") or []:
            name = str((c.get("data") or {}).get("display_name") or "")
            out.append(f"u/{name[2:]}" if name.startswith("u_") else f"r/{name}")
        after = d.get("after") or ""
        if not after:
            break
    return sorted(set(out), key=str.lower)


LOGIN_SCOPES = "identity read mysubreddits save"     # save: the Feed's Save button
LOGIN_REDIRECT = "http://localhost:6414/"


def login(argv: list[str]) -> None:
    """`follow reddit-login`: prints the address to approve dreamfeed on reddit.com.
    `follow reddit-login ADDRESS`: the address your browser was sent back to; prints the
    refresh token for REDDIT_REFRESH_TOKEN in .env."""
    import secrets
    import sys
    import urllib.parse
    creds = _api_creds()
    if not creds:
        sys.exit("set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET first")
    state_file = Path(os.environ["DATA_DIR"]) / "generated" / "follow" / ".reddit-login"
    if not argv:
        state = secrets.token_urlsafe(12)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(state)
        print("https://www.reddit.com/api/v1/authorize?" + urllib.parse.urlencode(
            {"client_id": creds[0], "response_type": "code", "state": state, "redirect_uri": LOGIN_REDIRECT,
             "duration": "permanent", "scope": LOGIN_SCOPES}))
        return
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(argv[0]).query))
    if q.get("error"):
        sys.exit(f"Reddit said: {q['error']}")
    if not state_file.is_file() or q.get("state") != state_file.read_text():
        sys.exit("that isn't the address from this sign-in: run `follow reddit-login` again")
    d = _token_request(creds, {"grant_type": "authorization_code", "code": q.get("code", ""), "redirect_uri": LOGIN_REDIRECT})
    state_file.unlink()
    if not d.get("refresh_token"):
        sys.exit(f"Reddit refused: {d.get('error') or d}")
    print(d["refresh_token"])


def _api_posts(listing: bytes) -> list[dict]:
    """An API listing's posts, like _entries' but "media" is every picture and video of the post:
    a gallery's pictures in order, Reddit's own video (its HLS stream, with sound), a redgifs
    link or the post's picture. A crosspost's media are the original's."""
    import datetime as dt
    out = []
    for child in json.loads(listing).get("data", {}).get("children", []):
        p = child.get("data") or {}
        src = (p.get("crosspost_parent_list") or [p])[0]
        media = []
        if src.get("is_gallery"):
            meta = src.get("media_metadata") or {}
            for item in (src.get("gallery_data") or {}).get("items", []):
                m = meta.get(item.get("media_id")) or {}
                big = m.get("s") or {}
                if m.get("status") == "valid":
                    media.append(big.get("mp4") or big.get("u") or big.get("gif") or "")
        elif (src.get("secure_media") or {}).get("reddit_video"):
            media.append(src["secure_media"]["reddit_video"].get("hls_url") or "")
        elif src.get("url"):
            media.append(src["url"])
        when = dt.datetime.fromtimestamp(p.get("created_utc") or 0, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        out.append({"id": str(p.get("id") or ""), "title": p.get("title") or "", "author": p.get("author") or "",
                    "subreddit": p.get("subreddit"), "date": when, "permalink": p.get("permalink") or "",
                    "media": [u for u in media if u]})
    return out


def _entries(feed: bytes) -> list[dict]:
    """An RSS (Atom) feed's posts: {"id", "author", "subreddit", "title", "date", "permalink", "media"}."""
    import html
    import re
    import xml.etree.ElementTree as ET
    out = []
    for e in ET.fromstring(feed).findall("a:entry", ATOM):
        content = html.unescape(e.findtext("a:content", "", ATOM))
        media = re.search(r'<a href="([^"]+)">\[link\]</a>', content)
        link = (e.find("a:link", ATOM).get("href") if e.find("a:link", ATOM) is not None else "") or ""
        sub = re.search(r"/r/([^/]+)/comments/", link)
        when = (e.findtext("a:published", "", ATOM) or "")[:19].replace("T", " ")
        out.append({"id": e.findtext("a:id", "", ATOM).removeprefix("t3_"), "title": e.findtext("a:title", "", ATOM),
                    "author": e.findtext("a:author/a:name", "", ATOM).removeprefix("/u/"),
                    "subreddit": sub.group(1) if sub else None, "date": when,
                    "permalink": link.removeprefix("https://www.reddit.com"), "media": [media.group(1)] if media else []})
    return out


def _reddit(incoming: Path, seen_file: Path) -> str | None:
    """Signed in: your front page (Best, as Reddit sorts it for you), its newest FRONT_PAGE each
    round. Then each subreddit and user due (not read in the last REDDIT_EVERY): its top posts
    of the day, through the API with your app if it's set (galleries and Reddit videos too),
    else RSS."""
    import re
    import time
    seen = seen_file.read_text().split() if seen_file.is_file() else []
    last_file = seen_file.with_suffix(".last")     # when each was last read
    try:
        last = json.loads(last_file.read_text())
    except (OSError, ValueError):
        last = {}
    known, errors, new = set(seen), [], []
    s = settings()
    creds, token = _api_creds(), None
    follow = list(s["follow"])
    if creds and _signed_in_as_you():             # signed in: your subscriptions, and the Dashboard's extras
        try:
            token = _api_token(creds)
            subs = subscriptions(token)
            (seen_file.parent / "reddit-subs.json").write_text(json.dumps(subs))
            follow += [w for w in subs if w.lower() not in {f.lower() for f in follow}]
        except (OSError, ValueError) as e:
            errors.append(f"your subscriptions: {e}")
    def take(posts: list[dict], limit: int, via: str | None = None) -> None:
        for p in posts[:limit]:
            if not re.fullmatch(r"[a-z0-9]{3,12}", p["id"]) or p["id"] in known:
                continue
            if _place_blocked(p.get("subreddit") or ""):      # left out before anything's downloaded
                continue
            if via:
                p["via"] = via
            known.add(p["id"]); new.append(p["id"])
            urls = p.pop("media")[:MAX_GALLERY]
            meta = json.dumps(p)
            for n, url in enumerate(urls, 1):
                try:
                    _reddit_file(url, f"{p['id']}_{n:02d}", incoming, meta, gap=API_GAP if creds else None)
                except (OSError, subprocess.SubprocessError) as e:
                    print(f"follow: reddit post {p['id']}: {e}", flush=True)

    if token:                                     # your front page, every round
        try:
            take(_api_posts(_fetch(f"{REDDIT_API}/best?limit={FRONT_PAGE}&raw_json=1",
                                   {"Authorization": f"bearer {token}"}, gap=API_GAP)), FRONT_PAGE, via="foryou")
        except (OSError, ValueError) as e:
            errors.append(f"your front page: {e}")
    for who in follow:
        if time.time() - last.get(who, 0) < REDDIT_EVERY:
            continue
        kind, _, name = who.partition("/")
        try:
            if creds:
                token = token or _api_token(creds)
                path = (f"/r/{name}/top?t=day" if kind == "r" else f"/user/{name}/submitted?sort=top&t=day")
                posts = _api_posts(_fetch(f"{REDDIT_API}{path}&limit={s['top']}&raw_json=1",
                                          {"Authorization": f"bearer {token}"}, gap=API_GAP))
            else:
                posts = _entries(_fetch(REDDIT_RSS[kind].format(name, s["top"])))
        except (OSError, ValueError) as e:
            errors.append(f"{who}: {e}")
            continue
        last[who] = time.time()
        take(posts, s["top"])
    seen_file.write_text("\n".join((seen + new)[-SEEN_KEEP:]))
    last_file.write_text(json.dumps({w: t for w, t in last.items() if w in follow}))
    return "; ".join(errors)[:200] if errors and not new else None


def _reddit_file(url: str, stem: str, incoming: Path, meta: str, gap: float | None) -> None:
    """One picture or video of a post into incoming as STEM.ext, with the post's details."""
    import urllib.parse
    u = urllib.parse.urlparse(url)
    host, ext = u.hostname or "", Path(u.path).suffix.lower()
    if "format=mp4" in u.query:                   # a gallery's animated item: a .gif address serving MP4
        ext = ".mp4"
    if host in REDDIT_IMAGES and ext in IMAGES | VIDEOS:
        dest = incoming / f"{stem}{ext}"
        dest.write_bytes(_fetch(url, gap=gap))
    elif host == "v.redd.it" and u.path.endswith(".m3u8"):
        dest = incoming / f"{stem}.mp4"           # Reddit's own video, picture and sound together
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-user_agent", _agent(), "-i", url, "-c", "copy",
                        "-fs", str(VIDEO_MAX_BYTES), "-movflags", "+faststart", str(dest)], check=True, timeout=600)
    elif host in REDDIT_LINKED:
        return _redgifs(url, stem, incoming, meta)
    else:
        return
    dest.with_name(dest.name + ".json").write_text(meta)


def _e621(incoming: Path, seen_file: Path) -> str | None:
    """Each search due (not read in the last E621_EVERY): its top-scored posts of the last day
    that have no tag dreamfeed never allows (e621.blocked), as many as the Dashboard says."""
    import time
    from . import e621
    seen = seen_file.read_text().split() if seen_file.is_file() else []
    last_file = seen_file.with_suffix(".last")
    try:
        last = json.loads(last_file.read_text())
    except (OSError, ValueError):
        last = {}
    s = settings()["e621"]
    known, errors, new = set(seen), [], []
    for search in s["searches"]:
        if time.time() - last.get(search, 0) < E621_EVERY:
            continue
        try:
            posts = e621.get("/posts.json", {"tags": f"{e621.query(search)} date:day order:score",
                                             "limit": min(320, s["top"] * 3)}).get("posts") or []
        except (OSError, ValueError) as e:
            errors.append(f"{search}: {e}")
            continue
        last[search] = time.time()
        for p in [p for p in posts if not e621.blocked(p)][:s["top"]]:
            pid = str(p.get("id") or "")
            if not pid.isdigit() or pid in known:
                continue
            known.add(pid); new.append(pid)
            got = e621.media(p)
            if not got:
                continue
            try:
                dest = incoming / f"{pid}_01.{got[1]}"
                dest.write_bytes(e621.fetch(got[0]))
                dest.with_name(dest.name + ".json").write_text(json.dumps({**e621.details(p), "place": search}))
            except (OSError, ValueError) as e:
                print(f"follow: e621 post {pid}: {e}", flush=True)
    seen_file.write_text("\n".join((seen + new)[-SEEN_KEEP:]))
    last_file.write_text(json.dumps({q: t for q, t in last.items() if q in s["searches"]}))
    return "; ".join(errors)[:200] if errors and not new else None


def _redgifs(url: str, post_id: str, incoming: Path, meta: str) -> None:
    """A redgifs clip a Reddit post links to, with the post's details (gallery-dl reads redgifs'
    own API)."""
    folder = incoming / f".redgifs-{post_id}"
    subprocess.run(["gallery-dl", "--config-ignore", "-D", str(folder), "-o", f"filesize-max={MAX_SIZE}",
                    "-o", "extractor.redgifs.format=[\"hd\",\"sd\"]", url], capture_output=True, timeout=600)
    clips = sorted(f for f in folder.iterdir() if f.suffix.lower() in VIDEOS) if folder.is_dir() else []
    for n, f in enumerate(clips, 1):              # (redgifs' are .m4v)
        dest = incoming / f"{post_id}_{n}{f.suffix.lower()}"
        shutil.move(f, dest)
        dest.with_name(dest.name + ".json").write_text(meta)
    shutil.rmtree(folder, ignore_errors=True)


def _post(source: str, md: dict) -> dict:
    """A downloaded file's post: its id, who posted it, where, what they wrote, the link and when."""
    if source == "x":
        author = md.get("author") or {}
        named = [m.get("name") for m in md.get("mentions") or []] + [md.get("reply_to")]
        user = {"handle": author.get("name"), "nick": author.get("nick"), "bio": author.get("description"),
                "location": author.get("location"), "followers": author.get("followers_count"),
                "following": author.get("friends_count"), "posts": author.get("statuses_count"),
                "image_url": author.get("profile_image")}
        return {"post_id": str(md["tweet_id"]), "author": author.get("name") or "", "place": None, "user": user,
                "mentions": sorted({n for n in named if n and n != author.get("name")}),
                "text": md.get("content") or "", "posted_at": str(md.get("date") or ""),
                "link": f"https://x.com/{author.get('name')}/status/{md['tweet_id']}"}
    p = md.get("_parent") or md        # Reddit and e621: details written by _reddit and _e621
    link = p.get("link") or ("https://www.reddit.com" + p["permalink"] if p.get("permalink") else None)
    return {"post_id": str(p["id"]), "author": p.get("author") or "", "place": p.get("subreddit") or p.get("place"),
            "text": p.get("title") or "", "posted_at": str(p.get("date") or ""), "link": link, "via": p.get("via")}


AVATAR_HOSTS = ("pbs.twimg.com",)
AVATAR_SIDE = 256


def _save_user(conn, user: dict, vision, cfg, folder: Path) -> None:
    """An X account's details, and its profile picture: fetched when new or changed and kept only
    if it passes the same checks as posts (else none is shown)."""
    import io
    import urllib.parse
    import urllib.request
    handle = str(user.get("handle") or "")
    if not X_HANDLE.match(handle):
        return
    old = conn.execute("SELECT image_url, avatar FROM x_users WHERE handle = ?", (handle,)).fetchone()
    url = str(user.get("image_url") or "")
    with conn:
        conn.execute("INSERT INTO x_users(handle, nick, bio, location, followers, following, posts, image_url)"
                     " VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(handle) DO UPDATE SET nick = excluded.nick,"
                     " bio = excluded.bio, location = excluded.location, followers = excluded.followers,"
                     " following = excluded.following, posts = excluded.posts, image_url = excluded.image_url,"
                     " updated_at = datetime('now')",
                     (handle, str(user.get("nick") or "")[:100], str(user.get("bio") or "")[:1000],
                      str(user.get("location") or "")[:100], user.get("followers"), user.get("following"),
                      user.get("posts"), url))
    if old and old[0] == url and old[1] != 0:       # the same picture as before, already looked at
        return
    if urllib.parse.urlparse(url).hostname not in AVATAR_HOSTS:
        return
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "dreamfeed"}), timeout=30) as r:
        data = r.read(5 << 20)
    img = Image.open(io.BytesIO(data)).convert("RGB")
    ok = _problem(vision, cfg, [img]) is None
    dest = folder / f"{handle.lower()}.jpg"
    if ok:
        folder.mkdir(parents=True, exist_ok=True)
        img.thumbnail((AVATAR_SIDE, AVATAR_SIDE))
        img.save(dest, quality=88)
    else:
        dest.unlink(missing_ok=True)
    with conn:
        conn.execute("UPDATE x_users SET avatar = ? WHERE handle = ?", (1 if ok else -1, handle))


def _place_blocked(subreddit: str) -> bool:
    """A subreddit whose name has words dreamfeed never takes (young, feral and the like): its
    posts aren't fetched at all (the checks would drop them anyway)."""
    from . import safety
    from .e621 import NEVER
    words = subreddit.replace("_", " ").lower()
    return bool(safety.request_blocked(words) or safety.story_blocked(words)
                or any(w in words for w in NEVER if len(w) > 3))


def _frames(path: Path) -> list[Image.Image]:
    """A picture, or VIDEO_FRAMES frames spread over a video; at most CHECK_SIDE."""
    if path.suffix.lower() in IMAGES:
        with Image.open(path) as im:
            frames = [im.convert("RGB")]
    else:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        length = float(out) if out and out != "N/A" else 0.0
        frames = []
        for i in range(VIDEO_FRAMES):
            at = length * (i + 0.5) / VIDEO_FRAMES
            png = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{at:.2f}", "-i", str(path), "-frames:v", "1",
                                  "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, timeout=120).stdout
            if png:
                import io
                frames.append(Image.open(io.BytesIO(png)).convert("RGB"))
        if not frames:
            raise ValueError("no frames could be read")
    for f in frames:
        f.thumbnail((CHECK_SIDE, CHECK_SIDE))
    return frames


def _problem(vision, cfg, frames) -> tuple[str, str] | None:
    from . import safety
    from .checks import face_ages, problem
    a = vision.analyze(frames)
    photo = safety.photo_signs(a.general, a.medium_probs) is not None
    reason = problem(a, "photo" if photo else "drawing", frames, cfg, strict=True)
    if reason or photo:
        return reason
    ages = face_ages(frames, cfg)      # a drawing that's close to a photo gets the estimate too
    if ages and min(ages) < cfg.photo_min_age:
        return "age-estimate", f"{min(ages):.0f}"
    return None


def check_new(conn, source: str, incoming: Path, media: Path, vision, cfg, discovered: bool = False,
              via: str | None = None, yields: bool = False) -> tuple[int, int]:
    """The downloaded files, checked and kept or deleted, post by post: (kept, dropped). If a
    job or training starts meanwhile it stops, and the rest wait in incoming for next time.
    discovered: not from your own feeds (via: foryou, X's For you; preview, a profile's preview),
    shown in the Feed's For you and on profiles, never with your Following posts.
    yields: stop between posts while a Browse now waits (the feeds' rounds; the rest next time)."""
    from .follow import busy
    for meta in incoming.glob("*.json"):       # details whose file is gone
        if not meta.with_suffix("").exists():
            meta.unlink()
    posts: dict[str, dict] = {}
    for f in sorted(incoming.iterdir()):
        if not f.is_file() or f.suffix == ".json":
            continue
        if f.suffix.lower() not in IMAGES | VIDEOS:     # nothing the page can show
            f.unlink()
            continue
        meta = f.with_name(f.name + ".json")
        try:
            post = _post(source, json.loads(meta.read_text()))
        except (OSError, ValueError, KeyError) as e:
            print(f"follow: {source}: {f.name} has no details ({e}); left out", flush=True)
            f.unlink(missing_ok=True)
            continue
        posts.setdefault(post["post_id"], {**post, "files": []})["files"].append(f)
    kept = dropped = 0
    for pid, post in posts.items():
        if busy(conn, cfg.data_dir):
            print(f"follow: {source}: stopped for a job or training; the rest next time", flush=True)
            break
        if yields and browsing(conn):
            print(f"follow: {source}: stopped for Browse now; the rest next time", flush=True)
            break
        reason, frames_of = None, {}
        for f in post["files"]:
            try:
                frames_of[f] = _frames(f)
                reason = _problem(vision, cfg, frames_of[f])
            except (OSError, ValueError, subprocess.SubprocessError) as e:
                reason = ("unreadable", str(e)[:100])
            if reason:
                break
        for f in post["files"]:
            f.with_name(f.name + ".json").unlink(missing_ok=True)
        if reason:
            dropped += 1
            for f in post["files"]:
                f.unlink(missing_ok=True)
            print(f"follow: {source} post {pid} dropped: {reason[0]} ({reason[1]})", flush=True)
            continue
        folder = media / source / pid
        folder.mkdir(parents=True, exist_ok=True)
        items = []
        for f in post["files"]:
            dest = folder / f.name
            shutil.move(f, dest)
            # A GIF shows as a picture (it plays itself) but is checked frame by frame like a video.
            item = {"file": str(dest.relative_to(media)), "kind": "video" if f.suffix.lower() in VIDEOS - {".gif"} else "image"}
            if item["kind"] == "video":
                poster = dest.with_suffix(".poster.jpg")
                frames_of[f][0].save(poster, quality=85)
                item["poster"] = str(poster.relative_to(media))
            items.append(item)
        with conn:
            v = post.get("via") or via            # Reddit's front page is marked post by post
            conn.execute("INSERT OR IGNORE INTO follow_posts(source, post_id, author, place, text, link, posted_at, media,"
                         " mentions, discovered, via) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (source, pid, post["author"], post["place"], post["text"][:2000], post["link"], post["posted_at"],
                          json.dumps(items), json.dumps(post.get("mentions") or []), int(discovered or bool(v)), v))
        if post.get("user"):
            try:
                _save_user(conn, post["user"], vision, cfg, media.parent / "avatars" / "x")
            except (OSError, ValueError) as e:
                print(f"follow: x/{post['user'].get('handle')}: profile picture: {e}", flush=True)
        kept += 1
    return kept, dropped


def expire(conn, media: Path) -> None:
    with conn:
        old = conn.execute("SELECT id, source, post_id FROM follow_posts WHERE saved = 0 AND added_at < datetime('now', ?)",
                           (f"-{KEEP_DAYS} days",)).fetchall()
        for pid, source, post_id in old:
            shutil.rmtree(media / source / post_id, ignore_errors=True)
            conn.execute("DELETE FROM follow_posts WHERE id = ?", (pid,))


def main() -> None:
    import torch
    from .config import Config, need
    from .db import connect
    from .vision import Vision
    torch.set_num_threads(int(need("FOLLOW_THREADS")))
    cfg = Config()
    conn = connect(cfg.db_path)
    root = cfg.data_dir / "generated" / "follow"
    media = root / "media"
    status = {"at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")}
    vision = lock = None
    try:
        for source in FEEDS:
            why = _signed_in(source)
            if why:
                status[source] = {"error": why}
                continue
            incoming = root / "incoming" / source
            error = download(source, incoming, root / f"{source}.archive")
            if error:
                status[source] = {"error": f"{FEEDS[source]['name']}: {error}"}
                continue
            if browsing(conn):          # Browse now first: these wait in incoming for next time
                status[source] = {"kept": 0, "dropped": 0}
                continue
            if vision is None and any(incoming.iterdir()):
                lock = vision_lock()
                vision = Vision(cfg.models_dir)
            feed = FEEDS[source]
            kept, dropped = check_new(conn, feed.get("as", source), incoming, media, vision, cfg,
                                      discovered=bool(feed.get("via")), via=feed.get("via"), yields=True) if vision else (0, 0)
            if vision is not None and browsing(conn):     # its models' memory, for the browse
                vision.close(); vision = None
                lock.close(); lock = None
            status[source] = {"kept": kept, "dropped": dropped}
            print(f"follow: {source}: {kept} new posts, {dropped} dropped by the checks", flush=True)
        expire(conn, media)
    finally:
        if vision is not None:
            vision.close()
        if lock is not None:
            lock.close()
        tmp = root / "feeds.tmp"
        tmp.write_text(json.dumps(status))
        tmp.replace(root / "feeds.json")


PREVIEW_POSTS = 30        # media files read for a profile's latest posts
PREVIEW_FIRST = 6         # the first batch of them (shown while the rest download)
X_HANDLE = re.compile(r"^[A-Za-z0-9_]{1,15}$")


def preview(job_id: int) -> None:
    """`follow preview <job>`: an X account's latest media posts (gallery-dl, your cookies),
    through the same checks as the Feed, kept as discovered posts for its profile."""
    import torch
    from .config import Config, need
    from .db import connect
    from .vision import Vision
    torch.set_num_threads(int(need("FOLLOW_THREADS")))
    cfg = Config()
    conn = connect(cfg.db_path)
    row = conn.execute("SELECT handle FROM previews WHERE id = ?", (job_id,)).fetchone()
    if not row:
        return
    handle = row[0]
    root = cfg.data_dir / "generated" / "follow"
    incoming = root / "incoming" / f"preview-{job_id}"
    vision = lock = None
    try:
        if not X_HANDLE.match(handle):
            raise RuntimeError("not an X handle")
        why = _signed_in("x")
        if why:
            raise RuntimeError(why)
        incoming.mkdir(parents=True, exist_ok=True)
        conf = {"extractor": {
            "base-directory": str(incoming), "directory": [], "cookies-update": False,
            "twitter": {"text-tweets": False, "retweets": False, "quoted": False, "filename": "{tweet_id}_{num}.{extension}"},
        }, "downloader": {"part-directory": str(incoming / ".part"), "filesize-max": MAX_SIZE}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(conf, f)
        kept = dropped = 0
        error = None
        try:
            # A few first, checked and shown, then the rest: the profile fills in as it goes.
            for first, last in ((1, PREVIEW_FIRST), (PREVIEW_FIRST + 1, PREVIEW_POSTS)):
                r = subprocess.run(["gallery-dl", "--config-ignore", "--config", f.name, "--cookies", str(FEEDS["x"]["cookies"]),
                                    "--range", f"{first}-{last}", "--write-metadata", f"https://x.com/{handle}/media"],
                                   capture_output=True, text=True, timeout=900)
                shutil.rmtree(incoming / ".part", ignore_errors=True)
                if not any(incoming.iterdir()):
                    errors = [line for line in r.stderr.splitlines() if "][error]" in line]
                    error = errors[-1].split("][error]", 1)[1].strip()[:200] if errors else None
                    break
                if vision is None:
                    lock = vision_lock()
                    vision = Vision(cfg.models_dir)
                k, d = check_new(conn, "x", incoming, root / "media", vision, cfg, discovered=True, via="preview")
                kept, dropped = kept + k, dropped + d
        finally:
            Path(f.name).unlink(missing_ok=True)
        if not kept and not dropped:
            raise RuntimeError(error or "no pictures or videos there")
        with conn:
            conn.execute("UPDATE previews SET status = 'done', kept = ?, dropped = ? WHERE id = ?", (kept, dropped, job_id))
        print(f"follow: preview of x/{handle}: {kept} posts, {dropped} dropped by the checks", flush=True)
    except Exception as e:      # the request's failure, shown where it was asked for
        with conn:
            conn.execute("UPDATE previews SET status = 'failed', error = ? WHERE id = ?", (str(e)[:300], job_id))
        print(f"follow: preview of x/{handle} failed: {e}", flush=True)
    finally:
        if vision is not None:
            vision.close()
        if lock is not None:
            lock.close()
        shutil.rmtree(incoming, ignore_errors=True)


def reddit_saves(conn) -> None:
    """Saves and unsaves tapped in the Feed, sent to Reddit as you (the follow service, within
    seconds). Needs the save permission: sign in again (`follow reddit-login`) if it's missing."""
    rows = conn.execute("SELECT a.id, a.action, p.post_id FROM save_actions a JOIN follow_posts p ON p.id = a.post"
                        " WHERE a.status = 'queued' AND p.source = 'reddit' ORDER BY a.id").fetchall()
    if not rows:
        return
    import urllib.error
    import urllib.request
    creds = _api_creds()
    error = None if creds and _signed_in_as_you() else "sign in to Reddit first (README: Following)"
    token = None
    for job, action, pid in rows:
        err = error
        if not err:
            try:
                token = token or _api_token(creds)
                req = urllib.request.Request(f"{REDDIT_API}/api/{action}", data=f"id=t3_{pid}".encode(), method="POST",
                                             headers={"User-Agent": _agent(), "Authorization": f"bearer {token}"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    r.read()
            except urllib.error.HTTPError as e:
                err = ("dreamfeed can't save on Reddit yet: sign in again (`follow reddit-login`) to give it that permission"
                       if e.code == 403 else f"Reddit said {e.code}")
            except (OSError, ValueError) as e:
                err = str(e)[:200]
        with conn:
            conn.execute("UPDATE save_actions SET status = ?, error = ? WHERE id = ?", ("failed" if err else "done", err, job))
        print(f"follow: {action} reddit post {pid}: {err or 'done'}", flush=True)


def vision_lock():
    """Held while the checks' models are loaded (the feeds, a preview, a browse): one at a time,
    for the follow service's memory. Waits for it; close the returned file to let go."""
    import fcntl
    f = open(Path(os.environ["DATA_DIR"]) / "generated" / "follow" / ".vision.lock", "a")
    fcntl.flock(f, fcntl.LOCK_EX)
    return f


def browsing(conn) -> bool:
    """A Browse now or a profile's posts are waiting or being fetched (the feeds make way)."""
    return bool(conn.execute("SELECT 1 FROM browses WHERE status IN ('queued', 'running')"
                             " UNION SELECT 1 FROM previews WHERE status IN ('queued', 'running') LIMIT 1").fetchone())


BROWSE_SORTS = {"hot": "/hot?", "new": "/new?", "top": "/top?t=day&"}
BROWSE_POSTS = 25
SUBREDDIT = re.compile(r"^[A-Za-z0-9_]{2,21}$")


def browse(job_id: int) -> None:
    """`follow browse <job>`: a subreddit as it is now (hot, new or the day's top), its posts
    fetched and checked one by one, each shown as soon as it passes (the browses tables)."""
    import torch
    from .config import Config, need
    from .db import connect
    from .vision import Vision
    torch.set_num_threads(int(need("FOLLOW_THREADS")))
    cfg = Config()
    conn = connect(cfg.db_path)
    row = conn.execute("SELECT sub, sort FROM browses WHERE id = ?", (job_id,)).fetchone()
    if not row:
        return
    sub, sort = row
    root = cfg.data_dir / "generated" / "follow"
    incoming = root / "incoming" / f"browse-{job_id}"
    vision = lock = None

    def bump(**kw) -> None:
        with conn:
            conn.execute("UPDATE browses SET " + ", ".join(f"{k} = {k} + ?" for k in kw) + " WHERE id = ?", (*kw.values(), job_id))

    try:
        if not SUBREDDIT.match(sub) or sort not in BROWSE_SORTS or _place_blocked(sub):
            raise RuntimeError("not a subreddit dreamfeed reads")
        creds = _api_creds()
        if not creds:
            raise RuntimeError("Browse now needs your Reddit app (README: Following)")
        token = _api_token(creds)
        posts = _api_posts(_fetch(f"{REDDIT_API}/r/{sub}{BROWSE_SORTS[sort]}limit={BROWSE_POSTS}&raw_json=1",
                                  {"Authorization": f"bearer {token}"}, gap=API_GAP))
        with conn:                     # (from the start again, after a restart)
            conn.execute("UPDATE browses SET total = ?, checked = 0, kept = 0, dropped = 0 WHERE id = ?", (len(posts), job_id))
            conn.execute("DELETE FROM browse_posts WHERE browse = ?", (job_id,))
        for n, p in enumerate(posts):
            have = conn.execute("SELECT id FROM follow_posts WHERE source = 'reddit' AND post_id = ?", (p["id"],)).fetchone()
            if have:                   # already here (your feeds, or an earlier browse)
                with conn:
                    conn.execute("INSERT OR IGNORE INTO browse_posts(browse, post, n) VALUES (?, ?, ?)", (job_id, have[0], n))
                bump(checked=1, kept=1)
                continue
            if not re.fullmatch(r"[a-z0-9]{3,12}", p["id"]) or _place_blocked(p.get("subreddit") or "") or not p["media"]:
                bump(checked=1)
                continue
            shutil.rmtree(incoming, ignore_errors=True)
            incoming.mkdir(parents=True)
            urls = p.pop("media")[:MAX_GALLERY]
            p["via"] = "browse"
            meta = json.dumps(p)
            for i, url in enumerate(urls, 1):
                try:
                    _reddit_file(url, f"{p['id']}_{i:02d}", incoming, meta, gap=API_GAP)
                except (OSError, subprocess.SubprocessError) as e:
                    print(f"follow: browse r/{sub}: post {p['id']}: {e}", flush=True)
            if not any(incoming.iterdir()):
                bump(checked=1)
                continue
            if vision is None:
                lock = vision_lock()
                vision = Vision(cfg.models_dir)
            kept, dropped = check_new(conn, "reddit", incoming, root / "media", vision, cfg, discovered=True, via="browse")
            got = conn.execute("SELECT id FROM follow_posts WHERE source = 'reddit' AND post_id = ?", (p["id"],)).fetchone()
            if got:
                with conn:
                    conn.execute("INSERT OR IGNORE INTO browse_posts(browse, post, n) VALUES (?, ?, ?)", (job_id, got[0], n))
            bump(checked=1, kept=int(bool(got)), dropped=dropped)
            if not kept and not dropped:   # stopped for a job or training
                raise RuntimeError("stopped: a job or training started (the checks make way for it)")
        with conn:
            conn.execute("UPDATE browses SET status = 'done' WHERE id = ?", (job_id,))
        print(f"follow: browse r/{sub} ({sort}): done", flush=True)
    except Exception as e:      # shown where it was asked for
        with conn:
            conn.execute("UPDATE browses SET status = 'failed', error = ? WHERE id = ?", (str(e)[:300], job_id))
        print(f"follow: browse r/{sub} failed: {e}", flush=True)
    finally:
        if vision is not None:
            vision.close()
        if lock is not None:
            lock.close()
        shutil.rmtree(incoming, ignore_errors=True)
