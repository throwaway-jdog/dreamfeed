"""Pictures to train a character LoRA on, for a persona's own character that has no art yet.

    python -m dreamfeed bootstrap PERSONA [--count 160] [--keep 40] [--add] [--nude]

Draws COUNT pictures of the persona's look (no LoRA) in varied framings, poses, outfits and
backgrounds, checks each like a post (adults-only at the strict threshold, feral, blocked
tags), and keeps those where the tagger sees what the persona's character needs (the
REQUIRE groups, from the persona file's "bootstrap" entry) and none of what she mustn't be
(AVOID). Of those, the KEEP most like each other (CLIP) become data/lora/PERSONAboot, laid
out like a checked style, so character-prep can build the LoRA from it:

    python -m dreamfeed character-prep PERSONA --from PERSONAboot --tagged PERSONAboot --solo ...

data/lora/PERSONAboot/sheet.jpg shows the kept pictures, to look over before training.
--add keeps the pictures already there and adds KEEP more (judged alike against all of them);
--nude draws only nude pictures (with --add: more of her body for the LoRA to learn).
"""
import argparse
import json
import random
import shutil
import sys

import numpy as np

from ..core.config import Config

FRAMINGS = ["full body, standing", "full body, sitting", "cowboy shot", "upper body", "portrait",
            "full body, from behind, looking back", "from side, full body", "lying on bed",
            "kneeling", "full body, walking"]
MOODS = ["smile", "blush", "shy", "happy, open mouth", "looking at viewer", "closed eyes, smile"]
BACKGROUNDS = ["simple background, white background", "simple background, grey background"]
TAG_MIN = 0.35


def _settings(cfg: Config, persona) -> list[str]:
    return persona.settings or ["bedroom", "living room", "outdoors, park"]


