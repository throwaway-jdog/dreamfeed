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

    def start(self, mode: str = "image") -> None:
        """Start ComfyUI (or keep it running). Call before each job; it resets the idle timer.
        mode "video" runs it with options that keep RAM down for Wan (see the supervisor)."""
        self._post(f"{self.supervisor}/start?mode={mode}", timeout=400)

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
                subdir: str, name: str, strict: bool = False,
                loras: list[tuple[str, str, float]] = ()) -> Path:
        """Animate a (generated, already checked) image into a ~5 second clip. loras: Wan video
        LoRAs as (high-noise file, low-noise file, strength), e.g. a sex act's motion LoRA and
        the persona's style video LoRA, applied in order."""
        positive, negative = safety.prompts(medium, prompt, VIDEO_NEGATIVE, strict)
        self.start("video")
        source = self.upload(image)
        if engine == "wan":
            workflow = _wan_workflow(source, positive, negative, seed, f"{subdir}/{name}", loras)
        else:
            workflow = _ltx_workflow(source, positive, negative, seed, f"{subdir}/{name}")
        return self._run(workflow, timeout=1800)

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
                subdir: str, name: str, extra_negative: str = "", strict: bool = False,
                lora: tuple[str, float] | None = None) -> Path:
        """lora: (file in models/loras, strength), applied to the model and text encoder."""
        p = presets.for_checkpoint(checkpoint)
        positive, negative = safety.prompts(medium, p.positive_prefix + prompt,
                                            p.negative + (", " + extra_negative if extra_negative else ""), strict)
        workflow = {
            "ckpt": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
            "clip": {"class_type": "CLIPSetLastLayer",
                     "inputs": {"clip": ["lora", 1] if lora else ["ckpt", 1], "stop_at_clip_layer": -p.clip_skip}},
            "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": positive}},
            "neg": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": negative}},
            "latent": {"class_type": "EmptyLatentImage",
                       "inputs": {"width": p.width, "height": p.height, "batch_size": 1}},
            "sample": {"class_type": "KSampler", "inputs": {
                "model": ["lora", 0] if lora else ["ckpt", 0], "positive": ["pos", 0], "negative": ["neg", 0],
                "latent_image": ["latent", 0], "seed": seed, "steps": p.steps, "cfg": p.cfg,
                "sampler_name": p.sampler, "scheduler": p.scheduler, "denoise": 1.0}},
            "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["sample", 0], "vae": ["ckpt", 2]}},
            "save": {"class_type": "SaveImage",
                     "inputs": {"images": ["decode", 0], "filename_prefix": f"{subdir}/{name}"}},
        }
        if lora:
            workflow["lora"] = {"class_type": "LoraLoader", "inputs": {
                "model": ["ckpt", 0], "clip": ["ckpt", 1], "lora_name": lora[0],
                "strength_model": lora[1], "strength_clip": lora[1]}}
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


VIDEO_NEGATIVE = ("blurry, low quality, worst quality, static, still image, frozen, slow motion, distorted, "
                  "deformed, bad anatomy, "
                  "extra limbs, extra fingers, flicker, watermark, text, subtitles")

# Wan 2.2 image-to-video, compressed (GGUF Q4) to fit 12 GB, sampled in three stages:
# 1. the high-noise expert on its own, at real CFG, for the first steps: this is where the
#    motion is decided, and the 4-step lightx2v LoRA flattens it (and pulls away from NSFW)
# 2. the high-noise expert with lightx2v, CFG 1
# 3. the low-noise expert with lightx2v, CFG 1, for the detail
WAN = {"high": "wan2.2-i2v-high-q4km.gguf", "low": "wan2.2-i2v-low-q4km.gguf",
       "lora_high": "wan2.2-i2v-lightx2v-4step-high.safetensors",
       "lora_low": "wan2.2-i2v-lightx2v-4step-low.safetensors",
       "text": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "vae": "wan_2.1_vae.safetensors",
       "width": 480, "height": 704, "frames": 81, "fps": 16, "shift": 5.0,
       "steps": 8, "motion_steps": 2, "high_steps": 4, "motion_cfg": 3.5}
LTX = {"ckpt": "ltxv-2b-0.9.8-distilled.safetensors", "text": "t5xxl_fp8_e4m3fn_scaled.safetensors",
       "width": 512, "height": 768, "frames": 121, "fps": 24, "steps": 8}


def _save_video(images: list, fps: float, prefix: str) -> dict:
    return {
        "video": {"class_type": "CreateVideo", "inputs": {"images": images, "fps": fps}},
        "save": {"class_type": "SaveVideo", "inputs": {"video": ["video", 0], "filename_prefix": prefix,
                                                       "format": "mp4", "codec": "h264"}},
    }


def _wan_workflow(source: str, positive: str, negative: str, seed: int, prefix: str,
                  loras: list[tuple[str, str, float]] = ()) -> dict:
    w = WAN
    nodes = {
        "text": {"class_type": "CLIPLoader", "inputs": {"clip_name": w["text"], "type": "wan"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": w["vae"]}},
        "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["text", 0], "text": positive}},
        "neg": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["text", 0], "text": negative}},
        "image": {"class_type": "LoadImage", "inputs": {"image": source}},
        "i2v": {"class_type": "WanImageToVideo", "inputs": {
            "positive": ["pos", 0], "negative": ["neg", 0], "vae": ["vae", 0], "start_image": ["image", 0],
            "width": w["width"], "height": w["height"], "length": w["frames"], "batch_size": 1}},
    }
    for i, tag in enumerate(("high", "low")):
        nodes[f"unet_{tag}"] = {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": w[tag]}}
        base = [f"unet_{tag}", 0]
        for n, lora in enumerate(loras):
            nodes[f"lora{n}_{tag}"] = {"class_type": "LoraLoaderModelOnly", "inputs": {
                "model": base, "lora_name": lora[i], "strength_model": lora[2]}}
            base = [f"lora{n}_{tag}", 0]
        nodes[f"raw_{tag}"] = {"class_type": "ModelSamplingSD3", "inputs": {"model": base, "shift": w["shift"]}}
        nodes[f"fast_lora_{tag}"] = {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": base, "lora_name": w[f"lora_{tag}"], "strength_model": 1.0}}
        nodes[f"fast_{tag}"] = {"class_type": "ModelSamplingSD3", "inputs": {
            "model": [f"fast_lora_{tag}", 0], "shift": w["shift"]}}

    def stage(model: list, latent: list, start: int, end: int, cfg: float, first: bool, last: bool) -> dict:
        return {"class_type": "KSamplerAdvanced", "inputs": {
            "model": model, "positive": ["i2v", 0], "negative": ["i2v", 1], "latent_image": latent,
            "noise_seed": seed, "steps": w["steps"], "cfg": cfg, "sampler_name": "euler", "scheduler": "simple",
            "add_noise": "enable" if first else "disable", "start_at_step": start, "end_at_step": end,
            "return_with_leftover_noise": "disable" if last else "enable"}}

    nodes["motion"] = stage(["raw_high", 0], ["i2v", 2], 0, w["motion_steps"], w["motion_cfg"], True, False)
    nodes["high"] = stage(["fast_high", 0], ["motion", 0], w["motion_steps"], w["high_steps"], 1.0, False, False)
    nodes["low"] = stage(["fast_low", 0], ["high", 0], w["high_steps"], 10000, 1.0, False, True)
    nodes["decode"] = {"class_type": "VAEDecode", "inputs": {"samples": ["low", 0], "vae": ["vae", 0]}}
    return nodes | _save_video(["decode", 0], w["fps"], prefix)


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
