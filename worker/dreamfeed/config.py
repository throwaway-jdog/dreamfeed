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
        self.bookmarks_dir = self.data_dir / "bookmarks"
        self.db_path = self.data_dir / "feed.db"
        # Tagger confidence needed to keep a descriptive tag in the profile.
        self.tag_threshold = opt_float("TAG_THRESHOLD", 0.35)
        # Tagger confidence at which a youth tag drops the bookmark (deliberately low).
        self.youth_tag_threshold = opt_float("YOUTH_TAG_THRESHOLD", 0.2)
        # Real-life images: MiVOLO age estimates from the agecheck service. Any clearly
        # visible face estimated under this age drops the bookmark. Never below 18.
        self.agecheck_url = need("AGECHECK_URL").rstrip("/")
        self.photo_min_age = max(18.0, opt_float("PHOTO_MIN_AGE", 21))
        # Faces smaller than this (pixels, shorter side) are too small to judge.
        self.min_face_px = opt_float("MIN_FACE_PX", 48)
        # CLIP share for "child" over "adult" descriptions at which a bookmark is dropped.
        # Used for drawings, and for photos where no face is clear enough to estimate.
        self.age_threshold = opt_float("AGE_THRESHOLD", 0.35)
        # Furry-tag confidence that moves a drawing from anime to furry.
        self.furry_threshold = opt_float("FURRY_THRESHOLD", 0.5)
        self.scan_seconds = opt_float("SCAN_SECONDS", 60)
