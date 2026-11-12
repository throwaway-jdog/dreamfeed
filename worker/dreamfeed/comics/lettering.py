"""What stays still when a comic panel is animated, and who's in it.

Lettering: speech bubbles, the text in them and the text outside them (captions, credits), found
by ogkalu's comic text and bubble detector (RT-DETR v2, Apache 2.0, about 170 MB, downloaded
into HF_HOME on first use; it runs on the CPU in under a second a page). A bubble is the light
shape inside its box, followed from its text, so character art in the box's corners still
moves; one that isn't light (a coloured caption box) is its whole box. Drawn sound effects
aren't lettering to it: they move with the art.

Outlines: the characters in each panel (cutout.Cutout) less the lettering, as loops the reader
offers to start from when the person outlines what moves.
"""
import numpy as np
from PIL import Image

REPO = "ogkalu/comic-text-and-bubble-detector"
REVISION = "16e8a622f91fabc6b5b65c96d32d1183f8843546"   # pinned
SURE = 0.4             # detections less sure than this are left out
WORK = 1400            # pages are worked on at this long side
LIGHT = 45             # this close in grey to a bubble's brightest is its inside
BUBBLE_MIN = 0.35      # a light shape smaller than this share of its box isn't the bubble: the box is
EDGE = 0.004           # lettering grown by this share of the page's long side (the bubble's ink edge)
CHARACTER = 128        # cutout mask value that is character
CRUMB = 0.01           # outlines smaller than this share of their panel are left out
SMOOTH = 0.003         # outline points this close (share of the panel's diagonal) are merged


class Lettering:
    def __init__(self, device: str = "cpu"):
        import torch
        from transformers import RTDetrImageProcessor, RTDetrV2ForObjectDetection
        self.torch, self.device = torch, device
        self.proc = RTDetrImageProcessor.from_pretrained(REPO, revision=REVISION)
        self.model = RTDetrV2ForObjectDetection.from_pretrained(REPO, revision=REVISION).to(device).eval()

    def find(self, img: Image.Image) -> list[tuple[str, list[float]]]:
        """(kind, box in img's pixels) for each bubble, text_bubble and text_free."""
        with self.torch.no_grad():
            out = self.model(**self.proc(img.convert("RGB"), return_tensors="pt").to(self.device))
        res = self.proc.post_process_object_detection(out, target_sizes=[img.size[::-1]], threshold=SURE)[0]
        return [(self.model.config.id2label[int(k)], [float(v) for v in b])
                for k, b in zip(res["labels"].cpu(), res["boxes"].cpu())]

    def mask(self, img: Image.Image) -> Image.Image:
        """The lettering (255) at img's size."""
        import cv2
        r = min(1.0, WORK / max(img.size))
        small = img.convert("L").resize((round(img.width * r), round(img.height * r)), Image.BILINEAR)
        grey = np.asarray(small)
        h, w = grey.shape
        found = [(kind, [v * r for v in box]) for kind, box in self.find(img)]
        bubbles = [b for k, b in found if k == "bubble"]
        texts = [b for k, b in found if k != "bubble"]
        out = np.zeros((h, w), np.uint8)
        held = set()
        for box in bubbles:
            x0, y0, x1, y1 = _ints(box, w, h)
            if x1 - x0 < 4 or y1 - y0 < 4:
                continue
            inside = [i for i, t in enumerate(texts) if x0 <= (t[0] + t[2]) / 2 <= x1 and y0 <= (t[1] + t[3]) / 2 <= y1]
            held.update(inside)
            out[y0:y1, x0:x1] |= _bubble(grey[y0:y1, x0:x1], [_ints(texts[i], w, h) for i in inside], (x0, y0))
        for i, box in enumerate(texts):
            if i not in held:   # text with no bubble round it: its box
                x0, y0, x1, y1 = _ints(box, w, h)
                out[y0:y1, x0:x1] = 255
        grow = max(1, round(EDGE * max(w, h)))
        out = cv2.dilate(out, np.ones((2 * grow + 1, 2 * grow + 1), np.uint8))
        return Image.fromarray(out).resize(img.size, Image.BILINEAR)

    def close(self) -> None:
        del self.model
        if self.device != "cpu":
            self.torch.cuda.empty_cache()


def _ints(box, w, h) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    return max(0, int(x0)), max(0, int(y0)), min(w, int(np.ceil(x1))), min(h, int(np.ceil(y1)))


def _bubble(grey: np.ndarray, texts: list, at: tuple[int, int]) -> np.ndarray:
    """A bubble's shape in its box (255): the light area its text sits in, letters filled in."""
    import cv2
    h, w = grey.shape
    light = (grey >= int(np.percentile(grey, 95)) - LIGHT).astype(np.uint8)
    _, label = cv2.connectedComponents(light, connectivity=4)
    seeds = np.zeros((h, w), bool)
    for x0, y0, x1, y1 in texts or [(at[0] + w // 3, at[1] + h // 3, at[0] + 2 * w // 3, at[1] + 2 * h // 3)]:
        seeds[max(0, y0 - at[1]):max(0, y1 - at[1]), max(0, x0 - at[0]):max(0, x1 - at[0])] = True
    picked = set(np.unique(label[seeds & (light > 0)])) - {0}
    shape = np.isin(label, list(picked)).astype(np.uint8) * 255 if picked else np.zeros((h, w), np.uint8)
    contours, _ = cv2.findContours(shape, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    shape = cv2.drawContours(np.zeros((h, w), np.uint8), contours, -1, 255, cv2.FILLED)   # the letters filled in
    if shape.mean() < BUBBLE_MIN * 255:
        return np.full((h, w), 255, np.uint8)
    return shape


def outlines(img: Image.Image, panels: list[list[float]], still: Image.Image, cutout) -> list[list[list[float]]]:
    """Loops (points in page shares) round the characters in each panel, the lettering left out."""
    import cv2
    loops = []
    for box in panels or [[0.0, 0.0, 1.0, 1.0]]:
        x0, y0, x1, y1 = (round(v * s) for v, s in zip(box, (img.width, img.height) * 2))
        if x1 - x0 < 32 or y1 - y0 < 32:
            continue
        crop = img.crop((x0, y0, x1, y1))
        chars = np.asarray(cutout.mask(crop)) >= CHARACTER
        chars &= np.asarray(still.crop((x0, y0, x1, y1))) < 128
        r = min(1.0, 600 / max(crop.size))     # traced small: smoother and fewer points
        m = cv2.resize(chars.astype(np.uint8) * 255, (round(crop.width * r), round(crop.height * r)), cv2.INTER_AREA)
        m = cv2.morphologyEx((m >= 128).astype(np.uint8) * 255, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        diag = float(np.hypot(*m.shape))
        for c in contours:
            if cv2.contourArea(c) < CRUMB * m.size:
                continue
            c = cv2.approxPolyDP(c, SMOOTH * diag, True)[:, 0]
            if len(c) >= 3:
                loops.append([[round((x0 + px / r) / img.width, 4), round((y0 + py / r) / img.height, 4)] for px, py in c])
    return loops
