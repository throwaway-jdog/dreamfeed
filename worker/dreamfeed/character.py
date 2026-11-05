"""A character LoRA from a trained style's pictures of one character.

    python -m dreamfeed character-prep NAME --from STYLE --look "red hair, green eyes"
                                       --traits "red hair, green eyes, freckles, ..." [--train STEPS]

Some artists mostly draw one character. Their style LoRA learns her a little, but it learns
from everything they draw. This keeps only the style's training pictures that show her:
- the tagger saw every --look tag in it, and not two or more girls (she'd share the picture);
- of those, the ones closest to all the others (CLIP), so off-model pictures drop out.
Each caption starts with the trigger NAME and leaves out her --traits, so the LoRA ties her
whole look to the one word; everything else (pose, outfit, partner, text) stays tagged, so it
can still be asked for or kept out.

The pictures were already checked when the style was prepared (adults-only at the strict
threshold, photos, feral, blocked tags); they are copied, not downloaded again. --train
asks the trainer service for STEPS steps on the medium's checkpoint, like a style.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np

from .config import Config
from .lora import write_status

CROWD = {"2girls", "3girls", "4girls", "multiple girls", "group sex", "yuri"}
KEEP_SHARE = 0.8     # of the pictures that show her: the most alike, by CLIP
MIN_PICTURES = 20
REPEATS = 8          # fewer pictures than a style, each seen more often


def _tags(txt: Path) -> list[str]:
    return [t.strip() for t in txt.read_text().split(",")[1:] if t.strip()]   # [0] is the style trigger


def prepare(cfg: Config, name: str, style: str, look: list[str], traits: set[str]) -> dict:
    from PIL import Image
    from .vision import Vision
    src = cfg.data_dir / "lora" / style
    prep = json.loads((src / "prep.json").read_text())
    medium = prep["medium"]
    picks = []
    for txt in sorted(src.glob("dataset/*/*.txt")):
        tags = set(_tags(txt))
        if set(look) <= tags and not tags & CROWD and txt.with_suffix(".png").is_file():
            picks.append(txt)
    print(f"character-prep: {len(picks)} of the {style} pictures show {', '.join(look)}", flush=True)
    vision = Vision(cfg.models_dir)
    try:
        embs = []
        for txt in picks:
            with Image.open(txt.with_suffix(".png")) as im:
                embs.append(vision.embed([im.convert("RGB")])[0])
    finally:
        vision.close()
    embs = np.stack(embs) if embs else np.zeros((0, 1))
    centre = embs.mean(0) / max(np.linalg.norm(embs.mean(0)), 1e-6) if len(embs) else None
    sims = embs @ centre if centre is not None else np.zeros(0)
    cut = np.quantile(sims, 1 - KEEP_SHARE) if len(sims) else 0
    keep = [t for t, s in zip(picks, sims) if s >= cut]
    if len(keep) < MIN_PICTURES:
        raise RuntimeError(f"only {len(keep)} pictures of her; at least {MIN_PICTURES} are needed")
    base = cfg.data_dir / "lora" / name
    out = base / "dataset" / f"{REPEATS}_{name}"
    if out.parent.exists():
        shutil.rmtree(out.parent)
    out.mkdir(parents=True)
    for n, txt in enumerate(keep):
        shutil.copy(txt.with_suffix(".png"), out / f"{n:04d}.png")
        (out / f"{n:04d}.txt").write_text(", ".join([name] + [t for t in _tags(txt) if t not in traits]))
    stats = {"kept": len(keep), "trigger": name, "medium": medium, "from": style, "look": look}
    (base / "prep.json").write_text(json.dumps(stats))
    # No "source": it isn't downloaded, so the dashboard offers no retrain from a page.
    (base / "source.json").write_text(json.dumps({"source": None, "medium": medium, "from": style}))
    write_status(base, phase="prepared", kept=len(keep), message=None)
    print(f"character-prep: {name} {stats}", flush=True)
    return stats


def train(cfg: Config, name: str, medium: str, steps: int) -> None:
    ckpt = cfg.generation().checkpoints.get(medium)
    if not ckpt:
        raise RuntimeError(f"no {medium} checkpoint set (CHECKPOINT_{medium.upper()})")
    base = cfg.data_dir / "lora" / name
    write_status(base, phase="waiting", done=0, total=steps, message="waiting for the trainer")
    (base / "train-request.json").write_text(json.dumps({"base": ckpt, "steps": steps}))
    print(f"character-prep: asked the trainer for {steps} steps on {ckpt}", flush=True)


def main(args: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="dreamfeed character-prep")
    ap.add_argument("name", help="the character's name: the trigger word and the file style-NAME")
    ap.add_argument("--from", dest="style", required=True, help="the trained style whose pictures to use")
    ap.add_argument("--look", required=True, help="tags every picture of her has, comma separated")
    ap.add_argument("--traits", default="", help="her tags to leave out of captions (the trigger learns them)")
    ap.add_argument("--train", type=int, metavar="STEPS", help="then ask the trainer for this many steps")
    a = ap.parse_args(args)
    if not a.name.replace("_", "").isalnum() or not a.style.replace("_", "").isalnum():
        sys.exit("character-prep: bad name")
    split = lambda s: [t.strip() for t in s.split(",") if t.strip()]
    look = split(a.look)
    cfg = Config()
    stats = prepare(cfg, a.name, a.style, look, set(look) | set(split(a.traits)))
    if a.train:
        train(cfg, a.name, stats["medium"], a.train)
