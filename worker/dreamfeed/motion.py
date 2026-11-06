"""What a clip should show moving: the sex act in the picture (if any) and a motion description.

Wan 2.2 knows little about sex motion, so clips of a sex act use a motion LoRA trained for
these acts (VIDEO_ACT_LORA_HIGH / _LOW, Wan 2.2 I2V, one file per noise expert) with the
act's trigger word. The act comes from the tagger's tags for the picture. Pictures without
one (pinups, poses) are animated without it.

Wan reads plain sentences better than booru tags, so with CAPTION_MODEL set the text model
describes the motion for each clip from the picture's tags; otherwise a fixed description of
the act is used. Descriptions go through the same checks as captions.
"""
from dataclasses import dataclass

from . import safety


@dataclass(frozen=True)
class Act:
    name: str
    trigger: str           # the motion LoRA's trigger word
    tags: tuple            # any of these booru tags in the picture means this act
    motion: str            # fallback description when no text model writes one
    lora: str = ""         # its own motion LoRA (models/loras/NAME-high/-low.safetensors); "" = VIDEO_ACT_LORA
    strength: float = 0.8


# In priority order: the first that matches wins (a double blowjob also has "fellatio").
ACTS = (
    Act("double blowjob", "d0ubl3_bj", ("cooperative fellatio", "double fellatio"),
        "two partners take turns sucking his penis, heads bobbing in a steady rhythm"),
    # Girl-girl acts, each with its own LoRA (Civitai: cunnilingus 1954774 and fingering 2007360
    # for Wan 2.2 I2V; scissoring 654646 was made for T2V, and is tried on I2V at less strength).
    # French Kiss 2171333 (Wan 2.2 I2V; no trigger word, the description carries it).
    Act("kissing", "", ("french kiss", "kiss"),
        "they kiss deeply, lips pressed together and mouths moving, tongues touching, heads tilting",
        lora="wan2.2-i2v-kissing", strength=0.8),
    Act("cunnilingus", "cunn1l1ngu5", ("cunnilingus",),
        "one girl licks between the other's thighs, her head moving, the other's hips rocking",
        lora="wan2.2-i2v-cunnilingus", strength=0.8),
    Act("fingering", "", ("fingering",),
        "fingers slide in and out of her pussy in a steady rhythm, her hips rising to meet them",
        lora="wan2.2-i2v-fingering", strength=0.8),
    Act("scissoring", "", ("tribadism",),
        "they grind their hips together in a steady rhythm, legs intertwined, bodies rocking",
        lora="wan2.2-i2v-scissoring", strength=0.6),
    # Rimming 2323540 (I2V; its trigger is a sentence, here about two women), Dildoing 2903074
    # (made for T2V, tried at less strength), Pegging 2410338 (I2V, a woman with a strap-on).
    Act("rimming", "a woman performing rimming on a woman, licking her anus", ("anilingus",),
        "one girl licks her partner's ass, her tongue moving, her face pressed between her cheeks",
        lora="wan2.2-i2v-rimming", strength=0.8),
    Act("strap-on", "", ("strap-on",),
        "she thrusts her hips in a steady rhythm, the strap-on sliding in and out, her partner's body rocking",
        lora="wan2.2-i2v-pegging", strength=0.7),
    Act("toy", "pumping a dildo inside her vagina", ("dildo", "vaginal object insertion", "object insertion"),
        "the dildo slides in and out of her pussy in a steady rhythm, her hips rising to meet it",
        lora="wan2.2-i2v-dildo", strength=0.6),
    Act("blowjob", "bl0wj0b", ("fellatio", "irrumatio", "deepthroat", "licking penis"),
        "she sucks his penis, her head bobbing up and down in a steady rhythm"),
    Act("reverse cowgirl", "r3v3rs3_c0wg1rl", ("reverse cowgirl position",),
        "she rides him facing away, her hips bouncing up and down in a steady rhythm, her ass bouncing",
        lora="wan2.2-i2v-revcowgirl"),
    Act("cowgirl", "c0wg1rl", ("cowgirl position", "girl on top", "straddling"),
        "she rides him, her hips bouncing up and down in a steady rhythm, breasts bouncing"),
    # Its trigger is the sentence it was trained on.
    Act("standing", "standing sex, the man is standing behind the woman and penetrating her. He is thrusting his hip up and down",
        ("standing sex", "standing split", "against wall"),
        "he stands behind her and thrusts his hips into her hard, her body bouncing with each thrust",
        lora="wan2.2-i2v-standing", strength=0.8),   # at 1.0 it smears the penis
    Act("doggy", "d0gg1e", ("doggystyle", "sex from behind", "top-down bottom-up", "from behind", "all fours"),
        "he thrusts into her from behind in a steady rhythm, her body rocking forward with each thrust"),
    Act("missionary", "m15510n4ry", ("missionary", "on back", "spread legs", "lying"),
        "he thrusts into her as she lies on her back, her body rocking with each thrust, breasts bouncing"),
)
SEX = {"sex", "vaginal", "anal", "penetration", "imminent penetration"}