def _sheet(paths, out) -> None:
    from PIL import Image
    h = 360
    ims = [Image.open(p).convert("RGB") for p in paths]
    ims = [i.resize((int(i.width * h / i.height), h)) for i in ims]
    w = max(i.width for i in ims) if ims else 1
    cols = 8
    sheet = Image.new("RGB", (cols * w, max(1, (len(ims) + cols - 1) // cols) * h), "white")
    for k, i in enumerate(ims):
        sheet.paste(i, ((k % cols) * w, (k // cols) * h))
    sheet.save(out, quality=85)


def run(cfg: Config, handle: str, count: int, keep: int, add: bool = False, nude: bool = False) -> dict:
    from PIL import Image
    from ..core import personas
    from ..core.checks import problem
    from .comfy import Comfy
    from .vision import Vision

    p = {x.handle: x for x in personas.load(cfg.personas_path)}.get(handle)
    if not p:
        raise SystemExit(f"bootstrap: no persona @{handle}")
    rules = json.loads(cfg.personas_path.read_text())
    rules = next(x for x in rules["personas"] if x.get("handle") == handle).get("bootstrap") or {}
    require = [set(g) for g in rules.get("require", [])]   # each group: at least one of these tags
    avoid = set(rules.get("avoid", []))
    want = set(rules.get("prefer", []))                    # ranks the rest
    if not require:
        raise SystemExit('bootstrap: the persona needs "bootstrap": {"require": [[tags], ...]}')

    gen = cfg.generation()
    name = f"{handle}boot"
    base = cfg.data_dir / "lora" / name
    out = base / "dataset" / f"1_{name}"
    have = sorted(out.glob("*.png")) if add else []
    if add and not have:
        raise SystemExit(f"bootstrap: --add, but {out} has no pictures yet")
    if not add and base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)
    comfy = Comfy(gen.comfy_url, gen.supervisor_url, cfg.data_dir / "generated")
    rng = random.Random()
    outfits = ["nude"] if nude else (p.outfits or ["casual clothes"]) + ["nude"] * 2
    drawn = []
    try:
        for n in range(count):
            outfit = rng.choice(outfits)
            where = rng.choice(BACKGROUNDS) if rng.random() < 0.5 else rng.choice(_settings(cfg, p))
            rating = "explicit" if outfit == "nude" else "general"
            prompt = personas.RATINGS[rating] + ", ".join(
                ["solo", p.look, outfit, rng.choice(FRAMINGS), rng.choice(MOODS), where])
            path = comfy.txt2img(gen.checkpoints[p.medium], p.medium, prompt, rng.randrange(2 ** 32),
                                 f"bootstrap-{name}", f"b{n:04d}", strict=True, extra_negative=p.negative)
            drawn.append((path, prompt))
            if (n + 1) % 20 == 0:
                print(f"bootstrap: {n + 1}/{count} drawn", flush=True)
    finally:
        comfy.stop()

    vision = Vision(cfg.models_dir)
    good, why = [], {}
    try:
        for path, prompt in drawn:
            img = Image.open(path).convert("RGB")
            a = vision.analyze([img])
            reason = problem(a, p.medium, [img], cfg, training=True)
            seen = {t for t, v in a.general.items() if v >= TAG_MIN}
            if reason:
                why[reason[0]] = why.get(reason[0], 0) + 1
            elif not all(g & seen for g in require):
                why["not her"] = why.get("not her", 0) + 1
            elif seen & avoid:
                why["off-model"] = why.get("off-model", 0) + 1
            else:
                tags = [t for t, v in sorted(a.general.items(), key=lambda kv: -kv[1]) if v >= TAG_MIN]
                good.append((path, img, tags, len(want & seen), a.embedding.astype(np.float32)))
                continue
            path.unlink(missing_ok=True)
    finally:
        vision.close()
    if not good:
        raise SystemExit(f"bootstrap: none of the {count} pictures look like her ({why})")
    # The most alike: closest to the centre of those with the most of her preferred traits (or,
    # adding, of the pictures already kept).
    if have:
        from .vision import Vision as _V
        v = _V(cfg.models_dir)
        try:
            core = [v.embed([Image.open(f).convert("RGB")])[0] for f in have]
        finally:
            v.close()
    else:
        best = max(g[3] for g in good)
        core = [g[4] for g in good if g[3] >= best - 1]
    centre = np.mean(core, 0)
    centre /= max(np.linalg.norm(centre), 1e-6)
    good.sort(key=lambda g: -(float(g[4] @ centre) + 0.02 * g[3]))
    kept = good[:keep]
    out.mkdir(parents=True, exist_ok=True)
    trigger = f"{name}_style"
    first = max((int(f.stem) for f in have), default=-1) + 1
    for n, (path, img, tags, _, _) in enumerate(kept, first):
        img.save(out / f"{n:04d}.png")
        (out / f"{n:04d}.txt").write_text(", ".join([trigger] + tags))
    for path, *_ in good:
        path.unlink(missing_ok=True)
    stats = {"kept": len(have) + len(kept), "added": len(kept), "drawn": count, "matched": len(good), "dropped": why,
             "trigger": trigger, "medium": p.medium}
    (base / "prep.json").write_text(json.dumps(stats))
    _sheet(sorted(out.glob("*.png")), base / "sheet.jpg")
    print(f"bootstrap: {name} {stats}; look over {base / 'sheet.jpg'}", flush=True)
    return stats


def main(args: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="dreamfeed bootstrap")
    ap.add_argument("persona")
    ap.add_argument("--count", type=int, default=160, help="pictures to draw")
    ap.add_argument("--keep", type=int, default=40, help="the most alike to keep")
    ap.add_argument("--add", action="store_true", help="add to the pictures already there")
    ap.add_argument("--nude", action="store_true", help="only nude pictures")
    a = ap.parse_args(args)
    if not a.persona.replace("_", "").isalnum():
        sys.exit("bootstrap: bad persona handle")
    run(Config(), a.persona, a.count, a.keep, add=a.add, nude=a.nude)
