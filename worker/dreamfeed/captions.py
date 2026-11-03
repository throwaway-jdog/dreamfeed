"""A fresh caption for every post, written by a small local text model (CAPTION_MODEL).

After the night's checks, each post that makes the feed gets a caption written from what the
tagger sees in the picture, in its persona's voice:
- a persona with a voice (a trained style whose artist's post texts were saved when it was
  downloaded) writes like that artist
- otherwise it writes like the persona's own example captions in data/personas.json

The artist's texts are cleaned before the model sees them: no @handles, links, hashtags,
commission or follower talk, and character, series and people's names become [name]. Every
caption the model writes is checked, and thrown away if it names anyone, mentions ages or
school or anything young (safety.CAPTION_NEVER), has links or @mentions, or copies an example.
A post whose caption fails every try keeps its example caption. CAPTION_MODEL empty: captions
come from the examples, as before.
"""
import csv
import difflib
import json
import random
import re
from functools import cache
from pathlib import Path

from . import safety
from .personas import RATINGS

TRIES = 4
EXAMPLES = 14         # example posts shown to the model per caption
MAX_VOICE = 300       # cleaned artist posts kept per style
MAX_CHARS = 280
PICTURE_TAGS = 25     # tagger tags describing the picture
TAG_MIN = 0.35
RECENT = 8            # the persona's latest captions, which a new one must not repeat
COPY_RUN = 5          # this many words in a row from an example counts as copied
META_TAG = re.compile(r"text|watermark|signature|artist|username|logo|censor|url|web address|commentary|border")
CHATTER = re.compile(  # artist posts about business, not the picture
    r"\b(comm(ission)?s?|ych|patreon|fanbox|ko-?fi|gumroad|fantia|subscribestar|request(s|ed)?|tiers?|"
    r"rewards?|stream(ing)?|giveaway|raffle|followers?|\d+k|link in bio|dm me|dms|open|slots?|"
    r"poll|vote|price|\$\d+|war|army|country|election|president|politic\w*)\b", re.I)
# Only posts in English (Latin letters) are used: names and blocked words can't be checked in others.
FOREIGN = re.compile(r"[^\W\da-zA-Z_À-ɏ]")
REFUSAL = re.compile(r"\b(i can'?t|i cannot|i'm sorry|as an ai|i won'?t)\b", re.I)
WORD = re.compile(r"[A-Za-z][A-Za-z']*")

SYSTEM = (
    "You write the caption for one post on a private feed of fictional adult artist and model "
    "accounts. Write as the account owner: match the tone, length, casing, punctuation and emoji "
    "habits of their past posts, but never reuse their sentences. Every character is an adult. "
    "Never name any character, series, game or real person: where their posts say [name], write "
    "she, he, they or a short description instead. Never mention "
    "ages, school, or anything young. No @mentions, links or hashtags. Reply with the caption only.")


# ---- which words are names -----------------------------------------------------------------
# A word counts as a name when it is part of a character tag the tagger knows and isn't a
# common English word (luna, fern, nia), or it is capitalized and rare in English (Deku,
# Reimu), or capitalized mid-sentence and not very common (Ruby, Fenrys).
TAG_NAME_BELOW = 4.0      # wordfreq zipf: 4 is about once per 100,000 words
CAPITAL_BELOW = 3.0
MID_CAPITAL_BELOW = 4.0


@cache
def tag_names() -> frozenset:
    """Tokens of the tagger's character tags (downloaded with the tagger, already on disk)."""
    from huggingface_hub import hf_hub_download
    from .vision import TAGGER_REPO, CAT_CHARACTER
    with open(hf_hub_download(TAGGER_REPO, "selected_tags.csv"), newline="") as f:
        rows = list(csv.DictReader(f))
    return frozenset(w for r in rows if int(r["category"]) == CAT_CHARACTER
                     for w in re.findall(r"[a-z]+", r["name"].replace("_", " ").lower()) if len(w) >= 3)


def _names_in(text: str, allowed: set[str]) -> list[str]:
    from wordfreq import zipf_frequency
    out = []
    for m in WORD.finditer(text):
        w = m.group(0)
        low = w.lower().removesuffix("'s").strip("'")
        if low in allowed or w == "I" or len(low) < 2:
            continue
        freq = zipf_frequency(low, "en")
        before = text[:m.start()].rstrip(" \t")
        starts = not before or not (before[-1].isalnum() or before[-1] in ",;'")   # a sentence starts here
        if ((low in tag_names() and freq < TAG_NAME_BELOW)
                or (w[0].isupper() and freq < CAPITAL_BELOW)
                or (w[0].isupper() and not starts and freq < MID_CAPITAL_BELOW)):
            out.append(w)
    return out


