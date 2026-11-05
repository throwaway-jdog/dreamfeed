"""Which acts a scene can have, by kind of scene, for scene.py's plans and the dashboard's
picker ("Make a scene": random, or chosen). No heavy imports: the web app uses it too."""

STRAIGHT_OPENERS = ("missionary", "blowjob")
STRAIGHT_MIDDLE = ("doggy", "cowgirl", "missionary", "reverse cowgirl", "standing")
GIRL_GIRL_MIDDLE = ("fingering", "cunnilingus", "rimming", "69", "toy")
GIRL_GIRL_PEAK = ("scissoring", "strap-on")   # the last act, where the climax happens

# Each kind's choices, in the order of the scene: (slot, label, options).
SLOTS = {
    "straight": (("opening", "Opening", STRAIGHT_OPENERS), ("first", "Then", STRAIGHT_MIDDLE),
                 ("second", "Climax in", STRAIGHT_MIDDLE)),
    "girl-girl": (("first", "After kissing", GIRL_GIRL_MIDDLE), ("second", "Then", GIRL_GIRL_MIDDLE),
                  ("peak", "Climax in", GIRL_GIRL_PEAK)),
}


def kind(prompt: str) -> str:
    tags = {t.strip() for t in prompt.split(",")}
    return "girl-girl" if "2girls" in tags and not {"1boy", "hetero"} & tags else "straight"


def checked(prompt: str, picks: dict | None) -> dict:
    """The picks that are set (a missing or empty one is random); ValueError for anything else."""
    slots = {s: opts for s, _, opts in SLOTS[kind(prompt)]}
    out = {}
    for slot, value in (picks or {}).items():
        if value in (None, ""):
            continue
        if slot not in slots or value not in slots[slot]:
            raise ValueError(f"{value!r} isn't a choice for {slot!r} in this scene")
        out[slot] = value
    if out.get("first") and out.get("first") == out.get("second"):
        raise ValueError("pick two different acts")
    return out
