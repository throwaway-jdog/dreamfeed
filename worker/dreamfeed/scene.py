"""Scenes: a short edited sex scene of about a minute, made the way animators do it: a few
looping shots, each a new drawing, cut together and building to a climax.

From the viewer ("Make a scene", a job of kind "scene"), or by hand:
    python -m dreamfeed scene-preview POST_ID [--seed N]   plan and draw the shots, contact sheet
    python -m dreamfeed scene-render POST_ID [--shots 4,5]  animate what scene-preview drew

A scene starts from a feed post with two characters. The post gives the cast and setting
(its tags minus the act, position and cum); each shot adds its own position, framing and
intensity. Only the climax and aftermath shots may show cum, and the others ask the model
not to draw it, so the scene can build up.

1. draw: one picture per shot (the persona's own model and style LoRA, the same image checks
   as posts; of SHOT_CANDIDATES, the one that shows the intended act and looks most like the
   post wins).
2. render: each picture becomes a 5-second Wan clip that ends on its own first frame, a
   seamless loop played shot.loops times before a hard cut. The climax plays once and builds.
   Every clip is checked before it's used; one that keeps failing is left out.
"""
import argparse
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import motion

SHOT_CANDIDATES = 4
# What the tagger must see for a shot's picture to show its act, beyond the position.
PENETRATION = ({"penis"}, {"vaginal", "sex", "penetration"})
ORAL = ({"penis"}, {"fellatio", "oral"})
SHOT_TRIES = 3         # a shot whose clip fails a check is made again, then left out
# Scene clips, picked by eye against the plain-clip settings (same picture and seed): the act
# LoRA at full strength moves the bodies; the style LoRA lower so it doesn't fight it; one more
# step without the speed-up LoRA so the motion keeps its detail.
ACT_STRENGTH = 1.0
STYLE_STRENGTH = 0.3
SCENE_WAN = {"motion_steps": 3}

# What a position looks like in a picture (booru tags for the image model), and the act
# the tagger should then find in it (motion.ACTS names; None when no act LoRA covers it).
POSITIONS = {
    "missionary": ("missionary, on back, spread legs, sex, vaginal, penis", "missionary"),
    "doggy": ("doggystyle, (all fours:1.3), on floor, kneeling, sex from behind, sex, vaginal, penis", "doggy"),
    "cowgirl": ("cowgirl position, girl on top, straddling, sex, vaginal, penis", "cowgirl"),
    "reverse cowgirl": ("reverse cowgirl position, girl on top, from behind, sex, vaginal, penis", "reverse cowgirl"),
    "blowjob": ("fellatio, oral, penis, kneeling, looking up, standing male, his hand on her head, "
                "his body in frame", "blowjob"),
    "standing": ("standing sex, sex from behind, standing, against wall, sex, vaginal, penis", "standing"),
}
# Penetration shots are drawn side-on with both bodies whole: from below, it sits on the
# picture's bottom edge and Wan makes the penis vanish instead of moving it.
SIDE_ON = "(from side:1.4), (full body:1.2), profile, his whole body"
SIDE_ON_NEGATIVE = "(pov:1.3), (from below:1.3), (from front:1.2), close-up, cropped, out of frame, head out of frame"
SIDE_TAGS = {"from side", "profile"}   # the tagger must see one of these in a side-on shot
SHOT_CANDIDATES_SIDE = 6
TAG_SURE = 0.35
# What he does in each position. The act LoRAs learned mostly POV clips where he barely
# moves, so without this only she does.
HIS_MOTION = {
    "missionary": "he thrusts his hips into her hard and fast, his whole body moving",
    "doggy": "he grips her hips and slams his hips into her from behind, his body moving with each thrust",
    "cowgirl": "he thrusts his hips up into her from below to meet each bounce, his hands on her hips",
    "reverse cowgirl": "he thrusts his hips up into her from below to meet each bounce, his hands on her hips",
    "standing": "he stands behind her and thrusts his hips into her hard, his whole body moving",
    "blowjob": "his hips push forward into her mouth, his hand on her head",
}
from .acts import (GIRL_GIRL_MIDDLE as YURI_MIDDLE, GIRL_GIRL_PEAK as YURI_PEAK,
                   STRAIGHT_MIDDLE as MIDDLE, STRAIGHT_OPENERS as OPENERS)

# Girl-girl scenes (a post with 2girls and no man): their own acts (motion.ACTS has a LoRA for
# each but kissing). Each act: its tags for the picture, and the tags the tagger must see for
# the picture to show it.
YURI_POSITIONS = {
    "kissing": ("(french kiss:1.2), kissing, hug, embracing, nude, breasts press, cowboy shot", {"kiss", "french kiss"}),
    "fingering": ("(fingering:1.3), (lying on back:1.2), spread legs, hand between legs, nude, full body", {"fingering"}),
    "cunnilingus": ("(cunnilingus:1.3), oral, (lying on back:1.2), spread legs, head between thighs, nude, full body",
                    {"cunnilingus"}),
    "scissoring": ("(tribadism:1.3), scissoring, (lying:1.2), legs intertwined, nude, full body, from side", {"tribadism"}),
    "rimming": ("(anilingus:1.3), licking ass, face in ass, (all fours:1.2), ass, nude, full body", {"anilingus"}),
    "69": ("(69:1.3), cunnilingus, mutual oral, (lying:1.2), nude, full body", {"69"}),
    "toy": ("(dildo:1.3), sex toy, vaginal object insertion, holding dildo, spread legs, (lying on back:1.2), nude, "
            "full body", {"dildo", "vaginal object insertion", "object insertion"}),
    "strap-on": ("(strap-on:1.3), sex from behind, (doggystyle:1.2), all fours, nude, full body, from side", {"strap-on"}),
}
YURI_TOYS = {"toy", "strap-on"}            # shots where toys aren't kept out
# Which motion.ACTS act (its LoRA) animates each, where the names differ.
YURI_CLIP_ACT = {"69": "cunnilingus"}
YURI_MOTION = {
    "kissing": "they kiss deeply and slowly, their hands moving over each other's backs",
    "fingering": "one girl's fingers move in and out between the other's legs, her hips rising to meet them",
    "cunnilingus": "one girl licks between the other's thighs, her head moving, the other's hips rocking",
    "scissoring": "they grind their hips together in a steady rhythm, legs intertwined, bodies rocking",
    "rimming": "one girl licks her partner's ass, her tongue moving, her face pressed between her cheeks",
    "69": "they lick each other at the same time, heads moving, hips rocking",
    "toy": "one girl slides a dildo in and out of the other in a steady rhythm, her hips rising to meet it",
    "strap-on": "the girl wearing the strap-on thrusts her hips in a steady rhythm, her partner's body rocking",
}
YURI_STILL = "they hold each other: gentle breathing, small shifts; nobody new appears"
YURI_BOTH = {"2girls", "yuri"}                                 # one of these: both are there
# Nobody else. (Not "multiple girls": the tagger always adds it to 2girls.)
YURI_NOT = {"1boy", "penis", "testicles", "multiple boys", "3girls", "4girls"}
YURI_NEGATIVE = "1boy, penis, testicles, multiple boys, 3girls"
NO_TOYS = "dildo, strap-on, sex toy"
YURI_ONLY = re.compile(r"\b(kiss\w*|french kiss|fingering|cunnilingus|tribadism|scissoring|hug\w*|"
                       r"anilingus|69|dildo|strap-on|sex toy|object insertion|mutual oral|"
                       r"embrac\w*|cheek-to-cheek|selfie|holding phone|smile)\b", re.I)


