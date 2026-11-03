"""The adults-only checks every generated post, clip and LoRA training image goes through."""
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


def drop_reason(a, medium: str, frames, cfg: Config, strict: bool = False) -> tuple[str, str] | None:
    """strict: use the lower STRICT_AGE_THRESHOLD (characters that models tend to draw young)."""
    hits = safety.youth_tag_hits(a.general, cfg.youth_tag_threshold)
    if hits:
        return "youth-tag", ", ".join(f"{h} {a.general[h]:.2f}" for h in hits)
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
