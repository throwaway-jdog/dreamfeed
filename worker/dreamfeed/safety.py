"""Adults-only rules shared by tagging and generation. Not configurable."""
import re

# Any of these on a bookmark (danbooru names from the WD tagger, plus e621 terms)
# drops it: nothing from it is stored and the file is deleted.
YOUTH_TAGS = {
    "child", "female child", "male child", "toddler", "baby", "aged down",
    "loli", "shota", "teenage", "teen", "cub", "young",
    "kindergarten uniform", "randoseru",
}

# Never stored in the taste profile, so never used in prompts. Youth tags plus tags
# that push generated characters toward looking young.
NEVER_PROMPT_TAGS = YOUTH_TAGS | {
    "flat chest", "petite", "school uniform", "serafuku", "school swimsuit",
    "gym uniform", "buruma", "school bag", "otoko no ko", "femboy", "trap",
    # Aliases of the same booru tag ("otoko no ko"), which pulls toward young-looking characters.
}

# Added to every generation prompt, per medium.
ADULT_POSITIVE = {
    "photo": "adult, ",
    "anime": "adult, mature, ",
    "furry": "adult, anthro, ",
}
YOUTH_NEGATIVE = {
    "photo": "child, kid, teen, teenager, young, underage, minor, school uniform, petite, flat chest",
    "anime": "loli, shota, child, female child, male child, young, aged down, petite, flat chest, "
             "school uniform, chibi",
    "furry": "cub, young, child, loli, shota, petite, flat chest, school uniform, chibi",
}


# Extra terms for characters where models drift young most often: feminine men, androgynous
# and petite-coded characters. Personas get this automatically when their look matches.
STRICT_POSITIVE = "adult, mature, adult proportions, tall, long legs, "
STRICT_NEGATIVE = "young boy, young girl, boyish face, childlike face, baby face, small body, short stature, aged down"
STRICT_MARKERS = ("crossdressing", "androgynous", "feminine", "futanari", "trans", "tomboy")
# Drawings of strict personas are dropped at this CLIP youth share (normal: AGE_THRESHOLD).
STRICT_AGE_THRESHOLD = 0.25


def blocked(text: str) -> list[str]:
    text = text.lower().replace("_", " ")
    return sorted(t for t in NEVER_PROMPT_TAGS if re.search(rf"\b{re.escape(t)}\b", text))


def needs_strict(text: str) -> bool:
    text = text.lower()
    return any(m in text for m in STRICT_MARKERS)


def prompts(medium: str, positive: str, negative: str, strict: bool = False) -> tuple[str, str]:
    """Wrap a prompt with the medium's adult-only terms. Refuses prompts with youth tags."""
    bad = blocked(positive)
    if bad:
        raise ValueError(f"prompt contains blocked tags: {', '.join(bad)}")
    strict = strict or needs_strict(positive)
    pos = ADULT_POSITIVE[medium] + (STRICT_POSITIVE if strict else "") + positive
    neg = YOUTH_NEGATIVE[medium] + (", " + STRICT_NEGATIVE if strict else "") + f", {negative}"
    return pos, neg


FURRY_TAGS ={"furry", "furry female", "furry male", "body fur", "snout", "animal nose"}

# CLIP zero-shot descriptions. Groups are the same size so none is favored.
MEDIUM_PROMPTS = {
    "photo": [
        "a photograph of a real person",
        "an amateur photo",
        "a professional photoshoot photo",
        "a still frame from a live-action video",
    ],
    "anime": [
        "an anime illustration",
        "a hentai drawing",
        "a manga-style drawing",
        "a 3d render of an anime character",
    ],
    "furry": [
        "furry art of an anthropomorphic animal character",
        "an anthro furry illustration",
        "a drawing of a furry character with fur and a muzzle",
        "a 3d render of an anthro furry character",
    ],
}

AGE_PROMPTS = {
    "youth": [
        "a photo of a child",
        "a photo of a young teenager",
        "a drawing of a child",
        "an anime drawing of a little girl",
        "an anime drawing of a little boy",
        "a drawing of a young cub character",
    ],
    "adult": [
        "a photo of an adult woman",
        "a photo of an adult man",
        "a drawing of an adult woman",
        "an anime drawing of an adult woman",
        "an anime drawing of an adult man",
        "a drawing of an adult anthro character",
    ],
    # Without this, images with no one in them are forced into youth or adult at random.
    "nobody": [
        "a screenshot of text",
        "an abstract pattern or graphic",
        "a landscape with no people",
        "a photo of an object with no people",
        "a meme with text",
        "a drawing with no characters",
    ],
}


def youth_tag_hits(scores: dict[str, float], threshold: float) -> list[str]:
    return sorted(t for t in YOUTH_TAGS if scores.get(t, 0.0) >= threshold)
