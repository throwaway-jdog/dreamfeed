"""Every adults-only and content rule in one place. Not configurable, except the two
thresholds in .env (AGE_THRESHOLD, YOUTH_TAG_THRESHOLD) and PHOTO_MIN_AGE.

Where they apply:
1. Written by people
   - personas file (personas.py):  no blocked tag anywhere in a persona (blocked); their
     LoRA trigger words too; strict mode for looks models draw young (needs_strict), which a
     file can switch on but never off; a strict persona can't be another one's {friend}.
   - persona builder (builder.py): descriptions with youth words are refused (YOUTH_TAGS,
     CAPTION_NEVER); blocked hashtags are dropped.
   - dashboard animation requests (web/app.py): request_blocked.
2. Every prompt sent to the image or video model (comfy.py): prompts() refuses blocked tags
   and adds the adult terms (ADULT_POSITIVE, YOUTH_NEGATIVE, and STRICT_* for strict
   personas); each region of a two-character picture is checked too.
3. Every picture and clip, before it's kept (checks.problem): youth tags, age (CLIP, and
   the agecheck service's face estimate for photos), feral; for training data also photos
   and blocked tags, always at the strict threshold. Applied to posts, avatars, clips, each
   shot of a scene and the finished scene, style and video training data, character
   close-ups (where a picture with one failing close-up is left out whole) and bootstrapped
   pictures. A dropped file is deleted.
4. Written text: generated captions and motion descriptions (caption_blocked), and artist
   posts and speech-bubble lines used as a voice (captions.clean).
"""
import re

# Any of these on a generated post, clip or training image (danbooru names from the WD
# tagger, plus e621 terms) drops it and deletes the file.
YOUTH_TAGS = {
    "child", "female child", "male child", "toddler", "baby", "aged down",
    "loli", "shota", "teenage", "teen", "cub", "young",
    "kindergarten uniform", "randoseru",
}

# Never allowed in a prompt (a persona using one is refused). Youth tags plus tags
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


# Never in a written caption (on top of the blocked tags above): ages, school, and words
# that make a character sound young. A caption with any of these is thrown away.
CAPTION_NEVER = re.compile(
    r"\b(\d+\s*(yo|y/?o|yrs?|years?)(\s*old)?|years? old|school\w*|student\w*|class(room|mates?)|"
    r"kids?|kiddo|minors?|underage|little (girl|boy|one|sister|brother)|barely legal|virgin\w*|"
    r"innocent|tiny|smol|loli\w*|shota\w*|teen\w*|grade|homework|puberty|"
    r"turn(ed|s|ing)? \d+|ages?|aged|birthdays?|bday|\d+(st|nd|rd|th) b)\b", re.I)


def caption_blocked(text: str) -> list[str]:
    return blocked(text) + [m.group(0).lower() for m in CAPTION_NEVER.finditer(text)]


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


# Sexual content with (non-anthro) animals is never generated or trained on. Generated
# posts and LoRA training images with any of these at FERAL_THRESHOLD are dropped.
FERAL_TAGS = {"bestiality", "zoophilia", "animal focus", "pokemon (creature)", "feral"}
FERAL_THRESHOLD = 0.25


# Training data is drawn art only. A picture is a photo when CLIP's share for "photo" or the
# tagger's photorealistic tag is this high.
PHOTO_SHARE = 0.35
PHOTO_TAGS = {"photorealistic"}
PHOTO_TAG_MIN = 0.4

# A tagger tag counts as seen in a picture (for the blocked-tag check on training data) at this.
SEEN = 0.35


def photo_signs(scores: dict[str, float], medium_probs: dict[str, float]) -> str | None:
    share = medium_probs.get("photo", 0.0)
    tags = [t for t in PHOTO_TAGS if scores.get(t, 0.0) >= PHOTO_TAG_MIN]
    return f"{share:.2f} {' '.join(tags)}".strip() if share >= PHOTO_SHARE or tags else None


# Words a person may not use in a request typed on the dashboard (on top of caption_blocked).
REQUEST_NEVER = re.compile(r"\b(child|children|kid|kids|toddler|baby|babies|loli|lolicon|shota|shotacon|teen|"
                           r"teens|teenage|teenager|underage|minor|minors|young|cub|preteen|schoolgirl|"
                           r"schoolboy|school uniform|petite|flat chest)\b", re.I)


def request_blocked(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in REQUEST_NEVER.finditer(text)} | set(caption_blocked(text)))


def feral_hits(scores: dict[str, float]) -> list[str]:
    return sorted(t for t in FERAL_TAGS if scores.get(t, 0.0) >= FERAL_THRESHOLD)


def youth_tag_hits(scores: dict[str, float], threshold: float) -> list[str]:
    return sorted(t for t in YOUTH_TAGS if scores.get(t, 0.0) >= threshold)
