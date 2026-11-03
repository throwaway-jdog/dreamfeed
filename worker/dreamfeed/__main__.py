"""
python -m dreamfeed run       Scheduler (container default). Every SCAN_SECONDS: runs requests
                              from the dashboard, and inside GENERATE_WINDOW tonight's persona
                              posts if they haven't finished. Each job runs in a child process, so the
                              GPU is only held while there is work (the miner's gpu-yield
                              pauses mining whenever any process holds it).
python -m dreamfeed generate  Tonight's run, if inside GENERATE_WINDOW.
    --now                     Run a test batch right away instead (night "test-<time>").
    --images N --keep K       Override IMAGES_PER_NIGHT / FEED_KEEP_TOP for this run.
    --persona HANDLE          Only these personas (repeatable).
python -m dreamfeed job ID    Run a request queued from the dashboard (posts or clips).
python -m dreamfeed lora-prep NAME --medium M --trigger W
                              Check and caption data/lora/NAME/raw for style-LoRA training.
python -m dreamfeed report    Per-persona posts, likes and drops, and recent runs.
"""
import argparse
import datetime as dt
import subprocess
import sys
import time

from .config import Config


def child(*args: str) -> None:
    code = subprocess.run([sys.executable, "-m", "dreamfeed", *args]).returncode
    if code:
        print(f"dreamfeed: {args[0]} failed (exit {code}), retrying next scan", flush=True)


TRAINING_STALE = 8 * 3600   # a lock older than this is left over from a crashed trainer


def training(cfg: Config) -> bool:
    """The trainer container holds the GPU; generation and dashboard requests wait."""
    lock = cfg.data_dir / "lora" / ".training"
    try:
        return time.time() - lock.stat().st_mtime < TRAINING_STALE
    except OSError:
        return False


def main() -> None:
    cmd, rest = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("run", [])
    if cmd == "run":
        from .generate import due_night, next_job, recover
        cfg = Config()
        cfg.generation()   # fail at start, not at 1am, if generation settings are missing
        recover(cfg)
        print("dreamfeed: waiting for the nightly window and dashboard requests", flush=True)
        while True:
            if not training(cfg):
                if due_night(cfg):
                    child("generate")
                job = next_job(cfg)
                if job:
                    child("job", str(job))
            time.sleep(cfg.scan_seconds)
    elif cmd == "generate":
        ap = argparse.ArgumentParser(prog="dreamfeed generate")
        ap.add_argument("--now", action="store_true")
        ap.add_argument("--images", type=int)
        ap.add_argument("--keep", type=int)
        ap.add_argument("--persona", action="append")
        args = ap.parse_args(rest)
        from .generate import run
        night = f"test-{dt.datetime.now():%Y%m%d-%H%M}" if args.now else None
        run(Config(), night=night, images=args.images, keep=args.keep, ignore_window=args.now, handles=args.persona)
    elif cmd == "job":
        from .generate import run_job
        run_job(Config(), int(rest[0]))
    elif cmd == "lora-prep":
        from .lora import main as lora_prep
        lora_prep(rest)
    elif cmd == "report":
        from .report import main as report
        report(rest)
    else:
        sys.exit(__doc__)


main()
