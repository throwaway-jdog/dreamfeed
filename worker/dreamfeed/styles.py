"""Train a style LoRA from the dashboard: download an artist's images, check them, train.

A "style" job (queued by the web page) runs three steps, writing progress to
data/lora/NAME/status.json for the dashboard:
1. download: gallery-dl fetches up to LIMIT images from the source link into
   data/lora/NAME/raw (images only; an archive skips files already fetched or rejected), and
   the text of each post into posts.jsonl. With "videos" (artists who only post animations),
   it fetches videos instead, and FRAMES_PER_VIDEO frames spread over each become the
   pictures (near-identical ones are dropped by lora-prep).
2. check:    lora-prep in a child process (so its GPU memory is freed afterwards); drops
             photos, anything the adults-only or feral checks flag, and blocked tags
   then the texts of posts whose images passed become the style's voice (voice.json), which
   personas can write their captions like (captions.py)
3. train:    a request file for the trainer service, which holds generation while it runs;
             this job waits for it to finish

data/lora/NAME/cancel (from the dashboard) stops whichever step is running.
"""
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import captions
from .config import Config
from .lora import write_status

MOUNTED_COOKIES = Path("/config/cookies.txt")   # X_COOKIES_FILE, needed for x.com sources


def x_cookies() -> Path | None:
    """Your X cookies: the dashboard's (Sign-ins), else X_COOKIES_FILE's (cookies.py)."""
    from . import cookies
    return cookies.path("x", MOUNTED_COOKIES)
COOKIE_HOSTS = ("x.com", "twitter.com")
MIN_IMAGES = 20           # fewer usable images than this is not worth training on
PICKUP_SECONDS = 120      # the trainer service checks for requests every few seconds
TRAIN_TIMEOUT = 6 * 3600
GALLERY_DL = {
    "extractor": {
        "directory": [],
        "cookies-update": False,
        "twitter": {"filename": "{tweet_id}_{num}.{extension}", "videos": False, "cards": False,
                    "quoted": False, "retweets": False, "text-tweets": False},
        # Each post's text, once per post (also for posts whose images are already downloaded).
        "postprocessors": [{"name": "metadata", "event": "post", "mode": "jsonl", "directory": "..",
                            "filename": "posts.jsonl", "open": "a",
                            "include": ["tweet_id", "content", "reply_id", "retweet_id"]}],
    },
}
IMAGE_FILTER = "extension in ('jpg', 'jpeg', 'png', 'webp')"
VIDEO_FILTER = "extension in ('mp4', 'webm', 'mov', 'm4v', 'gif')"
FRAMES_PER_VIDEO = 8      # spread over the middle 90% of each video


class Stopped(Exception):
    pass


def run(cfg: Config, conn, job_id: int, params: dict) -> None:
    name, medium = params["name"], params["medium"]
    base = cfg.data_dir / "lora" / name
    base.mkdir(parents=True, exist_ok=True)
    (base / "cancel").unlink(missing_ok=True)
    videos = bool(params.get("videos"))
    try:   # keep settings made by hand (crop_top)
        kept = {k: v for k, v in json.loads((base / "source.json").read_text()).items() if k == "crop_top"}
    except (OSError, ValueError):
        kept = {}
    (base / "source.json").write_text(json.dumps(kept | {"source": params["source"], "medium": medium,
                                                  "limit": params["limit"], "steps": params["steps"],
                                                  "videos": videos}))
    with conn:
        conn.execute("UPDATE jobs SET status = 'running' WHERE id = ?", (job_id,))
    status, message = "failed", None
    try:
        got = download(base, params["source"], params["limit"], videos=videos)
        kept = check(base, name, medium, trigger_for(base, name))
        captions.build_voice(base)
        if kept < MIN_IMAGES:
            raise RuntimeError(f"only {kept} images passed the checks; at least {MIN_IMAGES} are needed")
        free_gpu(cfg)
        train(cfg, base, name, medium, params["steps"])
        status, message = "done", f"{got} downloaded, {kept} used for training"
        write_status(base, phase="done", message=message)
    except Stopped:
        status, message = "cancelled", "cancelled"
        write_status(base, phase="cancelled", message=message)
    except Exception as e:
        message = str(e)[:300]
        write_status(base, phase="failed", message=message)
        print(f"style: {name} failed: {message}", flush=True)
    finally:
        (base / "cancel").unlink(missing_ok=True)
        with conn:
            conn.execute("UPDATE jobs SET status = ?, message = ?, finished_at = datetime('now') WHERE id = ?",
                         (status, message, job_id))


def trigger_for(base: Path, name: str) -> str:
    """Keep an existing style's trigger word (personas use it); new ones get NAME_style."""
    try:
        return json.loads((base / "prep.json").read_text())["trigger"]
    except (OSError, ValueError, KeyError):
        return f"{name.replace('_', '')}_style"


def _watch(base: Path, proc: subprocess.Popen) -> None:
    if (base / "cancel").exists():
        proc.kill()
        proc.wait()
        raise Stopped()


