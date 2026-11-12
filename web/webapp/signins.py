"""Sign-ins (the Dashboard): the sites' cookies, Reddit's sign-in (Sign in with Reddit), e621's
and Bluesky's, and the server's own browser (started and stopped through browserpower).
"""
import base64
import json
import os
import re
import time
import urllib.parse
from pathlib import Path

from dreamfeed.core import acts, cookies, personas as people, safety
from dreamfeed.feed import e621, livefeeds, savedposts

from .common import PREFIX, read_json


# Sign-ins (the dashboard): the sites' cookies, set by pasting an export (cookies.py). The files
# mounted for them (X_COOKIES_FILE, CHATURBATE_COOKIES_FILE) are used until then.
# The server's own browser (the browser service, a Firefox you sign in to the sites in, opened
# from the Dashboard at BROWSER_URL): its profile, where Take its cookies reads them.
BROWSER_PROFILE = os.environ.get("BROWSER_PROFILE", "").strip()
BROWSER_URL = os.environ.get("BROWSER_URL", "").strip()
# It runs only when needed: started for you (Sign in on the server's browser) or for a refresh,
# stopped when no one's watching it. dreamfeed only asks, leaving a file in BROWSER_POWER_DIR;
# systemd on the host starts and stops it (browserpower/install.sh): nothing here has a say
# over Docker. BROWSER_SCREEN: its page (host:port), to tell when it's up.
BROWSER_POWER_DIR = os.environ.get("BROWSER_POWER_DIR", "").strip()
BROWSER_SCREEN = os.environ.get("BROWSER_SCREEN", "").strip()
BROWSER_REFRESH = 86400    # cookies taken from it are taken again (it opening the sites) this often
BROWSER_LOAD = 90          # seconds it's given to open the sites before they're taken
BROWSER_TICK = 60
_browser = {"refresh": {}}   # site -> {"at", "error"}: its last refresh
MOUNTED_COOKIES = {"x": os.environ.get("X_COOKIES", "").strip() or None,
                   "chaturbate": os.environ.get("CHATURBATE_COOKIES", "").strip() or None}


def _signin_check(site: str) -> str | None:
    """Whether the site takes the cookies now: None when it does, else what's wrong."""
    import http.cookiejar
    import urllib.request
    try:
        if site == "x":
            livefeeds.forget("x:")
            items = livefeeds._x("https://x.com/home", 1, 1, timeout=60)
            return None if any(isinstance(i, list) and i and i[0] == 3 for i in items) else "X showed nothing: the cookies may be out of date"
        file = cookies.path(site, MOUNTED_COOKIES[site])
        if not file:
            return "no cookies set"
        jar = http.cookiejar.MozillaCookieJar(str(file))
        jar.load(ignore_discard=True, ignore_expires=True)
        req = urllib.request.Request("https://chaturbate.com/api/ts/roomlist/room-list/?follow=true&limit=5&offline=true",
                                     headers={"User-Agent": "dreamfeed (personal follow list)", "Accept": "application/json",
                                              "Referer": "https://chaturbate.com/"})
        with urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)).open(req, timeout=30) as r:
            rooms = json.loads(r.read()).get("rooms") or []
        # (signed out, it ignores follow=true and lists everyone's)
        return None if all(x.get("is_following") for x in rooms) else "Chaturbate doesn't see you signed in with these"
    except (LookupError, OSError, ValueError) as e:
        return str(e)[:200]


REDDIT_SCOPES = "identity read mysubreddits save history"     # save: the Save button; history: your saved posts
_reddit_states: dict[str, float] = {}       # sign-ins started (state -> when), each good for 10 minutes
HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}(?::\d{1,5})?$")


def reddit_redirect(headers) -> str:
    """Where Reddit sends you back after you approve: this page's own address (your Reddit app's
    redirect uri must be exactly this)."""
    host = headers.get("X-Forwarded-Host") or headers.get("Host") or ""
    proto = (headers.get("X-Forwarded-Proto") or "https").split(",")[0].strip()
    prefix = (headers.get("X-Forwarded-Prefix") or "").rstrip("/")
    if not HOST.match(host) or proto not in ("http", "https") or not PREFIX.match(prefix):
        raise ValueError("can't tell this page's address")
    return f"{proto}://{host}{prefix}/reddit/callback"


def _reddit_status(headers) -> dict:
    c = cookies.reddit()
    try:
        redirect = reddit_redirect(headers)
    except ValueError:
        redirect = None
    return {"site": "reddit", "name": "Reddit", "from": c["from"], "app": bool(c["client_id"] and c["client_secret"]),
            "client_id": c["client_id"], "signed_in": livefeeds.reddit_ready(), "username": c["username"] or None,
            "redirect": redirect}


