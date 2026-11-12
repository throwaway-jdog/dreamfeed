import os
import sys
from pathlib import Path


def need(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"dreamfeed: {name} is not set (see .env.example)")
    return value


def opt_float(name: str, default: float) -> float:
    value = os.environ.get(name, "").strip()
    try:
        return float(value) if value else default
    except ValueError:
        sys.exit(f"dreamfeed: {name}={value!r} is not a number")


class Config:
    def __init__(self):
        self.data_dir = Path(need("DATA_DIR"))
        self.models_dir = Path(need("MODELS_DIR"))
        self.db_path = self.data_dir / "feed.db"
        # The fictional posters (private: describes who you follow, so it lives in data/, not git).
        self.personas_path = self.data_dir / "personas.json"
        # Tagger confidence at which a youth tag drops an image (deliberately low).
        self.youth_tag_threshold = opt_float("YOUTH_TAG_THRESHOLD", 0.2)
        # Real-life images: MiVOLO age estimates from the agecheck service. Any clearly
        # visible face estimated under this age drops the image. Never below 18.
        self.agecheck_url = need("AGECHECK_URL").rstrip("/")
        self.photo_min_age = max(18.0, opt_float("PHOTO_MIN_AGE", 21))
        # Faces smaller than this (pixels, shorter side) are too small to judge.
        self.min_face_px = opt_float("MIN_FACE_PX", 48)
        # CLIP share for "child" over "adult" descriptions at which an image is dropped.
        # Used for drawings, and for photos where no face is clear enough to estimate.
        self.age_threshold = opt_float("AGE_THRESHOLD", 0.35)
        # Hugging Face id of the text model that writes a fresh caption for every post (see
        # captions.py). Empty: captions come from the personas' example captions.
        self.caption_model = os.environ.get("CAPTION_MODEL", "").strip()
        # A bigger text model for comics' stories (dialogue that answers the line before); empty:
        # the caption model writes them too. Pre-quantized (bitsandbytes 4-bit) models load as such.
        self.story_model = os.environ.get("STORY_MODEL", "").strip() or self.caption_model
        self.story_revision = os.environ.get("STORY_MODEL_REVISION", "").strip() or None
        # How often the worker checks the nightly window and dashboard requests.
        self.scan_seconds = opt_float("SCAN_SECONDS", 10)

    def generation(self) -> "GenConfig":
        return GenConfig()


def _window(value: str) -> tuple[int, int]:
    try:
        start, end = (int(h) * 60 + int(m) for h, m in (p.split(":") for p in value.split("-")))
    except ValueError:
        sys.exit(f"dreamfeed: GENERATE_WINDOW={value!r} must look like 01:00-07:00")
    return start, end


class GenConfig:
    """Settings only the nightly run needs."""
    def __init__(self):
        self.comfy_url = need("COMFYUI_URL")
        self.supervisor_url = need("COMFYUI_SUPERVISOR_URL")
        self.checkpoints = {m: os.environ.get(f"CHECKPOINT_{m.upper()}", "").strip()
                            for m in ("anime", "furry")}
        self.window = _window(need("GENERATE_WINDOW"))     # minutes after midnight
        self.images_per_night = int(opt_float("IMAGES_PER_NIGHT", 0)) or sys.exit(
            "dreamfeed: IMAGES_PER_NIGHT must be set")
        self.keep_top = int(opt_float("FEED_KEEP_TOP", 0)) or sys.exit(
            "dreamfeed: FEED_KEEP_TOP must be set")
        # Every enabled medium gets at least this share of the night, so it can come back.
        self.min_share = opt_float("MIN_MEDIUM_SHARE", 0.1)
        # Wan 2.2 clips made after each night's images (0 = off). About 5 minutes each.
        self.videos_per_night = int(opt_float("VIDEOS_PER_NIGHT", 0))
        # Wan 2.2 I2V motion LoRA for clips of sex acts (high- and low-noise files in
        # models/loras; motion.py has its trigger words). Empty: clips use Wan alone.
        high, low = (os.environ.get(f"VIDEO_ACT_LORA_{x}", "").strip() for x in ("HIGH", "LOW"))
        if bool(high) != bool(low):
            sys.exit("dreamfeed: set both VIDEO_ACT_LORA_HIGH and VIDEO_ACT_LORA_LOW, or neither")
        self.act_lora = (high, low, opt_float("VIDEO_ACT_LORA_STRENGTH", 0.8)) if high else None
        # Strength of a style's own video LoRA (videolora.py), for personas posting in that style.
        self.video_style_strength = opt_float("VIDEO_STYLE_LORA_STRENGTH", 0.7)
        # Feed images you haven't liked are deleted after this many days.
        self.feed_keep_days = opt_float("FEED_KEEP_DAYS", 14)
