"""Draft a whole persona from a short description, like "handle: Chinese femboy. Cosplays,
sex with men, wears a face mask".

A "persona_draft" job from the dashboard. The caption model writes the persona as JSON,
following a few existing personas as examples, and the draft is checked with the same rules
as the persona editor (personas.parse); a draft that fails is sent back with the reason, up to
TRIES times. The draft is saved in data/drafts/JOB.json and opened in the editor; nothing is
added until it's saved there.

Rules the draft always follows, whatever the description says:
- fictional: the real account's handle or name never becomes the persona's; the description
  is kept only as the private based_on note
- drawn: real-life creators become anime personas; never a real person's likeness
- adults only: descriptions with anything young are refused, blocked tags (femboy, petite...)
  are swapped for allowed ones by the model or refused by the checks, strict is automatic
- no feral or animal content: those descriptions are refused (anthro is fine)
"""
import json
import re
from functools import cache

from . import personas as people, safety
from .captions import REFUSAL, Writer

TRIES = 4
MAX_DESCRIPTION = 2000
HIDDEN_FACE = re.compile(r"\b(mask\w*|blur\w*|face(less)?|hides?|hidden|covers?|anonymous|no face)\b", re.I)
NON_CONSENT = re.compile(r"\b(voyeur\w*|hidden cam\w*|spy\w*|peep\w*|didn'?t know|without (his|her|their) knowledge|"
                         r"being watched|sleep\w*|asleep|unconscious|drunk|drugged|forced|rape\w*|non-?con\w*)\b", re.I)
FERAL = re.compile(r"\b(feral|bestiality|zoophil\w*|zoo|pok[eé]\s*porn|pok[eé]mon|animals?\s+(sex|porn))\b", re.I)

SYSTEM = """You design fictional adult personas for a private, Twitter-like feed of generated anime and furry posts. From the user's description of a real creator (their handle, what they are and what they post), invent a NEW fictional persona who posts similar content. Reply with one JSON object only, in exactly the format of the examples.

Rules:
- Invent a new name and handle. Never reuse the real handle, real name, or anything close to them.
- medium: "anime" for real-life creators and anime artists, "furry" for furry artists. Anime personas are drawn anime characters, never a real person.
- Every character is an adult. Put "adult, mature male" or "adult, mature female" in look. If the bio mentions an age, it is 21 or older.
- Prompts are danbooru tags, comma-separated. Never use these tags: femboy, trap, otoko no ko, petite, flat chest, loli, shota, child, teen, young, school uniform, serafuku, gym uniform. For a femboy use: male focus, androgynous, feminine, crossdressing. For a trans woman use 1girl (and futanari only if the description says so).
- Never name a real person, character or series anywhere (no character names in prompts or captions).
- look: tags that keep this persona recognisable from post to post (hair, eyes, body, mask, etc.). Artist personas who draw different characters leave look empty and list 3-7 characters instead.
- posts: 2-4 kinds of post matching what the creator posts, each with weight, rating (explicit, questionable or general), a prompt and 4-6 short captions in the creator's voice. Prompts may use {outfit}, {cosplay}, {setting}, and {character} (only with characters).
- Artists (people who draw or animate): the persona is the artist. Leave look empty, list 3-7 original adult characters they draw (tags only, no names), and use {character} in every prompt.
- Only a creator who hides their face gets a mask or similar in look, and "negative": "face, eyes" only if the face is never shown. Everyone else has no negative.
- Everything is consensual and between adults who know they are being filmed or drawn: no voyeurism, hidden cameras, sleeping, drunk or forced scenarios.
- emoji: 2-5 they would use. hashtags: 1-3, without #. bio: one short line in their voice.
"""


KEYS = ("handle", "name", "medium", "bio", "look", "avatar", "characters", "outfits", "settings", "emoji",
        "hashtags", "negative", "weight", "video_share", "posts")
# Used as the format example until there are a few personas of your own.
EXAMPLE = {
    "handle": "example_artist", "name": "Example Artist", "medium": "furry",
    "bio": "furry artist · original characters · adults only", "look": "",
    "avatar": "portrait, upper body, looking at viewer, smile, simple background",
    "characters": ["anthro, female, red fox, orange fur, fluffy tail, green eyes",
                   "anthro, male, wolf, grey fur, muscular, yellow eyes"],
    "emoji": ["🎨"], "hashtags": ["furryart"], "video_share": 0.5,
    "posts": [{"kind": "pinup", "weight": 2, "rating": "questionable",
               "prompt": "solo, {character}, {outfit}, pinup, looking at viewer, detailed background",
               "captions": ["new pinup", "sketch turned into a full piece", "WIP, finishing tonight"]},
              {"kind": "sex", "weight": 3, "rating": "explicit",
               "prompt": "duo, {character}, sex, penetration, penis, cum, detailed background, {setting}",
               "captions": ["new piece!", "this one took forever", "animated version soon"]}],
}


