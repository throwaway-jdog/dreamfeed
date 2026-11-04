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

from . import motion, safety
from .config import Config
from .lora import TAG_MIN, _photo, write_status

VIDEO_FILTER = "extension in ('mp4', 'webm', 'mov', 'm4v')"
CHECK_FRAMES = 16        # per clip, at least; more for long clips (media.frame_count)
FPS = 16                 # Wan 2.2 14B's frame rate
VIDEO_MAX_SIDE = 640     # training buckets are smaller; this just keeps files small
MIN_SECONDS = 1.5        # shorter than this has no motion worth learning
MIN_CLIPS = 15


def trigger_for(name: str) -> str:
    return f"{name.replace('_', '')}_anim"


def download(base: Path, source: str, limit: int) -> int:
    from .styles import GALLERY_DL, COOKIES, COOKIE_HOSTS
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
        if not COOKIES.is_file():
            raise RuntimeError("x.com needs your cookies: set X_COOKIES_FILE in .env")
        cmd += ["--cookies", str(COOKIES)]
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
    from .checks import drop_reason
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
                    reason = _photo(a) or drop_reason(a, medium, frames, cfg, strict=True)
                    hits = safety.feral_hits(a.general)
                    if not reason and hits:
                        reason = ("feral", ", ".join(hits))
                    tags = [t for t, s in sorted(a.general.items(), key=lambda kv: -kv[1]) if s >= TAG_MIN]
                    bad = safety.blocked(", ".join(tags))
                    if not reason and bad:
                        reason = ("blocked-tag", ", ".join(bad))
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
