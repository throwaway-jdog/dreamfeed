"""Scenes: a short edited sex scene of about a minute, made the way animators do it: a few
looping shots, each a new drawing, cut together and building to a climax.

    python -m dreamfeed scene-preview POST_ID [--seed N]

A scene starts from a feed post with two characters. The post gives the cast and setting
(its tags minus the act, position and cum); each shot adds its own position, framing and
intensity. Only the climax and aftermath shots may show cum, and the others ask the model
not to draw it, so the scene can build up.

This first part plans the shots and draws one picture per shot (the persona's own model and
style LoRA, the same image checks as posts; of SHOT_CANDIDATES, the one that shows the
intended act and looks most like the post wins). scene-preview saves them with a contact
sheet so the plan can be judged before any video is made.
"""
import argparse
import json
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import motion

SHOT_CANDIDATES = 3

# What a position looks like in a picture (booru tags for the image model), and the act
# the tagger should then find in it (motion.ACTS names; None when no act LoRA covers it).
POSITIONS = {
    "missionary": ("missionary, on back, spread legs, sex, vaginal, penis", "missionary"),
    "doggy": ("doggystyle, sex from behind, all fours, sex, vaginal, penis", "doggy"),
    "cowgirl": ("cowgirl position, girl on top, straddling, sex, vaginal, penis", "cowgirl"),
    "blowjob": ("fellatio, oral, penis, kneeling, looking up", "blowjob"),
}
OPENERS = ("missionary", "blowjob")
MIDDLE = ("doggy", "cowgirl", "missionary")

NO_CUM = "cum, semen, cum on body, cum in pussy, cum in mouth, creampie, ejaculation, cum string"
# Every shot: the partner mustn't turn into a second copy of her, and no artist text.
SCENE_NEGATIVE = "2girls, multiple girls, twins, watermark, signature, text, logo, patreon username"
PARTNER = "faceless male"   # how artists often draw him; keeps him from borrowing her tags

# Tags that belong to what's happening, not to who and where: dropped from the post's own
# tags to get the cast and setting.
SCENE_ONLY = re.compile(r"\b(cum|semen|creampie|ejaculat|bukkake|facial|after sex|orgasm|"
                        r"motion lines|trembling|heavy breathing|sweat|ahegao|tongue out|open mouth|"
                        r"from behind|on back|all fours|straddling|spread legs|lying|kneeling|"
                        r"girl on top|on top|penetration|vaginal|anal|sex|penis|fellatio|oral|"
                        r"doggystyle|missionary|cowgirl|paizuri|handjob|blowjob)\b", re.I)


@dataclass
class Shot:
    name: str          # what it is, for the plan and the contact sheet
    tags: str          # position, framing and intensity, added to the cast and setting
    act: str | None    # the act the picture must show (and the motion LoRA for the clip)
    cum: bool          # may show cum
    pace: str          # for the motion description: how fast and intense


def cast_tags(prompt: str) -> str:
    """The post's prompt minus everything that belongs to the act: who and where."""
    keep = [t.strip() for t in prompt.split(",") if t.strip() and not SCENE_ONLY.search(t)]
    keep = [t for t in keep if t not in ("duo", "male", "1boy", PARTNER)]
    # Rating first, then the pair, then her.
    rating = [t for t in keep if t in ("nsfw", "explicit", "questionable")]
    rest = [t for t in keep if t not in rating]
    return ", ".join(rating + ["duo", PARTNER] + rest)


def plan(rng: random.Random) -> list[Shot]:
    """Opener, a position, a close-up in it, another position, the climax in that one, after."""
    opener = rng.choice(OPENERS)
    a = rng.choice([p for p in MIDDLE if p != opener])
    b = rng.choice([p for p in MIDDLE if p not in (a, opener)] or [p for p in MIDDLE if p != a])
    pos = lambda name: POSITIONS[name][0]
    act = lambda name: POSITIONS[name][1]
    return [
        Shot(f"opening: {opener}", f"{pos(opener)}, blush, half-closed eyes", act(opener), False,
             "slow and gentle, just starting"),
        Shot(f"{a}", f"{pos(a)}, blush, open mouth", act(a), False, "a steady rhythm"),
        Shot(f"{a}, close-up", f"{pos(a)}, close-up, upper body, face focus, blush, open mouth, sweat, "
             "heavy breathing", act(a), False, "faster, she's lost in it"),
        Shot(f"{b}", f"{pos(b)}, open mouth, sweat, heavy breathing, motion lines", act(b), False,
             "fast and intense, building toward climax"),
        Shot(f"climax: {b}", f"{pos(b)}, orgasm, cum in pussy, creampie, cum overflow, trembling, open mouth, "
             "sweat", act(b), True, "the climax: he cums inside her, both shuddering"),
        Shot("aftermath", "after sex, lying, on back, cum in pussy, cum on body, sweat, heavy breathing, "
             "half-closed eyes, smile", None, True, "slow, catching their breath"),
    ]


