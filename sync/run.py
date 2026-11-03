"""Downloads new X bookmarks every SYNC_INTERVAL_HOURS, or right away when the dashboard
asks (it creates /data/sync/scan-now). Progress goes to /data/sync/status.json.
The archive remembers what was already fetched, so files the worker deletes after tagging
aren't downloaded again."""
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SYNC = Path("/data/sync")
TRIGGER = SYNC / "scan-now"
STATUS = SYNC / "status.json"
COOKIES = Path("/config/cookies.txt")
CMD = ["gallery-dl", "--config", "/app/gallery-dl.conf", "--cookies", str(COOKIES),
       "https://x.com/i/bookmarks"]

hours = os.environ.get("SYNC_INTERVAL_HOURS", "").strip()
try:
    INTERVAL = float(hours) * 3600
except ValueError:
    sys.exit("sync: SYNC_INTERVAL_HOURS must be set to a number")
if not os.access(COOKIES, os.R_OK):
    sys.exit("sync: /config/cookies.txt missing or unreadable (X_COOKIES_FILE)")


def now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def write_status(**fields) -> None:
    try:
        data = json.loads(STATUS.read_text())
    except (OSError, ValueError):
        data = {}
    data.update(fields)
    tmp = STATUS.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, STATUS)


def scan(reason: str) -> None:
    print(f"sync: {now()} fetching bookmarks ({reason})", flush=True)
    write_status(state="running", reason=reason, started=now(), new_files=0)
    new = 0
    errors = []
    proc = subprocess.Popen(CMD, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in proc.stdout:
        if line.startswith("/data/bookmarks/"):
            new += 1
            if new % 10 == 0:
                write_status(new_files=new)
        elif "[error]" in line:
            errors.append(line.strip())
            print(line, end="", flush=True)
    code = proc.wait()
    result = "ok" if code == 0 else ("partial" if new else "failed")
    write_status(state="idle", finished=now(), result=result, new_files=new,
                 error=" | ".join(errors[-3:])[:500] if errors or code else None)
    print(f"sync: {now()} done: {new} new files, {result}"
          + ("" if code == 0 else " (expired cookies or X changed? try updating GALLERY_DL_VERSION)"), flush=True)


SYNC.mkdir(parents=True, exist_ok=True)
TRIGGER.unlink(missing_ok=True)
while True:
    scan("scheduled")
    next_at = time.time() + INTERVAL
    write_status(next_scan=dt.datetime.fromtimestamp(next_at).astimezone().isoformat(timespec="seconds"))
    while time.time() < next_at:
        if TRIGGER.exists():
            TRIGGER.unlink(missing_ok=True)
            scan("manual")
        time.sleep(5)
