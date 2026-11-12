"""Prepare a video-LoRA training set (Wan 2.2 I2V) from an artist's animations.

    python -m dreamfeed video-prep NAME [--limit N]

Uses the style's source page and medium (data/lora/NAME/source.json) and:
1. download: gallery-dl fetches up to LIMIT of the artist's videos into data/lora/NAME/video_raw
2. check:    VIDEO_CHECK_FRAMES or more frames from each clip go through the same checks as
             style training images (photos, adults-only at the strict threshold, feral,
             blocked tags); a tag or youth score in any one frame drops the whole clip, and
             the file is deleted
3. convert:  clips that pass are re-encoded to Wan's 16 fps at VIDEO_MAX_SIDE into
             data/lora/NAME/video_dataset, with a caption: the trigger word plus a written
             description of what moves (the same text model and checks as clip prompts)
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

from . import motion
from ..core.config import Config
from .lora import TAG_MIN, write_status

VIDEO_FILTER = "extension in ('mp4', 'webm', 'mov', 'm4v')"
CHECK_FRAMES = 16        # per clip, at least; more for long clips (media.frame_count)
FPS = 16                 # Wan 2.2 14B's frame rate
VIDEO_MAX_SIDE = 640     # training buckets are smaller; this just keeps files small
MIN_SECONDS = 1.5        # shorter than this has no motion worth learning
MIN_CLIPS = 15


def trigger_for(name: str) -> str:
    return f"{name.replace('_', '')}_anim"


def download(base: Path, source: str, limit: int) -> int:
    from .styles import GALLERY_DL, COOKIE_HOSTS, x_cookies
    import tempfile
    raw = base / "video_raw"
    raw.mkdir(exist_ok=True)
    tw = dict(GALLERY_DL["extractor"]["twitter"], videos=True)
    conf = {"extractor": {"directory": [], "cookies-update": False, "twitter": tw,
                          "base-directory": str(raw), "archive": str(base / "video-archive.sqlite3")},
            "downloader": {"part-directory": str(raw / ".part")}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(conf, f)
    cmd = ["gallery-dl", "--config-ignore", "--config", f.name, "--range", f"1-{limit}",
           "--filter", VIDEO_FILTER]
    host = source.split("/")[2].lower() if source.count("/") >= 2 else ""
    if host.removeprefix("www.").removeprefix("mobile.") in COOKIE_HOSTS:
        if not x_cookies():
            raise RuntimeError("x.com needs your cookies: add them on the dashboard (Sign-ins)")
        cmd += ["--cookies", str(x_cookies())]
    write_status(base, video_phase="downloading")
    proc = subprocess.run(cmd + [source], capture_output=True, text=True)
    Path(f.name).unlink(missing_ok=True)
    have = sum(1 for p in raw.iterdir() if p.is_file())
    if proc.returncode and not have:
        raise RuntimeError("video download failed: " + proc.stdout.strip()[-300:])
    print(f"video-prep: {have} videos in {raw}", flush=True)
    return have


def _duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True, timeout=60)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def _convert(src: Path, dst: Path) -> bool:
    scale = (f"scale='if(gt(iw,ih),min({VIDEO_MAX_SIDE},iw),-2)':"
             f"'if(gt(iw,ih),-2,min({VIDEO_MAX_SIDE},ih))'")
    out = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", f"fps={FPS},{scale}",
                          "-an", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(dst)],
                         capture_output=True, timeout=600)
    return out.returncode == 0 and dst.is_file()


def check(cfg: Config, base: Path, medium: str) -> tuple[list[tuple[Path, list[str]]], dict]:
    """Clips that pass every check, with their tags. Failing clips are deleted."""
    from . import media
    from ..core.checks import problem
    from .vision import Vision
    files = sorted(p for p in (base / "video_raw").iterdir() if p.is_file() and media.kind(p) == "video")
    vision = Vision(cfg.models_dir)
    kept, dropped = [], {}
    try:
        for n, path in enumerate(files, 1):
            reason = None
            if _duration(path) < MIN_SECONDS:
                reason = ("too-short", "")
            else:
                try:
                    frames = media.load_frames(path, CHECK_FRAMES)
                except media.Unreadable as e:
                    frames, reason = None, ("unreadable", str(e))
                if frames:
                    a = vision.analyze(frames)
                    reason = problem(a, medium, frames, cfg, training=True)
                    tags = [t for t, s in sorted(a.general.items(), key=lambda kv: -kv[1]) if s >= TAG_MIN]
            if reason:
                dropped[reason[0]] = dropped.get(reason[0], 0) + 1
                path.unlink(missing_ok=True)
            else:
                kept.append((path, tags[:40]))
            if n % 5 == 0 or n == len(files):
                write_status(base, video_phase="checking", video_done=n, video_total=len(files))
                print(f"video-prep: checked {n}/{len(files)}, kept {len(kept)}, dropped {dropped}", flush=True)
    finally:
        vision.close()
    return kept, dropped


def prepare(cfg: Config, name: str, limit: int, download_first: bool = True) -> dict:
    base = cfg.data_dir / "lora" / name
    src = json.loads((base / "source.json").read_text())
    medium = src["medium"]
    if download_first:
        download(base, src["source"], limit)
    kept, dropped = check(cfg, base, medium)
    out = base / "video_dataset"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir()
    trigger = trigger_for(name)
    # Descriptions need the text model, which doesn't share the GPU with the checks: after them.
    write_status(base, video_phase="describing", video_done=0, video_total=len(kept))
    plans = motion.plan(cfg, list(enumerate(t for _, t in kept)))
    count = 0
    for i, (path, tags) in enumerate(kept):
        act, text = plans[i]
        # Without a written description: the act's, or the clip's own tags (more to learn from).
        desc = text or (act.motion if act else ", ".join(t.replace("_", " ") for t in tags[:20]) + ".")
        stem = f"{count:04d}"
        if not _convert(path, out / f"{stem}.mp4"):
            dropped["unconvertible"] = dropped.get("unconvertible", 0) + 1
            continue
        if not desc.endswith(".") and "." in desc:   # the text model can stop mid-sentence
            desc = desc[:desc.rfind(".") + 1]
        (out / f"{stem}.txt").write_text(f"{trigger}, {medium} animation. {desc}")
        count += 1
    stats = {"kept": count, "dropped": dropped, "trigger": trigger, "medium": medium}
    (base / "video-prep.json").write_text(json.dumps(stats))
    write_status(base, video_phase="prepared", video_kept=count)
    print(f"video-prep: {name} done {stats}", flush=True)
    return stats


def for_style(cfg: Config, style_file: str) -> tuple[str, str, str] | None:
    """A persona's style LoRA file (style-NAME.safetensors) -> its trained video LoRA as
    (high-noise file, low-noise file, trigger word), if both halves exist."""
    name = style_file.removeprefix("style-").removesuffix(".safetensors")
    files = tuple(f"video-{name}-{part}.safetensors" for part in ("high", "low"))
    if name == style_file or not all((cfg.models_dir / "loras" / f).is_file() for f in files):
        return None
    try:
        trigger = json.loads((cfg.data_dir / "lora" / name / "video-prep.json").read_text())["trigger"]
    except (OSError, ValueError, KeyError):
        trigger = trigger_for(name)
    return files[0], files[1], trigger


# ---- from the dashboard ---------------------------------------------------------------------

PICKUP_SECONDS = 120          # the video-trainer service checks for requests every few seconds
SECONDS_PER_STEP = 8          # per half, on a 12 GB GPU; only for the time limit
TRAIN_SLACK = 2 * 3600        # model loading and caching, twice


class Stopped(Exception):
    pass


def run_job(cfg: Config, conn, job_id: int, params: dict) -> None:
    """A "video_style" job: {"name", "limit", "steps"}. video-prep (download, check, describe)
    in a child process, so its GPU memory is freed; then a request for the video-trainer
    service, which trains both halves while this waits. data/lora/NAME/video-cancel stops it."""
    import time
    from .styles import free_gpu
    name, limit, steps = params["name"], int(params["limit"]), int(params["steps"])
    base = cfg.data_dir / "lora" / name
    (base / "video-cancel").unlink(missing_ok=True)
    with conn:
        conn.execute("UPDATE jobs SET status = 'running' WHERE id = ?", (job_id,))
    write_status(base, video_phase="downloading", video_done=0, video_total=0, video_message=None,
                 video_steps=steps, video_limit=limit)
    status, message = "failed", None
    try:
        proc = subprocess.Popen([sys.executable, "-m", "dreamfeed", "video-prep", name, "--limit", str(limit)])
        while proc.poll() is None:
            if (base / "video-cancel").exists():
                proc.kill()
                proc.wait()
                raise Stopped()
            time.sleep(2)
        if proc.returncode:
            raise RuntimeError(f"preparing the clips failed (exit {proc.returncode}); see the worker log")
        kept = json.loads((base / "video-prep.json").read_text())["kept"]
        if kept < MIN_CLIPS:
            raise RuntimeError(f"only {kept} clips passed the checks; at least {MIN_CLIPS} are needed")
        free_gpu(cfg)
        write_status(base, video_phase="waiting", video_done=0, video_total=steps,
                     video_message="waiting for the video trainer")
        req = base / "video-train-request.json"
        req.write_text(json.dumps({"steps": steps}))
        start, limit_s = time.time(), 2 * steps * SECONDS_PER_STEP + TRAIN_SLACK
        while True:
            time.sleep(5)
            phase = json.loads((base / "status.json").read_text()).get("video_phase")
            if phase == "trained":
                break
            if phase == "train-failed":
                raise RuntimeError(json.loads((base / "status.json").read_text()).get("video_message")
                                   or "training failed")
            if phase == "cancelled":
                raise Stopped()
            if req.exists() and (base / "video-cancel").exists():
                req.unlink(missing_ok=True)
                raise Stopped()
            if req.exists() and time.time() - start > PICKUP_SECONDS:
                req.unlink(missing_ok=True)
                raise RuntimeError("the video trainer didn't pick up the request; is dreamfeed-video-trainer running?")
            if time.time() - start > limit_s:
                raise RuntimeError(f"training took over {limit_s // 3600} hours; giving up")
        status, message = "done", f"{kept} clips trained"
        write_status(base, video_phase="done", video_message=message)
    except Stopped:
        status, message = "cancelled", "cancelled"
        write_status(base, video_phase="cancelled", video_message=message)
    except Exception as e:
        message = str(e)[:300]
        write_status(base, video_phase="failed", video_message=message)
        print(f"video-style: {name} failed: {message}", flush=True)
    finally:
        (base / "video-cancel").unlink(missing_ok=True)
        with conn:
            conn.execute("UPDATE jobs SET status = ?, message = ?, finished_at = datetime('now') WHERE id = ?",
                         (status, message, job_id))


def main(args: list[str]) -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="dreamfeed video-prep")
    ap.add_argument("name")
    ap.add_argument("--limit", type=int, default=600)
    ap.add_argument("--no-download", action="store_true", help="only check what's in video_raw")
    a = ap.parse_args(args)
    if not a.name.replace("_", "").isalnum():
        sys.exit("video-prep: bad name")
    prepare(Config(), a.name, a.limit, not a.no_download)
