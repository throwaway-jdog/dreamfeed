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

    def img2vid(self, image: Path, medium: str, prompt: str, seed: int,
                subdir: str, name: str, strict: bool = False,
                loras: list[tuple[str, str, float]] = (), end: Path | None = None,
                wan: dict | None = None) -> Path:
        """Animate a (generated, already checked) image into a ~5 second clip. loras: Wan video
        LoRAs as (high-noise file, low-noise file, strength), e.g. a sex act's motion LoRA and
        the persona's style video LoRA, applied in order. Wan only: end makes the clip finish on
        that image (the same image as the start makes a seamless loop). wan: settings that
        replace WAN's for this clip (e.g. width, height, motion_steps)."""
        positive, negative = safety.prompts(medium, prompt, VIDEO_NEGATIVE, strict)
        self.start("video")
        workflow = _wan_workflow(self.upload(image), positive, negative, seed, f"{subdir}/{name}", loras,
                                 end=self.upload(end) if end else None, settings=wan)
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
                lora=None, init: Path | None = None, denoise: float = 1.0, regions=None,
                reference: tuple[Path, float, str] | None = None,
                control: tuple[Path, float] | None = None, size: tuple[int, int] | None = None) -> Path:
        """lora: (file in models/loras, strength), or a list of them, applied in turn to the model
        and text encoder. regions: [(tags, x from, x to)] or [(tags, x from, x to, lora)], each
        added for its own vertical strip (shares of the width) on top of prompt for the whole
        picture: two characters each described again in their own part don't trade looks. A
        region's lora (file, strength) is used only for that part (a ComfyUI hook), so one
        character's LoRA doesn't turn the other into them.
        init: start from this picture instead of noise (img2img), keeping 1 - denoise of it.
        reference: (picture, weight, IP-Adapter weight type): the image model is also shown this
        picture (IP_ADAPTER), e.g. the post a scene is made from, so every shot keeps its
        characters' colours and look. control: (line-art picture, strength): ControlNet
        (CONTROLNET, line-art mode) keeps the drawing to those lines, white on black. size:
        (width, height) instead of the checkpoint's own, multiples of 64."""
        p = presets.for_checkpoint(checkpoint)
        loras = [lora] if isinstance(lora, tuple) else list(lora or [])
        last = f"lora{len(loras) - 1}" if loras else "ckpt"
        positive, negative = safety.prompts(medium, p.positive_prefix + prompt,
                                            p.negative + (", " + extra_negative if extra_negative else ""), strict)
        workflow = {
            "ckpt": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
            "clip": {"class_type": "CLIPSetLastLayer",
                     "inputs": {"clip": [last, 1], "stop_at_clip_layer": -p.clip_skip}},
            "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": positive}},
            "neg": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": negative}},
            "latent": {"class_type": "EmptyLatentImage",
                       "inputs": {"width": p.width, "height": p.height, "batch_size": 1}},
            "sample": {"class_type": "KSampler", "inputs": {
                "model": [last, 0], "positive": ["pos", 0], "negative": ["neg", 0],
                "latent_image": ["latent", 0], "seed": seed, "steps": p.steps, "cfg": p.cfg,
                "sampler_name": p.sampler, "scheduler": p.scheduler, "denoise": denoise if init else 1.0}},
            "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["sample", 0], "vae": ["ckpt", 2]}},
            "save": {"class_type": "SaveImage",
                     "inputs": {"images": ["decode", 0], "filename_prefix": f"{subdir}/{name}"}},
        }
        for n, (file, strength) in enumerate(loras):
            prev = f"lora{n - 1}" if n else "ckpt"
            workflow[f"lora{n}"] = {"class_type": "LoraLoader", "inputs": {
                "model": [prev, 0], "clip": [prev, 1], "lora_name": file,
                "strength_model": strength, "strength_clip": strength}}
        # A LoRA tied to one region keeps another copy of the model in memory, which image mode
        # can't hold: such a picture runs in the lean "regions" mode, on a fresh ComfyUI each time.
        hooked = any(len(r) > 3 and r[3] for r in regions or [])
        self.start("regions" if hooked else "image")
        if reference:
            pic, weight, kind = reference
            model = workflow["sample"]["inputs"]["model"]
            workflow |= {
                "ref_image": {"class_type": "LoadImage", "inputs": {"image": self.upload(pic)}},
                "ref_model": {"class_type": "IPAdapterModelLoader", "inputs": {"ipadapter_file": IP_ADAPTER["model"]}},
                "ref_vision": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": IP_ADAPTER["vision"]}},
                "ref": {"class_type": "IPAdapterAdvanced", "inputs": {
                    "model": model, "ipadapter": ["ref_model", 0], "image": ["ref_image", 0],
                    "clip_vision": ["ref_vision", 0], "weight": weight, "weight_type": kind,
                    "combine_embeds": "concat", "start_at": 0.0, "end_at": 1.0, "embeds_scaling": "V only"}},
            }
            workflow["sample"]["inputs"]["model"] = ["ref", 0]
        if size:
            workflow["latent"]["inputs"]["width"], workflow["latent"]["inputs"]["height"] = size
        for n, (tags, x0, x1, *own) in enumerate(regions or []):
            if safety.blocked(tags):
                raise ValueError(f"blocked tags in a region: {', '.join(safety.blocked(tags))}")
            clip = ["clip", 0]
            if own and own[0]:
                workflow[f"rhook{n}"] = {"class_type": "CreateHookLora", "inputs": {
                    "lora_name": own[0][0], "strength_model": own[0][1], "strength_clip": own[0][1]}}
                workflow[f"rclip{n}"] = {"class_type": "SetClipHooks", "inputs": {
                    "clip": ["clip", 0], "apply_to_conds": True, "schedule_clip": False, "hooks": [f"rhook{n}", 0]}}
                clip = [f"rclip{n}", 0]
            workflow[f"rpos{n}"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": clip, "text": tags}}
            workflow[f"rarea{n}"] = {"class_type": "ConditioningSetAreaPercentage", "inputs": {
                "conditioning": [f"rpos{n}", 0], "width": round(x1 - x0, 3), "height": 1.0,
                "x": round(x0, 3), "y": 0.0, "strength": 1.0}}
            workflow[f"rmix{n}"] = {"class_type": "ConditioningCombine", "inputs": {
                "conditioning_1": [f"rmix{n - 1}" if n else "pos", 0], "conditioning_2": [f"rarea{n}", 0]}}
            workflow["sample"]["inputs"]["positive"] = [f"rmix{n}", 0]
        if control:
            lines, strength = control
            sample = workflow["sample"]["inputs"]
            workflow |= {
                "cn_model": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": CONTROLNET["file"]}},
                "cn_type": {"class_type": "SetUnionControlNetType", "inputs": {
                    "control_net": ["cn_model", 0], "type": CONTROLNET["type"]}},
                "cn_image": {"class_type": "LoadImage", "inputs": {"image": self.upload(lines)}},
                "cn": {"class_type": "ControlNetApplyAdvanced", "inputs": {
                    "positive": sample["positive"], "negative": sample["negative"], "control_net": ["cn_type", 0],
                    "image": ["cn_image", 0], "strength": strength, "start_percent": 0.0, "end_percent": 1.0,
                    "vae": ["ckpt", 2]}},
            }
            sample["positive"], sample["negative"] = ["cn", 0], ["cn", 1]
        if init:
            workflow["init"] = {"class_type": "LoadImage", "inputs": {"image": self.upload(init)}}
            workflow["latent"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["init", 0], "vae": ["ckpt", 2]}}
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
                    if hooked:
                        self.stop()
                    return self.output_dir / img["subfolder"] / img["filename"]
            time.sleep(1)
        raise TimeoutError(f"ComfyUI prompt {prompt_id} did not finish in 600s")