def is_yuri(prompt: str) -> bool:
    from .acts import kind
    return kind(prompt) == "girl-girl"

NO_CUM = "cum, semen, cum on body, cum in pussy, cum in mouth, creampie, ejaculation, cum string"
# Every shot: the partner mustn't turn into a second copy of her, and no artist text.
SCENE_NEGATIVE = ("2girls, multiple girls, twins, watermark, signature, text, logo, patreon username, "
                  "comic, multiple views, panels, split screen, inset, furry male")
FURRY_PARTNER = {"furry male", "rabbit boy"}   # he's drawn as a second animal; a worse pick
# Pictures that lose to any without these: he isn't there (a penis through a wall), he's cut
# off at the edge, or the position turned into a different one.
NO_PARTNER = {"glory hole", "disembodied penis", "dildo", "sex toy", "penis on wall"}
CUT_OFF = {"head out of frame", "out of frame", "lower body"}
WRONG_POSE = {"doggy": {"standing sex", "standing split"}}   # he may stand; she mustn't
# What each shot keeps out of the picture, to match.
SHOT_NEGATIVE = {"doggy": "standing sex, she is standing", "blowjob": "wall", None: "pov, penis"}
PARTNER_NEGATIVE = "glory hole, disembodied penis, dildo, penis through wall"   # every shot
SOLO_FOCUS = 0.7   # "solo focus" this sure in a sex shot: he's barely there (a penis, no man)
PANELS = {"comic", "multiple views", "split screen", "inset", "4koma", "2koma", "panel"}   # a shot is one picture
FURRY_HIM_AVOID = "human male, cat boy, feminine male"   # a furry partner from the post
PARTNER = "faceless male"   # how artists often draw him; keeps him from borrowing her tags
# His look, one per scene, spelled out so he's the same man in every shot: (prompt, what to
# keep out, whether the tagger should read him as dark-skinned). Bald, like most anons in
# this art. Not grey: it reads as fur.
PARTNER_LOOKS = (
    ("(tan skin:1.2), (muscular male:1.1), (bald:1.2)", "dark skin, very dark skin, pale skin, black skin", False),
    ("(dark skin:1.2), dark-skinned male, (muscular male:1.1), (bald:1.2)", "pale skin, tan skin, light skin", True),
)
# Her hair, read off the post: the character often doesn't say, and then each shot guesses
# (long in one, none in the next). One colour, one length, plus a style if the tagger is sure.
HAIR_LENGTHS = ("very short hair", "short hair", "medium hair", "long hair", "very long hair")
HAIR_STYLES = {"ponytail", "twintails", "bob cut", "braid", "hair bun", "side ponytail", "pixie cut"}
NOT_HAIR = {"pubic hair", "female pubic hair", "male pubic hair", "body hair", "facial hair", "wet hair",
            "hair between eyes", "hair over one eye", "hair ornament", "hair flower", "hairband"}
# How furry she is, read off the post (a furry post only): these go in every shot weighted,
# and count toward a candidate's score. Without them, hair and a human-ish face pull her
# toward a bunny girl with skin.
FUR_TAGS = {"furry female": 1.3, "body fur": 1.25, "snout": 1.15, "animal nose": 1.1}
NOT_FURRY = "kemonomimi mode, human face, human skin, human nose, humanoid, skin"
# The room, drawn once per scene with nobody in it. Each shot is drawn on its own, then its
# characters are cut out and pasted onto the room (cutout.py), so it's the same room in all.
PLATE_CANDIDATES = 3
BLEND_DENOISE = 0.3   # the pass over each pasted shot: edges and light, not a new picture
PLATE_NEGATIVE = "1girl, 1boy, person, people, character, animal, furry, nude, text, watermark"
# The climax shows cum, but a little: the picture and the creampie LoRA each add their own.
CLIMAX_NEGATIVE = "cum overflow, excessive cum, cum pool, cum on floor, cum on legs, bukkake, cum string"
CROP = 0.04   # off the top and bottom of each shot: style LoRAs learn the artist's signature strip

# Her body, read off the post's picture and put in every shot: otherwise each picture draws
# its own (chubby in one, skinny in the next). One breast size, the most likely; build tags
# that pass. Each has the opposites to keep out of the picture.
BREASTS = {"flat chest": "large breasts, huge breasts", "small breasts": "large breasts, huge breasts",
           "medium breasts": "flat chest, huge breasts", "large breasts": "flat chest, small breasts",
           "huge breasts": "flat chest, small breasts, medium breasts",
           "gigantic breasts": "flat chest, small breasts, medium breasts"}
BUILD = {"plump": "skinny, slim", "chubby": "skinny, slim", "fat": "skinny, slim", "curvy": "skinny",
         "thick thighs": "skinny", "wide hips": "skinny", "voluptuous": "skinny",
         "slim": "plump, chubby, fat", "skinny": "plump, chubby, fat, thick thighs",
         "muscular female": "", "toned": "", "narrow waist": "", "short stack": "tall female"}


def _split(tags: str) -> list[str]:
    return [t.strip() for t in tags.split(",") if t.strip()]


def character_body(persona, prompt: str) -> list[str]:
    """Her build from the persona's character the post was made from (its other tags all in the
    post's prompt), as the persona file has it now: older posts may have a vaguer one."""
    have = set(_split(prompt))
    for c in (persona.characters if persona else []):
        tags = _split(c)
        core = [t for t in tags if t not in BREASTS and t not in BUILD]
        if core and set(core) <= have and "female" in core:
            return [t for t in tags if t in BREASTS or t in BUILD]
    # One-character personas say it in their look ("(medium breasts:1.3)").
    look = [re.sub(r"^\((.*):[\d.]+\)$", r"\1", t) for t in _split(persona.look if persona else "")]
    return [t for t in look if t in BREASTS or t in BUILD]


