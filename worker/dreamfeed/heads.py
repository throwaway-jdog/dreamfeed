"""Where the heads are in a drawing (deepghs anime_head_detection, MIT: a small YOLOv8 that
finds heads in anime and furry art), so a comic's speech bubbles stay off faces.
The model (45 MB) downloads into HF_HOME on first use and runs on the CPU.
"""
import numpy as np
from PIL import Image

REPO = "deepghs/anime_head_detection"
REVISION = "06604feee81983792a57c21081e539c0ae229833"   # pinned
MODEL = "head_detect_v1.6_s/model.onnx"
SIZE = 640
SURE = 0.381          # the model's own tuned threshold (threshold.json)
OVERLAP = 0.7         # boxes this alike are one head


class Heads:
    def __init__(self):
        import onnxruntime
        from huggingface_hub import hf_hub_download
        self.session = onnxruntime.InferenceSession(hf_hub_download(REPO, MODEL, revision=REVISION),
                                                    providers=["CPUExecutionProvider"])

    def find(self, img: Image.Image) -> list[tuple[int, int, int, int]]:
        """Head boxes (x0, y0, x1, y1) in img's pixels, surest first."""
        w, h = img.size
        r = SIZE / max(w, h)
        nw, nh = round(w * r), round(h * r)
        board = Image.new("RGB", (SIZE, SIZE), (114, 114, 114))
        board.paste(img.convert("RGB").resize((nw, nh), Image.BILINEAR), (0, 0))
        x = np.asarray(board, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
        out = self.session.run(None, {self.session.get_inputs()[0].name: x})[0][0].T   # (anchors, 5)
        out = out[out[:, 4] >= SURE]
        boxes = []
        for cx, cy, bw, bh, score in sorted(out.tolist(), key=lambda b: -b[4]):
            box = ((cx - bw / 2) / r, (cy - bh / 2) / r, (cx + bw / 2) / r, (cy + bh / 2) / r)
            if all(_iou(box, b) < OVERLAP for b in boxes):
                boxes.append(box)
        return [(max(0, round(a)), max(0, round(b)), min(w, round(c)), min(h, round(d))) for a, b, c, d in boxes]


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0