ARTIST = re.compile(r"\b(draws?|drawing|artist|animat\w*|illustrat\w*|art|comics?|paints?)\b", re.I)
FURRY = re.compile(r"\b(furry|furries|anthro|fursona)\b", re.I)


def _examples(cfg, description: str) -> list[dict]:
    """Two existing personas (without private notes) as the format to follow: the closest kind
    first (artist or creator, anime or furry), then one of the other kind."""
    try:
        raw = json.loads(cfg.personas_path.read_text())["personas"]
    except (OSError, ValueError, KeyError):
        raw = []
    medium = "furry" if FURRY.search(description) else "anime"
    artists = [p for p in raw if p.get("characters")]
    creators = [p for p in raw if p.get("look") and not p.get("characters") and not p.get("negative")]
    if ARTIST.search(description):
        first = [p for p in artists if p.get("medium") == medium] or artists or [EXAMPLE]
        picks = first[:1] + creators[:1]
    else:
        picks = creators[:1] + (artists or [EXAMPLE])[:1]
    out = []
    for p in picks:
        p = {k: v for k, v in p.items() if k not in ("based_on", "lora", "voice", "paused", "weight", "negative")}
        p["posts"] = [dict(k, captions=k["captions"][:4]) for k in p.get("posts", [])[:3]]
        out.append(p)
    return out


def _real_names(description: str) -> set[str]:
    """The real account's handle-like words: the persona must not reuse them."""
    first = description.split(":", 1)[0] if ":" in description[:60] else ""
    words = re.findall(r"@?([A-Za-z0-9_]{3,})", first) + re.findall(r"@([A-Za-z0-9_]{3,})", description)
    words += re.findall(r"(?:x|twitter)\.com/([A-Za-z0-9_]{3,})", description)
    return {w.lower() for w in words}


@cache
def characters() -> tuple[frozenset, ...]:
    """Each character tag the tagger knows as a set of name words ("souryuu asuka langley
    (evangelion)" -> {souryuu, asuka, langley}): a name containing all of one is that character."""
    import csv
    from huggingface_hub import hf_hub_download
    from .vision import TAGGER_REPO, CAT_CHARACTER
    with open(hf_hub_download(TAGGER_REPO, "selected_tags.csv"), newline="") as f:
        rows = [r["name"] for r in csv.DictReader(f) if int(r["category"]) == CAT_CHARACTER]
    out = set()
    for r in rows:
        name = re.sub(r"\(.*?\)", "", r.replace("_", " ")).lower()
        out.add(frozenset(re.findall(r"[a-z]+", name)))
    return tuple(t for t in out if t)


def refusal(description: str) -> str | None:
    if FERAL.search(description):
        return "personas are human or anthro: feral or animal content isn't made. Describe an anthro version instead."
    young = [t for t in safety.YOUTH_TAGS if re.search(rf"\b{re.escape(t)}\b", description, re.I)]
    young += [m.group(0) for m in safety.CAPTION_NEVER.finditer(description)]
    if young:
        return f"adults only: the description can't include {', '.join(sorted(set(young)))}"
    return None


def _json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the reply")
    return json.loads(text[start:end + 1])


def check(draft: dict, real: set[str], taken: set[str]) -> str | None:
    """Why the draft can't be used, in words the model can act on; None if it's fine."""
    handle, name = str(draft.get("handle", "")).lower(), str(draft.get("name", ""))
    if handle in taken:
        return f'the handle "{handle}" is taken; invent another'
    flat = re.sub(r"[^a-z]", "", handle + " " + name.lower())
    for r in real:   # the whole real handle, or any part of it (Ann_Bee7 -> ann, bee)
        pieces = [p for p in re.split(r"[^a-z]+", r) if len(p) >= 3]
        parts = {re.sub(r"[^a-z]", "", r)} | set(pieces) | {p[:3] for p in pieces}   # Kikooo99 -> kik too
        if any(len(p) >= 3 and p in flat for p in parts):
            return ("the handle and name must be new and not contain the real account's name or any "
                    f"part of it ({', '.join(sorted(parts))}); invent different ones")
    words = {w.lower() for w in re.findall(r"[A-Za-z]+", name)}
    if any(t <= words for t in characters()):
        return "the name is a known character's name; invent an original one"
    posts = [k for k in draft.get("posts", []) if isinstance(k, dict)]
    texts = [name, str(draft.get("bio", "")), " ".join(map(str, draft.get("hashtags") or []))]
    texts += [c for k in posts for c in k.get("captions", [])]
    for t in texts:
        bad = safety.caption_blocked(str(t).replace("_", " "))
        if bad:
            return f"remove these words from the name, bio, hashtags and captions: {', '.join(bad)}"
    everything = " ".join(texts + [str(k.get("prompt", "")) for k in posts] + [str(draft.get("look", ""))])
    if NON_CONSENT.search(everything):
        return (f"no voyeur or non-consent themes (found \"{NON_CONSENT.search(everything).group(0)}\"); "
                "everyone knows and wants it")
    if any(10 <= int(n) < 21 for n in re.findall(r"(?<![\d.])(\d{2})(?![\d+k%])", str(draft.get("bio", "")))):
        return "an age in the bio must be 21 or older"
    chars = " ".join(map(str, draft.get("characters") or []))
    if draft.get("medium") == "anime" and re.search(r"\b(anthro|furry)\b", chars):
        return "an anime persona's characters are humans (anime girls and men), not anthro animals"
    if draft.get("medium") == "furry" and chars and not re.search(r"\banthro\b", chars):
        return "a furry persona's characters are anthro animals: start each with anthro"
    try:
        people.parse({"personas": [draft]})
    except (ValueError, TypeError, AttributeError) as e:
        return str(e)
    return None


