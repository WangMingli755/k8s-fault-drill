#!/usr/bin/env python3
"""演练用推理服务：/healthz 反映模型是否加载，/predict 可注入延迟。"""
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = os.getenv("MODEL_PATH", "/models/model.json")
DELAY = float(os.getenv("PREDICT_DELAY", "0"))
MEM_MB = int(os.getenv("MODEL_MEMORY_MB", "0"))
STRICT = os.getenv("STRICT_MODEL", "0") == "1"
EXPECTED_FORMAT = int(os.getenv("EXPECTED_FORMAT", "0"))


def log(msg):
    print(f"[serve] {msg}", flush=True)


def load_model():
    if not os.path.exists(MODEL):
        if STRICT:
            raise FileNotFoundError(f"model file not found: {MODEL}")
        log(f"model not found: {MODEL} (healthz will return 503)")
        return None
    with open(MODEL, encoding="utf-8") as f:
        model = json.load(f)
    version = int(model.get("format_version", 0))
    if EXPECTED_FORMAT and version != EXPECTED_FORMAT:
        raise RuntimeError(
            f"unsupported model format_version={version}, expected {EXPECTED_FORMAT}"
        )
    log(f"model loaded: {MODEL} format_version={version}")
    return model


MODEL_DATA = load_model()
if MEM_MB:
    log(f"allocating {MEM_MB}MB for model weights")
    _WEIGHTS = bytearray(MEM_MB * 1024 * 1024)
    log("model weights allocated")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            if MODEL_DATA is None:
                self._send(503, {"status": "model_not_loaded", "model": MODEL})
            else:
                self._send(200, {"status": "ok", "model": MODEL})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/predict":
            time.sleep(DELAY)
            self._send(200, {"prediction": [0.12, 0.88], "model": MODEL})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        log(fmt % args)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    log(f"listening on :{port} delay={DELAY}s")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
