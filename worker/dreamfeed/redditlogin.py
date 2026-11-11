"""Signing dreamfeed in to Reddit as you, for the live Feed (livefeeds.py): `python -m dreamfeed
follow reddit-login` prints the address to approve it on reddit.com; `... reddit-login ADDRESS`
(the address your browser was sent back to) prints the refresh token for REDDIT_REFRESH_TOKEN
in .env. Needs your own Reddit app: REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET.
"""
import base64
import json
import os
import secrets
import sys
import urllib.parse
import urllib.request
from pathlib import Path

LOGIN_SCOPES = "identity read mysubreddits save"     # save: the Feed's Save button
LOGIN_REDIRECT = "http://localhost:6414/"
AGENT = "linux:dreamfeed:1.0 (personal feed reader)"


def _agent() -> str:
    user = os.environ.get("REDDIT_USERNAME", "").strip()
    return f"linux:dreamfeed:1.0 (by /u/{user})" if user else AGENT


def _token_request(creds: tuple[str, str], form: dict) -> dict:
    req = urllib.request.Request("https://www.reddit.com/api/v1/access_token", data=urllib.parse.urlencode(form).encode(),
                                 headers={"User-Agent": _agent(),
                                          "Authorization": "Basic " + base64.b64encode(":".join(creds).encode()).decode()})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def login(argv: list[str]) -> None:
    cid, secret = (os.environ.get(k, "").strip() for k in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"))
    if not cid or not secret:
        sys.exit("set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET first")
    state_file = Path(os.environ["DATA_DIR"]) / "generated" / "follow" / ".reddit-login"
    if not argv:
        state = secrets.token_urlsafe(12)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(state)
        print("https://www.reddit.com/api/v1/authorize?" + urllib.parse.urlencode(
            {"client_id": cid, "response_type": "code", "state": state, "redirect_uri": LOGIN_REDIRECT,
             "duration": "permanent", "scope": LOGIN_SCOPES}))
        return
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(argv[0]).query))
    if q.get("error"):
        sys.exit(f"Reddit said: {q['error']}")
    if not state_file.is_file() or q.get("state") != state_file.read_text():
        sys.exit("that isn't the address from this sign-in: run `follow reddit-login` again")
    d = _token_request((cid, secret), {"grant_type": "authorization_code", "code": q.get("code", ""), "redirect_uri": LOGIN_REDIRECT})
    state_file.unlink()
    if not d.get("refresh_token"):
        sys.exit(f"Reddit refused: {d.get('error') or d}")
    print(d["refresh_token"])
