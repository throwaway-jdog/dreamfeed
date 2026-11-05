"""Prepare a style-LoRA training set from an artist's downloaded images.

    python -m dreamfeed lora-prep NAME --medium anime|furry --trigger WORD

Reads data/lora/NAME/raw (filled by the dashboard's downloader, or by hand), and for each image:
- drops photographs: styles learn drawings, never real people
- runs the same adults-only checks as generated posts, at the strict threshold, and the
  feral filter; anything flagged is deleted from raw and never trained on
- captions it with the trigger word and its general tags (no character or name tags, so the
  LoRA learns the drawing style, not specific characters)
- writes it to data/lora/NAME/dataset/<repeats>_<trigger>/ in the layout kohya sd-scripts reads.
Runs on the CPU when CUDA_VISIBLE_DEVICES is empty, so it can run while ComfyUI has the GPU.
"""
import json
import os
import shutil
import sys
import time

from .config import Config

# Text, watermark and signature tags stay in the captions on purpose: tagged, the LoRA learns
# them as removable things (and the negative prompt removes them); untagged, it would bake the
# artist's watermark into the style itself.
SKIP_TAGS = {"commentary", "translated", "character name"}
TAG_MIN = 0.35
MAX_TAGS = 40
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
# Every training image goes through checks.problem(training=True): see safety.py.


def write_status(base, **fields) -> None:
    """data/lora/NAME/status.json, which the dashboard shows (shared with styles.py and the trainer)."""
    path = base / "status.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        data = {}
    data.update(fields, updated=int(time.time()))
    tmp = path.with_name("status.json.tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)


def prepare(cfg: Config, name: str, medium: str, trigger: str, repeats: int) -> dict:
    from PIL import Image
    from .checks import problem
    from .vision import Vision

    base = cfg.data_dir / "lora" / name
    raw, out = base / "raw", base / "dataset" / f"{repeats}_{trigger}"
    if out.parent.exists():
        shutil.rmtree(out.parent)
    out.mkdir(parents=True)
    files = sorted(p for p in raw.rglob("*") if p.suffix.lower() in IMAGE_EXT and ".part" not in p.parts)
    vision = Vision(cfg.models_dir)
    stats = {"kept": 0, "dropped": {}, "unreadable": 0}
    # An artist who always signs in the same strip: source.json "crop_top" (a share of the
    # height) is cut off every picture first, or the LoRA learns to draw the signature.
    try:
        crop_top = float(json.loads((base / "source.json").read_text()).get("crop_top") or 0)
    except (OSError, ValueError):
        crop_top = 0.0
    for n, path in enumerate(files, 1):
        try:
            img = Image.open(path).convert("RGB")
        except Exception:
            stats["unreadable"] += 1
            continue
        if crop_top:
            img = img.crop((0, round(img.height * crop_top), img.width, img.height))
        a = vision.analyze([img])
        reason = problem(a, medium, [img], cfg, training=True)
        if reason:
            stats["dropped"][reason[0]] = stats["dropped"].get(reason[0], 0) + 1
            path.unlink(missing_ok=True)
            continue
        tags = [t for t, s in sorted(a.general.items(), key=lambda kv: -kv[1])
                if s >= TAG_MIN and t not in SKIP_TAGS][:MAX_TAGS]
        stem = f"{stats['kept']:04d}"
        img.save(out / f"{stem}.png")
        (out / f"{stem}.txt").write_text(", ".join([trigger, *tags]))
        stats["kept"] += 1
        if n % 5 == 0 or n == len(files):
            write_status(base, phase="checking", done=n, total=len(files), kept=stats["kept"])
        if n % 25 == 0:
            print(f"lora-prep: {n}/{len(files)} {stats}", flush=True)
    (base / "prep.json").write_text(json.dumps(stats | {"trigger": trigger, "medium": medium}))
    print(f"lora-prep: {name} done {stats}", flush=True)
    return stats


def main(args: list[str]) -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="dreamfeed lora-prep")
    ap.add_argument("name")
    ap.add_argument("--medium", choices=["anime", "furry"], required=True)
    ap.add_argument("--trigger", required=True)
    ap.add_argument("--repeats", type=int, default=5)
    a = ap.parse_args(args)
    if not a.trigger.replace("_", "").isalnum():
        sys.exit("lora-prep: trigger must be letters, digits and _")
    prepare(Config(), a.name, a.medium, a.trigger, a.repeats)