def body_tags(prompt_body: list[str], general: dict[str, float]) -> tuple[list[str], str]:
    """(her body tags, what to keep out): the character's build, and what the tagger reads off
    the post's picture where that says nothing (a breast size it can see; build tags)."""
    tags = list(prompt_body)
    if not BREASTS.keys() & set(tags):
        sizes = [(s, t) for t, s in general.items() if t in BREASTS and s >= TAG_SURE]
        tags += [max(sizes)[1]] if sizes else []
    tags += [t for t, s in sorted(general.items(), key=lambda kv: -kv[1])
             if t in BUILD and s >= TAG_SURE and t not in tags]
    avoid = {x.strip() for t in tags for x in (BREASTS.get(t) or BUILD.get(t) or "").split(",") if x.strip()}
    return tags, ", ".join(sorted(avoid - set(tags)))


# The post's background, in every shot: otherwise each picture draws its own room. What the
# tagger names goes in the prompt; colours it can't name are matched by picking candidates whose
# edges (top and sides, mostly background) are coloured like the post's.
BACKGROUND = {"tiles", "tile wall", "tile floor", "shower head", "shower (place)", "bathroom", "bathtub",
              "steam", "bedroom", "bed", "bed sheet", "pillow", "window", "curtains", "couch", "indoors",
              "outdoors", "beach", "ocean", "sand", "sky", "cloud", "sunset", "night", "night sky", "tree",
              "grass", "forest", "water", "pool", "onsen", "kitchen", "lamp", "door", "wooden floor",
              "carpet", "plant", "potted plant", "city", "building", "locker room", "classroom", "office"}
BG_WEIGHT = 0.6      # of a candidate's score: background colours against likeness to the post
# A shot whose frames drift this far from its first (one character turning into someone else
# mid-clip) is made again. Normal motion stays above 0.95.
DRIFT_MIN = 0.9
DRIFT_FRAMES = 16
STACK_SCALE = 0.8    # each LoRA's strength when a climax stacks two: at full strength they fight


def _edges(img: Image.Image) -> np.ndarray:
    """A colour histogram of the picture's top and sides, where the background mostly is."""
    a = np.asarray(img.convert("RGB").resize((96, 128)))
    strips = np.concatenate([a[:20].reshape(-1, 3), a[20:, :12].reshape(-1, 3), a[20:, -12:].reshape(-1, 3)])
    h, _ = np.histogramdd(strips // 32, bins=(8, 8, 8), range=((0, 8),) * 3)
    return (h / h.sum()).ravel()


# Named colours for the walls, as the image model knows them (RGB).
COLOURS = {"white": (235, 235, 235), "light grey": (190, 190, 192), "grey": (150, 152, 156), "dark grey": (70, 72, 76), "black": (25, 25, 28),
           "blue": (70, 120, 190), "light blue": (160, 200, 225), "teal": (80, 160, 160),
           "beige": (215, 195, 160), "brown": (120, 85, 55), "pink": (225, 160, 180), "green": (100, 160, 100)}
WALLS = {"tiles": "tiles", "tile wall": "tile wall", "tile floor": "tile floor", "indoors": "walls"}


def wall_colour(img: Image.Image) -> str:
    """The nearest named colour to the picture's top corners, where the wall mostly is (the
    middle of the top edge often has her head in it)."""
    a = np.asarray(img.convert("RGB").resize((96, 128)))
    a = np.concatenate([a[:32, :18].reshape(-1, 3), a[:32, -18:].reshape(-1, 3)]).astype(np.float32)
    mid = np.median(a, axis=0)   # the median: highlights and her ears don't count
    return min(COLOURS, key=lambda c: float(((np.array(COLOURS[c]) - mid) ** 2).sum()))


# Words in a post's prompt that name where it is (its {setting}), for the empty room.
SETTING_WORDS = {"shower", "bathroom", "bedroom", "beach", "beach at sunset", "hot spring", "steam", "onsen",
                 "kitchen", "living room", "classroom", "office", "forest", "pool", "night", "sunset", "city"}


def draw_plate(cfg, comfy, post: dict, room: str, lora, negative: str, subdir: str, name: str,
               rng: random.Random, post_edges: np.ndarray) -> Path | None:
    """The scene's room with nobody in it, coloured like the post's; None if every try had
    someone in it (then shots start from noise, as before)."""
    from .vision import Vision
    prompt = f"no humans, scenery, empty room, detailed background, {room}"
    try:
        paths = [comfy.txt2img(post["checkpoint"], post["medium"], prompt, rng.randrange(2 ** 32), subdir,
                               f"{name}-room-{c}", extra_negative=", ".join(n for n in (negative, PLATE_NEGATIVE) if n),
                               strict=post["strict"], lora=lora) for c in range(PLATE_CANDIDATES)]
    finally:
        comfy.stop()
    vision = Vision(cfg.models_dir)
    scored = []
    try:
        for p in paths:
            with Image.open(p) as im:
                img = im.convert("RGB")
            a = vision.analyze([img])
            if a.general.get("no humans", 0) < 0.5 or a.general.get("1girl", 0) >= TAG_SURE:
                continue
            scored.append((float(np.minimum(_edges(img), post_edges).sum()), p))
    finally:
        vision.close()
    best = max(scored)[1] if scored else None
    for p in paths:
        if p != best:
            p.unlink(missing_ok=True)
    print(f"scene: room {'drawn' if best else 'not drawn (people in every try)'}: {room}", flush=True)
    return best


def background_tags(general: dict[str, float], cast: str) -> list[str]:
    have = set(_split(cast))
    return [t for t, sc in sorted(general.items(), key=lambda kv: -kv[1])
            if t in BACKGROUND and sc >= TAG_SURE and t not in have]


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
    loops: int = 2     # times the 5-second clip plays before the cut
    climax: str = ""   # motion.CLIMAXES name: the clip adds that LoRA to the position's, and plays
                       # once without looping (a climax builds; it doesn't reset)
    yuri: bool = False   # a girl-girl shot: act is a YURI_POSITIONS name


def _frames(path: Path) -> np.ndarray:
    """Every frame of a video, as one RGB array."""
    import subprocess
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=60).stdout.strip().split(",")
    w, h = int(probe[0]), int(probe[1])
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, timeout=300, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)


def _sample(frames: np.ndarray, count: int) -> list[Image.Image]:
    idx = [int(len(frames) * (i + 0.5) / count) for i in range(count)]
    return [Image.fromarray(frames[i]) for i in idx]


def hair_tags(general: dict[str, float]) -> tuple[list[str], str]:
    """(her hair tags, what to keep out) from the tagger's scores for the post's picture."""
    sure = {t: sc for t, sc in general.items() if sc >= TAG_SURE}
    colours = [(sc, t) for t, sc in sure.items() if t.endswith(" hair") and t not in NOT_HAIR
               and t not in HAIR_LENGTHS and t not in ("multicolored hair", "two-tone hair", "gradient hair")]
    lengths = [(sc, t) for t, sc in sure.items() if t in HAIR_LENGTHS]
    tags = [max(colours)[1]] if colours else []
    tags += [max(lengths)[1]] if lengths else []
    tags += [t for t in sure if t in HAIR_STYLES]
    avoid = [t for t in HAIR_LENGTHS if lengths and t != max(lengths)[1]]
    return tags, ", ".join(avoid)