def reddit_login_url(headers) -> str:
    c = cookies.reddit()
    if c["from"] != "dashboard" or not c["client_secret"]:
        raise ValueError("set your Reddit app's id and secret first")
    import secrets
    now = time.time()
    for k in [k for k, t in _reddit_states.items() if now - t > 600]:
        _reddit_states.pop(k, None)
    state = secrets.token_urlsafe(16)
    _reddit_states[state] = now
    return "https://www.reddit.com/api/v1/authorize?" + urllib.parse.urlencode(
        {"client_id": c["client_id"], "response_type": "code", "state": state, "redirect_uri": reddit_redirect(headers),
         "duration": "permanent", "scope": REDDIT_SCOPES})


def reddit_callback(query: dict, headers) -> str:
    """Reddit's answer: the sign-in kept (with your username). What to say on the dashboard."""
    import urllib.request
    if query.get("error"):
        return f"Reddit said: {query['error'][:80]}"
    if _reddit_states.pop(query.get("state", ""), 0) < time.time() - 600:
        return "That sign-in had run out: try again"
    c = cookies.reddit()
    auth = "Basic " + base64.b64encode(f"{c['client_id']}:{c['client_secret']}".encode()).decode()
    form = {"grant_type": "authorization_code", "code": query.get("code", ""), "redirect_uri": reddit_redirect(headers)}
    try:
        req = urllib.request.Request("https://www.reddit.com/api/v1/access_token", data=urllib.parse.urlencode(form).encode(),
                                     headers={"User-Agent": livefeeds.REDDIT_AGENT, "Authorization": auth})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
        if not d.get("refresh_token"):
            return f"Reddit refused: {str(d.get('error') or d)[:80]}"
        me = urllib.request.Request("https://oauth.reddit.com/api/v1/me", headers={
            "User-Agent": livefeeds.REDDIT_AGENT, "Authorization": "bearer " + d["access_token"]})
        with urllib.request.urlopen(me, timeout=30) as r:
            name = str(json.load(r).get("name") or "")
    except (OSError, ValueError) as e:
        return f"Reddit didn't answer ({str(e)[:80]})"
    cookies.save_reddit_signin(d["refresh_token"], name if livefeeds.REDDIT_USER.match(name) else "")
    livefeeds.forget()            # (your subscriptions and the rest, read again as you)
    return f"Signed in to Reddit as u/{name}" if name else "Signed in to Reddit"


def _power(action: str) -> dict:
    """The server's browser: {"running", "viewers"}, after asking it to start or stop (a file left in
    BROWSER_POWER_DIR, which systemd on the host acts on: browserpower/) or just as it is now."""
    import socket
    if not BROWSER_POWER_DIR or not os.path.isdir(BROWSER_POWER_DIR):
        raise LookupError("the server's browser can't be started from here (sudo browserpower/install.sh)")
    folder = Path(BROWSER_POWER_DIR)

    def now() -> dict | None:
        d = read_json(folder / "status.json")
        return d if isinstance(d, dict) and time.time() - float(d.get("at") or 0) < 180 else None
    if action == "status":
        d = now()
        if d is None:
            raise LookupError("the server's browser isn't looked after (sudo browserpower/install.sh)")
        return d
    asked = time.time()
    (folder / action).write_text("")
    for _ in range(90):
        time.sleep(1)
        d = now()
        if d and float(d.get("at") or 0) >= int(asked) and not (folder / action).exists():
            if action == "start":
                host, _, port = BROWSER_SCREEN.rpartition(":")
                for _ in range(60):                 # its page answers once its desktop is up
                    try:
                        with socket.create_connection((host, int(port)), timeout=2):
                            return d
                    except OSError:
                        time.sleep(1)
                raise LookupError("the server's browser started, but its page doesn't answer")
            return d
    raise LookupError("the server's browser didn't answer: is browserpower installed? (sudo browserpower/install.sh)")


def browser_start(req: dict) -> dict:
    """Starts the server's browser, for you to use (stopped again once no one's watching)."""
    cookies.firefox_prefs(BROWSER_PROFILE)
    return _power("start")


def _browser_refresh() -> None:
    """Takes again the cookies taken from the server's browser, once a day: it's started out of
    sight, opens the sites (which freshens them), and stopped. Not while you're using it."""
    due = [s for s in cookies.SITES if cookies.status(s).get("browser")
           and time.time() - (cookies.status(s).get("updated") or 0) >= BROWSER_REFRESH
           and time.time() - _browser["refresh"].get(s, {}).get("at", 0) >= BROWSER_REFRESH]
    if not due:
        return
    st = _power("status")
    if st["viewers"]:
        return                     # (you're in it: next time)
    was = st["running"]
    try:
        if not was:
            cookies.firefox_prefs(BROWSER_PROFILE)
            _power("start")
        time.sleep(BROWSER_LOAD)
        for site in due:
            try:
                cookies.from_firefox(site, BROWSER_PROFILE)
                error = _signin_check(site)
            except (ValueError, OSError) as e:
                error = str(e)[:200]
            _browser["refresh"][site] = {"at": time.time(), "error": error}
            print(time.strftime("%F %T"), f"web: {site}'s cookies from the server's browser:", error or "taken again", flush=True)
            if site == "x":
                livefeeds.forget("x:")
    finally:
        if not was:
            _power("stop")        # (it's stopped only if no one's watching it)


