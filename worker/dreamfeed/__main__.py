"""
python -m dreamfeed run       Scheduler (container default). Every SCAN_SECONDS: runs requests
                              from the dashboard (comics, panel animations, styles). The nightly
                              persona posts no longer run on their own (the feed is X and Reddit
                              now); `generate --now` still makes some. Each job runs in a child process, so the
                              GPU is only held while there is work (the miner's gpu-yield
                              pauses mining whenever any process holds it).
python -m dreamfeed generate  Tonight's run, if inside GENERATE_WINDOW.
    --now                     Run a test batch right away instead (night "test-<time>").
    --images N --keep K       Override IMAGES_PER_NIGHT / FEED_KEEP_TOP for this run.
    --persona HANDLE          Only these personas (repeatable).
python -m dreamfeed job ID    Run a request queued from the dashboard (posts or clips).
python -m dreamfeed lora-prep NAME --medium M --trigger W
                              Check and caption data/lora/NAME/raw for style-LoRA training.
python -m dreamfeed video-prep NAME [--limit N] [--no-download]
                              Download, check and caption a style's videos for a video LoRA.
python -m dreamfeed scene-preview POST_ID [--seed N]   plan a scene's shots and draw them (no video)
python -m dreamfeed character-prep NAME --from STYLE --look TAGS [--traits TAGS] [--train STEPS]
                              A character LoRA from a style's pictures of one character.
python -m dreamfeed comic HANDLE (HANDLE|partner) --story TEXT [--pages N]
                              A comic about two characters: script, panels, speech bubbles
                              (the dashboard's Comics page queues the same).
python -m dreamfeed bootstrap PERSONA [--count N] [--keep N]
                              Pictures of a persona's own character (no art yet) to train a
                              character LoRA on.
python -m dreamfeed speech NAME
                              A trained style's character voice, from its speech bubbles.
python -m dreamfeed report    Per-persona posts, likes and drops, and recent runs.
python -m dreamfeed follow    Who you follow on Chaturbate, live or not (the follow service).
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
        from .generate import next_job, recover
        cfg = Config()
        cfg.generation()   # fail at start, not at 1am, if generation settings are missing
        recover(cfg)
        print("dreamfeed: waiting for dashboard requests", flush=True)
        from .comicimport import due_update
        while True:
            if not training(cfg):
                due_update(cfg)          # once a day: new pages of imported comics
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
    elif cmd == "character-prep":
        from .character import main as character_prep
        character_prep(rest)
    elif cmd == "speech":
        from .speech import main as speech
        speech(rest)
    elif cmd == "comic":
        from .comic import main as comic
        comic(rest)
    elif cmd == "comic-panels":
        from .comicanim import main as comic_panels
        comic_panels(rest)
    elif cmd == "bootstrap":
        from .bootstrap import main as bootstrap
        bootstrap(rest)
    elif cmd == "video-prep":
        from .videolora import main as video_prep
        video_prep(rest)
    elif cmd == "scene-preview":
        from .scene import preview
        preview(rest)
    elif cmd == "scene-render":
        from .scene import render_preview
        render_preview(rest)
    elif cmd == "follow":
        from .follow import main as follow
        follow(rest)
    elif cmd == "report":
        from .report import main as report
        report(rest)
    else:
        sys.exit(__doc__)


main()