# xinsir's ControlNet Union for SDXL (ProMax, Apache 2.0), in its line-art mode.
CONTROLNET = {"file": "controlnet-union-sdxl-promax.safetensors", "type": "canny/lineart/anime_lineart/mlsd"}

IP_ADAPTER = {"model": "ip-adapter-plus_sdxl_vit-h.safetensors",
              "vision": "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"}

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
def _save_video(images: list, fps: float, prefix: str) -> dict:
    return {
        "video": {"class_type": "CreateVideo", "inputs": {"images": images, "fps": fps}},
        "save": {"class_type": "SaveVideo", "inputs": {"video": ["video", 0], "filename_prefix": prefix,
                                                       "format": "mp4", "codec": "h264"}},
    }


def _wan_workflow(source: str, positive: str, negative: str, seed: int, prefix: str,
                  loras: list[tuple[str, str, float]] = (), end: str | None = None,
                  settings: dict | None = None) -> dict:
    """source: the uploaded first frame; end: an uploaded last frame (first-last-frame mode)."""
    w = WAN | (settings or {})
    nodes = {
        "text": {"class_type": "CLIPLoader", "inputs": {"clip_name": w["text"], "type": "wan"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": w["vae"]}},
        "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["text", 0], "text": positive}},
        "neg": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["text", 0], "text": negative}},
    }
    nodes["image"] = {"class_type": "LoadImage", "inputs": {"image": source}}
    common = {"positive": ["pos", 0], "negative": ["neg", 0], "vae": ["vae", 0], "start_image": ["image", 0],
              "width": w["width"], "height": w["height"], "length": w["frames"], "batch_size": 1}
    if end:
        nodes["end"] = {"class_type": "LoadImage", "inputs": {"image": end}}
        nodes["i2v"] = {"class_type": "WanFirstLastFrameToVideo", "inputs": common | {"end_image": ["end", 0]}}
    else:
        nodes["i2v"] = {"class_type": "WanImageToVideo", "inputs": common}
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