def draw(cfg, comfy, persona, post: dict, shots: list[Shot], subdir: str, name: str,
         rng: random.Random) -> list[tuple[Path | None, str]]:
    """One checked picture per shot: (path or None, note). Candidates that lose are deleted."""
    from . import captions
    from .checks import drop_reason
    from .generate import _feral
    from .vision import Vision
    cast = cast_tags(post["prompt"])
    lora = persona.lora_for(post["prompt"]) if persona else None
    negative = persona.negative if persona else ""
    cands: list[list[Path]] = []
    try:
        for i, shot in enumerate(shots):
            neg = ", ".join(n for n in (negative, SCENE_NEGATIVE, "" if shot.cum else NO_CUM) if n)
            cands.append([comfy.txt2img(post["checkpoint"], post["medium"], f"{cast}, {shot.tags}",
                                        rng.randrange(2 ** 32), subdir, f"{name}-shot{i}-{c}",
                                        extra_negative=neg, strict=post["strict"], lora=lora)
                          for c in range(SHOT_CANDIDATES)])
    finally:
        comfy.stop()
    vision = Vision(cfg.models_dir)
    out = []
    try:
        with Image.open(post["file"]) as im:
            base = vision.analyze([im.convert("RGB")]).embedding.astype(np.float32)
        for shot, paths in zip(shots, cands):
            scored = []
            for p in paths:
                with Image.open(p) as im:
                    img = im.convert("RGB")
                a = vision.analyze([img])
                if drop_reason(a, post["medium"], [img], cfg, strict=post["strict"]) or _feral(a):
                    continue
                act = motion.act_for(captions.picture(a.general))
                # Showing the intended act matters more than looking like the post.
                fits = (act.name if act else None) == shot.act
                scored.append((fits, float(a.embedding.astype(np.float32) @ base), p))
            best = max(scored, key=lambda s: s[:2]) if scored else None
            for p in paths:
                if not best or p != best[2]:
                    p.unlink(missing_ok=True)
            out.append((best[2], f"{'' if best[0] else 'act not seen, '}look {best[1]:.2f}") if best
                       else (None, f"all {len(paths)} failed the checks"))
    finally:
        vision.close()
    return out


def contact_sheet(post_file: Path, shots: list[Shot], pictures: list[tuple[Path | None, str]],
                  out: Path, width: int = 300) -> Path:
    """The post, then each shot's picture, labelled, in one image."""
    tiles = [(post_file, "the post")] + [(p, f"{i + 1}. {s.name}\n{note}")
                                        for i, (s, (p, note)) in enumerate(zip(shots, pictures))]
    cols, label = 4, 34
    rows = -(-len(tiles) // cols)
    cell_h = int(width * 1.5) + label
    sheet = Image.new("RGB", (cols * width, rows * cell_h), (24, 22, 20))
    pen = ImageDraw.Draw(sheet)
    for k, (path, text) in enumerate(tiles):
        x, y = (k % cols) * width, (k // cols) * cell_h
        if path:
            with Image.open(path) as im:
                im = im.convert("RGB")
                im.thumbnail((width, cell_h - label))
                sheet.paste(im, (x, y))
        pen.multiline_text((x + 6, y + cell_h - label + 2), text, fill=(235, 230, 220), spacing=2)
    sheet.save(out, quality=85)
    return out


def load_post(cfg, conn, gid: int) -> dict:
    row = conn.execute("SELECT g.medium, g.prompt, g.file, g.persona, g.checkpoint, coalesce(p.strict, 1)"
                       " FROM generations g LEFT JOIN personas p ON p.handle = g.persona"
                       " WHERE g.id = ? AND g.kind = 'image'", (gid,)).fetchone()
    if not row:
        raise LookupError(f"no image post {gid}")
    medium, prompt, file, handle, ckpt, strict = row
    return {"medium": medium, "prompt": prompt, "file": cfg.data_dir / "generated" / file, "persona": handle,
            "checkpoint": ckpt, "strict": bool(strict)}


def preview(args: list[str]) -> None:
    from . import db, personas as people
    from .comfy import Comfy
    from .config import Config
    ap = argparse.ArgumentParser(prog="dreamfeed scene-preview")
    ap.add_argument("post", type=int)
    ap.add_argument("--seed", type=int)
    a = ap.parse_args(args)
    cfg = Config()
    gen = cfg.generation()
    conn = db.connect(cfg.db_path)
    post = load_post(cfg, conn, a.post)
    persona = {p.handle: p for p in people.load(cfg.personas_path)}.get(post["persona"])
    rng = random.Random(a.seed)
    shots = plan(rng)
    out_dir = cfg.data_dir / "generated"
    subdir = f"scene-preview-{a.post}"
    comfy = Comfy(gen.comfy_url, gen.supervisor_url, out_dir)
    print(f"scene-preview: cast and setting: {cast_tags(post['prompt'])}", flush=True)
    pictures = draw(cfg, comfy, persona, post, shots, subdir, f"post{a.post}", rng)
    sheet = contact_sheet(post["file"], shots, pictures, out_dir / subdir / "contact-sheet.jpg")
    (out_dir / subdir / "plan.json").write_text(json.dumps(
        [{"shot": s.name, "tags": s.tags, "picture": str(p) if p else None, "note": n}
         for s, (p, n) in zip(shots, pictures)], indent=1))
    print(f"scene-preview: {sheet}", flush=True)
