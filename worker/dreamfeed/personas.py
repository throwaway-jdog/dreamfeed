"""Fictional posters for the v2 timeline, defined in data/personas.json (private, not in git).

Each persona has a fixed look (tags that keep them recognisable from post to post) and a few
kinds of post, each with its own prompt, rating and captions. The nightly run picks personas
by weight (likes raise it, skips lower it), then a kind of post, then fills in an outfit and a
setting. See personas.example.json for the format. A post's captions are examples: with
CAPTION_MODEL set, every post gets a freshly written caption in that voice, or in the voice of
the artist behind the style named in "voice" (captions.py).

Placeholders allowed in a post prompt: {outfit} (from the persona's outfits, or a generic
list), {cosplay} (generic costumes only, never named characters), {setting}, {character}
(one of the persona's characters, for artist personas that draw different people), {partner}
(one of the persona's partners, so the man in their duo posts isn't always the same one).
"""
import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import safety

MEDIUMS = ("anime", "furry")
HANDLE = re.compile(r"^[a-z0-9_]{2,20}$")
RATINGS = {"explicit": "nsfw, explicit, ", "questionable": "nsfw, ", "general": ""}
LIKE_WEIGHT, SKIP_WEIGHT, MIN_WEIGHT = 1.0, 0.3, 0.25

OUTFITS = [
    "pink frilled lingerie, thighhighs", "black lace lingerie, garter belt, thighhighs", "maid outfit, maid headdress",
    "oversized sweater, off shoulder, thighhighs", "sundress", "china dress, side slit", "bunny suit, fishnet pantyhose",
    "crop top, denim shorts", "silk robe, open robe", "sports bra, yoga pants", "nightgown, see-through",
    "choker, harness, leather", "turtleneck sweater dress", "bikini", "white shirt only, naked shirt",
]
# Generic costumes only. Named characters are never used: many are canonically minors.
COSPLAY = [
    "maid outfit, maid headdress", "playboy bunny, bunny ears, leotard", "nurse outfit, nurse cap",
    "china dress, qipao", "witch hat, witch costume", "succubus costume, demon horns, demon tail, demon wings",
    "kimono, obi", "police uniform, police hat", "miko outfit, hakama", "latex bodysuit",
    "elf ears, fantasy bikini armor", "cat ears, cat lingerie, cat tail", "fox ears, fox tail, kimono",
    "vampire costume, cape, fangs", "nun outfit, habit", "office lady, pencil skirt, pantyhose",
]
SETTINGS = [
    "bedroom, bed sheets", "bathroom mirror, mirror selfie", "hotel room, night", "living room couch",
    "shower, wet", "city window at night, neon lights", "kitchen counter", "photo studio, ring light",
    "bedroom, fairy lights", "hot spring, steam", "beach at sunset", "messy bedroom, posters on wall",
]


@dataclass
class Post:
    kind: str
    weight: float
    prompt: str
    rating: str
    captions: list[str]


