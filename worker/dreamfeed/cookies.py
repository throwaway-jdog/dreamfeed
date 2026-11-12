"""Your sign-ins to the sites, as cookies: set from the dashboard (Sign-ins), kept in
<DATA_DIR>/cookies/<site>.txt (Netscape cookies.txt, readable only by dreamfeed's user). A site
without one there uses the file mounted for it (X_COOKIES_FILE, CHATURBATE_COOKIES_FILE), so
those still work; one set from the dashboard replaces it. Read on each use: no restart needed.

A paste can be a cookies.txt export, a JSON export (Cookie-Editor's and the like: a list of
{"domain", "name", "value", ...}) or a Cookie header ("name=value; name2=value2", e.g. copied
from the browser's developer tools). Only the site's own cookies are kept, and the ones it
needs to be signed in must be there.
"""
import json
import os
import re
import tempfile
import time
from pathlib import Path

# site: its name, its domains (cookies for others are dropped) and the cookies a sign-in needs
SITES = {
    "x": {"name": "X", "domains": ("x.com", "twitter.com"), "needs": ("auth_token", "ct0"), "home": "https://x.com/home"},
    "chaturbate": {"name": "Chaturbate", "domains": ("chaturbate.com",), "needs": ("sessionid", "csrftoken"),
                   "home": "https://chaturbate.com/followed-cams/"},
}
MAX_TEXT = 1 << 20          # a paste's size
NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,200}$")


def folder() -> Path:
    data = os.environ.get("DATA_DIR", "").strip()
    if not data:
        raise RuntimeError("DATA_DIR isn't set")
    return Path(data) / "cookies"


def _site(site: str) -> dict:
    if site not in SITES:
        raise ValueError("unknown site")
    return SITES[site]


def path(site: str, mounted: str | os.PathLike | None = None) -> Path | None:
    """The cookies file to use for site: the dashboard's, else the mounted one, else None.
    (A service without DATA_DIR only has the mounted one.)"""
    _site(site)
    own = folder() / f"{site}.txt" if os.environ.get("DATA_DIR", "").strip() else None
    if own and own.is_file():
        return own
    if mounted and Path(mounted).is_file():
        return Path(mounted)
    return None


def _ours(domain: str, domains: tuple) -> bool:
    d = domain.lstrip(".").lower()
    return any(d == x or d.endswith("." + x) for x in domains)


def parse(text: str, site: str) -> list[dict]:
    """The site's cookies in text (any of the forms above): [{"domain", "name", "value", "path",
    "secure", "expires"}]."""
    s = _site(site)
    text = (text or "").strip().lstrip("﻿")
    if not text:
        raise ValueError("nothing pasted")
    if len(text) > MAX_TEXT:
        raise ValueError("too long for a cookies export")
    found = []
    if text[0] in "[{":
        try:
            d = json.loads(text)
        except ValueError:
            raise ValueError("that looks like JSON but doesn't read as it")
        items = d.get("cookies", []) if isinstance(d, dict) else d
        for c in items if isinstance(items, list) else []:
            if not isinstance(c, dict):
                continue
            exp = c.get("expirationDate", c.get("expires", c.get("expiry")))
            found.append({"domain": str(c.get("domain") or s["domains"][0]), "name": str(c.get("name") or ""),
                          "value": str(c.get("value") or ""), "path": str(c.get("path") or "/"),
                          "secure": bool(c.get("secure")), "expires": int(float(exp)) if isinstance(exp, (int, float)) and exp > 0 else 0})
    elif "\t" in text:
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("#HttpOnly_"):
                line = line[len("#HttpOnly_"):]
            elif not line or line.startswith("#"):
                continue
            f = line.split("\t")
            if len(f) < 7:
                continue
            found.append({"domain": f[0], "name": f[5], "value": f[6], "path": f[2] or "/",
                          "secure": f[3].upper() == "TRUE", "expires": int(f[4]) if f[4].isdigit() else 0})
    else:
        header = re.sub(r"^\s*cookie:\s*", "", text, flags=re.I)
        for part in header.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                found.append({"domain": "." + s["domains"][0], "name": k.strip(), "value": v.strip(), "path": "/",
                              "secure": True, "expires": 0})
    now = time.time()
    out = {}
    for c in found:
        if not NAME.match(c["name"]) or any(ch in c["value"] for ch in "\t\r\n") or not _ours(c["domain"], s["domains"]):
            continue
        if c["expires"] and c["expires"] < now:
            continue
        out[(c["domain"].lower(), c["path"], c["name"])] = c
    cookies = list(out.values())
    if not cookies:
        raise ValueError(f"no {s['name']} cookies in it (export them while on {s['domains'][0]})")
    missing = [n for n in s["needs"] if not any(c["name"] == n for c in cookies)]
    if missing:
        raise ValueError(f"it's missing {', '.join(missing)}: export them while signed in to {s['name']}")
    return cookies


