"""Trainer service: waits for training requests from the worker's style jobs and runs them.

The worker writes data/lora/NAME/train-request.json ({"base": checkpoint, "steps": N}); this
runs train.sh for it, reports progress in data/lora/NAME/status.json (phase "training", then
"trained" or "train-failed"), and stops early if data/lora/NAME/cancel appears. Idle, it holds
no GPU memory.

With arguments it runs one training directly, as before:
    docker compose run --rm trainer NAME BASE_CHECKPOINT [STEPS]
"""
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

LORA = Path("/data/lora")
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


def train(base: Path, req: dict) -> None:
    name, steps = base.name, int(req["steps"])
    print(f"trainer: {name} on {req['base']}, {steps} steps", flush=True)
    status(base, phase="training", done=0, total=steps, message=None)
    proc = subprocess.Popen(["bash", "/train.sh", name, req["base"], str(steps)], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, start_new_session=True)
    tail, buf, last, stopping = [], b"", 0.0, False
    while True:
        chunk = proc.stdout.read1(4096)
        if not chunk:
            break
        buf += chunk
        *parts, buf = re.split(rb"[\r\n]", buf)
        for part in parts:
            m = STEP.search(part)
            if m and time.time() - last > 5:
                status(base, done=int(m.group(1)), total=int(m.group(2)))
                last = time.time()
            elif part.strip() and not m:
                tail = (tail + [part.decode(errors="replace").strip()])[-20:]
                print(tail[-1], flush=True)
        if not stopping and (base / "cancel").exists():
            stopping = True
            os.killpg(proc.pid, signal.SIGTERM)
    code = proc.wait()
    for old in Path("/models/loras").glob(f"style-{name}-step*.safetensors"):   # keep only the final file
        old.unlink(missing_ok=True)
    if (base / "cancel").exists():
        status(base, phase="cancelled", message="cancelled")
    elif code:
        err = next((t for t in reversed(tail) if "Error" in t or "error" in t), tail[-1] if tail else "")
        status(base, phase="train-failed", message=f"training failed (exit {code}): {err}"[:300])
    else:
        status(base, phase="trained", done=steps, total=steps)
    print(f"trainer: {name} finished with exit {code}", flush=True)


def main() -> None:
    if len(sys.argv) > 1:
        os.execv("/bin/bash", ["bash", "/train.sh", *sys.argv[1:]])
    print("trainer: waiting for training requests", flush=True)
    while True:
        for req_file in sorted(LORA.glob("*/train-request.json")):
            base = req_file.parent
            try:
                req = json.loads(req_file.read_text())
            except (OSError, ValueError):
                continue
            req_file.unlink(missing_ok=True)
            try:
                train(base, req)
            except Exception as e:
                status(base, phase="train-failed", message=f"trainer error: {e}"[:300])
        time.sleep(LOOP_SECONDS)


main()
