"""Comics: a short story about two characters, drawn as pages of panels with speech bubbles.

    python -m dreamfeed comic HANDLE (HANDLE | partner) --story "..." [--pages 1-4] [--seed N]

The dashboard's Comics page queues the same thing as a job (kind "comic"). Steps:
1. Cast: two personas (a friend pair: each with their own character LoRA), or a persona and her
   partner (a man from her partners list). Two women make a girl-girl story; with a man, a
   straight one (acts.kind).
2. A reference picture of the two of them, dressed, drawn and checked like a post (scenes taught
   us a clean starting picture is what keeps every shot alike). It's the comic's cast and room.
3. Script: the panels' actions are planned here (build-up, then acts, cuddling at the end); the
   text model writes each page's lines from the story, following on from the page before.
   Lines get the caption checks plus safety.story_blocked (consensual, adults), mustn't copy an
   example line, and mustn't bring in anyone else.
4. Panels: scene.draw, all pages in one go (one cast, one room, the same checks as a scene).
   Build-up panels are dressed (an outfit of the persona's; nude kept out), act panels nude.
5. Bubbles are drawn here, not by the image model (it can't write): where the cut-out shows no
   one, near the top, the tail toward the speaker (told apart by hair colour).
6. Pages of 2 by 2 panels, saved as generated/comic-.../page-N.jpg with comic.json, and a
   generations row (kind and status "comic", the first page as its file) for the dashboard.
"""
import argparse
import datetime as dt
import difflib
import json
import random
import re
import sys
import textwrap
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import acts, safety, scene

PANELS = 4             # per page
MAX_PAGES = 4
FONT = Path(__file__).parent / "fonts" / "ComicNeue-Bold.ttf"   # SIL Open Font License (fonts/OFL.txt)
PAGE_W, GUTTER, BORDER = 1600, 24, 5
MAX_LINE = 70          # characters in one panel's line
COPIED = 0.7           # a line this alike (difflib) to an example line is a copy
REFERENCE_TRIES = 4
EXPRESSIONS = ("smile", "blush", "smug", "surprised", "embarrassed", "happy", "teasing", "open mouth")
NAKED = ("nude, completely nude, nipples, pussy, penis, topless, breasts out, sex")   # kept out of dressed panels
# What a panel can show, by kind of story: name -> (picture tags, the scene act it's checked as).
TALK = {
    "talking": ("talking, looking at another, cowboy shot", None),
    "teasing": ("teasing, leaning close, finger to own lips, cowboy shot", None),
    "hug": ("hug, embracing, upper body", None),
    "undressing": ("undressing, taking off shirt, blush, cowboy shot", None),
}
AFTER = ("cuddling", ("lying together, cuddling, hug, nude, smile", None))
ACTIONS = {
    "girl-girl": TALK | {a: (scene.YURI_POSITIONS[a][0], a) for a in scene.YURI_POSITIONS} | dict([AFTER]),
    "straight": TALK | {a: (scene.POSITIONS[a][0] + (", " + scene.SIDE_ON if a != "blowjob" else ""),
                            scene.POSITIONS[a][1]) for a in scene.POSITIONS} | dict([AFTER]),
}
HAIR = {"red": (200, 45, 45), "orange": (230, 120, 40), "grey": (150, 150, 155), "gray": (150, 150, 155),
        "white": (235, 235, 235), "silver": (200, 200, 210), "black": (30, 30, 35), "brown": (110, 70, 40),
        "blonde": (230, 200, 110), "blue": (60, 90, 200), "pink": (235, 140, 175), "purple": (130, 60, 170),
        "green": (60, 150, 70)}
MAN = re.compile(r"\b(he|him|his|he's|boyfriend|man|guy)\b", re.I)

SCRIPT_SYSTEM = (
    "You write short adult comics about fictional adult characters who are a couple and want each "
    "other. Everything is consensual, playful and affectionate. Never mention ages, school, family "
    "or anything young, and never use anyone's name. Reply with JSON only.")