@dataclass
class Persona:
    handle: str
    name: str
    medium: str
    bio: str
    look: str
    avatar: str
    posts: list[Post]
    outfits: list[str] = field(default_factory=list)
    partners: list[str] = field(default_factory=list)
    settings: list[str] = field(default_factory=list)
    characters: list[str] = field(default_factory=list)
    emoji: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    video_share: float = 0.2
    weight: float = 1.0
    strict: bool = False
    lora: tuple[str, float] | None = None   # (file in models/loras, strength)
    lora_female_only: bool = False          # skip the LoRA for male characters
    trigger: str = ""                       # the LoRA's trigger word, put first in every prompt
    negative: str = ""                      # extra negative prompt for every post (e.g. "face, eyes")
    paused: bool = False                    # keeps the profile and posts, makes no new ones
    voice: str = ""                         # a style whose artist's posts their captions sound like

    def prompt_for(self, post: Post, rng: random.Random) -> str:
        fill = {
            "outfit": rng.choice(self.outfits or OUTFITS),
            "cosplay": rng.choice(COSPLAY),
            "setting": rng.choice(self.settings or SETTINGS),
            "character": rng.choice(self.characters) if self.characters else "",
            "partner": rng.choice(self.partners) if self.partners else "faceless male",
        }
        body = post.prompt.format(**fill)
        if "{setting}" not in post.prompt:
            body += ", " + fill["setting"]
        parts = [p for p in (self.trigger, self.look, body) if p]
        return RATINGS[post.rating] + ", ".join(parts)

    def lora_for(self, prompt: str) -> tuple[str, float] | None:
        """The style LoRA, unless the prompt's character is male and the LoRA is marked
        female-only (trained mostly on women, it would turn men into women)."""
        if not self.lora or not self.lora_female_only:
            return self.lora
        tags = {t.strip() for t in prompt.split(",")}
        return None if "male" in tags and "female" not in tags else self.lora

    def avatar_prompt(self, rng: random.Random) -> str:
        who = self.look or (rng.choice(self.characters) if self.characters else "")
        return ", ".join(p for p in (self.trigger, who, self.avatar) if p)

    def caption_for(self, post: Post, rng: random.Random) -> str:
        text = rng.choice(post.captions)
        if self.emoji and rng.random() < 0.6:
            text += " " + "".join(rng.sample(self.emoji, k=min(len(self.emoji), rng.randint(1, 2))))
        if self.hashtags and rng.random() < 0.35:
            text += " " + " ".join("#" + t for t in rng.sample(self.hashtags, k=min(2, len(self.hashtags))))
        return text


class Invalid(ValueError):
    """A persona that can't be used, with a message fit to show on the dashboard."""


def load(path: Path) -> list[Persona]:
    """Read and check the personas file. Fails loudly on anything invalid or blocked."""
    if not path.is_file():
        return []
    try:
        return parse(json.loads(path.read_text()))
    except ValueError as e:   # bad JSON, or Invalid
        raise SystemExit(f"personas: {path}: {e}")


def parse(raw: dict) -> list[Persona]:
    """Check every persona in the file's contents (the dashboard runs this before saving)."""
    out, seen = [], set()
    for i, p in enumerate(raw.get("personas", [])):
        out.append(_persona(p, f"{p.get('name') or p.get('handle') or f'persona {i + 1}'}", seen))
    return out


def _persona(p: dict, where: str, seen: set) -> Persona:
    handle = str(p.get("handle", ""))
    if not HANDLE.match(handle) or handle in seen:
        raise Invalid(f"{where}: handle must be 2-20 of a-z 0-9 _ and unique")
    seen.add(handle)
    if p.get("medium") not in MEDIUMS:
        raise Invalid(f"{where}: medium must be one of {', '.join(MEDIUMS)}")
    posts = []
    for k in p.get("posts", []):
        rating = k.get("rating", "explicit")
        if rating not in RATINGS or not k.get("prompt") or not k.get("captions"):
            raise Invalid(f"{where}: every kind of post needs a prompt, captions and a rating")
        try:
            k["prompt"].format(outfit="", cosplay="", setting="", character="", partner="")
        except (KeyError, IndexError, ValueError):
            raise Invalid(f"{where}: a prompt uses an unknown placeholder; allowed are "
                          "{outfit} {cosplay} {setting} {character} {partner}")
        posts.append(Post(str(k.get("kind", "post")), float(k.get("weight", 1)), k["prompt"], rating,
                          [str(c) for c in k["captions"]]))
    if not posts:
        raise Invalid(f"{where}: needs at least one kind of post")
    if "{character}" in " ".join(k.prompt for k in posts) and not p.get("characters"):
        raise Invalid(f"{where}: a prompt uses {{character}} but there are no characters")
    persona = Persona(
        handle=handle, name=str(p.get("name") or handle), medium=p["medium"], bio=str(p.get("bio", "")),
        look=str(p.get("look", "")), avatar=str(p.get("avatar", "portrait, upper body, looking at viewer, smile")),
        posts=posts, outfits=list(p.get("outfits", [])), partners=list(p.get("partners", [])), settings=list(p.get("settings", [])),
        characters=list(p.get("characters", [])), emoji=list(p.get("emoji", [])),
        hashtags=list(p.get("hashtags", [])), video_share=float(p.get("video_share", 0.2)),
        weight=float(p.get("weight", 1.0)), negative=str(p.get("negative", "")),
        paused=bool(p.get("paused", False)), voice=str(p.get("voice") or ""))
    if persona.voice and not HANDLE.match(persona.voice):
        raise Invalid(f"{where}: voice must be the name of a trained style")
    text = " ".join([persona.look, persona.avatar, *persona.outfits, *persona.partners, *persona.settings, *persona.characters,
                     *(k.prompt for k in posts)])
    bad = safety.blocked(text)
    if bad:
        raise Invalid(f"{where}: uses blocked tags: {', '.join(bad)}")
    # Strict is automatic for feminine-man, androgynous, trans and tomboy looks; the file can
    # turn it on for anyone but never off.
    persona.strict = bool(p.get("strict")) or safety.needs_strict(text)
    lo = p.get("lora")
    if lo:
        if not isinstance(lo, dict) or not str(lo.get("file", "")).endswith(".safetensors"):
            raise Invalid(f"{where}: lora needs {{\"file\": \"x.safetensors\", \"strength\": 0.8, \"trigger\": \"word\"}}")
        trigger = str(lo.get("trigger", ""))
        if safety.blocked(trigger):
            raise Invalid(f"{where}: the style's trigger word uses blocked tags")
        if lo.get("enabled", True):   # switched off keeps the settings for later
            persona.lora = (str(lo["file"]), float(lo.get("strength", 0.8)))
            persona.lora_female_only = bool(lo.get("female_only", False))
            persona.trigger = trigger
    return persona


