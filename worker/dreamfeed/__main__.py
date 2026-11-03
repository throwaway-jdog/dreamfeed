"""
python -m dreamfeed run      Scheduler (container default). Checks for new bookmarks every
                             SCAN_SECONDS and tags them in a child process, so the GPU is
                             only held while there is work (the miner's gpu-yield pauses
                             mining whenever any process holds it).
python -m dreamfeed tag      Tag whatever is waiting, then exit.
python -m dreamfeed report   Profile summary: mediums, dropped counts, top tags.
"""
import subprocess
import sys
import time

from .config import Config


def main() -> None:
    cmd, rest = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("run", [])
    if cmd == "run":
        from . import media
        cfg = Config()
        cfg.bookmarks_dir.mkdir(parents=True, exist_ok=True)
        print(f"dreamfeed: watching {cfg.bookmarks_dir}", flush=True)
        while True:
            if media.ready_files(cfg.bookmarks_dir):
                code = subprocess.run([sys.executable, "-m", "dreamfeed", "tag"]).returncode
                if code:
                    print(f"dreamfeed: tag run failed (exit {code}), retrying next scan", flush=True)
            time.sleep(cfg.scan_seconds)
    elif cmd == "tag":
        from .tagging import run_once
        run_once(Config())
    elif cmd == "report":
        from .report import main as report
        report(rest)
    else:
        sys.exit(__doc__)


main()