BROWSER_NOTE = "# from the server's browser"      # (cookies taken from it: refreshed from it by themselves)


def save(site: str, text: str, from_browser: bool = False) -> dict:
    """Keeps the site's cookies from a paste (replacing any set before). Its status()."""
    cookies = parse(text, site)
    lines = ["# Netscape HTTP Cookie File", f"# {SITES[site]['name']}, set from dreamfeed's dashboard",
             BROWSER_NOTE if from_browser else "", ""]
    for c in cookies:
        dom = c["domain"] if c["domain"].startswith(".") else c["domain"]
        lines.append("\t".join([dom, "TRUE" if dom.startswith(".") else "FALSE", c["path"],
                                "TRUE" if c["secure"] else "FALSE", str(c["expires"]), c["name"], c["value"]]))
    d = folder()
    d.mkdir(mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=f".{site}-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, d / f"{site}.txt")       # (in one step: readers see the old or the new)
    except BaseException:
        os.unlink(tmp)
        raise
    return status(site)


def firefox_prefs(profile: str | os.PathLike) -> None:
    """The server's browser opens the sites at each start (its homepage tabs), so their cookies
    are freshened whenever it runs, and doesn't offer to restore what it had open."""
    p = Path(profile)
    if not p.is_dir():
        return
    home = "|".join(s["home"] for s in SITES.values())
    (p / "user.js").write_text("\n".join([
        'user_pref("browser.startup.page", 1);', f'user_pref("browser.startup.homepage", "{home}");',
        'user_pref("browser.sessionstore.resume_from_crash", false);', ""]))


def from_firefox(site: str, profile: str | os.PathLike) -> dict:
    """Keeps the site's cookies from a Firefox profile (the server's own browser, signed in
    there by you): read from a copy of its cookies.sqlite, as it's in use. Its status()."""
    import shutil
    import sqlite3
    s = _site(site)
    src = Path(profile) / "cookies.sqlite"
    if not src.is_file():
        raise ValueError("the server's browser hasn't been opened yet")
    with tempfile.TemporaryDirectory() as tmp:
        for suffix in ("", "-wal"):            # (what it's written lately is in the -wal)
            if Path(f"{src}{suffix}").is_file():
                shutil.copy(f"{src}{suffix}", Path(tmp) / f"cookies.sqlite{suffix}")
        conn = sqlite3.connect(Path(tmp) / "cookies.sqlite")
        try:
            rows = conn.execute("SELECT host, name, value, path, expiry, isSecure FROM moz_cookies").fetchall()
        finally:
            conn.close()
    lines = []
    for host, name, value, path_, expiry, secure in rows:
        if not _ours(str(host), s["domains"]):
            continue
        exp = int(expiry or 0)
        exp = exp // 1000 if exp > 10 ** 11 else exp      # (newer Firefox keeps it in milliseconds)
        lines.append("\t".join([host, "TRUE" if str(host).startswith(".") else "FALSE", path_ or "/",
                                "TRUE" if secure else "FALSE", str(exp), name, value]))
    if not lines:
        raise ValueError(f"the server's browser isn't signed in to {s['name']}: sign in there first")
    return save(site, "\n".join(lines), from_browser=True)


def forget(site: str) -> dict:
    """Drops the dashboard's cookies for site (a mounted file, if any, is used again)."""
    _site(site)
    (folder() / f"{site}.txt").unlink(missing_ok=True)
    return status(site)


def status(site: str, mounted: str | os.PathLike | None = None) -> dict:
    """What dreamfeed has for site, never the values: {"site", "name", "set" (dashboard|file|None),
    "count", "expires" (when the first needed one runs out, unix; 0: with the browser session),
    "updated" (unix), "missing"}."""
    s = _site(site)
    p = path(site, mounted)
    out = {"site": site, "name": s["name"], "set": None, "count": 0, "expires": None, "updated": None, "missing": list(s["needs"]),
           "browser": False}
    if not p:
        return out
    try:
        cookies = parse(p.read_text(errors="replace"), site)
        missing = []
    except ValueError:
        cookies, missing = [], list(s["needs"])
    need = [c for c in cookies if c["name"] in s["needs"]]
    exp = [c["expires"] for c in need if c["expires"]]
    text = p.read_text(errors="replace")
    out["browser"] = BROWSER_NOTE in text.splitlines()[:4]
    out.update(set="dashboard" if p.parent == folder() else "file", count=len(cookies),
               expires=min(exp) if exp else (0 if need else None), updated=int(p.stat().st_mtime), missing=missing)
    return out


# ---- Reddit: your own app's keys and the sign-in, the same way (<DATA_DIR>/cookies/reddit.json) ----
# Set from the dashboard (the keys, then Sign in with Reddit); until then REDDIT_CLIENT_ID,
# REDDIT_CLIENT_SECRET, REDDIT_USERNAME and REDDIT_REFRESH_TOKEN from the environment are used.
REDDIT_KEYS = ("client_id", "client_secret", "username", "refresh_token")
REDDIT_FIELD = re.compile(r"^[A-Za-z0-9_-]{1,200}$")


def _reddit_file() -> Path | None:
    return folder() / "reddit.json" if os.environ.get("DATA_DIR", "").strip() else None


def _reddit_saved() -> dict:
    f = _reddit_file()
    try:
        d = json.loads(f.read_text()) if f and f.is_file() else {}
    except ValueError:
        d = {}
    return {k: str(d.get(k) or "") for k in REDDIT_KEYS}


def reddit() -> dict:
    """{"client_id", "client_secret", "username", "refresh_token", "from": dashboard|env|None}: the
    dashboard's when it has an app set, else the environment's."""
    own = _reddit_saved()
    if own["client_id"]:
        return {**own, "from": "dashboard"}
    env = {k: os.environ.get(f"REDDIT_{k.upper()}", "").strip() for k in REDDIT_KEYS}
    return {**env, "from": "env" if env["client_id"] else None}


def _reddit_write(d: dict) -> None:
    folder().mkdir(mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder(), prefix=".reddit-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump({k: d.get(k, "") for k in REDDIT_KEYS}, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, folder() / "reddit.json")
    except BaseException:
        os.unlink(tmp)
        raise


def save_reddit_app(client_id: str, client_secret: str) -> None:
    """Your Reddit app's keys (a new app: sign in again)."""
    client_id, client_secret = client_id.strip(), client_secret.strip()
    if not REDDIT_FIELD.match(client_id) or not REDDIT_FIELD.match(client_secret):
        raise ValueError("those don't look like a Reddit app's id and secret")
    old = _reddit_saved()
    same = old["client_id"] == client_id
    _reddit_write({"client_id": client_id, "client_secret": client_secret,
                   "username": old["username"] if same else "", "refresh_token": old["refresh_token"] if same else ""})


def save_reddit_signin(refresh_token: str, username: str) -> None:
    d = _reddit_saved()
    if not d["client_id"]:
        raise ValueError("set your Reddit app's id and secret first")
    _reddit_write({**d, "refresh_token": refresh_token, "username": username})


def forget_reddit() -> None:
    f = _reddit_file()
    if f:
        f.unlink(missing_ok=True)


# ---- e621: your username and API key (e621.net: Account, Manage API Access), the same way
# (<DATA_DIR>/cookies/e621.json); until set there, E621_USERNAME and E621_API_KEY from the environment.
E621_NAME = re.compile(r"^[A-Za-z0-9_.~-]{2,40}$")
E621_KEY = re.compile(r"^[A-Za-z0-9]{10,64}$")


def _e621_file() -> Path | None:
    return folder() / "e621.json" if os.environ.get("DATA_DIR", "").strip() else None


def e621() -> dict:
    """{"username", "api_key", "from": dashboard|env|None}."""
    f = _e621_file()
    try:
        d = json.loads(f.read_text()) if f and f.is_file() else {}
    except ValueError:
        d = {}
    if d.get("username") and d.get("api_key"):
        return {"username": str(d["username"]), "api_key": str(d["api_key"]), "from": "dashboard"}
    env = {"username": os.environ.get("E621_USERNAME", "").strip(), "api_key": os.environ.get("E621_API_KEY", "").strip()}
    return {**env, "from": "env" if env["username"] and env["api_key"] else None}


def save_e621(username: str, api_key: str) -> None:
    username, api_key = username.strip(), api_key.strip()
    if not E621_NAME.match(username) or not E621_KEY.match(api_key):
        raise ValueError("that doesn't look like an e621 username and API key")
    folder().mkdir(mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder(), prefix=".e621-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump({"username": username, "api_key": api_key}, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, folder() / "e621.json")
    except BaseException:
        os.unlink(tmp)
        raise


def forget_e621() -> None:
    f = _e621_file()
    if f:
        f.unlink(missing_ok=True)


# ---- Bluesky: your handle and an app password (Settings, Privacy and security, App passwords),
# the same way (<DATA_DIR>/cookies/bsky.json, with the session it makes so it signs in once).
BSKY_NAME = re.compile(r"^(?:did:plc:[a-z2-7]{24}|[A-Za-z0-9.-]{3,253}|[^@\s]{1,64}@[^@\s]{1,253})$")


def _bsky_file() -> Path | None:
    return folder() / "bsky.json" if os.environ.get("DATA_DIR", "").strip() else None


def bsky() -> dict:
    """{"identifier", "password", "session": {...} or None, "from": dashboard|None}."""
    f = _bsky_file()
    try:
        d = json.loads(f.read_text()) if f and f.is_file() else {}
    except ValueError:
        d = {}
    ok = bool(d.get("identifier") and d.get("password"))
    return {"identifier": d.get("identifier", ""), "password": d.get("password", ""),
            "session": d.get("session") if ok else None, "from": "dashboard" if ok else None}


def _bsky_write(d: dict) -> None:
    folder().mkdir(mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder(), prefix=".bsky-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(d, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, folder() / "bsky.json")
    except BaseException:
        os.unlink(tmp)
        raise


def save_bsky(identifier: str, password: str, session: dict | None = None) -> None:
    identifier, password = identifier.strip().lstrip("@"), password.strip()
    if not BSKY_NAME.match(identifier) or not 4 <= len(password) <= 200:
        raise ValueError("that doesn't look like a Bluesky handle and app password")
    _bsky_write({"identifier": identifier, "password": password, "session": session})


def save_bsky_session(session: dict) -> None:
    d = bsky()
    if d["from"]:
        _bsky_write({"identifier": d["identifier"], "password": d["password"], "session": session})


def forget_bsky() -> None:
    f = _bsky_file()
    if f:
        f.unlink(missing_ok=True)
