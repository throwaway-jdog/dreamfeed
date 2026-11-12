"""Smoother clips: a frame made between each two, so Wan's 16 fps plays at 32.

RIFE 4.25 (Practical-RIFE by hzwer, MIT): the model below is its IFNet_HDv3, cut down to
inference. Its weights (about 21 MB, mirrored on Hugging Face) download into HF_HOME on first
use. A frame between two follows the motion between them (optical flow), not a cross-fade.
"""
import subprocess
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

REPO = "daydreamlive/RIFE"
REVISION = "36f1cfcd3d81d39311e62b46dc766d35767f1585"   # pinned
WEIGHTS = "flownet.pkl"
BATCH = 8               # frame pairs at a time
SCALES = (8, 4, 2, 1)
TRAINING = ("teacher.", "caltime.")   # parts of the weights only training uses


def _conv(cin, cout, k=3, stride=1, pad=1):
    return nn.Sequential(nn.Conv2d(cin, cout, k, stride, pad, bias=True), nn.LeakyReLU(0.2, True))


class _Head(nn.Module):
    def __init__(self):
        super().__init__()
        self.cnn0 = nn.Conv2d(3, 16, 3, 2, 1)
        self.cnn1 = nn.Conv2d(16, 16, 3, 1, 1)
        self.cnn2 = nn.Conv2d(16, 16, 3, 1, 1)
        self.cnn3 = nn.ConvTranspose2d(16, 4, 4, 2, 1)
        self.relu = nn.LeakyReLU(0.2, True)

    def forward(self, x):
        x = self.relu(self.cnn0(x))
        x = self.relu(self.cnn1(x))
        x = self.relu(self.cnn2(x))
        return self.cnn3(x)


class _ResConv(nn.Module):
    def __init__(self, c):
        super().__init__()
        self.conv = nn.Conv2d(c, c, 3, 1, 1)
        self.beta = nn.Parameter(torch.ones((1, c, 1, 1)))
        self.relu = nn.LeakyReLU(0.2, True)

    def forward(self, x):
        return self.relu(self.conv(x) * self.beta + x)