def _hair(look: str) -> tuple[int, int, int] | None:
    for t in look.split(","):
        t = re.sub(r"^\((.*):[\d.]+\)$", r"\1", t.strip()).lower()
        if "hair" in t:
            for word, rgb in HAIR.items():
                if word in t:
                    return rgb
    return None


def _voice(cfg, p, girls_only: bool) -> list[str]:
    from . import captions
    lines = (captions.voice(cfg, p.voice) if p.voice else []) + [c for k in p.posts for c in k.captions]
    return [l for l in lines if len(l) <= MAX_LINE and not (girls_only and MAN.search(l))]


def _line_ok(line: str, examples: list[str], girls_only: bool) -> bool:
    from .captions import REFUSAL
    if not line or len(line) > MAX_LINE or REFUSAL.search(line) or safety.story_blocked(line):
        return False
    if re.search(r"@\w|https?://|www\.|#\w|\[|\]", line) or (girls_only and MAN.search(line)):
        return False
    return all(difflib.SequenceMatcher(None, line.lower(), e.lower()).ratio() < COPIED for e in examples)


def plan(kind: str, pages: int, rng: random.Random, picks: list[str] | None = None) -> list[str]:
    """Each panel's action: two build-up panels, then acts (the ones picked, else random), the
    last panel cuddling."""
    sex = [a for a in ACTIONS[kind] if a not in TALK and a != AFTER[0]]
    out = rng.sample(list(TALK), 2)
    acts_ = [a for a in (picks or []) if a in sex] or []
    while len(out) < pages * PANELS - 1:
        out.append(acts_.pop(0) if acts_ else rng.choice([a for a in sex if a != out[-1]] or sex))
    return out + [AFTER[0]]


def script(cfg, cast: list, kind: str, story: str, actions: list[str], rng: random.Random) -> dict:
    """{"title", "panels": [{"action", "expression", "speaker" (0, 1 or None), "line"}]}, one page
    at a time, each following on from the lines before."""
    from .captions import Writer
    girls = kind == "girl-girl"
    voices = [rng.sample(v, min(8, len(v))) for v in (_voice(cfg, p, girls) for p in cast)]
    examples = [l for v in voices for l in v]
    who = "\n".join(f"- {'AB'[i]}: {p.bio or p.name}. How they talk: " + " / ".join(v)
                    for i, (p, v) in enumerate(zip(cast, voices)))
    panels, title = [], ""
    writer = Writer(cfg.caption_model) if cfg.caption_model else None
    try:
        for start in range(0, len(actions), PANELS):
            page_actions = actions[start:start + PANELS]
            so_far = "\n".join(f"- {'AB'[p['speaker']]}: {p['line']}" for p in panels if p["speaker"] is not None)
            user = (f"Characters:\n{who}\n\nThe story: {story}\n\n"
                    + (f"What they said so far:\n{so_far}\n\n" if so_far else "")
                    + f"Write page {start // PANELS + 1} of the comic. Only these two are in it. What happens in "
                      f"each panel, in order: {', '.join(page_actions)}. The lines follow the story and each "
                      f"other, in each one's own way of talking, but never copy their example lines. For each "
                      f"panel: \"expression\" (one of {', '.join(EXPRESSIONS)}), \"speaker\" (\"A\", \"B\" or "
                      f"null), \"line\" (at most 10 words)."
                    + (" Also a \"title\" for the comic (a short post caption)." if start == 0 else "")
                    + '\n{"title": "...", "panels": [{"expression": "...", "speaker": "A", "line": "..."}]}')
            got = None
            for _ in range(4 if writer else 0):
                raw = writer._sample([{"role": "system", "content": SCRIPT_SYSTEM},
                                      {"role": "user", "content": user}], max_new_tokens=400)
                try:
                    data = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
                    out = []
                    for action, pn in zip(page_actions, data["panels"]):
                        speaker = {"A": 0, "B": 1}.get(str(pn.get("speaker") or "").strip().upper())
                        line = " ".join(str(pn.get("line") or "").split())
                        if speaker is not None and not _line_ok(line, examples, girls):
                            raise ValueError(f"line {line!r}")
                        expr = str(pn.get("expression", "smile")).strip().lower()
                        out.append({"action": action, "expression": expr if expr in EXPRESSIONS else "smile",
                                    "speaker": speaker if line else None, "line": line if speaker is not None else ""})
                    t = " ".join(str(data.get("title", "")).split())
                    if len(out) != len(page_actions) or (start == 0 and not _line_ok(t, examples, girls)):
                        raise ValueError("panels or title")
                    got, title = out, title or t
                    break
                except (ValueError, KeyError, TypeError, AttributeError) as e:
                    print(f"comic: page {start // PANELS + 1} retry ({str(e)[:80]})", flush=True)
            # Without a usable script: the pictures alone, no bubbles.
            panels += got or [{"action": a, "expression": rng.choice(EXPRESSIONS), "speaker": None, "line": ""}
                              for a in page_actions]
    finally:
        if writer:
            writer.close()
    print(f"comic: script {json.dumps(panels)}", flush=True)
    return {"title": title or story[:60], "panels": panels}


