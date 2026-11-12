"""Sampler settings and quality tags per model family. A checkpoint's family is found by
matching these keys against its file name (first match wins)."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    sampler: str
    scheduler: str
    steps: int
    cfg: float
    clip_skip: int          # 1 = last layer; 2 for anime/furry SDXL families
    positive_prefix: str    # quality tags the family was trained with
    negative: str
    width: int = 832
    height: int = 1216


_PHOTO_NEG = ("worst quality, low quality, cartoon, anime, drawing, painting, 3d render, "
              "deformed, bad anatomy, extra fingers, watermark, text")
_BOORU_NEG = "worst quality, low quality, lowres, bad anatomy, bad hands, signature, username, logo, watermark"

PRESETS: dict[str, Preset] = {
    "realvis": Preset("dpmpp_2m_sde", "karras", 30, 5.0, 1, "", _PHOTO_NEG),
    "juggernaut": Preset("dpmpp_2m_sde", "karras", 30, 4.5, 1, "", _PHOTO_NEG),
    "lustify": Preset("dpmpp_2m_sde", "karras", 30, 4.0, 1, "", _PHOTO_NEG),
    "wai": Preset("euler_ancestral", "normal", 28, 6.0, 2,
                  "masterpiece, best quality, amazing quality, ", _BOORU_NEG),
    "noobai": Preset("euler_ancestral", "normal", 28, 5.0, 2,
                     "masterpiece, best quality, newest, absurdres, highres, ", _BOORU_NEG + ", old, early"),
    "furryvision": Preset("euler_ancestral", "normal", 28, 5.0, 2,
                          "masterpiece, best quality, newest, absurdres, highres, ", _BOORU_NEG + ", old, early"),
    "nova-furry": Preset("euler_ancestral", "normal", 30, 5.0, 2,
                         "masterpiece, best quality, amazing quality, ", _BOORU_NEG),
}


def for_checkpoint(filename: str) -> Preset:
    name = filename.lower()
    for key, preset in PRESETS.items():
        if key in name:
            return preset
    raise KeyError(f"no preset matches checkpoint {filename!r}; add one in presets.py")
