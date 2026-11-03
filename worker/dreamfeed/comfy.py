"""Client for the comfyui service: start it on demand, run text-to-image and image-to-video,
stop it."""
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

    def upload(self, image: Path) -> str:
        """Put an image in ComfyUI's input folder; returns the name LoadImage uses."""
        boundary = uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{image.name}\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n").encode() + image.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(f"{self.api}/upload/image", data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)["name"]

    def img2vid(self, engine: str, image: Path, medium: str, prompt: str, seed: int,
                subdir: str, name: str) -> Path:
        """Animate a (generated, already checked) image into a ~5 second clip."""
        positive, negative = safety.prompts(medium, prompt, VIDEO_NEGATIVE)
        self.start()
        source = self.upload(image)
        build = {"wan": _wan_workflow, "ltx": _ltx_workflow}[engine]
        return self._run(build(source, positive, negative, seed, f"{subdir}/{name}"), timeout=1800)

    def _run(self, workflow: dict, timeout: float = 600) -> Path:
        prompt_id = self._post(f"{self.api}/prompt",
                               {"prompt": workflow, "client_id": uuid.uuid4().hex})["prompt_id"]
        deadline = time.time() + timeout
        while time.time() < deadline:
            with urllib.request.urlopen(f"{self.api}/history/{prompt_id}", timeout=30) as resp:
                entry = json.load(resp).get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise RuntimeError(f"ComfyUI error: {json.dumps(status.get('messages'))[-800:]}")
                files = entry.get("outputs", {}).get("save", {}).get("images", [])
                if files:
                    return self.output_dir / files[0]["subfolder"] / files[0]["filename"]
            time.sleep(1)
        raise TimeoutError(f"ComfyUI prompt {prompt_id} did not finish in {timeout:.0f}s")

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


VIDEO_NEGATIVE = ("blurry, low quality, worst quality, static, still image, distorted, deformed, bad anatomy, "
                  "extra limbs, extra fingers, flicker, watermark, text, subtitles")

# Wan 2.2 image-to-video, compressed (GGUF Q4) to fit 12 GB, with the 4-step lightx2v LoRAs:
# the high-noise half does steps 0-2, the low-noise half steps 2-4.
WAN = {"high": "wan2.2-i2v-high-q4km.gguf", "low": "wan2.2-i2v-low-q4km.gguf",
       "lora_high": "wan2.2-i2v-lightx2v-4step-high.safetensors",
       "lora_low": "wan2.2-i2v-lightx2v-4step-low.safetensors",
       "text": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "vae": "wan_2.1_vae.safetensors",
       "width": 480, "height": 704, "frames": 81, "fps": 16, "steps": 4, "shift": 5.0}
LTX = {"ckpt": "ltxv-2b-0.9.8-distilled.safetensors", "text": "t5xxl_fp8_e4m3fn_scaled.safetensors",
       "width": 512, "height": 768, "frames": 121, "fps": 24, "steps": 8}


def _save_video(images: list, fps: float, prefix: str) -> dict:
    return {
        "video": {"class_type": "CreateVideo", "inputs": {"images": images, "fps": fps}},
        "save": {"class_type": "SaveVideo", "inputs": {"video": ["video", 0], "filename_prefix": prefix,
                                                       "format": "mp4", "codec": "h264"}},
    }


def _wan_workflow(source: str, positive: str, negative: str, seed: int, prefix: str) -> dict:
    w = WAN
    half = w["steps"] // 2

    def expert(tag: str) -> dict:
        return {
            f"unet_{tag}": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": w[tag]}},
            f"lora_{tag}": {"class_type": "LoraLoaderModelOnly", "inputs": {
                "model": [f"unet_{tag}", 0], "lora_name": w[f"lora_{tag}"], "strength_model": 1.0}},
            f"model_{tag}": {"class_type": "ModelSamplingSD3", "inputs": {"model": [f"lora_{tag}", 0],
                                                                         "shift": w["shift"]}},
        }

    sampler = {"cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "steps": w["steps"],
               "noise_seed": seed, "positive": ["i2v", 0], "negative": ["i2v", 1]}
    return {
        **expert("high"), **expert("low"),
        "text": {"class_type": "CLIPLoader", "inputs": {"clip_name": w["text"], "type": "wan"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": w["vae"]}},
        "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["text", 0], "text": positive}},
        "neg": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["text", 0], "text": negative}},
        "image": {"class_type": "LoadImage", "inputs": {"image": source}},
        "i2v": {"class_type": "WanImageToVideo", "inputs": {
            "positive": ["pos", 0], "negative": ["neg", 0], "vae": ["vae", 0], "start_image": ["image", 0],
            "width": w["width"], "height": w["height"], "length": w["frames"], "batch_size": 1}},
        "first": {"class_type": "KSamplerAdvanced", "inputs": {
            **sampler, "model": ["model_high", 0], "add_noise": "enable", "latent_image": ["i2v", 2],
            "start_at_step": 0, "end_at_step": half, "return_with_leftover_noise": "enable"}},
        "second": {"class_type": "KSamplerAdvanced", "inputs": {
            **sampler, "model": ["model_low", 0], "add_noise": "disable", "latent_image": ["first", 0],
            "start_at_step": half, "end_at_step": 10000, "return_with_leftover_noise": "disable"}},
        "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["second", 0], "vae": ["vae", 0]}},
        **_save_video(["decode", 0], w["fps"], prefix),
    }


def _ltx_workflow(source: str, positive: str, negative: str, seed: int, prefix: str) -> dict:
    l = LTX
    return {
        "ckpt": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": l["ckpt"]}},
        "text": {"class_type": "CLIPLoader", "inputs": {"clip_name": l["text"], "type": "ltxv"}},
        "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["text", 0], "text": positive}},
        "neg": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["text", 0], "text": negative}},
        "image": {"class_type": "LoadImage", "inputs": {"image": source}},
        "prep": {"class_type": "LTXVPreprocess", "inputs": {"image": ["image", 0], "img_compression": 35}},
        "i2v": {"class_type": "LTXVImgToVideo", "inputs": {
            "positive": ["pos", 0], "negative": ["neg", 0], "vae": ["ckpt", 2], "image": ["prep", 0],
            "width": l["width"], "height": l["height"], "length": l["frames"], "batch_size": 1, "strength": 1.0}},
        "cond": {"class_type": "LTXVConditioning", "inputs": {
            "positive": ["i2v", 0], "negative": ["i2v", 1], "frame_rate": float(l["fps"])}},
        "sampler": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "sigmas": {"class_type": "LTXVScheduler", "inputs": {
            "steps": l["steps"], "max_shift": 2.05, "base_shift": 0.95, "stretch": True, "terminal": 0.1,
            "latent": ["i2v", 2]}},
        "sample": {"class_type": "SamplerCustom", "inputs": {
            "model": ["ckpt", 0], "add_noise": True, "noise_seed": seed, "cfg": 1.0,
            "positive": ["cond", 0], "negative": ["cond", 1], "sampler": ["sampler", 0],
            "sigmas": ["sigmas", 0], "latent_image": ["i2v", 2]}},
        "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["sample", 0], "vae": ["ckpt", 2]}},
        **_save_video(["decode", 0], l["fps"], prefix),
    }
