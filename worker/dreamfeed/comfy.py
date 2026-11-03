"""Client for the comfyui service: start it on demand, run text-to-image, stop it."""
import json
import time
import urllib.request
import uuid
from pathlib import Path

from . import presets, safety


class Comfy:
    def __init__(self, api_url: str, supervisor_url: str, output_dir: Path):
        self.api = api_url.rstrip("/")
        self.supervisor = supervisor_url.rstrip("/")
        self.output_dir = output_dir

    def _post(self, url: str, data: dict | None = None, timeout: float = 30) -> dict:
        body = json.dumps(data).encode() if data is not None else b""
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)

    def start(self) -> None:
        """Start ComfyUI (or keep it running). Call before each job; it resets the idle timer."""
        self._post(f"{self.supervisor}/start", timeout=330)

    def stop(self) -> None:
        self._post(f"{self.supervisor}/stop", timeout=60)

    def txt2img(self, checkpoint: str, medium: str, prompt: str, seed: int,
                subdir: str, name: str, extra_negative: str = "") -> Path:
        p = presets.for_checkpoint(checkpoint)
        positive, negative = safety.prompts(medium, p.positive_prefix + prompt,
                                            p.negative + (", " + extra_negative if extra_negative else ""))
        workflow = {
            "ckpt": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
            "clip": {"class_type": "CLIPSetLastLayer",
                     "inputs": {"clip": ["ckpt", 1], "stop_at_clip_layer": -p.clip_skip}},
            "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": positive}},
            "neg": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": negative}},
            "latent": {"class_type": "EmptyLatentImage",
                       "inputs": {"width": p.width, "height": p.height, "batch_size": 1}},
            "sample": {"class_type": "KSampler", "inputs": {
                "model": ["ckpt", 0], "positive": ["pos", 0], "negative": ["neg", 0],
                "latent_image": ["latent", 0], "seed": seed, "steps": p.steps, "cfg": p.cfg,
                "sampler_name": p.sampler, "scheduler": p.scheduler, "denoise": 1.0}},
            "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["sample", 0], "vae": ["ckpt", 2]}},
            "save": {"class_type": "SaveImage",
                     "inputs": {"images": ["decode", 0], "filename_prefix": f"{subdir}/{name}"}},
        }
        self.start()
        prompt_id = self._post(f"{self.api}/prompt",
                               {"prompt": workflow, "client_id": uuid.uuid4().hex})["prompt_id"]
        deadline = time.time() + 600
        while time.time() < deadline:
            with urllib.request.urlopen(f"{self.api}/history/{prompt_id}", timeout=30) as resp:
                entry = json.load(resp).get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise RuntimeError(f"ComfyUI error: {json.dumps(status.get('messages'))[:500]}")
                images = entry.get("outputs", {}).get("save", {}).get("images", [])
                if images:
                    img = images[0]
                    return self.output_dir / img["subfolder"] / img["filename"]
            time.sleep(1)
        raise TimeoutError(f"ComfyUI prompt {prompt_id} did not finish in 600s")
