"""WD v3 tagger + CLIP. Importing this initializes nothing; Vision() loads to the GPU."""
import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import open_clip
import timm
import torch
import torch.nn.functional as F
from huggingface_hub import hf_hub_download
from PIL import Image
from timm.data import create_transform, resolve_data_config

from . import safety

TAGGER_REPO = "SmilingWolf/wd-eva02-large-tagger-v3"
CLIP_ARCH, CLIP_WEIGHTS = "ViT-L-14-quickgelu", "openai"
CAT_GENERAL, CAT_CHARACTER, CAT_RATING = 0, 4, 9


@dataclass
class Analysis:
    general: dict[str, float]      # every general tag with its score
    rating: str
    medium_probs: dict[str, float]
    youth_prob: float              # CLIP, worst frame
    embedding: np.ndarray          # float16, normalized


def _pad_square(img: Image.Image) -> Image.Image:
    w, h = img.size
    side = max(w, h)
    out = Image.new("RGB", (side, side), (255, 255, 255))
    out.paste(img, ((side - w) // 2, (side - h) // 2))
    return out


class Vision:
    def __init__(self, models_dir: Path):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"vision: loading models on {self.device}", flush=True)

        self.tagger = timm.create_model(f"hf-hub:{TAGGER_REPO}", pretrained=True)
        self.tagger = self.tagger.eval().to(self.device)
        self.tag_tf = create_transform(**resolve_data_config(self.tagger.pretrained_cfg, model=self.tagger))
        with open(hf_hub_download(TAGGER_REPO, "selected_tags.csv"), newline="") as f:
            rows = list(csv.DictReader(f))
        self.tag_names = [r["name"].replace("_", " ") for r in rows]
        cats = np.array([int(r["category"]) for r in rows])
        self.general_idx = np.where(cats == CAT_GENERAL)[0]
        self.rating_idx = np.where(cats == CAT_RATING)[0]

        self.clip, _, self.clip_tf = open_clip.create_model_and_transforms(
            CLIP_ARCH, pretrained=CLIP_WEIGHTS, cache_dir=str(models_dir / "clip"), device=self.device)
        self.clip.eval()
        tokenizer = open_clip.get_tokenizer(CLIP_ARCH)
        self.prompts = {}
        for name, groups in (("medium", safety.MEDIUM_PROMPTS), ("age", safety.AGE_PROMPTS)):
            labels = [label for label, ps in groups.items() for _ in ps]
            texts = [p for ps in groups.values() for p in ps]
            with torch.no_grad():
                t = self.clip.encode_text(tokenizer(texts).to(self.device)).float()
            self.prompts[name] = (labels, F.normalize(t, dim=-1))

    def close(self) -> None:
        """Free the GPU for what comes next (the caption model)."""
        del self.tagger, self.clip, self.prompts
        torch.cuda.empty_cache()

    @torch.no_grad()
    def _tag(self, img: Image.Image) -> np.ndarray:
        x = self.tag_tf(_pad_square(img)).unsqueeze(0)[:, [2, 1, 0]]   # model expects BGR
        return torch.sigmoid(self.tagger(x.to(self.device)))[0].float().cpu().numpy()

    @torch.no_grad()
    def _embed(self, img: Image.Image) -> torch.Tensor:
        x = self.clip_tf(img).unsqueeze(0).to(self.device)
        return F.normalize(self.clip.encode_image(x).float(), dim=-1)[0]

    def _zero_shot(self, emb: torch.Tensor, name: str) -> dict[str, float]:
        labels, text = self.prompts[name]
        probs = torch.softmax(100 * emb @ text.T, dim=-1).cpu().numpy()
        out: dict[str, float] = {}
        for label, p in zip(labels, probs):
            out[label] = out.get(label, 0.0) + float(p)
        return out

    def analyze(self, frames: list[Image.Image]) -> Analysis:
        scores = np.max([self._tag(f) for f in frames], axis=0)   # a tag in any frame counts
        embs = [self._embed(f) for f in frames]
        mediums = [self._zero_shot(e, "medium") for e in embs]
        return Analysis(
            general={self.tag_names[i]: float(scores[i]) for i in self.general_idx},
            rating=self.tag_names[self.rating_idx[np.argmax(scores[self.rating_idx])]],
            medium_probs={m: float(np.mean([d[m] for d in mediums])) for m in mediums[0]},
            youth_prob=max(self._zero_shot(e, "age")["youth"] for e in embs),
            embedding=F.normalize(torch.stack(embs).mean(0), dim=-1).cpu().numpy().astype(np.float16),
        )
