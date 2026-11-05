"""The one check every picture and clip goes through before it is kept (see safety.py for the
rules and where else they apply).

    problem(a, medium, frames, cfg, strict=False, training=False) -> (reason, detail) or None

a is the tagger and CLIP's analysis (vision.Analysis) of frames. In order:
- youth-tag:    the tagger sees a youth tag (safety.YOUTH_TAGS) at YOUTH_TAG_THRESHOLD
- age-estimate: photos only, a clearly visible face estimated under PHOTO_MIN_AGE (agecheck)
- age-check:    CLIP's share for "youth" at AGE_THRESHOLD, or the lower STRICT_AGE_THRESHOLD
                for strict personas; for photos with no clear face, and every drawing
- feral:        sexual content with (non-anthro) animals (safety.FERAL_TAGS)
and for training data (training=True: always strict, since a LoRA repeats what it learns):
- photo:        it's a photo, not a drawing (training uses drawn art only)
- blocked-tag:  the tagger sees a tag that's never allowed in a prompt (safety.NEVER_PROMPT_TAGS)
"""
import io
import json
import urllib.request

from . import safety
from .config import Config


def face_ages(frames, cfg: Config) -> list[float]:
    """MiVOLO estimates for clearly visible faces in any frame. Body-only estimates are
    too unreliable to use (they swing by decades between frames of one video)."""
    ages = []
    for frame in frames:
        buf = io.BytesIO()
        frame.save(buf, format="PNG")
        req = urllib.request.Request(f"{cfg.agecheck_url}/estimate", data=buf.getvalue(), method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:   # unreachable: batch stops, file stays
            people = json.load(resp)["people"]
        ages += [p["age"] for p in people if p["face_px"] >= cfg.min_face_px]
    return ages


def problem(a, medium: str, frames, cfg: Config, strict: bool = False,
            training: bool = False) -> tuple[str, str] | None:
    """Why this picture or clip must not be kept, or None. strict: a persona whose look models
    tend to draw young; training: it's for a LoRA."""
    strict = strict or training
    hits = safety.youth_tag_hits(a.general, cfg.youth_tag_threshold)
    if hits:
        return "youth-tag", ", ".join(f"{h} {a.general[h]:.2f}" for h in hits)
    if training:
        photo = safety.photo_signs(a.general, a.medium_probs)
        if photo:
            return "photo", photo
    reason = _age(a, medium, frames, cfg, strict)
    if reason:
        return reason
    hits = safety.feral_hits(a.general)
    if hits:
        return "feral", ", ".join(hits)
    if training:   # e.g. flat chest, petite: a LoRA shouldn't learn them
        bad = safety.blocked(", ".join(t for t, s in a.general.items() if s >= safety.SEEN))
        if bad:
            return "blocked-tag", ", ".join(bad)
    return None


def _age(a, medium: str, frames, cfg: Config, strict: bool) -> tuple[str, str] | None:
    if medium == "photo":
        ages = face_ages(frames, cfg)
        if ages:
            youngest = min(ages)
            return ("age-estimate", f"{youngest:.0f}") if youngest < cfg.photo_min_age else None
    # Drawings, or photos with no face clear enough to estimate.
    threshold = min(cfg.age_threshold, safety.STRICT_AGE_THRESHOLD) if strict else cfg.age_threshold
    if a.youth_prob >= threshold:
        return "age-check", f"{a.youth_prob:.2f}"
    return None