def _browser_keeper() -> None:
    """Refreshes the cookies taken from the server's browser (stopping it when unused is the
    host's: browserpower's idle timer)."""
    while True:
        time.sleep(BROWSER_TICK)
        try:
            _browser_refresh()
        except LookupError as e:
            print(time.strftime("%F %T"), f"web: {e}", flush=True)
            time.sleep(BROWSER_TICK * 59)


def _bsky_status() -> dict:
    c = cookies.bsky()
    out = {"site": "bsky", "name": "Bluesky", "from": c["from"], "handle": None, "signed_in": False}
    if c["from"]:
        try:
            sess = livefeeds._bsky_session()
            out.update(signed_in=True, handle=sess.get("handle") or c["identifier"])
        except LookupError as e:
            out["error"] = str(e)[:200]
    return out


def _e621_status() -> dict:
    c = cookies.e621()
    out = {"site": "e621", "name": "e621", "from": c["from"], "username": c["username"] or None, "signed_in": False}
    if c["from"]:
        try:
            me = livefeeds._cached("e621-me", e621.me, 600)
            out.update(signed_in=True, favorites=me["favorites"], blacklist=len(me["blacklist"]))
        except (LookupError, OSError, ValueError) as e:
            out["error"] = str(e)[:200]
    return out


def signins(headers=None) -> dict:
    return {"sites": [{**cookies.status(s, MOUNTED_COOKIES[s]), "refresh": _browser["refresh"].get(s)} for s in cookies.SITES],
            "e621": _e621_status(), "bsky": _bsky_status(),
            "browser": BROWSER_URL if BROWSER_PROFILE and BROWSER_URL else None,
            "reddit": _reddit_status(headers or {})}


def save_signin(req: dict) -> dict:
    """{"site", "cookies": TEXT} keeps them and checks them; {"site", "forget": true} drops them;
    {"site": "reddit", "client_id", "client_secret"} your Reddit app's keys."""
    site = str(req.get("site", ""))
    if site == "bsky":
        if req.get("forget"):
            cookies.forget_bsky()
            livefeeds.forget("bsky:")
            return {"site": _bsky_status()}
        cookies.save_bsky(str(req.get("identifier", "")), str(req.get("password", "")))
        livefeeds.forget("bsky:")
        try:
            livefeeds._bsky_session(fresh=True)        # (checked by signing in now)
        except LookupError as e:
            cookies.forget_bsky()
            raise ValueError(str(e))
        return {"site": _bsky_status()}
    if site == "e621":
        if req.get("forget"):
            cookies.forget_e621()
        else:
            cookies.save_e621(str(req.get("username", "")), str(req.get("api_key", "")))
        livefeeds.forget()
        st = _e621_status()
        if not req.get("forget") and not st["signed_in"]:
            cookies.forget_e621()            # (a key e621 doesn't take isn't kept)
            livefeeds.forget()
            raise ValueError(st.get("error") or "e621 didn't take them")
        return {"site": st}
    if site == "reddit":
        if req.get("forget"):
            cookies.forget_reddit()
        elif req.get("from_env"):          # the keys and sign-in from .env, kept here instead
            env = cookies.reddit()
            if env["from"] != "env":
                raise ValueError("there are no Reddit keys in the environment")
            cookies.save_reddit_app(env["client_id"], env["client_secret"])
            if env["refresh_token"]:
                cookies.save_reddit_signin(env["refresh_token"], env["username"])
        else:
            cookies.save_reddit_app(str(req.get("client_id", "")), str(req.get("client_secret", "")))
        livefeeds.forget()
        return {"ok": True}
    if req.get("from_browser"):
        if not BROWSER_PROFILE:
            raise ValueError("no server browser set up (BROWSER_PROFILE)")
        cookies.from_firefox(site, BROWSER_PROFILE)
        problem = _signin_check(site)
        if site == "x":
            livefeeds.forget("x:")
        return {"site": cookies.status(site, MOUNTED_COOKIES.get(site)), "check": problem}
    if req.get("forget"):
        st = cookies.forget(site)
        return {"site": cookies.status(site, MOUNTED_COOKIES.get(site))}
    cookies.save(site, str(req.get("cookies", "")))
    problem = _signin_check(site)
    if site == "x":
        livefeeds.forget("x:")
    return {"site": cookies.status(site, MOUNTED_COOKIES.get(site)), "check": problem}
