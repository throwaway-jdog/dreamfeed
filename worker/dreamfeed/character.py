"""A character LoRA from a trained style's pictures of one character.

    python -m dreamfeed character-prep NAME --from STYLE --look "red hair, green eyes"
                                       --traits "red hair, green eyes, freckles, ..."
                                       [--closeups PARTS] [--train STEPS]

Some artists mostly draw one character. Their style LoRA learns her a little, but it learns
from everything they draw. This keeps only the style's training pictures that show her:
- the tagger saw every --look tag in it, and not two or more girls (she'd share the picture);
- of those, the ones closest to all the others (CLIP), so off-model pictures drop out.
Each caption starts with the trigger NAME and leaves out her --traits, so the LoRA ties her
whole look to the one word; everything else (pose, outfit, partner, text) stays tagged, so it
can still be asked for or kept out.

--closeups PARTS adds close-ups of her: hairclip, face, breasts, pussy, ass, or penis (for
femboy characters; solo pictures only). For each picture, the square where the tagger sees the
part most surely. Small details are a few pixels of a whole picture, so the LoRA learns "a
hairclip" but not which one; close-ups show it. They go in their own folder with half the
repeats and are captioned "close-up", so she isn't drawn cropped unless asked. A square with
someone else in it is left out, and each one is checked again like the pictures (adults-only
at the strict threshold). closeups.json lists what was kept and why the rest weren't.

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
TAG_MIN = 0.35
CLOSEUP_REPEATS = 4   # half a whole picture's: close-ups of her shouldn't outweigh her
CLOSEUP_MIN_PX = 384
CLOSEUP_SURE = 0.5    # the tagger's score for the part in the best square
# Each part: the tag that finds it, the square's side as shares of the picture's shorter side,
# tags that mean the square shows someone else too, and whether only solo pictures count
# (a penis in a picture with a partner may be his).
NOT_HER = {"1boy", "multiple boys", "penis", "testicles", "male pubic hair"} | CROWD
PARTS = {
    "hairclip": ("hairclip", (0.3, 0.45), CROWD, False),
    "face": ("portrait", (0.35, 0.5), NOT_HER, False),
    "breasts": ("nipples", (0.35, 0.5), NOT_HER, False),
    "pussy": ("pussy", (0.3, 0.45), NOT_HER, False),
    "ass": ("ass", (0.4, 0.55), NOT_HER, False),
    "penis": ("penis", (0.3, 0.45), CROWD | {"1girl", "pussy"}, True),   # femboy characters
}


def _tags(txt: Path) -> list[str]:
    return [t.strip() for t in txt.read_text().split(",")[1:] if t.strip()]   # [0] is the style trigger


def _closeup(vision, img, tag: str, sizes):
    """(score, square crop, its analysis) where the tagger sees tag most surely, or None."""
    w, h = img.size
    best = None
    for share in sizes:
        side = int(min(w, h) * share)
        if side < CLOSEUP_MIN_PX:
            continue
        step = side // 2
        for y in range(0, h - side + 1, step):
            for x in range(0, w - side + 1, step):
                crop = img.crop((x, y, x + side, y + side))
                a = vision.analyze([crop])
                score = a.general.get(tag, 0)
                if best is None or score > best[0]:
                    best = (score, crop, a)
    return best


def _closeups(cfg: Config, vision, keep: list[Path], out: Path, name: str, parts: list[str],
              traits: set[str], medium: str) -> dict:
    """Close-ups of each part, into their own folder (fewer repeats). Every one is checked
    again like the pictures; data/lora/NAME/closeups.json lists what was kept and why the
    rest weren't."""
    from PIL import Image
    from .checks import drop_reason
    log, counts = [], {}
    for part in parts:
        tag, sizes, others, solo_only = PARTS[part]
        n = 0
        for txt in keep:
            if n >= len(keep):   # no more close-ups of one part than whole pictures
                break
            entry = {"part": part, "picture": txt.with_suffix(".png").name}
            log.append(entry)
            if solo_only and "solo" not in _tags(txt):
                entry["why"] = "not a solo picture"
                continue
            with Image.open(txt.with_suffix(".png")) as im:
                found = _closeup(vision, im.convert("RGB"), tag, sizes)
            if not found or found[0] < CLOSEUP_SURE:
                entry["why"] = f"no {tag} (best {found[0]:.2f})" if found else "picture too small"
                continue
            score, crop, a = found
            seen = {t for t, v in a.general.items() if v >= TAG_MIN}
            if seen & others:
                entry["why"] = "someone else in it: " + ", ".join(sorted(seen & others))
                continue
            reason = drop_reason(a, medium, [crop], cfg, strict=True)
            if reason:
                entry["why"] = "check: " + " ".join(reason)
                continue
            tags = [t for t, v in sorted(a.general.items(), key=lambda kv: -kv[1])
                    if v >= TAG_MIN and t not in traits and t not in CROWD and t != "close-up"]
            stem = f"{part}-{n:03d}"
            crop.resize((1024, 1024), Image.LANCZOS).save(out / f"{stem}.png")
            (out / f"{stem}.txt").write_text(", ".join([name, "close-up"] + tags))
            entry.update(kept=stem, score=round(score, 2))
            n += 1
        counts[part] = n
        dropped = [e for e in log if e["part"] == part and "kept" not in e]
        print(f"character-prep: {n} close-ups of {part}, {len(dropped)} not used", flush=True)
        for e in dropped:
            if e["why"].startswith(("check", "someone")):
                print(f"  {e['picture']}: {e['why']}", flush=True)
    (out.parent.parent / "closeups.json").write_text(json.dumps(log, indent=1))
    return counts