# ---- the artist's voice: saved post texts, cleaned ------------------------------------------

def clean(text: str) -> str | None:
    """An artist's post text fit to show the model, or None to leave it out."""
    if FOREIGN.search(text) or CHATTER.search(text) or safety.caption_blocked(text):
        return None
    text = re.sub(r"https?://\S+|www\.\S+", "", text)
    text = re.sub(r"[@#]\w+", "", text)
    for n in sorted(set(_names_in(text, set())), key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(n)}\b('s)?", "[name]", text)
    text = re.sub(r"\[name\]((\s*(x|and|&|,)\s*)?\[name\])+", "[name]", text)
    text = "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())
    text = re.sub(r"\(\s*\[name\]\s*\)", "", text).strip()
    if len(WORD.findall(text.replace("[name]", ""))) < 1 or len(text) > MAX_CHARS:
        return None
    return text


def build_voice(base: Path) -> int:
    """data/lora/NAME/voice.json from posts.jsonl (written by the downloader), keeping only posts
    whose images survived the checks. Returns how many posts it kept."""
    src = base / "posts.jsonl"
    if not src.is_file():
        return 0
    kept_ids = {p.name.split("_", 1)[0] for p in (base / "raw").iterdir() if p.is_file()}
    seen, out = set(), []
    for line in src.read_text().splitlines():
        try:
            post = json.loads(line)
        except ValueError:
            continue
        tid = str(post.get("tweet_id", ""))
        if tid in seen or post.get("reply_id") or post.get("retweet_id") or (tid and tid not in kept_ids):
            continue
        seen.add(tid)
        text = clean(str(post.get("content") or ""))
        if text and text not in out:
            out.append(text)
    out = out[:MAX_VOICE]
    (base / "voice.json").write_text(json.dumps({"posts": out}, ensure_ascii=False, indent=1))
    print(f"captions: {len(out)} of {len(seen)} posts kept as {base.name}'s voice", flush=True)
    return len(out)


def voice(cfg, name: str) -> list[str]:
    try:
        return json.loads((cfg.data_dir / "lora" / name / "voice.json").read_text())["posts"]
    except (OSError, ValueError, KeyError):
        return []


# ---- checking what the model wrote -----------------------------------------------------------

def problem(text: str, examples: list[str], allowed: set[str]) -> str | None:
    if not text or len(text) > MAX_CHARS:
        return "length"
    if re.search(r"@\w|https?://|www\.|#\w|\[|\]", text):
        return "mention, link, hashtag or [name]"
    if REFUSAL.search(text):
        return "refusal"
    bad = safety.caption_blocked(text)
    if bad:
        return "blocked: " + ", ".join(bad)
    names = _names_in(text, allowed)
    if names:
        return "name: " + ", ".join(names)
    from wordfreq import zipf_frequency
    used = {w.lower() for w in WORD.findall(text)}
    for ex in examples:   # names the cleaning missed (Lena, Diane): no capitalized example word
        for w in WORD.findall(ex):
            if w[0].isupper() and w != "I" and w.lower() in used and zipf_frequency(w.lower(), "en") < 4:
                return f"name from an example: {w}"
    words = [w.lower() for w in WORD.findall(text)]
    runs = {tuple(words[i:i + COPY_RUN]) for i in range(len(words) - COPY_RUN + 1)}
    for ex in examples:
        ew = [w.lower() for w in WORD.findall(ex)]
        if runs & {tuple(ew[i:i + COPY_RUN]) for i in range(len(ew) - COPY_RUN + 1)}:
            return "copied"
        if difflib.SequenceMatcher(None, text.lower(), ex.lower()).ratio() > 0.8:
            return "copied"
    return None


def _repeats(text: str, recent: list[str]) -> str | None:
    """Too close to one of the persona's latest captions."""
    core = lambda t: " ".join(w.lower() for w in WORD.findall(re.sub(r"#\w+", "", t)))
    for r in recent:
        if difflib.SequenceMatcher(None, core(text), core(r)).ratio() > 0.65:
            return "repeats a recent caption"
    return None


def _tidy(out: str) -> str:
    out = out.strip().strip('"“”').strip()
    lines = [l.strip() for l in out.splitlines() if l.strip()][:3]
    return "\n".join(lines)


def rating_of(prompt: str) -> str:
    """The post's rating, from the prefix personas.RATINGS put on its prompt."""
    for name, prefix in sorted(RATINGS.items(), key=lambda kv: -len(kv[1])):
        if prefix and prompt.startswith(prefix):
            return name
    return "general"


def picture(general: dict[str, float]) -> list[str]:
    return [t for t, s in sorted(general.items(), key=lambda kv: -kv[1])
            if s >= TAG_MIN and not META_TAG.search(t) and not safety.blocked(t)][:PICTURE_TAGS]


# ---- the model ------------------------------------------------------------------------------

class Writer:
    def __init__(self, model_id: str):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        print(f"captions: loading {model_id}", flush=True)
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(model_id)
        self.model = AutoModelForCausalLM.from_pretrained(model_id, dtype=torch.bfloat16).to("cuda").eval()

    def close(self) -> None:
        del self.model
        self.torch.cuda.empty_cache()

    def ask(self, system: str, user: str, max_new_tokens: int = 90) -> str:
        return _tidy(self._sample([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                  max_new_tokens))

    def _sample(self, messages: list[dict], max_new_tokens: int = 90) -> str:
        ids = self.tok.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt").to("cuda")
        with self.torch.no_grad():
            out = self.model.generate(ids, attention_mask=self.torch.ones_like(ids), max_new_tokens=max_new_tokens,
                                      do_sample=True, temperature=0.9, top_p=0.95,
                                      pad_token_id=self.tok.eos_token_id)
        return self.tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True)

    def write(self, persona, examples: list[str], tags: list[str], rating: str, rng: random.Random,
              recent: list[str] = ()) -> tuple[str | None, list[str]]:
        """A checked caption (or None) and why the rejected tries were rejected."""
        allowed = {w.lower() for w in WORD.findall(persona.name)}
        words = sorted(len(WORD.findall(e)) for e in examples) or [8]
        target = max(2, words[len(words) // 2])
        why = []
        for _ in range(TRIES):
            shown = rng.sample(examples, min(EXAMPLES, len(examples)))
            user = (f"Account: {persona.name}, a {persona.medium} account."
                    + (f" Bio: {persona.bio}" if persona.bio else "")
                    + (f"\nEmoji they like (use one or two at most, or none): {' '.join(persona.emoji)}"
                       if persona.emoji else "")
                    + "\n\nTheir past posts:\n" + "\n".join(f"- {e}" for e in shown)
                    + ("\n\nTheir latest captions (say something different, with other words):\n"
                       + "\n".join(f"- {r}" for r in recent) if recent else "")
                    + f"\n\nThe new picture ({rating}): {', '.join(tags)}"
                    + f"\nWrite the caption, about {target} words.")
            text = self.ask(SYSTEM, user)
            reason = problem(text, examples, allowed) or _repeats(text, recent)
            if not reason:
                return text, why
            why.append(reason)
        return None, why


def write_all(cfg, conn, night: str, posts: list[tuple[int, str, list[str]]], progress) -> dict[int, str]:
    """Captions for (generation id, persona handle, picture tags); {} when CAPTION_MODEL is off
    or the model can't load (posts then keep their example captions)."""
    model_id = cfg.caption_model
    if not model_id or not posts:
        return {}
    from .personas import load
    by_handle = {p.handle: p for p in load(cfg.personas_path)}
    try:
        writer = Writer(model_id)
    except Exception as e:
        print(f"captions: couldn't load {model_id} ({e}); keeping example captions", flush=True)
        return {}
    rng = random.Random()
    out, failed = {}, 0
    recent = {h: [c for (c,) in conn.execute(
        "SELECT caption FROM generations WHERE persona = ? AND status = 'feed' AND kind = 'image'"
        " AND caption IS NOT NULL ORDER BY id DESC LIMIT ?", (h, RECENT))] for h in {h for _, h, _ in posts}}
    try:
        for n, (gid, handle, tags) in enumerate(posts, 1):
            progress(n - 1, len(posts))
            p = by_handle.get(handle)
            row = conn.execute("SELECT prompt FROM generations WHERE id = ?", (gid,)).fetchone()
            if not p or not row or not tags:
                continue
            examples = (voice(cfg, p.voice) if p.voice else []) or [c for k in p.posts for c in k.captions]
            text, why = writer.write(p, examples, tags, rating_of(row[0]), rng, recent[handle][:RECENT])
            if text is None:
                failed += 1
                print(f"captions: gave up on #{gid} (@{handle}): {'; '.join(why)}", flush=True)
                continue
            if p.hashtags and rng.random() < 0.35:
                text += " " + " ".join("#" + t for t in rng.sample(p.hashtags, k=min(2, len(p.hashtags))))
            out[gid] = text
            recent[handle].insert(0, text)
    finally:
        writer.close()
    print(f"captions: wrote {len(out)} of {len(posts)}, {failed} kept their example caption", flush=True)
    return out