def cast_tags(prompt: str, partner: str = "", faceless: bool = True) -> str:
    """The post's prompt minus everything that belongs to the act: who and where. partner: his
    look, the same in every shot of a scene. faceless: draw him as a faceless male (a human
    partner; a furry one from the post is drawn as the post says)."""
    keep = [t.strip() for t in prompt.split(",") if t.strip() and not SCENE_ONLY.search(t)]
    keep = [t for t in keep if t not in ("duo", "male", "1boy", PARTNER)]
    # Rating first, then the pair, then her.
    rating = [t for t in keep if t in ("nsfw", "explicit", "questionable")]
    rest = [t for t in keep if t not in rating]
    return ", ".join(rating + ["duo"] + ([PARTNER] if faceless else ["1boy"]) + ([partner] if partner else []) + rest)


def plan(rng: random.Random, picks: dict | None = None) -> list[Shot]:
    """Opener, a position, a close-up in it, another position, the climax in that one, after.
    picks: acts.SLOTS choices ({"opening", "first", "second"}); the rest at random."""
    picks = picks or {}
    opener = picks.get("opening") or rng.choice(OPENERS)
    a = picks.get("first") or rng.choice([p for p in MIDDLE if p not in (opener, picks.get("second"))])
    b = picks.get("second") or rng.choice([p for p in MIDDLE if p not in (a, opener)] or [p for p in MIDDLE if p != a])
    act = lambda name: POSITIONS[name][1]

    def pos(name: str, view: str = SIDE_ON) -> str:
        return POSITIONS[name][0] if name == "blowjob" else f"{POSITIONS[name][0]}, {view}"
    return [
        Shot(f"opening: {opener}", f"{pos(opener)}, blush, half-closed eyes", act(opener), False,
             "slow and gentle, just starting"),
        Shot(f"{a}", f"{pos(a)}, blush, open mouth", act(a), False,
             "a steady rhythm"),
        # No "close-up" here: in this kind of art it draws inset panels.
        Shot(f"{a}, from the side", f"{pos(a, '(from side:1.3), (three-quarter view:1.1), (full body:1.2)')}, blush, open mouth, sweat, "
             "heavy breathing", act(a), False, "faster, she's lost in it"),
        Shot(f"{b}", f"{pos(b)}, open mouth, sweat, heavy breathing, motion lines", act(b), False,
             "fast and intense, building toward climax"),
        Shot(f"climax: {b}", f"{pos(b)}, orgasm, cum in pussy, trembling, open mouth, "
             "sweat", act(b), True, "the climax: he cums inside her, both shuddering", loops=1, climax="creampie"),
        Shot("aftermath", "after sex, lying, on back, cum in pussy, cum on body, sweat, heavy breathing, "
             "half-closed eyes, smile", None, True, "slow, catching their breath", loops=1),
    ]


def plan_yuri(rng: random.Random, picks: dict | None = None) -> list[Shot]:
    """Kissing, two of YURI_MIDDLE, one of YURI_PEAK and the climax in it, cuddling after.
    picks: acts.SLOTS choices ({"first", "second", "peak"}); the rest at random."""
    picks = picks or {}
    a = picks.get("first") or rng.choice([x for x in YURI_MIDDLE if x != picks.get("second")])
    b = picks.get("second") or rng.choice([x for x in YURI_MIDDLE if x != a])
    peak = picks.get("peak") or rng.choice(YURI_PEAK)
    pos = lambda name: YURI_POSITIONS[name][0]
    return [
        Shot("opening: kissing", f"{pos('kissing')}, blush, half-closed eyes", "kissing", False,
             "slow and tender, just starting", yuri=True),
        Shot(a, f"{pos(a)}, blush, open mouth", a, False, "a steady rhythm", yuri=True),
        Shot(b, f"{pos(b)}, blush, open mouth, sweat, heavy breathing", b, False,
             "faster, she's lost in it", yuri=True),
        Shot(peak, f"{pos(peak)}, open mouth, sweat, heavy breathing", peak, False,
             "fast and intense, building toward climax", yuri=True),
        Shot(f"climax: {peak}", f"{pos(peak)}, orgasm, (female ejaculation:1.2), squirting, "
             "trembling, arched back, pussy juice, open mouth, sweat", peak, True,
             "the climax: both shuddering as they squirt, holding each other", loops=1, climax="squirt", yuri=True),
        Shot("aftermath", "after sex, lying together, cuddling, hug, nude, smile, sweat, half-closed eyes",
             None, False, "slow, catching their breath", loops=1, yuri=True),
    ]


def yuri_cast(prompt: str) -> str:
    """The post's prompt minus its act and framing: the two of them, and where."""
    keep = [t for t in _split(prompt) if not SCENE_ONLY.search(t) and not YURI_ONLY.search(t)]
    keep = [t for t in keep if t not in ("duo", "2girls", "yuri")]
    rating = [t for t in keep if t in ("nsfw", "explicit", "questionable")]
    return ", ".join(rating + ["duo", "2girls", "yuri"] + [t for t in keep if t not in rating])


def _bare(tag: str) -> str:
    return re.sub(r"^\((.*):[\d.]+\)$", r"\1", tag.strip())


def _crop(path: Path) -> None:
    with Image.open(path) as im:
        im = im.convert("RGB")
        w, h = im.size
        cut = round(h * CROP)
        im = im.crop((0, cut, w, h - cut))
    im.save(path)


@dataclass
class Kind:
    """What one kind of scene (straight, girl-girl) needs from the shared drawing pipeline."""
    cast: str                                  # who and where, the same in every shot
    avoid: str                                 # kept out of every shot
    regions: list | None                       # each character again in her own half
    negative: callable                         # shot -> its negative prompt
    candidates: callable                       # shot -> how many pictures to draw
    fits: callable                             # (shot, seen, analysis) -> sortable tuple, best first
    note: callable                             # (fits) -> what the winner lacks, for the log
    halves: callable = lambda shot: True       # shot -> whether to use regions in it