def _heads(mask: np.ndarray) -> list[tuple[int, int]]:
    """The top of each of the (up to) two people in a cut-out mask, left one first."""
    m = mask > 128
    cols = np.where(m.any(0))[0]
    if not len(cols):
        return []
    mid = (cols.min() + cols.max()) // 2
    out = []
    for lo, hi in ((cols.min(), mid), (mid, cols.max() + 1)):
        rows = np.where(m[:, lo:hi].any(1))[0]
        if len(rows):
            top = rows.min()
            xs = np.where(m[top:top + max(8, mask.shape[0] // 40), lo:hi].any(0))[0] + lo
            out.append((int(xs.mean()), int(top)))
    return out


def _speaker_head(img: Image.Image, mask: np.ndarray, heads: list, hair: tuple | None) -> tuple[int, int] | None:
    """Which head is the speaker's: the one whose hair (the character's own pixels in the cut-out,
    just below the top of the head) is closest in colour."""
    if not heads:
        return None
    if len(heads) == 1 or hair is None:
        return heads[0]
    a = np.asarray(img.convert("RGB"), dtype=np.float32)
    h, w = mask.shape

    def dist(head):
        x, y = head
        y0, y1, x0, x1 = y, min(h, y + h // 8), max(0, x - w // 8), min(w, x + w // 8)
        own = mask[y0:y1, x0:x1] > 128
        if not own.any():
            return 1e9
        return float(np.linalg.norm(a[y0:y1, x0:x1][own].mean(0) - np.array(hair)))
    return min(heads, key=dist)


def bubble(img: Image.Image, mask: Image.Image, line: str, head: tuple[int, int] | None) -> Image.Image:
    """The panel with a speech bubble for line: where nobody is (the cut-out mask), near the top,
    its tail toward head."""
    img = img.convert("RGB").copy()
    w, h = img.size
    font = ImageFont.truetype(str(FONT), max(18, w // 22))
    lines = textwrap.wrap(line, width=18) or [line]
    draw = ImageDraw.Draw(img)
    box = [draw.textbbox((0, 0), l, font=font) for l in lines]
    tw = max(b[2] - b[0] for b in box)
    lh = max(b[3] - b[1] for b in box) + font.size // 4
    bw, bh = int(tw * 1.25 + font.size * 1.6), int(lh * len(lines) * 1.2 + font.size * 1.2)
    m = np.asarray(mask.convert("L").resize((w, h)), dtype=np.float32) / 255
    best = None
    for y in range(int(h * 0.02), int(h * 0.45) - bh, max(8, h // 40)):
        for x in range(int(w * 0.02), w - bw - int(w * 0.02), max(8, w // 40)):
            cover = float(m[y:y + bh, x:x + bw].mean())
            near = 0.0 if head is None else np.hypot(x + bw / 2 - head[0], y + bh - head[1]) / max(w, h)
            score = cover * 3 + near * 0.5 + y / h * 0.2
            if best is None or score < best[0]:
                best = (score, x, y)
    _, x, y = best or (0, int(w * 0.05), int(h * 0.03))
    ink, fill = (20, 20, 20), (255, 255, 255)
    if head is not None:   # the tail, under the bubble, from its edge toward the speaker
        cx, cy = x + bw / 2, y + bh / 2
        tx, ty = cx + (head[0] - cx) * 0.75, cy + (head[1] - cy) * 0.75
        base = font.size * 0.7
        ang = np.arctan2(ty - cy, tx - cx) + np.pi / 2
        p1 = (cx + np.cos(ang) * base, cy + np.sin(ang) * base)
        p2 = (cx - np.cos(ang) * base, cy - np.sin(ang) * base)
        draw.polygon([p1, p2, (tx, ty)], fill=fill, outline=ink, width=3)
    draw.ellipse([x, y, x + bw, y + bh], fill=fill, outline=ink, width=4)
    ty = y + (bh - lh * len(lines)) / 2
    for l, b in zip(lines, box):
        draw.text((x + (bw - (b[2] - b[0])) / 2, ty), l, font=font, fill=ink)
        ty += lh
    return img


def page(panels: list[Image.Image]) -> Image.Image:
    """2 by 2 panels on a white page, each in a black border."""
    cell_w = (PAGE_W - 3 * GUTTER) // 2
    cell_h = int(cell_w * 1.35)
    out = Image.new("RGB", (PAGE_W, 3 * GUTTER + 2 * cell_h), "white")
    d = ImageDraw.Draw(out)
    for i, p in enumerate(panels):
        x, y = GUTTER + (i % 2) * (cell_w + GUTTER), GUTTER + (i // 2) * (cell_h + GUTTER)
        r = max(cell_w / p.width, cell_h / p.height)   # cover the cell, cropped from the middle
        q = p.resize((int(p.width * r) + 1, int(p.height * r) + 1), Image.LANCZOS)
        left, top = (q.width - cell_w) // 2, min((q.height - cell_h) // 4, q.height - cell_h)
        out.paste(q.crop((left, top, left + cell_w, top + cell_h)), (x, y))
        d.rectangle([x, y, x + cell_w - 1, y + cell_h - 1], outline=(0, 0, 0), width=BORDER)
    return out


def cast_for(cfg, handles: list[str]):
    """(personas [A, B] for the script, the persona drawing it with B as a friend or partner,
    the reference prompt). handles: [A, B] with B a persona handle or "partner"."""
    from . import personas as people
    every = {p.handle: p for p in people.load(cfg.personas_path)}
    a = every.get(handles[0])
    if not a or not a.lora:
        raise ValueError(f"@{handles[0]} isn't a persona with a trained character")
    rng = random.Random()
    if handles[1] == "partner":
        partner = rng.choice(a.partners) if a.partners else "faceless male"
        post = people.Post("comic", 1, f"duo, 1boy, hetero, {partner}, hug, smile, blush, {{outfit}}, {{setting}}",
                           "questionable", [""])
        return [a, a], a, a.prompt_for(post, rng)
    b = every.get(handles[1])
    if not b or b.handle == a.handle or b.medium != a.medium:
        raise ValueError(f"@{handles[1]} can't be in a comic with @{a.handle}")
    if a.strict or b.strict:   # their stricter adult checks can't follow them into someone else's picture
        raise ValueError("personas using the strict checks can't be in a comic together")
    a.friends = [b.handle]
    two = "2girls, yuri" if "1boy" not in b.look else "1boy, hetero"
    post = people.Post("comic", 1, f"duo, {two}, {{friend}}, hug, smile, blush, {{outfit}}, {{setting}}",
                       "questionable", [""])
    return [a, b], a, a.prompt_for(post, rng)


def reference(cfg, comfy, persona, prompt: str, subdir: str, name: str, rng: random.Random) -> Path:
    """The comic's starting picture: drawn until one passes every post check."""
    from .checks import problem
    from .generate import CLOTHED_NEGATIVE, _watermark
    from .vision import Vision
    gen = cfg.generation()
    ckpt = gen.checkpoints[persona.medium]
    paths = []
    try:
        for n in range(REFERENCE_TRIES):
            paths.append(comfy.txt2img(ckpt, persona.medium, prompt, rng.randrange(2 ** 32), subdir, f"{name}-ref{n}",
                                       strict=persona.strict, lora=persona.lora_for(prompt),
                                       extra_negative=f"{persona.negative}, {CLOTHED_NEGATIVE}",
                                       regions=persona.regions(prompt, rng)))
    finally:
        comfy.stop()
    vision = Vision(cfg.models_dir)
    best = None
    try:
        for p in paths:
            with Image.open(p) as im:
                img = im.convert("RGB")
            a = vision.analyze([img])
            seen = {t for t, s in a.general.items() if s >= 0.35}
            if problem(a, persona.medium, [img], cfg, strict=persona.strict) or _watermark(a) or \
                    persona.off_model(seen, prompt):
                continue
            best = best or p
    finally:
        vision.close()
    for p in paths:
        if p != best:
            p.unlink(missing_ok=True)
    if not best:
        raise RuntimeError(f"no reference picture passed the checks in {REFERENCE_TRIES} tries")
    return best


def make(cfg, handles: list[str], story: str, pages: int, seed: int | None = None,
         progress=lambda phase, done, total: None) -> dict:
    """A comic: {"title", "pages": [files under generated/], "dir"}."""
    from . import cutout
    from .comfy import Comfy
    bad = safety.story_blocked(story)
    if bad:
        raise ValueError(f"the story can't include: {', '.join(bad)}")
    pages = max(1, min(MAX_PAGES, pages))
    cast, persona, ref_prompt = cast_for(cfg, handles)
    kind = acts.kind(ref_prompt)
    rng = random.Random(seed)
    gen = cfg.generation()
    out_dir = cfg.data_dir / "generated"
    night = f"comic-{dt.datetime.now():%Y%m%d-%H%M%S}"
    comfy = Comfy(gen.comfy_url, gen.supervisor_url, out_dir)
    progress("drawing the two of them", 0, 1)
    ref = reference(cfg, comfy, persona, ref_prompt, night, "comic", rng)
    actions = plan(kind, pages, rng)
    progress("writing", 0, 1)
    sc = script(cfg, cast, kind, story, actions, rng)
    # The panels' cast and room: the reference picture's prompt, minus its outfit (dressed panels
    # get it back; act panels are nude).
    outfit = next((o for o in persona.outfits if o in ref_prompt), "")
    base = ", ".join(t for t in ref_prompt.split(", ") if t.strip() not in {x.strip() for x in outfit.split(",")})
    post = {"medium": persona.medium, "prompt": base, "file": ref, "persona": persona.handle,
            "checkpoint": gen.checkpoints[persona.medium], "strict": persona.strict}
    yuri = kind == "girl-girl"
    shots = []
    for i, pn in enumerate(sc["panels"]):
        tags, act = ACTIONS[kind][pn["action"]]
        dressed = pn["action"] in TALK and pn["action"] != "undressing"
        shots.append(scene.Shot(
            f"page {i // PANELS + 1} panel {i % PANELS + 1}: {pn['action']}",
            f"{tags}, {pn['expression']}" + (f", ({outfit}:1.2), clothed" if dressed and outfit else "")
            + (", talking, open mouth" if pn["speaker"] is not None else ""),
            act, False, "", yuri=yuri, avoid=NAKED if dressed else ""))
    progress("drawing the panels", 0, len(shots))
    drawn = scene.draw(cfg, comfy, persona, post, shots, night, "comic", rng)
    ref.unlink(missing_ok=True)
    progress("lettering", 0, 1)
    cut = cutout.Cutout()
    try:
        panels = []
        for (path, note), pn in zip(drawn, sc["panels"]):
            if path is None:   # every candidate failed a check: a blank panel rather than none
                panels.append(Image.new("RGB", (832, 1216), "white"))
                print(f"comic: blank panel ({note})", flush=True)
                continue
            with Image.open(path) as im:
                img = im.convert("RGB")
            if pn["speaker"] is not None and pn["line"]:
                mask = cut.mask(img)
                m = np.asarray(mask)
                head = _speaker_head(img, m, _heads(m), _hair(cast[pn["speaker"]].look))
                img = bubble(img, mask, pn["line"], head)
            panels.append(img)
            path.unlink(missing_ok=True)
    finally:
        cut.close()
    folder = out_dir / night
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    for n in range(0, len(panels), PANELS):
        path = folder / f"page-{n // PANELS + 1}.jpg"
        page(panels[n:n + PANELS]).save(path, quality=90)
        files.append(str(path.relative_to(out_dir)))
    meta = {"title": sc["title"], "pages": files, "cast": handles, "story": story, "script": sc["panels"]}
    (folder / "comic.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print(f"comic: {night} {sc['title']!r}, {len(files)} pages", flush=True)
    return meta | {"night": night}


def run_job(cfg, conn, job_id: int, params: dict) -> None:
    """A comic queued from the dashboard: params {"kind": "comic", "cast": [A, B|partner], "story", "pages"}."""
    from .generate import _cancel_requested, _progress, _set
    night = f"comicjob-{job_id}"
    with conn:
        conn.execute("UPDATE jobs SET status = 'running', night = ? WHERE id = ?", (night, job_id))
        conn.execute("INSERT INTO runs(night, status, attempts, started_at) VALUES (?, 'running', 1, datetime('now'))",
                     (night,))
    status, message = "done", None
    try:
        meta = make(cfg, params["cast"], params["story"], int(params.get("pages", 1)),
                    progress=lambda phase, d, t: _progress(conn, night, phase, d, t))
        persona = params["cast"][0]
        with conn:
            gid = conn.execute(
                "INSERT INTO generations(night, medium, checkpoint, prompt, seed, persona, caption, kind, status, file)"
                " SELECT ?, medium, 'comic', ?, 0, handle, ?, 'comic', 'comic', ? FROM personas WHERE handle = ?",
                (meta["night"], params["story"], meta["title"], meta["pages"][0], persona)).lastrowid
        message = f"{len(meta['pages'])} pages: {meta['title']}"
        _set(conn, gid, posted_at=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
        if _cancel_requested(conn, night):
            status = "cancelled"
    except Exception as e:
        status, message = "failed", str(e)[:300]
        print(f"comic: job {job_id} failed: {message}", flush=True)
    finally:
        with conn:
            conn.execute("UPDATE runs SET status = ?, progress = NULL, finished_at = datetime('now') WHERE night = ?",
                         (status, night))
            conn.execute("UPDATE jobs SET status = ?, message = ?, finished_at = datetime('now') WHERE id = ?",
                         (status, message, job_id))


def main(args: list[str]) -> None:
    from .config import Config
    ap = argparse.ArgumentParser(prog="dreamfeed comic")
    ap.add_argument("a", help="a persona's handle")
    ap.add_argument("b", help="another persona's handle, or partner (a man from A's partners list)")
    ap.add_argument("--story", required=True)
    ap.add_argument("--pages", type=int, default=1)
    ap.add_argument("--seed", type=int)
    a = ap.parse_args(args)
    try:
        meta = make(Config(), [a.a, a.b], a.story, a.pages, a.seed)
    except ValueError as e:
        sys.exit(f"comic: {e}")
    print(json.dumps({k: meta[k] for k in ("title", "pages")}))
