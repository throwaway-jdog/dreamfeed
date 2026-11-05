"""Video-trainer service: waits for video-LoRA requests from the worker and runs them.

The worker's "video_style" job (from the dashboard) prepares data/lora/NAME/video_dataset, then
writes data/lora/NAME/video-train-request.json ({"steps": N}). This trains both halves of
Wan 2.2 with train.sh (high, then low), reports progress in data/lora/NAME/status.json
(video_phase "training-high", "training-low", then "trained" or "train-failed"), and stops
early if data/lora/NAME/video-cancel appears. Idle, it holds no GPU memory.

With arguments it runs train.sh directly, as before:
    docker compose run --rm video-trainer NAME high|low|both [STEPS]
"""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

LORA = Path("/data/lora")
LOCK = LORA / ".training"      # holds the worker's generation while this trains
LOOP_SECONDS = 5
STEP = re.compile(rb"steps:\s+\d+%.*?(\d+)/(\d+)")


def status(base: Path, **fields) -> None:
    path = base / "status.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        data = {}
    data.update(fields, updated=int(time.time()))
    tmp = path.with_name("status.json.tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)


def half(base: Path, part: str, steps: int) -> tuple[int, list[str]]:
    """Train one half; (exit code, last lines of output)."""
    status(base, video_phase=f"training-{part}", video_done=0, video_total=steps, video_message=None)
    proc = subprocess.Popen(["sh", "/train.sh", base.name, part, str(steps)], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, start_new_session=True,
                            env=os.environ | {"VIDEO_TRAIN_HOLDING": "1"})
    tail, buf, last = [], b"", 0.0
    while True:
        chunk = proc.stdout.read1(4096)
        if not chunk:
            break
        buf += chunk
        *parts, buf = re.split(rb"[\r\n]", buf)
        for line in parts:
            m = STEP.search(line)
            if m and time.time() - last > 5:
                status(base, video_done=int(m.group(1)), video_total=int(m.group(2)))
                LOCK.touch()   # the worker treats a lock older than 8 hours as stale
                last = time.time()
            elif line.strip() and not m:
                tail = (tail + [line.decode(errors="replace").strip()])[-20:]
                print(tail[-1], flush=True)
        if (base / "video-cancel").exists():
            os.killpg(proc.pid, signal.SIGTERM)
            break
    return proc.wait(), tail


def train(base: Path, req: dict) -> None:
    name, steps = base.name, int(req["steps"])
    print(f"video-trainer: {name}, {steps} steps per half", flush=True)
    LOCK.write_text(f"video-{name} {int(time.time())}\n")
    try:
        for part in ("high", "low"):
            code, tail = half(base, part, steps)
            if (base / "video-cancel").exists():
                status(base, video_phase="cancelled", video_message="cancelled")
                return
            if code:
                err = next((t for t in reversed(tail) if "rror" in t), tail[-1] if tail else "")
                status(base, video_phase="train-failed",
                       video_message=f"training the {part} half failed (exit {code}): {err}"[:300])
                return
        # Both halves are converted into models/loras; the rest is step checkpoints.
        shutil.rmtree(base / "video_out", ignore_errors=True)
        status(base, video_phase="trained", video_done=steps, video_total=steps)
        print(f"video-trainer: {name} done", flush=True)
    finally:
        LOCK.unlink(missing_ok=True)


def main() -> None:
    if len(sys.argv) > 1:
        os.execv("/bin/sh", ["sh", "/train.sh", *sys.argv[1:]])
    print("video-trainer: waiting for training requests", flush=True)
    while True:
        for req_file in sorted(LORA.glob("*/video-train-request.json")):
            base = req_file.parent
            try:
                req = json.loads(req_file.read_text())
            except (OSError, ValueError):
                continue
            req_file.unlink(missing_ok=True)
            try:
                train(base, req)
            except Exception as e:
                status(base, video_phase="train-failed", video_message=f"trainer error: {e}"[:300])
        time.sleep(LOOP_SECONDS)


main()