def _straight(persona, post: dict, seen_post, rng: random.Random) -> Kind:
    """One woman and a man: her build, hair and fur from the post; him one look for the scene."""
    body, avoid = body_tags(character_body(persona, post["prompt"]), seen_post.general)
    # A post that says he's a furry (a persona's own partner) keeps him: his look is in the
    # post's prompt. Otherwise one of the human looks.
    furry_him = "furry male" in _split(post["prompt"])
    him, him_avoid, him_dark = ("", FURRY_HIM_AVOID, None) if furry_him else rng.choice(PARTNER_LOOKS)
    cast = cast_tags(post["prompt"], him, faceless=not furry_him)
    hair, hair_avoid = hair_tags(seen_post.general)
    if hair:
        cast += ", " + ", ".join(hair)
    fur = [t for t in FUR_TAGS if post["medium"] == "furry" and seen_post.general.get(t, 0) >= TAG_SURE]
    if fur:   # her fur colour too: the room's grey tints white fur otherwise
        cast = ", ".join(f"({t}:1.25)" if t.endswith(" fur") else t for t in _split(cast))
        cast += ", " + ", ".join(f"({t}:{FUR_TAGS[t]})" for t in fur)
    # Her avoid list goes in her half only when there are halves (his look may need short hair).
    regions = persona.regions(post["prompt"], rng) if persona else None
    avoid = ", ".join(a for a in (avoid, him_avoid, NOT_FURRY if fur else "",
                                  "" if regions else hair_avoid) if a)
    if body:   # her build once, weighted, in place of whatever the post's prompt said
        cast = ", ".join(t for t in _split(cast) if t not in BREASTS and t not in BUILD)
        cast += ", " + ", ".join(f"({t}:1.2)" for t in body)

    def negative(shot: Shot) -> str:
        side_on = shot.act not in (None, "blowjob")
        return ", ".join(n for n in (SCENE_NEGATIVE, "" if shot.cum else NO_CUM,
                                     SIDE_ON_NEGATIVE if side_on else "", SHOT_NEGATIVE.get(shot.act, ""),
                                     PARTNER_NEGATIVE, CLIMAX_NEGATIVE if shot.climax else "") if n)

    def fits(shot: Shot, seen: set, a) -> tuple:
        shows = {act.name for act in motion.ACTS if seen & set(act.tags)}
        # Side-on, the tagger can't tell which way she faces on top.
        if shot.act == "reverse cowgirl" and "cowgirl" in shows:
            shows.add("reverse cowgirl")
        # Showing the intended act matters more than looking like the post: the position,
        # and the penis actually in it (a cowgirl on his lap with nothing inside isn't).
        need = ORAL if shot.act == "blowjob" else PENETRATION if shot.act else None
        act_ok = (shot.act is None or shot.act in shows) and \
            (need is None or (need[0] <= seen and bool(need[1] & seen)))
        # Then side-on, for penetration: from below, Wan loses the penis at the edge.
        side = shot.act in (None, "blowjob") or bool(SIDE_TAGS & seen)
        # The tagger reads her as the post's build and hair, and him in his skin.
        same = sum(t in seen for t in body + hair + fur) + \
            int("furry male" in seen if furry_him else ("dark-skinned male" in seen) == him_dark)
        bad = (set() if furry_him else FURRY_PARTNER) | NO_PARTNER | WRONG_POSE.get(shot.act, set()) | \
            (CUT_OFF if shot.act not in (None, "blowjob") else set())
        missing = bool(NO_PARTNER & seen) or (shot.act is not None and a.general.get("solo focus", 0) >= SOLO_FOCUS)
        # He must be there before anything else counts: a fallback pick must never be a
        # penis through the wall.
        return (not missing and not (bad & seen), act_ok, side, same)

    total = len(body) + len(hair) + len(fur) + 1
    return Kind(cast, avoid, regions, negative,
                lambda shot: SHOT_CANDIDATES_SIDE if shot.act not in (None, "blowjob") else SHOT_CANDIDATES,
                fits,
                lambda f: f"{'' if f[0] else 'partner missing or cut off, '}{'' if f[1] else 'act not seen, '}"
                          f"{'' if f[2] else 'not side-on, '}her and him {f[3]}/{total}",
                # Halves sit them side by side: only after (an act needs them together).
                halves=lambda shot: shot.act is None)


def _girl_girl(persona, post: dict, seen_post, rng: random.Random) -> Kind:
    """Two women: both in every shot and nobody else."""
    regions = persona.regions(post["prompt"], rng) if persona else None
    traits = {_bare(t) for r in regions or [] for t in r[0].split(",")} - {"adult", "mature female", "anthro"}

    def negative(shot: Shot) -> str:
        # (cum means squirting here: NO_CUM would keep "ejaculation" out of the climax.)
        return ", ".join(n for n in (YURI_NEGATIVE, "twins, watermark, signature, text, logo, patreon username",
                                     "" if shot.cum else NO_CUM, "" if shot.act in YURI_TOYS else NO_TOYS,
                                     "close-up, cropped, out of frame, head out of frame",
                                     # Side by side and standing is what two characters default to.
                                     "" if shot.act in (None, "kissing") else "standing, side-by-side") if n)

    def fits(shot: Shot, seen: set, a) -> tuple:
        both = bool(YURI_BOTH & seen) and not (YURI_NOT & seen) and not (CUT_OFF & seen)
        shows = shot.act is None or bool(YURI_POSITIONS[shot.act][1] & seen)
        return (both, shows, len(traits & seen))

    return Kind(yuri_cast(post["prompt"]), "", regions, negative,
                lambda shot: SHOT_CANDIDATES_SIDE if shot.act not in (None, "kissing") else SHOT_CANDIDATES,
                fits,
                lambda f: f"{'' if f[0] else 'not just the two of them, '}{'' if f[1] else 'act not seen, '}"
                          f"their looks {f[2]}/{len(traits)}",
                # Halves stand them side by side, upright: only where that's the pose.
                halves=lambda shot: shot.act in (None, "kissing"))


