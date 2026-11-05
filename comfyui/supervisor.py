"""Starts ComfyUI only when asked, so the GPU is free the rest of the time.

POST /start   start ComfyUI if needed, wait until its API answers (also resets the idle timer);
              ?mode=video restarts it with video options (MODES) if it runs as image, and back
POST /stop    stop it
GET  /status  {"running": bool}
ComfyUI is also killed whenever the server runs short of memory (COMFY_HOST_MIN_FREE_GB).
ComfyUI's own API is on :8188 while running. It is stopped automatically after
COMFY_IDLE_STOP_SECONDS without a /start call, in case the worker dies mid-run.
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

idle_value = os.environ.get("COMFY_IDLE_STOP_SECONDS", "").strip()
if not idle_value.isdigit():
    sys.exit("supervisor: COMFY_IDLE_STOP_SECONDS must be set to a whole number")
IDLE_STOP = int(idle_value)
# ComfyUI is killed at once if the whole server has less than this much memory available
# (GB), so a big video job can never push the server into swap and freeze it.
try:
    HOST_MIN_FREE = float(os.environ["COMFY_HOST_MIN_FREE_GB"])
except (KeyError, ValueError):
    sys.exit("supervisor: COMFY_HOST_MIN_FREE_GB must be set to a number of GB")
PEAK = "/sys/fs/cgroup/memory.peak"   # this container's highest memory use (cgroup v2)

CMD = [
    sys.executable, "/app/ComfyUI/main.py",
    "--listen", "0.0.0.0", "--port", "8188",
    "--extra-model-paths-config", "/app/extra_model_paths.yaml",
    "--output-directory", "/data/generated",
    "--user-directory", "/tmp/comfy/user",
    "--temp-directory", "/tmp/comfy/temp",
    "--input-directory", "/tmp/comfy/input",
    "--disable-auto-launch",
    "--disable-api-nodes",       # no paid cloud nodes
]

# Extra ComfyUI options per kind of job. Video: drop each node's output as soon as nothing
# needs it, so the text encoder and the first Wan half leave RAM before the second loads
# (otherwise all three are held at once). Images keep the cache: one checkpoint serves the night.
# Video also uses SageAttention: Wan spends most of its time in attention, and this does it
# about twice as fast with no visible change.
MODES = {"image": [], "video": ["--cache-none", "--use-sage-attention"]}

lock = threading.Lock()
proc: subprocess.Popen | None = None
mode = "image"
last_touch = 0.0


def running() -> bool:
    return proc is not None and proc.poll() is None


def api_up() -> bool:
    try:
        urllib.request.urlopen("http://127.0.0.1:8188/system_stats", timeout=2)
        return True
    except Exception:
        return False


def start(want: str = "image") -> None:
    global proc, last_touch, mode
    if want not in MODES:
        raise RuntimeError(f"unknown mode {want!r}")
    if running() and mode != want:
        stop()
    with lock:
        last_touch = time.time()
        if not running():
            print(f"supervisor: starting ComfyUI for {want}", flush=True)
            for d in ("/tmp/comfy/user", "/tmp/comfy/temp", "/tmp/comfy/input", "/data/generated"):
                os.makedirs(d, exist_ok=True)
            proc, mode = subprocess.Popen(CMD + MODES[want], cwd="/app/ComfyUI"), want
        for _ in range(300):
            if api_up():
                return
            if not running():
                raise RuntimeError(f"ComfyUI exited with code {proc.returncode}")
            time.sleep(1)
        raise RuntimeError("ComfyUI did not answer within 300s")


def stop() -> None:
    global proc
    with lock:
        if running():
            print("supervisor: stopping ComfyUI", flush=True)
            proc.terminate()
            try:
                proc.wait(30)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        if proc is not None:
            peak = peak_gb()
            if peak is not None:
                print(f"supervisor: container memory peak so far {peak:.1f} GB", flush=True)
        proc = None


def host_available_gb() -> float:
    """MemAvailable from /proc/meminfo, which in a container is the host's."""
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024 / 1024
    return float("inf")


def peak_gb() -> float | None:
    try:
        with open(PEAK) as f:
            return int(f.read()) / 1024 ** 3
    except (OSError, ValueError):
        return None


def memory_watch() -> None:
    global proc
    while True:
        time.sleep(1)
        if running():
            free = host_available_gb()
            if free < HOST_MIN_FREE:
                print(f"supervisor: server down to {free:.1f} GB available (limit {HOST_MIN_FREE:g}); "
                      f"killing ComfyUI", flush=True)
                proc.kill()


def idle_watch() -> None:
    while True:
        time.sleep(15)
        if running() and time.time() - last_touch > IDLE_STOP:
            print(f"supervisor: idle for {IDLE_STOP}s", flush=True)
            stop()


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            if self.path.split("?")[0] == "/start":
                query = dict(p.split("=", 1) for p in self.path.partition("?")[2].split("&") if "=" in p)
                start(query.get("mode", "image"))
            elif self.path == "/stop":
                stop()
            else:
                return self._send(404, {"error": "not found"})
        except Exception as e:
            return self._send(500, {"error": str(e)})
        self._send(200, {"running": running()})

    def do_GET(self):
        if self.path == "/status":
            return self._send(200, {"running": running()})
        self._send(404, {"error": "not found"})

    def _send(self, code, data):
        out = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


threading.Thread(target=idle_watch, daemon=True).start()
threading.Thread(target=memory_watch, daemon=True).start()
print("supervisor: ready on :8189 (ComfyUI stopped)", flush=True)
ThreadingHTTPServer(("0.0.0.0", 8189), Handler).serve_forever()