def sync(conn, personas: list[Persona]) -> None:
    """Mirror the file into the personas table (the web page reads it from there)."""
    with conn:
        conn.execute("UPDATE personas SET active = 0")
        for p in personas:
            conn.execute(
                "INSERT INTO personas(handle, name, medium, bio, strict, video_share, active) VALUES (?,?,?,?,?,?,1)"
                " ON CONFLICT(handle) DO UPDATE SET name = excluded.name, medium = excluded.medium,"
                " bio = excluded.bio, strict = excluded.strict, video_share = excluded.video_share, active = 1,"
                " updated_at = datetime('now')",
                (p.handle, p.name, p.medium, p.bio, int(p.strict), p.video_share))


def weights(conn, personas: list[Persona]) -> list[float]:
    """Base weight from the file, raised by likes on their posts and lowered by skips."""
    fb = {h: (l, s) for h, l, s in conn.execute(
        "SELECT g.persona, sum(f.action = 'like'), sum(f.action = 'skip') FROM feedback f"
        " JOIN generations g ON g.id = f.generation_id WHERE g.persona IS NOT NULL GROUP BY g.persona")}
    out = []
    for p in personas:
        likes, skips = fb.get(p.handle, (0, 0))
        out.append(max(MIN_WEIGHT, p.weight * (1 + LIKE_WEIGHT * likes / 10 - SKIP_WEIGHT * skips / 10)))
    return out


def plan(conn, personas: list[Persona], total: int, rng: random.Random) -> dict[str, int]:
    """How many images each persona gets tonight. Everyone gets at least one when there are enough."""
    if not personas:
        return {}
    w = weights(conn, personas)
    if total < len(personas):   # small batch: that many different personas, by weight
        pool, chosen = list(zip(personas, w)), {}
        while len(chosen) < total:
            p, pw = rng.choices(pool, weights=[x[1] for x in pool])[0]
            pool.remove((p, pw))
            chosen[p.handle] = 1
        return chosen
    counts = {p.handle: 1 for p in personas}
    for _ in range(total - len(personas)):
        counts[rng.choices(personas, weights=w)[0].handle] += 1
    return counts


def pick_post(persona: Persona, rng: random.Random) -> Post:
    return rng.choices(persona.posts, weights=[k.weight for k in persona.posts])[0]
