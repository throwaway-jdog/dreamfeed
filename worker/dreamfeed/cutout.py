"""Cut the characters out of a picture (BiRefNet, MIT licence), to put them in another room.

Scenes draw the room once and paste each shot's characters onto it, so the room is the same
picture in every shot. The model (about 900 MB) downloads into HF_HOME on first use.
"""
import numpy as np
import torch
from PIL import Image, ImageFilter

MODEL = "ZhengPeng7/BiRefNet"
REVISION = "e2bf8e4460fc8fa32bba5ea4d94b3233d367b0e4"   # pinned: the model ships its own code
SIZE = 1024
MEAN, STD = np.array([0.485, 0.456, 0.406]), np.array([0.229, 0.224, 0.225])


class Cutout:
    def __init__(self, device: str = "cuda"):
        from transformers import AutoModelForImageSegmentation
        self.device, self.dtype = device, torch.half if device != "cpu" else torch.float32
        self.model = AutoModelForImageSegmentation.from_pretrained(
            MODEL, revision=REVISION, trust_remote_code=True).to(device, self.dtype).eval()

    @torch.no_grad()
    def mask(self, img: Image.Image) -> Image.Image:
        """The characters as a greyscale mask (255 = character), the picture's size."""
        x = np.asarray(img.convert("RGB").resize((SIZE, SIZE), Image.BILINEAR), np.float32) / 255
        x = torch.from_numpy(((x - MEAN) / STD).transpose(2, 0, 1)).unsqueeze(0).to(self.device, self.dtype)
        pred = self.model(x)[-1].sigmoid()[0, 0].float().cpu().numpy()
        return Image.fromarray((pred * 255).astype(np.uint8)).resize(img.size, Image.BILINEAR)

    def close(self) -> None:
        del self.model
        if self.device != "cpu":
            torch.cuda.empty_cache()


def paste(room: Image.Image, shot: Image.Image, mask: Image.Image, feather: int = 2) -> Image.Image:
    """The shot's characters over the room."""
    m = mask.filter(ImageFilter.GaussianBlur(feather))
    return Image.composite(shot.convert("RGB"), room.convert("RGB").resize(shot.size), m)


def keep_room(room: Image.Image, blended: Image.Image, mask: Image.Image, grow: int = 25) -> Image.Image:
    """After the blending pass: its pixels near the characters (edges, contact shadows), the
    room's exact pixels everywhere else, so the room doesn't drift between shots."""
    near = mask.point(lambda v: 255 if v > 24 else 0).filter(ImageFilter.MaxFilter(2 * (grow // 2) + 1))
    near = near.filter(ImageFilter.GaussianBlur(grow / 3))
    return Image.composite(blended.convert("RGB"), room.convert("RGB").resize(blended.size), near)
