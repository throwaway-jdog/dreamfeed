"""Long clips: Wan makes ~5 seconds at a time, so a longer clip is a chain of pieces, each
starting from the last frame of the one before, with its own motion description.

Every piece is checked (the same checks as clips) before its last frame is used for the next
one; a piece that fails drops the whole clip. Each piece's colours are matched to the source
picture's, so small shifts don't add up over the chain. The pieces are joined into one file,
without the repeated first frame of each.
"""
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from .comfy import WAN

PIECE_SECONDS = 5
LENGTHS = (5, 15, 30, 60)       # what the viewer can ask for
STD_RANGE = (0.8, 1.25)        # how far the colour match may stretch contrast


class Dropped(Exception):
    """A piece failed a check (args: reason, detail) or the request was cancelled."""


def pieces_for(seconds: int) -> int:
    return max(1, -(-int(seconds) // PIECE_SECONDS))


def _size(path: Path) -> tuple[int, int]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, timeout=60).stdout.strip().split(",")
    return int(out[0]), int(out[1])


def _frames(path: Path) -> np.ndarray:
    w, h = _size(path)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, timeout=300, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)


def _match_colors(frames: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """Per-channel mean and contrast of the whole piece, moved to the source picture's."""
    f = frames.astype(np.float32)
    m, s = f.mean(axis=(0, 1, 2)), f.std(axis=(0, 1, 2)) + 1e-3
    rm, rs = ref.mean(axis=(0, 1)), ref.std(axis=(0, 1)) + 1e-3
    scale = np.clip(rs / s, *STD_RANGE)
    return np.clip((f - m) * scale + rm, 0, 255).astype(np.uint8)


def _sample(frames: np.ndarray, count: int) -> list[Image.Image]:
    idx = [int(len(frames) * (i + 0.5) / count) for i in range(count)]
    return [Image.fromarray(frames[i]) for i in idx]


def make(comfy, check, image: Path, medium: str, prompts: list[str], seeds: list[int], subdir: str,
         name: str, out: Path, strict: bool, loras, check_frames: int, progress=None,
         cancelled=lambda: False) -> Path:
    """Make len(prompts) pieces and join them into out. check(frames) returns a drop reason or
    None. Raises Dropped when a piece fails or the request is cancelled."""
    start = image
    first_frame = out.with_suffix(".start.png")
    writer = None
    try:
        for i, (prompt, seed) in enumerate(zip(prompts, seeds)):
            if cancelled():
                raise Dropped("cancelled", f"after {i} of {len(prompts)} pieces")
            try:
                path = comfy.img2vid("wan", start, medium, prompt, seed, subdir, f"{name}-p{i:02d}",
                                     strict=strict, loras=loras)
            finally:
                comfy.stop()   # fresh ComfyUI per piece, so Wan's models don't pile up in RAM
            frames = _frames(path)
            path.unlink(missing_ok=True)
            h, w = frames.shape[1:3]
            if i == 0:
                with Image.open(image) as src:
                    ref = np.asarray(src.convert("RGB").resize((w, h), Image.LANCZOS))
            frames = _match_colors(frames, ref)
            reason = check(_sample(frames, check_frames))
            if reason:
                raise Dropped(reason[0], f"piece {i + 1}: {reason[1]}")
            if writer is None:
                writer = subprocess.Popen(
                    ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                     "-r", str(WAN["fps"]), "-i", "-", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                     "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)
            writer.stdin.write((frames if i == 0 else frames[1:]).tobytes())   # frame 0 repeats the last one
            Image.fromarray(frames[-1]).save(first_frame)
            start = first_frame
            if progress:
                progress(i + 1, len(prompts))
        writer.stdin.close()
        if writer.wait() != 0:
            raise RuntimeError("ffmpeg couldn't join the pieces")
        writer = None
        return out
    except BaseException:
        if writer:
            writer.kill()
            writer.wait()
        out.unlink(missing_ok=True)
        raise
    finally:
        first_frame.unlink(missing_ok=True)
