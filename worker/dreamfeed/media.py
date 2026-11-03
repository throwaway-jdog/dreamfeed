import io
import re
import subprocess
import time
from pathlib import Path

from PIL import Image

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".m4v"}
FRAME_MAX_SIDE = 1280   # frames are shrunk to this, plenty for tagging and age estimates


def frame_count(duration: float) -> int:
    """How many frames to sample from a video. Every frame goes through the age checks.
    Under 4 min: one per 10 s (at least 3). 4-10 min: 24, spread out. 10 min and longer:
    one per 25 s, no cap."""
    if duration >= 600:
        return round(duration / 25)
    return max(3, min(24, round(duration / 10)))


def frame_times(duration: float) -> list[float]:
    """Evenly spaced, centred in equal slices, so the very start and end are skipped."""
    n = frame_count(duration)
    return [duration * (i + 0.5) / n for i in range(n)]


class Unreadable(Exception):
    pass


def ready_files(folder: Path, min_age: float = 30) -> list[Path]:
    """Finished downloads (gallery-dl moves them in from .part when complete)."""
    if not folder.is_dir():
        return []
    now = time.time()
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXT | VIDEO_EXT
        and now - p.stat().st_mtime >= min_age
    )


def tweet_id(path: Path) -> str | None:
    m = re.match(r"(\d+)_\d+$", path.stem)
    return m.group(1) if m else None


def kind(path: Path) -> str:
    return "video" if path.suffix.lower() in VIDEO_EXT else "image"


def _rgb(img: Image.Image) -> Image.Image:
    img.load()
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.getchannel("A"))
        return bg
    return img.convert("RGB")


def load_frames(path: Path) -> list[Image.Image]:
    try:
        if kind(path) == "image":
            with Image.open(path) as img:
                return [_rgb(img)]
        return _video_frames(path)
    except Unreadable:
        raise
    except Exception as e:
        raise Unreadable(str(e)) from e


def _video_frames(path: Path) -> list[Image.Image]:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    try:
        duration = float(probe.stdout.strip())
    except ValueError:
        raise Unreadable(f"no duration: {probe.stderr.strip()[:200]}")
    frames = []
    scale = (f"scale='if(gt(iw,ih),min({FRAME_MAX_SIDE},iw),-2)':'if(gt(iw,ih),-2,min({FRAME_MAX_SIDE},ih))'")
    for at in frame_times(duration):
        out = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{at:.2f}", "-i", str(path), "-vf", scale,
             "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
            capture_output=True, timeout=120,
        )
        if out.returncode == 0 and out.stdout:
            frames.append(_rgb(Image.open(io.BytesIO(out.stdout))))
    if not frames:
        raise Unreadable("no frames decoded")
    return frames