def prepare(cfg: Config, name: str, style: str, look: list[str], traits: set[str],
            closeups: list[str] | None = None) -> dict:
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
        keep, out, base = _copy(cfg, name, picks, embs, traits)
        if closeups:
            crops = out.parent / f"{CLOSEUP_REPEATS}_{name}"
            crops.mkdir()
            extra = _closeups(cfg, vision, keep, crops, name, closeups, traits, medium)
        else:
            extra = {}
    finally:
        vision.close()
    stats = {"kept": len(keep), "closeups": extra, "trigger": name, "medium": medium, "from": style, "look": look}
    (base / "prep.json").write_text(json.dumps(stats))
    # No "source": it isn't downloaded, so the dashboard offers no retrain from a page.
    (base / "source.json").write_text(json.dumps({"source": None, "medium": medium, "from": style}))
    write_status(base, phase="prepared", kept=len(keep) + sum(extra.values()), message=None)
    print(f"character-prep: {name} {stats}", flush=True)
    return stats


def _copy(cfg: Config, name: str, picks: list[Path], embs: list, traits: set[str]):
    """The pictures most like the others, copied with captions: (kept, dataset folder, base)."""
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
    return keep, out, base


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
    ap.add_argument("--closeups", metavar="PARTS",
                    help="close-ups of these, comma separated: " + ", ".join(PARTS))
    ap.add_argument("--train", type=int, metavar="STEPS", help="then ask the trainer for this many steps")
    a = ap.parse_args(args)
    if not a.name.replace("_", "").isalnum() or not a.style.replace("_", "").isalnum():
        sys.exit("character-prep: bad name")
    split = lambda s: [t.strip() for t in s.split(",") if t.strip()]
    look = split(a.look)
    cfg = Config()
    parts = split(a.closeups or "")
    if set(parts) - set(PARTS):
        sys.exit(f"character-prep: unknown parts {sorted(set(parts) - set(PARTS))}; known: {', '.join(PARTS)}")
    stats = prepare(cfg, a.name, a.style, look, set(look) | set(split(a.traits)), parts)
    if a.train:
        train(cfg, a.name, stats["medium"], a.train)