def draw(cfg, comfy, persona, post: dict, shots: list[Shot], subdir: str, name: str,
         rng: random.Random, keep_room: Path | None = None) -> list[tuple[Path | None, str]]:
    """One checked picture per shot: (path or None, note), for any kind of scene (Kind). The
    room is drawn once; of each shot's candidates, the one that best shows what the kind needs,
    then looks most like the post, wins, and is pasted into the room. Losers are deleted;
    winners are cropped (CROP). The room is deleted too, or moved to keep_room."""
    from . import captions
    from .checks import problem
    from .vision import Vision
    # The post first: its likeness to score candidates by, and her body for every shot.
    vision = Vision(cfg.models_dir)
    try:
        with Image.open(post["file"]) as im:
            seen_post = vision.analyze([im.convert("RGB")])
    finally:
        vision.close()
    base = seen_post.embedding.astype(np.float32)
    kind = (_girl_girl if any(s.yuri for s in shots) else _straight)(persona, post, seen_post, rng)
    cast = kind.cast
    room = background_tags(seen_post.general, cast)
    with Image.open(post["file"]) as im:
        post_edges, colour = _edges(im), wall_colour(im)
    # The walls in the post's colour: "tiles" alone draws them blue in one shot, beige the next.
    walls = [f"({colour} {WALLS[t]}:1.2)" for t in room if t in WALLS]
    if room:
        cast += ", " + ", ".join(walls + [f"({t}:1.1)" for t in room if t not in WALLS])
    print(f"scene: cast and setting: {cast}; keeping out: {kind.avoid}; "
          f"each in their half: {bool(kind.regions)}", flush=True)
    lora = persona.lora_for(post["prompt"]) if persona else None
    negative = persona.negative if persona else ""
    room_tags = ", ".join(walls + [f"({t}:1.1)" for t in room if t not in WALLS] +
                          [t for t in _split(post["prompt"]) if t in SETTING_WORDS])
    plate = draw_plate(cfg, comfy, post, room_tags, lora, negative, subdir, name, rng, post_edges)
    cands: list[list[Path]] = []
    asks: list[tuple[str, str]] = []   # each shot's prompt and negative, for the blending pass
    try:
        for i, shot in enumerate(shots):
            neg = ", ".join(n for n in (negative, kind.avoid, kind.negative(shot)) if n)
            asks.append((f"{cast}, {shot.tags}", neg))
            cands.append([comfy.txt2img(post["checkpoint"], post["medium"], asks[-1][0],
                                        rng.randrange(2 ** 32), subdir, f"{name}-shot{i}-{c}",
                                        extra_negative=neg, strict=post["strict"], lora=lora,
                                        regions=kind.regions if kind.halves(shot) else None)
                          for c in range(kind.candidates(shot))])
    finally:
        comfy.stop()
    vision = Vision(cfg.models_dir)
    out = []
    try:
        for shot, paths in zip(shots, cands):
            scored = []
            for p in paths:
                with Image.open(p) as im:
                    img = im.convert("RGB")
                a = vision.analyze([img])
                if problem(a, post["medium"], [img], cfg, strict=post["strict"]):
                    continue
                if PANELS & set(captions.picture(a.general)):
                    continue
                # Every tag the tagger is sure of: its top-tags list cuts off "penis" and the view.
                seen = {t for t, sc in a.general.items() if sc >= TAG_SURE}
                fits = kind.fits(shot, seen, a)
                look = float(a.embedding.astype(np.float32) @ base)
                bg = float(np.minimum(_edges(img), post_edges).sum())   # 1 = the same colours
                scored.append((fits, (1 - BG_WEIGHT) * look + BG_WEIGHT * bg, p, look, bg))
            best = max(scored, key=lambda s: s[:2]) if scored else None
            for p in paths:
                if not best or p != best[2]:
                    p.unlink(missing_ok=True)
            out.append((best[2], f"{kind.note(best[0])}, look {best[3]:.2f}, background {best[4]:.2f}") if best
                       else (None, f"all {len(paths)} failed the checks"))
    finally:
        vision.close()
    try:
        if plate:
            into_room(cfg, comfy, post, plate, out, asks, lora, subdir, name, rng,
                      regions=[kind.regions if kind.halves(s) else None for s in shots])
    finally:
        if plate and keep_room:
            plate.replace(keep_room)
        elif plate:
            plate.unlink(missing_ok=True)
    for path, _ in out:
        if path:
            _crop(path)
    return out


def into_room(cfg, comfy, post: dict, plate: Path, out: list, asks: list, lora, subdir: str, name: str,
              rng: random.Random, regions: list | None = None) -> None:
    """Each winning shot's characters, cut out and pasted onto the scene's room, then a light
    pass of the image model to blend the edges and light, with the room's own pixels put back
    everywhere away from them. A shot whose blended picture fails a check keeps its own room."""
    from . import cutout
    from .checks import problem
    from .vision import Vision
    with Image.open(plate) as im:
        room = im.convert("RGB")
    cut = cutout.Cutout()
    try:
        masks = []
        for path, _ in out:
            if path is None:
                masks.append(None)
                continue
            with Image.open(path) as im:
                masks.append(cut.mask(im.convert("RGB")))
    finally:
        cut.close()
    pasted: list[Path | None] = []
    try:
        for i, ((path, _), mask) in enumerate(zip(out, masks)):
            if path is None:
                pasted.append(None)
                continue
            with Image.open(path) as im:
                comp = cutout.paste(room, im.convert("RGB"), mask)
            comp_path = path.with_name(f"{path.stem}-pasted.png")
            comp.save(comp_path)
            blended = comfy.txt2img(post["checkpoint"], post["medium"], asks[i][0], rng.randrange(2 ** 32),
                                    subdir, f"{name}-shot{i}-blend", extra_negative=asks[i][1],
                                    strict=post["strict"], lora=lora, init=comp_path, denoise=BLEND_DENOISE,
                                    regions=regions[i] if regions else None)
            comp_path.unlink(missing_ok=True)
            with Image.open(blended) as im:
                final = cutout.keep_room(room, im.convert("RGB"), mask)
            blended.unlink(missing_ok=True)
            final_path = path.with_name(f"{path.stem}-room.png")
            final.save(final_path)
            pasted.append(final_path)
    finally:
        comfy.stop()
    vision = Vision(cfg.models_dir)
    try:
        for i, final_path in enumerate(pasted):
            if final_path is None:
                continue
            with Image.open(final_path) as im:
                img = im.convert("RGB")
            a = vision.analyze([img])
            if problem(a, post["medium"], [img], cfg, strict=post["strict"]):
                final_path.unlink(missing_ok=True)
                out[i] = (out[i][0], out[i][1] + ", own room (the pasted one failed a check)")
                continue
            final_path.replace(out[i][0])
    finally:
        vision.close()


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
    ap.add_argument("--acts", help="acts.SLOTS picks, e.g. first=doggy,second=standing (the rest random)")
    a = ap.parse_args(args)
    from .acts import checked
    picked_raw = dict(x.split("=", 1) for x in a.acts.split(",")) if a.acts else {}
    cfg = Config()
    gen = cfg.generation()
    conn = db.connect(cfg.db_path)
    post = load_post(cfg, conn, a.post)
    persona = {p.handle: p for p in people.load(cfg.personas_path)}.get(post["persona"])
    rng = random.Random(a.seed)
    picked = checked(post["prompt"], picked_raw)
    shots = plan_yuri(rng, picked) if is_yuri(post["prompt"]) else plan(rng, picked)
    out_dir = cfg.data_dir / "generated"
    subdir = f"scene-preview-{a.post}"
    comfy = Comfy(gen.comfy_url, gen.supervisor_url, out_dir)
    pictures = draw(cfg, comfy, persona, post, shots, subdir, f"post{a.post}", rng,
                    keep_room=out_dir / subdir / "room.png")
    sheet = contact_sheet(post["file"], shots, pictures, out_dir / subdir / "contact-sheet.jpg")
    from dataclasses import asdict
    (out_dir / subdir / "plan.json").write_text(json.dumps(
        [asdict(s) | {"picture": str(p) if p else None, "note": n} for s, (p, n) in zip(shots, pictures)], indent=1))
    print(f"scene-preview: {sheet}", flush=True)


