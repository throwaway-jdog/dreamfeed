"""The iOS app's contract: what it reads from dreamfeed still comes as it expects.

- Every address the app calls (APP_CALLS, from its source) is one dreamfeed answers (app.py).
- Each one it reads (GET) is asked of the running web app, with real values found as it goes (a
  room you follow, a post, ...), and the reply is checked against the app's own types
  (app_models.json, from extract.py): every field it needs is there, with the kind of value it
  decodes. Fields it doesn't know about are fine. Nothing is changed: GETs only.

Run inside the web container (tests/check does): python3 tests/contract/check.py
"""
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
MODELS = json.loads((HERE / "app_models.json").read_text())["types"]
BASE = "http://127.0.0.1:8000"

# (method, address) the app calls; GETs with the type it decodes. (From dream-feed-ios; update
# together with app_models.json when the app changes.)
APP_GETS = {
    "api/summary": "Summary", "api/feed": "FeedPage", "api/following": "Following", "api/personas": "PersonaList",
    "api/personas/edit": "PersonaConfig", "api/styles": "StyleList", "api/dashboard": "Dashboard", "api/comics": "ComicList",
    "api/following/settings": "FollowSettings", "api/following/posts": "FollowPosts", "api/discover/cb": "DiscoverRooms",
    "api/discover/x": "DiscoverPeople", "api/reddit/browses": "RecentBrowses", "api/reddit/browse": "Browse",
    "api/reddit/random": "Pick", "api/profile": "PersonProfile", "api/person/posts": "PersonPosts", "api/live/videos": "RoomVideos",
    "api/live/stream": "LiveStream", "api/signins": "SignIns", "api/saved/import": "SavedImport", "api/post/comments": "PostComments",
    "api/xvideos": "XVideosPage", "api/xvideos/video": "XVideoFiles", "api/redgifs": "RedGifsPage", "api/videos/more": "MoreVideos",
    "api/x/related": "MoreVideos", "api/comics/search": "ComicSearch", "api/personas/draft": "DraftStatus",
}
APP_POSTS = ["api/feedback", "api/live/follow", "api/following/settings", "api/saved/import", "api/profile/link", "api/live/restore",
             "api/live/highlights", "api/live/delete", "api/following/save", "api/dvr", "api/comics/import", "api/comics/delete",
             "api/cancel", "api/animate", "api/styles/video-cancel", "api/styles/video", "api/styles/train", "api/styles/cancel",
             "api/retry", "api/profile/relink", "api/personas/save", "api/personas/delete", "api/personas/avatar", "api/generate",
             "api/e621/vote", "api/comics/update", "api/comics/rename", "api/comics/create", "api/comics/animation-delete",
             "api/comics/animate", "api/signins", "api/personas/draft"]

PRIMS = {"String": (str,), "Int": (int,), "Double": (int, float), "Float": (int, float), "Bool": (bool,),
         "JSONObject": (dict,), "JSONValue": None, "URL": (str,)}
problems: list[str] = []


def resolve(name: str, within: str) -> dict | None:
    outer = within.split(".")[0]
    return MODELS.get(f"{outer}.{name}") or MODELS.get(f"{within}.{name}") or MODELS.get(name)


def check(value, typ: str, within: str, at: str) -> None:
    typ = typ.strip()
    if typ.endswith("?"):
        if value is None:
            return
        typ = typ[:-1]
    if value is None:
        problems.append(f"{at}: null where the app needs {typ}")
        return
    m = re.fullmatch(r"\[(.+)\]", typ)
    if m:
        inner = m.group(1)
        kv = re.fullmatch(r"(\w+)\s*:\s*(.+)", inner)
        if kv:                                    # [String: T]
            if not isinstance(value, dict):
                problems.append(f"{at}: not an object (the app needs {typ})")
                return
            for k, v in list(value.items())[:5]:
                check(v, kv.group(2), within, f"{at}.{k}")
            return
        if not isinstance(value, list):
            problems.append(f"{at}: not a list (the app needs {typ})")
            return
        for i, v in enumerate(value[:5]):
            check(v, inner, within, f"{at}[{i}]")
        return
    if typ in PRIMS:
        want = PRIMS[typ]
        if want and (not isinstance(value, want) or (typ in ("Int", "Double") and isinstance(value, bool))):
            problems.append(f"{at}: {type(value).__name__} where the app needs {typ}")
        return
    model = resolve(typ, within)
    if not model or model["kind"] == "enum":
        return                                    # (not one of its decoded types, or an enum it decodes itself)
    if not isinstance(value, dict):
        problems.append(f"{at}: not an object (the app needs {typ})")
        return
    if model["kind"] == "custom":
        return
    qual = next(k for k, v in MODELS.items() if v is model)
    for key, f in model["fields"].items():
        if key not in value:
            if not f["optional"]:
                problems.append(f"{at}.{key}: missing (the app needs it: {qual})")
            continue
        check(value[key], f["type"] + ("?" if f["optional"] else ""), qual, f"{at}.{key}")


