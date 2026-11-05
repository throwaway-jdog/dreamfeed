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
    wanted = json.loads((HERE / "models.json").read_text())["loras"]
    key = env("CIVITAI_API_KEY")
    missing = [(name, m) for name, m in wanted.items()
               if not (models / "loras" / name).is_file() or sha256(models / "loras" / name) != m["sha256"]]
    print(f"{len(wanted) - len(missing)} of {len(wanted)} present")
    if check or not missing:
        for name, m in missing:
            print(f"missing: {name}  ({m['what']})")
        return
    if not key:
        sys.exit("set CIVITAI_API_KEY (in .env) to download from Civitai")
    for name, m in missing:
        dest = models / "loras" / name
        part = dest.with_suffix(".part")
        url = f"https://civitai.com/api/download/models/{m['civitai_version']}?type=Model&format=SafeTensor"
        req = urllib.request.Request(url, headers=AGENT | {"Authorization": f"Bearer {key}"})
        print(f"downloading {name} ...", flush=True)
        with urllib.request.urlopen(req) as resp, part.open("wb") as f:
            while block := resp.read(1 << 20):
                f.write(block)
        if sha256(part) != m["sha256"]:
            part.unlink()
            sys.exit(f"{name}: the download doesn't match its hash; Civitai may have replaced the file")
        part.replace(dest)
    print("done")


if __name__ == "__main__":
    main()
