"""
python -m dreamfeed run       Scheduler (container default). Every SCAN_SECONDS: tags new
                              bookmarks, and inside GENERATE_WINDOW runs tonight's generation
                              if it hasn't finished. Each job runs in a child process, so the
                              GPU is only held while there is work (the miner's gpu-yield
                              pauses mining whenever any process holds it).
python -m dreamfeed tag       Tag whatever is waiting, then exit.
python -m dreamfeed generate  Tonight's run, if inside GENERATE_WINDOW.
    --now                     Run a test batch right away instead (night "test-<time>").
    --images N --keep K       Override IMAGES_PER_NIGHT / FEED_KEEP_TOP for this run.
python -m dreamfeed report    Profile summary: mediums, dropped counts, top tags, recent runs.
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


def main() -> None:
    cmd, rest = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("run", [])
    if cmd == "run":
        from . import media
        from .generate import due_night
        cfg = Config()
        cfg.generation()   # fail at start, not at 1am, if generation settings are missing
        cfg.bookmarks_dir.mkdir(parents=True, exist_ok=True)
        print(f"dreamfeed: watching {cfg.bookmarks_dir}", flush=True)
        while True:
            if media.ready_files(cfg.bookmarks_dir):
                child("tag")
            if due_night(cfg):
                child("generate")
            time.sleep(cfg.scan_seconds)
    elif cmd == "tag":
        from .tagging import run_once
        run_once(Config())
    elif cmd == "generate":
        ap = argparse.ArgumentParser(prog="dreamfeed generate")
        ap.add_argument("--now", action="store_true")
        ap.add_argument("--images", type=int)
        ap.add_argument("--keep", type=int)
        args = ap.parse_args(rest)
        from .generate import run
        night = f"test-{dt.datetime.now():%Y%m%d-%H%M}" if args.now else None
        run(Config(), night=night, images=args.images, keep=args.keep, ignore_window=args.now)
    elif cmd == "report":
        from .report import main as report
        report(rest)
    else:
        sys.exit(__doc__)


main()