def get(cookie: str, path: str, **q):
    url = f"{BASE}/{path}" + ("?" + urllib.parse.urlencode(q) if q else "")
    req = urllib.request.Request(url, headers={"Cookie": cookie, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except ValueError:
            return e.code, None


def main() -> int:
    sys.path.insert(0, "/app")
    import formlogin
    from webapp.common import STATE
    login = formlogin.Login.from_env("DREAMFEED", "dreamfeed", STATE, title="dreamfeed")
    cookie = f"{login.cookie_name}={login.new_session()}"

    routes = Path("/app/app.py").read_text()
    for path in sorted(set(APP_GETS) | set(APP_POSTS)):
        if f'"/{path}"' not in routes:
            problems.append(f"/{path}: the app calls it, dreamfeed has no such address")

    asked = {}
    def ask(path, **q):
        status, body = get(cookie, path, **q)
        typ = APP_GETS[path]
        label = f"/{path}" + (f"?{urllib.parse.urlencode(q)}" if q else "")
        if status != 200:
            problems.append(f"{label}: HTTP {status} ({(body or {}).get('error') if isinstance(body, dict) else ''})")
            return None
        n = len(problems)
        check(body, typ, typ, label)
        print(f"  {'ok ' if len(problems) == n else 'BAD'} {label[:70]:72} {typ}")
        asked[path] = body
        return body

    print("the app's reads:")
    for p in ("api/summary", "api/personas", "api/personas/edit", "api/styles", "api/dashboard", "api/comics", "api/following/settings",
              "api/discover/x", "api/reddit/browses", "api/signins", "api/saved/import", "api/reddit/random"):
        ask(p)
    ask("api/feed", offset=0)
    following = ask("api/following") or {}
    room = next((r["name"] for r in following.get("rooms") or [] if r.get("source") == "chaturbate"), None)
    ask("api/discover/cb", mode="top", offset=0)
    posts = (ask("api/following/posts", mode="following", source="reddit") or {}).get("posts") or []
    ask("api/following/posts", mode="foryou", source="all")
    ask("api/reddit/browse", sub="pics", sort="hot")
    if room:
        prof = ask("api/profile", room=room) or {}
        ask("api/live/videos", name=room)
        ask("api/live/stream", name=room)
    post = next((p for p in posts if p.get("id")), None)
    if post:
        ask("api/post/comments", id=post["id"])
        ask("api/person/posts", source="reddit", handle=post["author"], cursor="")
    vid = next((p for p in posts if any(m.get("kind") in ("video", "hls") for m in p.get("media") or [])), None)
    if vid:
        ask("api/videos/more", id=vid["id"], cursor="")
    xposts = (get(cookie, "api/following/posts", mode="following", source="x")[1] or {}).get("posts") or []
    xv = next((p for p in xposts if any(m.get("kind") == "video" for m in p.get("media") or [])), None)
    if xv:
        ask("api/x/related", id=xv["id"].split(":", 1)[1], handle=xv["author"], cursor="")
    sys.path.insert(0, "/app")
    from webapp.common import db
    with db() as conn:
        linked = {r["source"]: r["handle"] for r in conn.execute("SELECT source, handle FROM links WHERE state != 'removed' AND source IN ('xvideos', 'redgifs')")}
    if linked.get("xvideos"):
        page = ask("api/xvideos", name=linked["xvideos"], page=0) or {}
        if page.get("videos"):
            ask("api/xvideos/video", id=page["videos"][0]["id"])
    if linked.get("redgifs"):
        ask("api/redgifs", name=linked["redgifs"], page=1)
    ask("api/comics/search", q="sonic", page=0)

    not_asked = sorted(set(APP_GETS) - set(asked) - {"api/personas/draft"})
    if not_asked:
        print("  (not asked, nothing to ask with here: " + ", ".join("/" + p for p in not_asked) + ")")
    print(f"\n{len(problems)} problem{'s' if len(problems) != 1 else ''}")
    for p in problems:
        print("  - " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