def _motion_of(shot: Shot) -> str:
    """What both of them do in the shot, for the video model."""
    if shot.yuri:
        return YURI_MOTION.get(shot.act, YURI_STILL)
    return HIS_MOTION.get(shot.act, "")


def _shot_prompt(writer, cast: str, shot: Shot, act) -> str | None:
    """A written, checked description of the shot's motion for its point in the scene."""
    move = _motion_of(shot)
    where = (f"This is one shot of a longer scene: {shot.pace}. The clip loops, so the motion is a "
             f"repeating cycle that ends where it started." +
             (f" Both of them move: {move}." if move and shot.act else
              f" {YURI_STILL}." if shot.yuri else
              " Only she moves: gentle breathing, small shifts; nobody new appears."))
    return motion.describe(writer, [t.strip() for t in f"{cast}, {shot.tags}".split(",")], act, context=where)


def render(cfg, comfy, post: dict, shots: list[Shot], pictures: list[Path | None], out: Path,
           rng: random.Random, progress=None, cancelled=lambda: False, act_strength: float | None = None,
           style_strength: float | None = None, wan: dict | None = None,
           seed: int | None = None) -> tuple[Path | None, list[str]]:
    """Animate each shot's picture into a 5-second loop (Wan, first and last frame the same
    picture), check it, play it shot.loops times, and cut to the next. Returns the scene file
    (None if no shot passed) and a note per shot."""
    import subprocess
    from . import personas as people, videolora
    from .comfy import WAN
    from .generate import MOTION
    gen = cfg.generation()
    persona = {p.handle: p for p in people.load(cfg.personas_path)}.get(post["persona"])
    own = persona and persona.lora and videolora.for_style(cfg, persona.lora[0])
    acts = {a.name: a for a in motion.ACTS}
    cast = yuri_cast(post["prompt"]) if any(s.yuri for s in shots) else cast_tags(post["prompt"])
    # Descriptions first: the text model and Wan don't share the GPU.
    comfy.stop()
    texts = [None] * len(shots)
    if cfg.caption_model:
        from .captions import Writer
        writer = Writer(cfg.caption_model)
        try:
            for i, shot in enumerate(shots):
                clip_act = motion.CLIMAXES.get(shot.climax) or acts.get(YURI_CLIP_ACT.get(shot.act, shot.act))
                texts[i] = _shot_prompt(writer, cast, shot, clip_act)
        finally:
            writer.close()
    # Each shot's motion LoRAs and prompt.
    jobs: dict[int, tuple] = {}
    for i, (shot, pic) in enumerate(zip(shots, pictures)):
        if pic is None:
            continue
        # The position's motion LoRA, plus the climax's on a climax shot.
        own_act = acts.get(YURI_CLIP_ACT.get(shot.act, shot.act)) if shot.yuri else acts.get(shot.act)
        used = [a for a in (own_act, motion.CLIMAXES.get(shot.climax)) if a]
        with_lora = [(a, motion.lora_for(a, gen.act_lora, cfg.models_dir)) for a in used]
        with_lora = [(a, l) for a, l in with_lora if l]
        # The shared act LoRA at ACT_STRENGTH; an act's own LoRA at the strength it's made for.
        scale = STACK_SCALE if len(with_lora) > 1 else 1.0
        with_lora = [(a, (l[0], l[1], round(scale * (act_strength if act_strength is not None
                                                      else l[2] if a.lora else ACT_STRENGTH), 2)))
                     for a, l in with_lora]
        style_s = STYLE_STRENGTH if style_strength is None else style_strength
        loras = [l for _, l in with_lora] + ([(own[0], own[1], style_s)] if own and style_s > 0 else [])
        clip_act = used[-1] if used else None
        body = texts[i] or ", ".join(p for p in (clip_act.motion if clip_act else "", shot.pace) if p)
        body = ", ".join(p for p in (body, _motion_of(shot)) if p)
        prompt = ", ".join(p for p in (own[2] if own else "", *(a.trigger for a, _ in with_lora),
                                       body, MOTION[post["medium"]]) if p)
        jobs[i] = (pic, prompt, loras, "ok " + " + ".join(l[0].split("-high")[0] for _, l in with_lora))
    # Every shot, then all the checks (loading their models once), then again for the ones
    # that failed. ComfyUI restarts after each clip: kept running, Wan's models pile up in RAM
    # and the second clip runs the server out of memory.
    clips: dict[int, np.ndarray] = {}
    pending, made = sorted(jobs), 0
    for attempt in range(SHOT_TRIES):
        if not pending or cancelled():
            break
        paths: dict[int, Path] = {}
        try:
            for i in pending:
                if cancelled():
                    break
                pic, prompt, loras, _ = jobs[i]
                paths[i] = comfy.img2vid("wan", pic, post["medium"], prompt,
                                         seed if seed is not None else rng.randrange(2 ** 32), out.parent.name,
                                         f"{out.stem}-shot{i}", strict=post["strict"], loras=loras,
                                         end=None if shots[i].climax else pic, wan=SCENE_WAN | (wan or {}))
                comfy.stop()
                made += 1
                if progress:
                    progress(min(made, len(jobs)), len(jobs))
        finally:
            comfy.stop()
        frames = {}
        for i, path in paths.items():
            frames[i] = _frames(path)
            path.unlink(missing_ok=True)
        for i, reason in _check_shots(cfg, frames, post).items():
            if reason:
                print(f"scene: shot {i + 1} try {attempt + 1} dropped ({reason[0]}: {reason[1]})", flush=True)
            else:
                clips[i] = frames[i]
                print(f"scene: shot {i + 1} {shots[i].name}: {jobs[i][3]}", flush=True)
        pending = [i for i in pending if i not in clips]
    notes = []
    for i, shot in enumerate(shots):
        notes.append(jobs[i][3] if i in clips else "no picture" if i not in jobs else
                     "cancelled" if cancelled() else f"dropped after {SHOT_TRIES} tries")
    if not clips:
        return None, notes
    h, w = next(iter(clips.values())).shape[1:3]
    writer = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
         "-r", str(WAN["fps"]), "-i", "-", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)
    try:
        for i in sorted(clips):
            cycle = (clips[i] if shots[i].climax else clips[i][:-1]).tobytes()   # a loop's last frame is its first
            for _ in range(shots[i].loops):
                writer.stdin.write(cycle)
        writer.stdin.close()
        if writer.wait() != 0:
            raise RuntimeError("ffmpeg couldn't join the shots")
        return out, notes
    except BaseException:
        writer.kill()
        writer.wait()
        out.unlink(missing_ok=True)
        raise


