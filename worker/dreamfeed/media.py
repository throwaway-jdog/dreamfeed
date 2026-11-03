import io
import re
import subprocess
import time
from pathlib import Path

from PIL import Image

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".m4v"}
VIDEO_FRAMES = (0.2, 0.5, 0.8)   # positions in the clip to sample


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
    for pos in VIDEO_FRAMES:
        out = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{duration * pos:.2f}", "-i", str(path),
             "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
            capture_output=True, timeout=120,
        )
        if out.returncode == 0 and out.stdout:
            frames.append(_rgb(Image.open(io.BytesIO(out.stdout))))
    if not frames:
        raise Unreadable("no frames decoded")
    return frames