# Climaxes, for the last shot of a scene (not picked from a picture's tags).
CREAMPIE = Act("creampie", "cr34mp13", ("creampie", "cum in pussy"),
               "he thrusts deep and holds still inside her as he cums, a little cum leaking out around his penis",
               lora="wan2.2-i2v-creampie", strength=0.6)   # higher floods the shot
FACIAL = Act("facial", "", ("facial", "cum on face"),
             "cum shoots out of his penis and lands on her face and tongue and mouth",
             lora="wan2.2-i2v-facial", strength=1.0)
CUMSHOT = Act("cumshot", "f4c3spl4sh", ("cum on body", "ejaculation"),
              "he pulls out and cum shoots out of his penis onto her body in thick spurts",
              lora="wan2.2-i2v-cumshot", strength=1.0)
# Girl-girl climax (Civitai 2518574, Wan 2.2 I2V; it was trained on one long sentence, of
# which this is the part about the act).
SQUIRT = Act("squirt", "her vagina squirting clear fluid", ("female ejaculation", "squirting"),
             "her hips shake as she cums, clear fluid squirting from her pussy in bursts",
             lora="wan2.2-i2v-squirt", strength=0.8)
CLIMAXES = {a.name: a for a in (CREAMPIE, FACIAL, CUMSHOT, SQUIRT)}


def lora_for(act: Act, default: tuple | None, models_dir) -> tuple | None:
    """(high file, low file, strength) for an act's motion LoRA: its own if it has one and both
    files are there, otherwise VIDEO_ACT_LORA (default)."""
    if not act.lora:
        return default
    files = (f"{act.lora}-high.safetensors", f"{act.lora}-low.safetensors")
    if all((models_dir / "loras" / f).is_file() for f in files):
        return (*files, act.strength)
    return None


def act_for(tags: list[str]) -> Act | None:
    have = {t.strip() for t in tags}
    for act in ACTS:
        hit = have & set(act.tags)
        if not hit:
            continue
        # Positions only count with sex in the picture (lying on her back alone is a pinup).
        if act.name in ("reverse cowgirl", "cowgirl", "standing", "doggy", "missionary") and not have & SEX:
            continue
        return act
    return None


SYSTEM = (
    "You write the motion prompt for a 5-second animated clip made from one adult illustration. "
    "Describe in one or two plain sentences what moves and how: body movement, rhythm, speed, "
    "hair, clothes and expressions. Be explicit and concrete about sexual motion when the picture "
    "is sexual. Every character is an adult. Never name characters or series, never mention ages or "
    "anything young. Don't describe the camera unless it moves. Reply with the description only.")
TRIES = 3


def describe(writer, tags: list[str], act: Act | None, extra: str = "", context: str = "") -> str | None:
    """A checked motion description, or None (the caller uses the act's fixed one)."""
    user = (f"The picture: {', '.join(tags)}"
            + (f"\nThe act: {act.name} ({act.motion})" if act else "")
            + (f"\nThe viewer asked for: {extra}" if extra else "")
            + (f"\n{context}" if context else "")
            + "\nWrite the motion description.")
    for _ in range(TRIES):
        text = " ".join(writer.ask(SYSTEM, user, max_new_tokens=120).split())
        from .captions import REFUSAL, _names_in
        if text and len(text) < 600 and not REFUSAL.search(text) and not safety.caption_blocked(text) \
                and "[" not in text:
            if not _names_in(text, set()):
                return text
    return None


def plan(cfg, items: list[tuple[int, list[str]]], extra: str = "") -> dict[int, tuple[Act | None, str | None]]:
    """For each (generation id, picture tags): its act and a written motion description (None when
    CAPTION_MODEL is off or nothing passed the checks). Runs before ComfyUI starts: the text
    model and Wan don't fit on the GPU together."""
    out = {gid: (act_for(tags), None) for gid, tags in items}
    if not cfg.caption_model or not items:
        return out
    from .captions import Writer
    try:
        writer = Writer(cfg.caption_model)
    except Exception as e:
        print(f"motion: couldn't load {cfg.caption_model} ({e}); using fixed motion", flush=True)
        return out
    try:
        for gid, tags in items:
            act = out[gid][0]
            out[gid] = (act, describe(writer, tags, act, extra))
    finally:
        writer.close()
    return out
