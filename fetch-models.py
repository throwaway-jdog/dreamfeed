#!/usr/bin/env python3
"""Download the models listed in models.json that are missing (or don't match their hash),
for a restore: the backup leaves out models/ except trained LoRAs, which can't be downloaded.

    python3 fetch-models.py [--check]

Needs CIVITAI_API_KEY (from the environment, or this folder's .env). --check only lists what
is missing. Models go into MODELS_DIR (same sources), default ./models.
"""
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT = {"User-Agent": "dreamfeed-fetch/1.0"}


def env(name: str) -> str:
    if os.environ.get(name):
        return os.environ[name]
    dotenv = HERE / ".env"
    if dotenv.is_file():
        for line in dotenv.read_text().splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    return ""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    check = "--check" in sys.argv
    models = Path(env("MODELS_DIR") or HERE / "models")
    if not models.is_absolute():
        models = HERE / models
    manifest = json.loads((HERE / "models.json").read_text())
    # (path under models/, how to download it, its hash): Civitai LoRAs, then plain URLs (Hugging Face).
    wanted = {f"loras/{n}": (f"https://civitai.com/api/download/models/{m['civitai_version']}?type=Model&format=SafeTensor",
                             m["sha256"], m["what"]) for n, m in manifest["loras"].items()}
    wanted |= {rel: (m["url"], m["sha256"], rel) for rel, m in manifest.get("files", {}).items()}
    key = env("CIVITAI_API_KEY")
    missing = [(rel, m) for rel, m in wanted.items()
               if not (models / rel).is_file() or sha256(models / rel) != m[1]]
    print(f"{len(wanted) - len(missing)} of {len(wanted)} present")
    if check or not missing:
        for rel, m in missing:
            print(f"missing: {rel}  ({m[2]})")
        return
    if not key and any("civitai.com" in m[0] for _, m in missing):
        sys.exit("set CIVITAI_API_KEY (in .env) to download from Civitai")
    for rel, (url, digest, _) in missing:
        dest = models / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(".part")
        auth = {"Authorization": f"Bearer {key}"} if "civitai.com" in url else {}
        req = urllib.request.Request(url, headers=AGENT | auth)
        print(f"downloading {rel} ...", flush=True)
        with urllib.request.urlopen(req) as resp, part.open("wb") as f:
            while block := resp.read(1 << 20):
                f.write(block)
        if sha256(part) != digest:
            part.unlink()
            sys.exit(f"{rel}: the download doesn't match its hash; the source may have replaced the file")
        part.replace(dest)
    print("done")


if __name__ == "__main__":
    main()
