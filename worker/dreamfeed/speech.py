"""A character's voice from the speech bubbles in an artist's pictures.

    python -m dreamfeed speech NAME [--no-ocr]

Some artists mostly draw one character and give her lines in speech bubbles. Those lines are
how she talks, which suits a persona that posts as that character better than the artist's
own post texts. This reads the text in the style's training pictures (only ones that passed
the checks, and only where the tagger saw text), splits it into lines, cleans each one like
an artist's post (captions.clean: business chatter, links, handles and blocked words out;
names become [name]), and saves them in data/lora/NAME/voice.json as "speech". A persona
whose voice is NAME then writes like these lines (captions.voice prefers them).
--no-ocr cleans the text read last time again (speech-raw.json), after changing the rules.

OCR can't tell who is speaking, so a line said to her ends up in the list too. Reading uses
GOT-OCR 2.0 (Apache 2.0, about 1.5 GB, downloaded into HF_HOME on first use).
"""
import json
import re
import sys
from pathlib import Path

from .config import Config

MODEL = "stepfun-ai/GOT-OCR-2.0-hf"
REVISION = "d3017ef2c2c1395888c8d635c5e0508bcb0ac78d"
TEXT_TAGS = ("speech bubble", "english text", "dialogue", "comic", "spoken heart", "text")
MIN_WORDS = 3          # shorter is a sound effect ("AH!", "mmh~") more often than a line
MAX_LINES = 300
LETTERS = re.compile(r"[A-Za-z]")
RARE = 2.0              # wordfreq zipf: about once in 100 million words
SPEAKER = re.compile(r"^[^:]{2,24}:\s")
# The artist's plugs and watermark, which OCR splits up ("PAT RE ON CAT N iPLE"): any line
# with one of these, in any spacing, is the artist talking, not her.
PLUG = re.compile(r"p\s*a\s*t\s*r?\s*e\s*o\s*n|c\s*a\s*t\s*n\s*i\s*p|l\s*e\s*w\s*d\s*s|read rules|\byc\s*h\b|"
                  r"https?|\.\s*com\b|\bsub\s*\d|subscribe|commission|discord|twitter|gumroad|\d{3,}", re.I)


def _pictures(base: Path) -> list[Path]:
    """Training pictures the tagger saw text in (their caption lists the tag)."""
    out = []
    for txt in sorted(base.glob("dataset/*/*.txt")):
        tags = {t.strip() for t in txt.read_text().split(",")}
        png = txt.with_suffix(".png")
        if png.is_file() and tags & set(TEXT_TAGS):
            out.append(png)
    return out


def _lines(text: str) -> list[str]:
    """OCR text -> candidate lines: one per bubble line, joined where a sentence wraps."""
    parts = [" ".join(p.split()) for p in re.split(r"\n+|(?<=[.!?~♥])\s{2,}", text) if p.strip()]
    out, cur = [], ""
    for p in parts:
        if cur and not re.search(r"[.!?~♥]$", cur):   # the sentence wraps onto this line
            cur = f"{cur} {p}"
        else:
            if cur:
                out.append(cur)
            cur = p
    if cur:
        out.append(cur)
    return out


def _tidy(line: str) -> str:
    """OCR quirks: "YOU' RE" -> "you're"; comics letter in capitals, which reads as shouting
    and makes every word look like a name, so all-caps lines are lower-cased."""
    line = re.sub(r"(\w)\s*['’]\s*(\w)", r"\1'\2", line)
    line = re.sub(r"\s+([,.!?~])", r"\1", line)
    letters = LETTERS.findall(line)
    if letters and sum(c.isupper() for c in letters) > 0.7 * len(letters):
        line = line.lower()
        line = re.sub(r"\bi\b", "I", line)
    return line


