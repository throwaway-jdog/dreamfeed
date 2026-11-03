"""Starts ComfyUI only when asked, so the GPU is free the rest of the time.

POST /start   start ComfyUI if needed, wait until its API answers (also resets the idle timer)
POST /stop    stop it
GET  /status  {"running": bool}
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

lock = threading.Lock()
proc: subprocess.Popen | None = None
last_touch = 0.0


def running() -> bool:
    return proc is not None and proc.poll() is None


def api_up() -> bool:
    try:
        urllib.request.urlopen("http://127.0.0.1:8188/system_stats", timeout=2)
        return True
    except Exception:
        return False


def start() -> None:
    global proc, last_touch
    with lock:
        last_touch = time.time()
        if not running():
            print("supervisor: starting ComfyUI", flush=True)
            for d in ("/tmp/comfy/user", "/tmp/comfy/temp", "/tmp/comfy/input", "/data/generated"):
                os.makedirs(d, exist_ok=True)
            proc = subprocess.Popen(CMD, cwd="/app/ComfyUI")
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
        proc = None


def idle_watch() -> None:
    while True:
        time.sleep(15)
        if running() and time.time() - last_touch > IDLE_STOP:
            print(f"supervisor: idle for {IDLE_STOP}s", flush=True)
            stop()


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            if self.path == "/start":
                start()
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
print("supervisor: ready on :8189 (ComfyUI stopped)", flush=True)
ThreadingHTTPServer(("0.0.0.0", 8189), Handler).serve_forever()
