"""Your own videos of the Chaturbate rooms you follow, from a folder you keep (CB_VIDEOS,
mounted read-only; CB_VIDEOS_DIR in .env): each room's under a folder named after it
(<folder>/<room>/..., subfolders too; "<room> [CB]/" as recorders name it works too), or loose
in the folder with a name starting with the room's ("<room>_2026-11-10.mp4"). Either way the
longest room name that fits wins. The Live tab lists
them on the room's profile and plays them. dreamfeed writes there only when you ask it to:
- highlights (cbhighlights.py) go in the room's folder, under highlights/ (made if needed);
- a video you delete is moved to .trash/ there first (Undo puts it back) and is gone for good
  after TRASH_DAYS (the follow service empties it).

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
HIGHLIGHTS = ".highlights.mp4"
TRASH = ".trash"
TRASH_DAYS = 7


def root() -> Path | None:
    """The videos folder, or None when it isn't set up (no CB_VIDEOS)."""
    value = os.environ.get("CB_VIDEOS", "").strip()
    return Path(value) if value and Path(value).is_dir() else None


def posters(data: Path) -> Path:
    return data / "generated" / "follow" / "videos"


def _room_of(name: str, rooms) -> str | None:
    """The room a folder or file name is of: the longest of rooms it starts with, followed by
    nothing or by something that isn't a letter or digit ("room", "room [CB]", "room_2026...")."""
    low = name.lower()
    return next((r for r in sorted(rooms, key=len, reverse=True)
                 if low.startswith(r) and not low[len(r):len(r) + 1].isalnum()), None)


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
    for entry in sorted(base.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            name = _room_of(entry.name, rooms)
            files = list(_videos(entry)) if name else []
        elif entry.is_file() and entry.suffix.lower() in EXTS:
            name = _room_of(entry.name, rooms)
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
    return _room_of(parts[0], {r.lower() for r in rooms})


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


def is_highlight(rel: str) -> bool:
    return rel.lower().endswith(HIGHLIGHTS)


def room_folder(room: str) -> Path:
    """The room's folder (an existing one, "room" or "room [CB]", else <room>, made when written to)."""
    base = root()
    dirs = [e for e in sorted(base.iterdir()) if e.is_dir() and not e.name.startswith(".") and _room_of(e.name, {room})]
    return next((e for e in dirs if e.name.lower() == room), dirs[0] if dirs else base / room)


def highlight_of(rel: str, room: str) -> str:
    """Where the highlights of the video at rel go (relative to the folder)."""
    stem = Path(rel).stem
    tag = hashlib.sha1(rel.encode()).hexdigest()[:6]
    return (room_folder(room) / "highlights" / f"{stem} [{tag}]{HIGHLIGHTS}").relative_to(root()).as_posix()


def trash(path: Path) -> str:
    """Moves a video (and nothing else) to the trash; returns the token that puts it back."""
    import time
    base = root()
    rel = path.relative_to(base).as_posix()
    token = time.strftime("%Y%m%d-%H%M%S") + "-" + hashlib.sha1(rel.encode()).hexdigest()[:8]
    dest = base / TRASH / token / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    path.rename(dest)
    return token


def restore(token: str) -> str:
    """Puts a deleted video back where it was; returns its path."""
    if not re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{8}", token):
        raise ValueError("bad token")
    base = root()
    folder = base / TRASH / token
    files = [p for p in folder.rglob("*") if p.is_file()] if folder.is_dir() else []
    if len(files) != 1:
        raise LookupError("that video is gone from the trash")
    rel = files[0].relative_to(folder)
    dest = base / rel
    if dest.exists():
        raise LookupError("a video is already there")
    dest.parent.mkdir(parents=True, exist_ok=True)
    files[0].rename(dest)
    for d in sorted((p for p in folder.rglob("*") if p.is_dir()), reverse=True):
        d.rmdir()
    folder.rmdir()
    return rel.as_posix()


def empty_trash() -> int:
    """Deletes what's been in the trash over TRASH_DAYS; returns how many videos."""
    import shutil
    import time
    base = root()
    folder = base / TRASH if base else None
    if not folder or not folder.is_dir():
        return 0
    gone = 0
    for d in folder.iterdir():
        try:
            at = time.mktime(time.strptime(d.name[:15], "%Y%m%d-%H%M%S"))
        except ValueError:
            continue
        if d.is_dir() and time.time() - at > TRASH_DAYS * 86400:
            gone += sum(1 for p in d.rglob("*") if p.is_file())
            shutil.rmtree(d)
    return gone