class _Block(nn.Module):
    def __init__(self, cin, c):
        super().__init__()
        self.conv0 = nn.Sequential(_conv(cin, c // 2, 3, 2, 1), _conv(c // 2, c, 3, 2, 1))
        self.convblock = nn.Sequential(*[_ResConv(c) for _ in range(8)])
        self.lastconv = nn.Sequential(nn.ConvTranspose2d(c, 4 * 13, 4, 2, 1), nn.PixelShuffle(2))

    def forward(self, x, flow, scale):
        x = F.interpolate(x, scale_factor=1.0 / scale, mode="bilinear", align_corners=False)
        if flow is not None:
            flow = F.interpolate(flow, scale_factor=1.0 / scale, mode="bilinear", align_corners=False) / scale
            x = torch.cat((x, flow), 1)
        tmp = self.lastconv(self.convblock(self.conv0(x)))
        tmp = F.interpolate(tmp, scale_factor=scale, mode="bilinear", align_corners=False)
        return tmp[:, :4] * scale, tmp[:, 4:5], tmp[:, 5:]


def _warp(img, flow):
    n, _, h, w = flow.shape
    gx = torch.linspace(-1.0, 1.0, w, device=flow.device, dtype=flow.dtype).view(1, 1, 1, w).expand(n, -1, h, -1)
    gy = torch.linspace(-1.0, 1.0, h, device=flow.device, dtype=flow.dtype).view(1, 1, h, 1).expand(n, -1, -1, w)
    flow = torch.cat([flow[:, 0:1] / ((img.shape[3] - 1.0) / 2.0), flow[:, 1:2] / ((img.shape[2] - 1.0) / 2.0)], 1)
    grid = (torch.cat([gx, gy], 1) + flow).permute(0, 2, 3, 1)
    return F.grid_sample(img, grid.to(img.dtype), mode="bilinear", padding_mode="border", align_corners=True)


class _IFNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.block0 = _Block(7 + 8, 192)
        self.block1 = _Block(8 + 4 + 8 + 8, 128)
        self.block2 = _Block(8 + 4 + 8 + 8, 64)
        self.block3 = _Block(8 + 4 + 8 + 8, 32)
        self.encode = _Head()

    def forward(self, img0, img1):
        t = img0[:, :1] * 0 + 0.5
        f0, f1 = self.encode(img0), self.encode(img1)
        w0, w1, flow, mask, feat = img0, img1, None, None, None
        for i, block in enumerate((self.block0, self.block1, self.block2, self.block3)):
            if flow is None:
                flow, mask, feat = block(torch.cat((img0, img1, f0, f1, t), 1), None, SCALES[i])
            else:
                fd, mask, feat = block(torch.cat((w0, w1, _warp(f0, flow[:, :2]), _warp(f1, flow[:, 2:4]), t, mask, feat), 1),
                                       flow, SCALES[i])
                flow = flow + fd
            w0, w1 = _warp(img0, flow[:, :2]), _warp(img1, flow[:, 2:4])
        m = torch.sigmoid(mask)
        return w0 * m + w1 * (1 - m)


class Smoother:
    def __init__(self, device: str = "cuda"):
        from huggingface_hub import hf_hub_download
        state = torch.load(hf_hub_download(REPO, WEIGHTS, revision=REVISION), map_location="cpu", weights_only=True)
        self.net = _IFNet()
        state = {k.removeprefix("module."): v for k, v in state.items()}
        self.net.load_state_dict({k: v for k, v in state.items() if not k.startswith(TRAINING)})
        self.device, self.dtype = device, torch.half if device != "cpu" else torch.float32
        self.net.to(device, self.dtype).eval()

    @torch.no_grad()
    def double(self, frames: np.ndarray, loop: bool = False) -> np.ndarray:
        """frames (T, H, W, 3) uint8 with a frame made between each two: 2T - 1 of them, or 2T
        for a loop (one between the last and the first too)."""
        if len(frames) < 2:
            return frames
        h, w = frames.shape[1:3]
        ph, pw = -h % 64, -w % 64     # the smallest scale works on 1/64 of the size
        pairs = list(zip(range(len(frames) - 1), range(1, len(frames)))) + ([(len(frames) - 1, 0)] if loop else [])
        made = []
        for k in range(0, len(pairs), BATCH):
            part = pairs[k:k + BATCH]
            a = np.stack([frames[i] for i, _ in part])
            b = np.stack([frames[j] for _, j in part])
            x = [F.pad(torch.from_numpy(v).to(self.device).permute(0, 3, 1, 2).to(self.dtype) / 255, (0, pw, 0, ph),
                       mode="replicate") for v in (a, b)]
            mid = self.net(*x)[:, :, :h, :w]
            made.append((mid.float().clamp(0, 1) * 255).round().byte().permute(0, 2, 3, 1).cpu().numpy())
        made = np.concatenate(made)
        out = np.empty((len(frames) + len(made), h, w, 3), np.uint8)
        out[0::2], out[1::2] = frames, made
        return out

    def close(self) -> None:
        del self.net
        if self.device != "cpu":
            torch.cuda.empty_cache()


def smoothed(frames: np.ndarray, loop: bool = False, device: str = "cuda") -> np.ndarray | None:
    """Smoother.double, loading the model for it; None if that fails (the clip is kept as it is)."""
    import time
    try:
        start = time.time()
        s = Smoother(device)
        try:
            out = s.double(frames, loop)
        finally:
            s.close()
        print(f"smooth: {len(frames)} frames to {len(out)} in {time.time() - start:.1f}s", flush=True)
        return out
    except Exception as e:
        print(f"smooth: kept as drawn ({e})", flush=True)
        return None


def fps_of(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=60, check=True).stdout
    num, _, den = out.strip().partition("/")
    return float(num) / float(den or 1)


def smooth_file(path: Path, fps: float, device: str = "cuda") -> bool:
    """An mp4 at fps made twice as smooth in place (twice the frames at twice fps); False if it
    wasn't (one already smoother, like a scene, is left as it is)."""
    from .scene import _frames
    if fps_of(path) > fps + 0.5:
        return False
    frames = smoothed(_frames(path), device=device)
    if frames is None:
        return False
    h, w = frames.shape[1:3]
    tmp = path.with_name(path.stem + "-smooth.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps * 2),
                    "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-movflags", "+faststart", str(tmp)],
                   input=frames.tobytes(), check=True, timeout=600)
    tmp.replace(path)
    return True
