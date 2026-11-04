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


# In priority order: the first that matches wins (a double blowjob also has "fellatio").
ACTS = (
    Act("double blowjob", "d0ubl3_bj", ("cooperative fellatio", "double fellatio"),
        "two partners take turns sucking his penis, heads bobbing in a steady rhythm"),
    Act("blowjob", "bl0wj0b", ("fellatio", "irrumatio", "deepthroat", "licking penis"),
        "she sucks his penis, her head bobbing up and down in a steady rhythm"),
    Act("cowgirl", "c0wg1rl", ("cowgirl position", "reverse cowgirl position", "girl on top", "straddling"),
        "she rides him, her hips bouncing up and down in a steady rhythm, breasts bouncing"),
    Act("doggy", "d0gg1e", ("doggystyle", "sex from behind", "top-down bottom-up", "from behind", "all fours"),
        "he thrusts into her from behind in a steady rhythm, her body rocking forward with each thrust"),
    Act("missionary", "m15510n4ry", ("missionary", "on back", "spread legs", "lying"),
        "he thrusts into her as she lies on her back, her body rocking with each thrust, breasts bouncing"),
)
SEX = {"sex", "vaginal", "anal", "penetration", "imminent penetration"}


def act_for(tags: list[str]) -> Act | None:
    have = {t.strip() for t in tags}
    for act in ACTS:
        hit = have & set(act.tags)
        if not hit:
            continue
        # Positions only count with sex in the picture (lying on her back alone is a pinup).
        if act.trigger in ("c0wg1rl", "d0gg1e", "m15510n4ry") and not have & SEX:
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


# ---- long clips: one description per 5-second piece -----------------------------------------
# One request per piece (the text model refuses a whole numbered list but writes single
# descriptions fine), each told where it is in the clip and what the piece before showed.

ARC = ("it starts slowly and gently, settling in",
       "the pace picks up a little",
       "a small change: a shift in pose, a look back, a new expression",
       "a steady, stronger rhythm",
       "it builds toward the most intense moment",
       "the most intense moment",
       "it eases off, slower and softer",
       "it slows to a calm, relaxed ending")


def _arc(i: int, n: int) -> str:
    return ARC[round(i * (len(ARC) - 1) / max(1, n - 1))] if n > 1 else ARC[0]


def describe_beats(writer, tags: list[str], act: Act | None, n: int, extra: str = "") -> list[str | None]:
    """n checked descriptions, one per piece; None where nothing passed (the caller falls back)."""
    out, prev = [], ""
    for i in range(n):
        where = (f"This is part {i + 1} of {n} of a {n * 5}-second clip, made of 5-second parts that "
                 f"follow each other. In this part: {_arc(i, n)}."
                 + (f" The part before showed: {prev} Continue from there without repeating it." if prev else ""))
        text = describe(writer, tags, act, extra, context=where)
        if text and not text.endswith(".") and "." in text:   # cut off mid-sentence
            text = text[:text.rfind(".") + 1]
        out.append(text)
        prev = text or prev
    return out


def plan_beats(cfg, items: list[tuple[int, list[str]]], n: int,
               extra: str = "") -> dict[int, tuple[Act | None, list[str | None]]]:
    """Like plan(), with n descriptions per item for a long clip."""
    out = {gid: (act_for(tags), [None] * n) for gid, tags in items}
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
            out[gid] = (act, describe_beats(writer, tags, act, n, extra))
    finally:
        writer.close()
    return out
