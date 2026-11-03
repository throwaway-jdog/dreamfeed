"""Age estimates for the people in an image.

POST /estimate with image bytes (JPEG/PNG) ->
  {"people": [{"age": 27.4, "face_px": 112, "body_px": 640}, ...]}
face_px / body_px are the shorter side of the face / height of the body box (0 = not
found), so the caller can ignore estimates from tiny, unreliable crops.
"""
import io
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import torch
from huggingface_hub import hf_hub_download
from PIL import Image
from transformers import AutoConfig, AutoImageProcessor, AutoModelForImageClassification
from ultralytics import YOLO

MIVOLO_REPO, MIVOLO_REV = "iitolstykh/mivolo_v2", "53393526c220e34cdd7b722b36d22b6f9e5f4241"
DETECT_REPO, DETECT_REV = "iitolstykh/YOLO-Face-Person-Detector", "b3d071aedccd46a3b2d4b40609da6880a815f395"
PERSON, FACE = 0, 1
DETECT_CONF = 0.4


def env_int(name: str) -> int:
    value = os.environ.get(name, "").strip()
    if not value.isdigit():
        sys.exit(f"agecheck: {name} must be set to a whole number")
    return int(value)


torch.set_num_threads(env_int("AGECHECK_THREADS"))
print("agecheck: loading models", flush=True)
detector = YOLO(hf_hub_download(DETECT_REPO, "yolov8x_person_face.pt", revision=DETECT_REV))
AutoConfig.from_pretrained(MIVOLO_REPO, revision=MIVOLO_REV, trust_remote_code=True)
mivolo = AutoModelForImageClassification.from_pretrained(
    MIVOLO_REPO, revision=MIVOLO_REV, trust_remote_code=True, torch_dtype=torch.float32).eval()
processor = AutoImageProcessor.from_pretrained(MIVOLO_REPO, revision=MIVOLO_REV, trust_remote_code=True)


def _inside(face, body) -> bool:
    cx, cy = (face[0] + face[2]) / 2, (face[1] + face[3]) / 2
    return body[0] <= cx <= body[2] and body[1] <= cy <= body[3]


def pair(faces, bodies):
    """Match each face to the body containing it; unmatched faces and bodies stand alone."""
    pairs, used = [], set()
    for b in bodies:
        best = None
        for i, f in enumerate(faces):
            if i not in used and _inside(f, b) and (best is None or f[4] > faces[best][4]):
                best = i
        if best is not None:
            used.add(best)
        pairs.append((faces[best] if best is not None else None, b))
    pairs += [(f, None) for i, f in enumerate(faces) if i not in used]
    return pairs


@torch.no_grad()
def estimate(image: Image.Image) -> list[dict]:
    bgr = np.ascontiguousarray(np.asarray(image.convert("RGB"))[:, :, ::-1])
    boxes = detector(bgr, conf=DETECT_CONF, iou=0.7, verbose=False)[0].boxes
    faces, bodies = [], []
    for xyxy, cls, conf in zip(boxes.xyxy.tolist(), boxes.cls.tolist(), boxes.conf.tolist()):
        (faces if int(cls) == FACE else bodies).append([int(v) for v in xyxy] + [conf])
    pairs = pair(faces, bodies)
    if not pairs:
        return []

    def crop(box):
        return None if box is None else bgr[box[1]:box[3], box[0]:box[2]]

    face_in = processor(images=[crop(f) for f, _ in pairs])["pixel_values"]
    body_in = processor(images=[crop(b) for _, b in pairs])["pixel_values"]
    ages = mivolo(faces_input=face_in, body_input=body_in).age_output.reshape(-1).tolist()
    return [{
        "age": round(float(age), 1),
        "face_px": min(f[2] - f[0], f[3] - f[1]) if f else 0,
        "body_px": (b[3] - b[1]) if b else 0,
    } for age, (f, b) in zip(ages, pairs)]


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/estimate":
            return self._send(404, {"error": "not found"})
        try:
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            people = estimate(Image.open(io.BytesIO(body)))
        except Exception as e:
            return self._send(400, {"error": str(e)[:300]})
        self._send(200, {"people": people})

    def do_GET(self):
        self._send(200 if self.path == "/health" else 404, {"ok": self.path == "/health"})

    def _send(self, code, data):
        out = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


print("agecheck: ready on :8080", flush=True)
HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
