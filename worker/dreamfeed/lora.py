"""Prepare a style-LoRA training set from an artist's downloaded images.

    python -m dreamfeed lora-prep NAME --medium anime|furry --trigger WORD

Reads data/lora/NAME/raw (filled by gallery-dl), and for each image:
- runs the same adults-only checks as generated posts, at the strict threshold, and the
  feral filter; anything flagged is deleted from raw and never trained on
- captions it with the trigger word and its general tags (no character or name tags, so the
  LoRA learns the drawing style, not specific characters)
- writes it to data/lora/NAME/dataset/<repeats>_<trigger>/ in the layout kohya sd-scripts reads.
Runs on the CPU when CUDA_VISIBLE_DEVICES is empty, so it can run while ComfyUI has the GPU.
"""
import json
import shutil
import sys

from . import safety
from .config import Config

SKIP_TAGS = {
    "text", "english text", "japanese text", "chinese text", "watermark", "signature", "artist name",
    "web address", "patreon username", "twitter username", "patreon logo", "logo", "dated", "copyright name",
    "commentary", "translated", "speech bubble", "artist logo", "character name", "multiple views",
}
TAG_MIN = 0.35
MAX_TAGS = 40
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def prepare(cfg: Config, name: str, medium: str, trigger: str, repeats: int) -> dict:
    from PIL import Image
    from .tagging import drop_reason
    from .vision import Vision

    base = cfg.data_dir / "lora" / name
    raw, out = base / "raw", base / "dataset" / f"{repeats}_{trigger}"
    if out.parent.exists():
        shutil.rmtree(out.parent)
    out.mkdir(parents=True)
    files = sorted(p for p in raw.rglob("*") if p.suffix.lower() in IMAGE_EXT and ".part" not in p.parts)
    vision = Vision(cfg.models_dir)
    stats = {"kept": 0, "dropped": {}, "unreadable": 0}
    for n, path in enumerate(files, 1):
        try:
            img = Image.open(path).convert("RGB")
        except Exception:
            stats["unreadable"] += 1
            continue
        a = vision.analyze([img])
        reason = drop_reason(a, medium, [img], cfg, strict=True)
        hits = safety.feral_hits(a.general)
        if not reason and hits:
            reason = ("feral", ", ".join(hits))
        blocked = safety.blocked(", ".join(t for t, s in a.general.items() if s >= TAG_MIN))
        if not reason and blocked:   # e.g. flat chest, petite: the style shouldn't learn them
            reason = ("blocked-tag", ", ".join(blocked))
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