def download(base: Path, source: str, limit: int, videos: bool = False) -> int:
    raw = base / "raw"
    raw.mkdir(exist_ok=True)
    write_status(base, phase="downloading", done=0, total=limit, message=None, kept=None)
    ext = dict(GALLERY_DL["extractor"], **{"base-directory": str(raw), "archive": str(base / "archive.sqlite3")})
    if videos:
        ext["twitter"] = dict(ext["twitter"], videos=True)
    conf = dict(GALLERY_DL, extractor=ext, downloader={"part-directory": str(raw / ".part")})
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(conf, f)
    cmd = ["gallery-dl", "--config-ignore", "--config", f.name, "--range", f"1-{limit}",
           "--filter", VIDEO_FILTER if videos else IMAGE_FILTER]
    host = source.split("/")[2].lower() if source.count("/") >= 2 else ""
    if host.removeprefix("www.").removeprefix("mobile.") in COOKIE_HOSTS:
        if not x_cookies():
            raise RuntimeError("x.com needs your cookies: add them on the dashboard (Sign-ins)")
        cmd += ["--cookies", str(x_cookies())]
    print(f"style: downloading up to {limit} images for {base.name}", flush=True)
    proc = subprocess.Popen(cmd + [source], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    new, errors = 0, []
    for line in proc.stdout:
        _watch(base, proc)
        if line.startswith(str(raw)):
            new += 1
            if new % 5 == 0:
                write_status(base, done=new)
        elif "[error]" in line:
            errors.append(line.split("[error]", 1)[1].strip())
    code = proc.wait()
    Path(f.name).unlink(missing_ok=True)
    have = sum(1 for p in raw.iterdir() if p.is_file())
    write_status(base, done=new, total=limit)
    if code and not have:
        raise RuntimeError("download failed: " + (errors[-1] if errors else f"gallery-dl exit {code}")
                           + (" (expired cookies?)" if "x.com" in source or "twitter.com" in source else ""))
    if videos:
        frames = _frames_from_videos(raw)
        print(f"style: {new} new videos, {frames} frames from them", flush=True)
        return new
    print(f"style: {new} new images, {have} in raw", flush=True)
    return new


def _frames_from_videos(raw: Path) -> int:
    """Each video in raw becomes FRAMES_PER_VIDEO pictures, full size; the video is deleted
    (the archive remembers it, so it isn't fetched again)."""
    from .videolora import _duration
    made = 0
    for video in sorted(p for p in raw.iterdir() if p.is_file() and p.suffix.lower() in
                        (".mp4", ".webm", ".mov", ".m4v", ".gif")):
        length = _duration(video)
        for n in range(FRAMES_PER_VIDEO if length > 0 else 0):
            at = length * (0.05 + 0.9 * n / max(1, FRAMES_PER_VIDEO - 1))
            out = raw / f"{video.stem}_f{n}.png"
            done = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.2f}", "-i", str(video),
                                   "-frames:v", "1", str(out)], capture_output=True, timeout=120)
            made += done.returncode == 0 and out.is_file()
        video.unlink(missing_ok=True)
    return made


def check(base: Path, name: str, medium: str, trigger: str) -> int:
    proc = subprocess.Popen([sys.executable, "-m", "dreamfeed", "lora-prep", name, "--medium", medium,
                             "--trigger", trigger])
    while proc.poll() is None:
        _watch(base, proc)
        time.sleep(2)
    if proc.returncode:
        raise RuntimeError(f"checking the images failed (exit {proc.returncode}); see the worker log")
    return json.loads((base / "prep.json").read_text())["kept"]


def free_gpu(cfg: Config) -> None:
    """ComfyUI may still hold the GPU from an earlier run; the trainer needs all of it."""
    from .comfy import Comfy
    gen = cfg.generation()
    try:
        Comfy(gen.comfy_url, gen.supervisor_url, cfg.data_dir / "generated").stop()
    except Exception as e:
        print(f"style: couldn't stop ComfyUI ({e}); training anyway", flush=True)


def train(cfg: Config, base: Path, name: str, medium: str, steps: int) -> None:
    ckpt = cfg.generation().checkpoints.get(medium)
    if not ckpt:
        raise RuntimeError(f"no {medium} checkpoint set (CHECKPOINT_{medium.upper()})")
    write_status(base, phase="waiting", done=0, total=steps, message="waiting for the trainer")
    (base / "train-request.json").write_text(json.dumps({"base": ckpt, "steps": steps}))
    start = time.time()
    while True:
        time.sleep(5)
        st = json.loads((base / "status.json").read_text())
        if st.get("phase") == "trained":
            return
        if st.get("phase") == "train-failed":
            raise RuntimeError(st.get("message") or "training failed")
        if st.get("phase") == "cancelled":
            raise Stopped()
        if (base / "train-request.json").exists() and time.time() - start > PICKUP_SECONDS:
            (base / "train-request.json").unlink(missing_ok=True)
            raise RuntimeError("the trainer service didn't pick up the request; is dreamfeed-trainer running?")
        if (base / "cancel").exists() and (base / "train-request.json").exists():
            (base / "train-request.json").unlink(missing_ok=True)
            raise Stopped()
        if time.time() - start > TRAIN_TIMEOUT:
            raise RuntimeError("training took over 6 hours; giving up")
