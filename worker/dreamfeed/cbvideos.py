"""Your own videos of the Chaturbate rooms you follow, from a folder you keep (CB_VIDEOS,
mounted read-only; CB_VIDEOS_DIR in .env): each room's under a folder named after it
(<folder>/<room>/..., subfolders too), or loose in the folder with a name starting with the
room's ("<room>_2026-11-10.mp4"; the longest room name that fits wins). The Live tab lists
them on the room's profile and plays them; dreamfeed never writes there.

The follow service makes each one a poster (a frame from 10% in) and reads its length, kept in
data/generated/follow/videos/ (left out of the backup) and redone when a file changes.
Standard library only: the web app uses it too. These are real people: nothing here goes to
training, styles, comics or generation.
"""
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

EXTS = (".mp4", ".m4v", ".mov", ".webm", ".mkv")
ROOM = re.compile(r"^[a-z0-9_]{1,64}$")
MAX_POSTERS = 30          # made per round of the follow service (the rest next time)


def root() -> Path | None:
    """The videos folder, or None when it isn't set up (no CB_VIDEOS)."""
    value = os.environ.get("CB_VIDEOS", "").strip()
    return Path(value) if value and Path(value).is_dir() else None


def posters(data: Path) -> Path:
    return data / "generated" / "follow" / "videos"


def _videos(folder: Path):
    for p in folder.rglob("*"):
        if p.suffix.lower() in EXTS and not any(part.startswith(".") for part in p.relative_to(folder).parts) and p.is_file():
            yield p


def scan(rooms) -> dict[str, list[dict]]:
    """{room: [{"path" (relative to the folder), "size", "mtime"}, ...] newest first} for the rooms
    given (the ones you follow); other files are left out."""
    base, rooms = root(), {r.lower() for r in rooms if ROOM.match(r.lower())}
    out: dict[str, list[dict]] = {}
    if not base:
        return out
    by_length = sorted(rooms, key=len, reverse=True)
    for entry in sorted(base.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            name = entry.name.lower()
            files = list(_videos(entry)) if name in rooms else []
        elif entry.is_file() and entry.suffix.lower() in EXTS:
            low = entry.name.lower()
            name = next((r for r in by_length if low.startswith(r) and not low[len(r):len(r) + 1].isalnum()), None)
            files = [entry] if name else []
        else:
            continue
        for p in files:
            st = p.stat()
            out.setdefault(name, []).append({"path": p.relative_to(base).as_posix(), "size": st.st_size, "mtime": int(st.st_mtime)})
    for vids in out.values():
        vids.sort(key=lambda v: (-v["mtime"], v["path"]))
    return out


def key(v: dict) -> str:
    """The poster's name: changes when the file does."""
    return hashlib.sha1(f"{v['path']}\0{v['size']}\0{v['mtime']}".encode()).hexdigest()[:20]


def _owner(rel: str, rooms) -> str | None:
    """Whose video rel is, by the same rules as scan."""
    parts = rel.split("/")
    if any(not p or p.startswith(".") for p in parts):
        return None
    rooms = {r.lower() for r in rooms}
    if len(parts) > 1:
        return parts[0].lower() if parts[0].lower() in rooms else None
    low = parts[0].lower()
    return next((r for r in sorted(rooms, key=len, reverse=True)
                 if low.startswith(r) and not low[len(r):len(r) + 1].isalnum()), None)


def file(room: str, rel: str, rooms) -> Path | None:
    """The video at rel (a path from scan) if it's room's (rooms: everyone you follow), else None."""
    base = root()
    if not base or not ROOM.match(room) or _owner(rel, rooms) != room:
        return None
    path = (base / rel).resolve()
    if not path.is_relative_to(base.resolve()) or not path.is_file() or path.suffix.lower() not in EXTS:
        return None
    return path


def make_posters(data: Path, rooms) -> str:
    """The follow service's part: posters and lengths for new videos, old ones removed."""
    base, out = root(), posters(data)
    if not base:
        return ""
    found = scan(rooms)
    want = {key(v): v for vids in found.values() for v in vids}
    out.mkdir(parents=True, exist_ok=True)
    index_file = out / "index.json"
    try:
        index = json.loads(index_file.read_text())
    except (OSError, ValueError):
        index = {}
    made = 0
    for k, v in want.items():
        if k in index or made >= MAX_POSTERS:
            continue
        src = base / v["path"]
        try:
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(src)],
                                   capture_output=True, text=True, timeout=60)
            seconds = float(probe.stdout.strip() or 0)
        except (subprocess.TimeoutExpired, ValueError, OSError):
            seconds = 0.0
        tmp = out / f".{k}.jpg"
        try:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{seconds * 0.1:.1f}", "-i", str(src), "-frames:v", "1",
                            "-vf", "scale=480:-2", "-q:v", "4", str(tmp)], capture_output=True, timeout=120)
        except (subprocess.TimeoutExpired, OSError):
            pass
        if tmp.is_file() and tmp.stat().st_size:
            tmp.replace(out / f"{k}.jpg")
        index[k] = {"duration": round(seconds), "poster": (out / f"{k}.jpg").is_file()}
        made += 1
    for k in [k for k in index if k not in want]:
        index.pop(k)
        (out / f"{k}.jpg").unlink(missing_ok=True)
    tmp = index_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(index))
    tmp.replace(index_file)
    total = len(want)
    return f"{total} video{'s' if total != 1 else ''}" if total else ""