def _check_shots(cfg, clips: dict[int, np.ndarray], post: dict) -> dict[int, tuple[str, str] | None]:
    """_check_shot for several clips, loading the models once."""
    from .vision import Vision
    if not clips:
        return {}
    vision = Vision(cfg.models_dir)
    try:
        return {i: _check_shot(cfg, frames, post, vision) for i, frames in clips.items()}
    finally:
        vision.close()


def _check_shot(cfg, frames: np.ndarray, post: dict, vision) -> tuple[str, str] | None:
    """The clip checks, and that no frame drifts away from the first (a morph)."""
    from .checks import problem
    from .generate import VIDEO_CHECK_FRAMES
    sample = _sample(frames, VIDEO_CHECK_FRAMES)
    a = vision.analyze(sample)
    reason = problem(a, post["medium"], sample, cfg, strict=post["strict"])
    if reason:
        return reason
    embs = vision.embed([Image.fromarray(frames[0])] + _sample(frames, DRIFT_FRAMES))
    low = float((embs[1:] @ embs[0]).min())
    return ("drift", f"a frame is only {low:.2f} like the first") if low < DRIFT_MIN else None


def render_preview(args: list[str]) -> None:
    """scene-render POST_ID [--shots 4,5]: animate the pictures scene-preview drew."""
    from . import db
    from .comfy import Comfy
    from .config import Config
    from dataclasses import fields
    ap = argparse.ArgumentParser(prog="dreamfeed scene-render")
    ap.add_argument("post", type=int)
    ap.add_argument("--shots", help="which shots, e.g. 4,5 (default all)")
    ap.add_argument("--act-strength", type=float)
    ap.add_argument("--style-strength", type=float, help="0 turns the style video LoRA off")
    ap.add_argument("--motion-steps", type=int, help="steps without the speed-up LoRA (WAN motion_steps)")
    ap.add_argument("--high-steps", type=int, help="steps on the high-noise expert (WAN high_steps)")
    ap.add_argument("--size", help="WxH, e.g. 576x848")
    ap.add_argument("--seed", type=int, help="the same seed for every try, to compare settings")
    ap.add_argument("--out", default="scene.mp4")
    a = ap.parse_args(args)
    cfg = Config()
    gen = cfg.generation()
    conn = db.connect(cfg.db_path)
    post = load_post(cfg, conn, a.post)
    out_dir = cfg.data_dir / "generated"
    subdir = out_dir / f"scene-preview-{a.post}"
    saved = json.loads((subdir / "plan.json").read_text())
    names = {f.name for f in fields(Shot)}
    shots = [Shot(**{k: v for k, v in d.items() if k in names}) for d in saved]
    pics = [Path(d["picture"]) if d["picture"] else None for d in saved]
    if a.shots:
        pick = [int(x) - 1 for x in a.shots.split(",")]
        shots, pics = [shots[i] for i in pick], [pics[i] for i in pick]
    comfy = Comfy(gen.comfy_url, gen.supervisor_url, out_dir)
    wan = {}
    if a.motion_steps is not None:
        wan["motion_steps"] = a.motion_steps
    if a.high_steps is not None:
        wan["high_steps"] = a.high_steps
    if a.size:
        wan["width"], wan["height"] = (int(x) for x in a.size.lower().split("x"))
    path, notes = render(cfg, comfy, post, shots, pics, subdir / a.out, random.Random(),
                         act_strength=a.act_strength, style_strength=a.style_strength, wan=wan or None, seed=a.seed)
    print(f"scene-render: {path} {notes}", flush=True)


def run_job(cfg, conn, job_id: int, params: dict) -> None:
    """A "Make a scene" request from the viewer: params {"kind": "scene", "ids": [post]}."""
    import datetime as dt
    from . import personas as people
    from .comfy import Comfy
    from .generate import _cancel_requested, _finish, _progress, _set, check_videos
    night = f"scene-{dt.datetime.now():%Y%m%d-%H%M%S}"
    with conn:
        conn.execute("UPDATE jobs SET status = 'running', night = ? WHERE id = ?", (night, job_id))
        conn.execute("INSERT INTO runs(night, status, attempts, started_at) VALUES (?, 'running', 1, datetime('now'))",
                     (night,))
    status, message, pictures = "done", None, []
    gen = cfg.generation()
    out_dir = cfg.data_dir / "generated"
    comfy = Comfy(gen.comfy_url, gen.supervisor_url, out_dir)
    try:
        src = int(params["ids"][0])
        post = load_post(cfg, conn, src)
        persona = {p.handle: p for p in people.load(cfg.personas_path)}.get(post["persona"])
        rng = random.Random()
        from .acts import checked
        picked = checked(post["prompt"], params.get("picks"))
        shots = plan_yuri(rng, picked) if is_yuri(post["prompt"]) else plan(rng, picked)
        with conn:
            gid = conn.execute(
                "INSERT INTO generations(night, medium, checkpoint, prompt, seed, source_generation, persona,"
                " caption, kind, status) SELECT ?, medium, 'wan2.2-i2v scene', ?, 0, id, persona, caption,"
                " 'video', 'queued' FROM generations WHERE id = ?",
                (night, " | ".join(s.name for s in shots), src)).lastrowid
        _progress(conn, night, "drawing", 0, len(shots))
        drawn = draw(cfg, comfy, persona, post, shots, night, f"scene-{gid}", rng)
        pictures = [p for p, _ in drawn if p]
        _progress(conn, night, "animating", 0, len(shots))
        path, notes = render(cfg, comfy, post, shots, [p for p, _ in drawn], out_dir / night / f"video-{gid}.mp4",
                             rng, progress=lambda d, t: _progress(conn, night, "animating", d, t),
                             cancelled=lambda: _cancel_requested(conn, night))
        print(f"scene: {night} {notes}", flush=True)
        if path:
            from .comfy import WAN
            seconds = round(len(_frames(path)) / WAN["fps"])
            _set(conn, gid, status="generated", file=str(path.relative_to(out_dir)),
                 checkpoint=f"wan2.2-i2v scene {seconds}s")
        else:
            _set(conn, gid, status="dropped", reason="no shot passed: " + "; ".join(notes)[:180])
        stats = check_videos(cfg, conn, night)
        if _cancel_requested(conn, night):
            status = "cancelled"
        _finish(conn, night, status, stats)
    except Exception as e:
        status, message = "failed", str(e)[:300]
        with conn:
            conn.execute("UPDATE runs SET status = 'failed', progress = NULL, finished_at = datetime('now')"
                         " WHERE night = ?", (night,))
        raise
    finally:
        comfy.stop()
        for p in pictures:
            p.unlink(missing_ok=True)
        with conn:
            conn.execute("UPDATE jobs SET status = ?, message = ?, finished_at = datetime('now') WHERE id = ?",
                         (status, message, job_id))