def build(cfg, writer: Writer, description: str, taken: set[str]) -> dict:
    real = _real_names(description)
    examples = "\n\n".join(json.dumps(p, ensure_ascii=False) for p in _examples(cfg, description))
    user = f"Examples:\n{examples}\n\nDescription:\n{description}\n\nWrite the new persona as JSON."
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    why = "no reply"
    for _ in range(TRIES):
        reply = writer._sample(messages, max_new_tokens=1500)
        if REFUSAL.search(reply[:200]):
            why = "the model refused"
            continue
        try:
            draft = _json(reply)
        except ValueError as e:
            why = f"the reply wasn't valid JSON ({e})"
        else:
            draft = _tidy(draft, description)
            why = check(draft, real, taken)
            if not why:
                draft["based_on"] = description[:200]
                return draft
        messages += [{"role": "assistant", "content": reply},
                     {"role": "user", "content": f"That can't be used: {why}. Reply with the corrected JSON only."}]
    raise RuntimeError(f"couldn't build a valid persona: {why}")


def _tidy(d: dict, description: str) -> dict:
    """Fill obvious gaps so small model slips don't cost a retry."""
    d = {k: v for k, v in d.items() if k in KEYS}
    if d.get("negative") and not HIDDEN_FACE.search(description):
        d.pop("negative")   # only creators who hide their face
    d["avatar"] = re.sub(r"\s*\{\w+\},?", "", str(d.get("avatar", ""))).strip(", ")   # no placeholders there
    d["handle"] = re.sub(r"[^a-z0-9_]", "", str(d.get("handle", "")).lower().lstrip("@"))[:20]
    for k in ("emoji", "hashtags", "characters", "outfits", "settings"):
        if isinstance(d.get(k), str):
            d[k] = d[k].split()
        if k == "hashtags" and d.get(k):   # blocked ones (femboy...) are just dropped
            d[k] = [t for t in (str(t).lstrip("#") for t in d[k]) if not safety.caption_blocked(t.replace("_", " "))][:3]
    for k in d.get("posts", []):
        if isinstance(k, dict):
            k.setdefault("weight", 1)
            k.pop("negative", None)
            k["rating"] = k.get("rating") if k.get("rating") in people.RATINGS else "explicit"
            if isinstance(k.get("captions"), str):
                k["captions"] = [k["captions"]]
    d.setdefault("weight", 1.0)
    d.setdefault("video_share", 0.2)
    return d


def run(cfg, conn, job_id: int, params: dict) -> None:
    """The dashboard's "Build from a description"."""
    from .styles import free_gpu
    out_dir = cfg.data_dir / "drafts"
    out_dir.mkdir(exist_ok=True)
    with conn:
        conn.execute("UPDATE jobs SET status = 'running' WHERE id = ?", (job_id,))
    status, message = "failed", None
    description = " ".join(str(params.get("description", "")).split())[:MAX_DESCRIPTION]
    try:
        why = refusal(description)
        if why:
            raise RuntimeError(why)
        if not cfg.caption_model:
            raise RuntimeError("building personas needs CAPTION_MODEL (the text model) set in .env")
        taken = {p.handle for p in people.load(cfg.personas_path)}
        taken |= {h for (h,) in conn.execute("SELECT handle FROM personas")}   # removed ones keep posts
        free_gpu(cfg)
        writer = Writer(cfg.caption_model)
        try:
            draft = build(cfg, writer, description, taken)
        finally:
            writer.close()
        (out_dir / f"{job_id}.json").write_text(json.dumps(draft, ensure_ascii=False, indent=1))
        status, message = "done", "draft ready"
    except Exception as e:
        message = str(e)[:300]
        print(f"builder: job {job_id} failed: {message}", flush=True)
    finally:
        with conn:
            conn.execute("UPDATE jobs SET status = ?, message = ?, finished_at = datetime('now') WHERE id = ?",
                         (status, message, job_id))
