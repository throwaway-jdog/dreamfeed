"""Long clips, made the way an animator works: key poses first, then the motion between them.

1. Key poses: the post's own picture, then one new pose per 5 seconds: the same picture
   redrawn by the persona's own model and style (img2img, so the character, outfit and
   scene stay) with the expression and pose of that point in the clip. Each key goes
   through the image checks and must still show the same act; of the candidates that pass,
   the one closest to the original picture is used. The clip ends on the original picture,
   so it loops cleanly in the feed.
2. Motion: Wan animates each 5-second piece from one key to the next (first and last frame
   both fixed), with its own motion description. Each piece also starts from the last few
   frames of the piece before, so motion carries on across the join.

Every piece starts and ends on a clean, checked picture, so details and colours can't drift
over the clip. Every piece is also checked itself; a failing piece is made again (with a new
seed), and after PIECE_TRIES failures the whole clip is dropped.
"""
import random
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from .comfy import WAN

PIECE_SECONDS = 5
LENGTHS = (5, 15, 30, 60)       # what the viewer can ask for
PIECE_TRIES = 3                # a piece that fails a check is made again
CONTEXT = 5                    # frames carried into the next piece (1 + 4k, Wan's latent steps)
KEY_CANDIDATES = 2             # img2img tries per key pose
KEY_DENOISE = 0.5              # how much of the picture a key pose redraws


class Dropped(Exception):
    """A piece failed a check (args: reason, detail) or the request was cancelled."""


def pieces_for(seconds: int) -> int:
    return max(1, -(-int(seconds) // PIECE_SECONDS))


def keyframes(variant, judge, source: Path, n: int, rng: random.Random) -> list[Path]:
    """n + 1 key poses for n pieces: the source, n - 1 new ones, the source again.
    variant(i, seed) makes a candidate for key i; judge(paths) returns, per path, its
    similarity to the source, or None if it failed a check. A key with no passing
    candidate is the source picture again."""
    cands = {i: [variant(i, rng.randrange(2 ** 32)) for _ in range(KEY_CANDIDATES)] for i in range(1, n)}
    verdict = judge([p for ps in cands.values() for p in ps])
    keys = [source]
    for i in range(1, n):
        ok = [(verdict[p], str(p)) for p in cands[i] if verdict.get(p) is not None]
        keys.append(Path(max(ok)[1]) if ok else source)
    return keys + [source]


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


def _sample(frames: np.ndarray, count: int) -> list[Image.Image]:
    idx = [int(len(frames) * (i + 0.5) / count) for i in range(count)]
    return [Image.fromarray(frames[i]) for i in idx]


def make(comfy, check, keys: list[Path], medium: str, prompts: list[str], seeds: list[int], subdir: str,
         name: str, out: Path, strict: bool, loras, check_frames: int, progress=None,
         cancelled=lambda: False) -> Path:
    """Animate len(prompts) pieces, piece i from keys[i] to keys[i + 1], and join them into out.
    check(frames) returns a drop reason or None. Raises Dropped when a piece fails every try
    or the request is cancelled."""
    ctx = [out.with_name(f"{out.stem}-ctx{k}.png") for k in range(CONTEXT)]
    starts = [keys[0]]
    writer = None
    try:
        for i, (prompt, seed) in enumerate(zip(prompts, seeds)):
            if cancelled():
                raise Dropped("cancelled", f"after {i} of {len(prompts)} pieces")
            for attempt in range(PIECE_TRIES):   # a failing piece is thrown away and made again
                try:
                    path = comfy.img2vid("wan", keys[i], medium, prompt, (seed + attempt * 7919) % 2 ** 32,
                                         subdir, f"{name}-p{i:02d}", strict=strict, loras=loras,
                                         end=keys[i + 1], start_frames=starts)
                finally:
                    comfy.stop()   # fresh ComfyUI per piece, so Wan's models don't pile up in RAM
                frames = _frames(path)
                path.unlink(missing_ok=True)
                reason = check(_sample(frames, check_frames))
                if not reason:
                    break
                print(f"longclip: piece {i + 1} try {attempt + 1} dropped ({reason[0]}: {reason[1]})", flush=True)
            else:
                raise Dropped(reason[0], f"piece {i + 1}, {PIECE_TRIES} tries: {reason[1]}")
            if writer is None:
                h, w = frames.shape[1:3]
                writer = subprocess.Popen(
                    ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                     "-r", str(WAN["fps"]), "-i", "-", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                     "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)
            # The first frames repeat the ones carried over from the piece before.
            writer.stdin.write(frames[len(starts) if i else 0:].tobytes())
            for k, f in enumerate(frames[-CONTEXT:]):
                Image.fromarray(f).save(ctx[k])
            starts = ctx
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
        for f in ctx:
            f.unlink(missing_ok=True)