def _good(line: str) -> bool:
    words = line.split()
    if len(words) < MIN_WORDS or len(line) > 200 or PLUG.search(line):
        return False
    if len(LETTERS.findall(line)) < 0.6 * len(line.replace(" ", "")):
        return False
    if SPEAKER.match(line):   # "Name: ..." comments drawn into a panel, not her talking
        return False
    # Mostly one- and two-letter pieces, or words that aren't English: OCR noise.
    if sum(len(w.strip(".,!?~*-")) <= 2 for w in words) > 0.4 * len(words):
        return False
    # A stray letter ("hard b is sui y wait") is a word OCR split; "c- can't" is a stutter.
    if any(re.fullmatch(r"[b-hj-zB-HJ-Z][.,!?~]*", w) for w in words):
        return False
    if re.search(r"[a-z][A-Z]", line):   # "pTH", "WAnTs": OCR mixing up letter sizes
        return False
    # Any word rarer than "tsk" is a misread ("w olt ing", "in'tno"), not her slang.
    from wordfreq import zipf_frequency
    bare = [re.sub(r"[^a-z']", "", w.lower()) for w in words if "[name]" not in w]
    return all(zipf_frequency(w, "en") >= RARE for w in bare if w)


def _keep(texts: list[str]) -> list[str]:
    """OCR texts -> her lines, cleaned and without repeats."""
    from . import captions
    seen, kept = set(), []
    for text in texts:
        for line in _lines(text):
            line = _tidy(line)
            if not _good(line):
                continue
            line = captions.clean(line)
            if not line or line.count("[name]") > 1:
                continue
            key = re.sub(r"[^a-z]", "", line.lower())
            if key not in seen:
                seen.add(key)
                kept.append(line)
    return kept[:MAX_LINES]


def _save(base: Path, name: str, lines: list[str]) -> int:
    path = base / "voice.json"
    try:
        voice = json.loads(path.read_text())
    except (OSError, ValueError):
        voice = {"posts": []}
    voice["speech"] = lines
    path.write_text(json.dumps(voice, ensure_ascii=False, indent=1))
    print(f"speech: {len(lines)} lines saved as {name}'s character voice", flush=True)
    return len(lines)


def build(cfg: Config, name: str, reread: bool = True) -> int:
    base = cfg.data_dir / "lora" / name
    if not reread and (base / "speech-raw.json").is_file():
        return _save(base, name, _keep(json.loads((base / "speech-raw.json").read_text())))
    return _read(cfg, name)


def _read(cfg: Config, name: str) -> int:
    import torch
    from PIL import Image
    from transformers import AutoProcessor, GotOcr2ForConditionalGeneration
    base = cfg.data_dir / "lora" / name
    pics = _pictures(base)
    print(f"speech: reading {len(pics)} pictures with text", flush=True)
    proc = AutoProcessor.from_pretrained(MODEL, revision=REVISION)
    model = GotOcr2ForConditionalGeneration.from_pretrained(
        MODEL, revision=REVISION, torch_dtype=torch.bfloat16).to("cuda").eval()
    raw = []
    try:
        for n, pic in enumerate(pics, 1):
            with Image.open(pic) as im:
                inputs = proc(im.convert("RGB"), return_tensors="pt").to("cuda")
            with torch.no_grad():
                ids = model.generate(**inputs, do_sample=False, max_new_tokens=512,
                                     tokenizer=proc.tokenizer, stop_strings="<|im_end|>")
            raw.append(proc.decode(ids[0, inputs["input_ids"].shape[1]:], skip_special_tokens=True))
            if n % 20 == 0:
                print(f"speech: {n}/{len(pics)} read", flush=True)
    finally:
        del model
        torch.cuda.empty_cache()
    # The OCR text as read, to tune the cleaning without reading every picture again (--no-ocr).
    (base / "speech-raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1))
    return _save(base, name, _keep(raw))


def main(args: list[str]) -> None:
    names = [a for a in args if not a.startswith("--")]
    if len(names) != 1 or not names[0].replace("_", "").isalnum():
        sys.exit("usage: python -m dreamfeed speech NAME [--no-ocr]")
    build(Config(), names[0], reread="--no-ocr" not in args)
