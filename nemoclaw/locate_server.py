#!/usr/bin/env python3
"""NVIDIA LocateAnything-3B HTTP inference server (Falcon-compatible /infer).

LocateAnything-3B 目前 vLLM 不支援(custom Qwen2.5+MoonViT architecture),
直接用 transformers + trust_remote_code 啟動常駐 server。

對外 API 與 Falcon Perception 同 contract:
  POST /infer  {"image_path": "/abs/path.jpg", "query": "person, car"}
  →  {"counts": {"person": 5, "car": 3}, "backend": "locate-anything-3b"}

  GET /health → {"ready": true, "model": "locate-anything-3b"}

由 PROD nemoclaw sweep 使用作為 cheap-gate 偵測後端。每 category 跑一次,
回 box 數量;model BF16 ~6-8GB,單卡 GB10 與 Nemotron-30B 共存。
"""
import json
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import torch
from PIL import Image
from transformers import AutoModel, AutoProcessor, AutoTokenizer


MODEL_PATH = os.environ.get("LOCATE_MODEL_PATH",
                            "/home/aiunion/hf-models/LocateAnything-3B")
HOST = os.environ.get("LOCATE_HOST", "127.0.0.1")
PORT = int(os.environ.get("LOCATE_PORT", "18794"))
MAX_NEW_TOKENS = int(os.environ.get("LOCATE_MAX_NEW_TOKENS", "512"))

BOX_RE = re.compile(r"<box>\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+\s*</box>")


def _log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


_log(f"Loading LocateAnything-3B from {MODEL_PATH}...")
_tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, trust_remote_code=True)
_processor = AutoProcessor.from_pretrained(MODEL_PATH, trust_remote_code=True)
_model = AutoModel.from_pretrained(
    MODEL_PATH,
    torch_dtype=torch.bfloat16,
    trust_remote_code=True,
).to("cuda").eval()
_log("LocateAnything-3B ready on cuda · bf16")


@torch.inference_mode()
def detect_one(image, category):
    """Single-category inference, count <box> instances in answer."""
    prompt = f"Locate all instances matching: {category}."
    messages = [{"role": "user", "content": [
        {"type": "image", "image": image},
        {"type": "text", "text": prompt},
    ]}]
    # Some processors expose apply_chat_template; the model's custom processor
    # uses py_apply_chat_template per the model card.
    chat_fn = getattr(_processor, "py_apply_chat_template", None) or \
              getattr(_processor, "apply_chat_template", None)
    text = chat_fn(messages, tokenize=False, add_generation_prompt=True)
    images, videos = _processor.process_vision_info(messages)
    inputs = _processor(text=[text], images=images, videos=videos,
                        return_tensors="pt").to("cuda")
    response = _model.generate(
        pixel_values=inputs["pixel_values"].to(torch.bfloat16),
        input_ids=inputs["input_ids"],
        attention_mask=inputs["attention_mask"],
        image_grid_hws=inputs.get("image_grid_hws", None),
        tokenizer=_tokenizer,
        max_new_tokens=MAX_NEW_TOKENS,
        generation_mode="hybrid",
        use_cache=True,
        temperature=0.0,
        do_sample=False,
    )
    text_out = response[0] if isinstance(response, tuple) else response
    if isinstance(text_out, (list, tuple)):
        text_out = text_out[0]
    return len(BOX_RE.findall(str(text_out)))


class H(BaseHTTPRequestHandler):
    def _send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"ready": True, "model": "locate-anything-3b",
                                  "device": "cuda", "dtype": "bf16"})
            return
        self.send_error(404)

    def do_POST(self):
        if self.path != "/infer":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length))
        except Exception:
            self._send_json(400, {"error": "bad json"})
            return
        image_path = body.get("image_path")
        query = body.get("query", "")
        if not image_path:
            self._send_json(400, {"error": "image_path required"})
            return
        try:
            image = Image.open(image_path).convert("RGB")
        except Exception as e:
            self._send_json(400, {"error": f"image load failed: {e}"})
            return
        categories = [c.strip() for c in (query or "").split(",") if c.strip()]
        counts = {}
        for cat in categories:
            try:
                counts[cat] = detect_one(image, cat)
            except Exception as e:
                _log(f"detect_one({cat!r}) failed: {e}")
                counts[cat] = 0
        self._send_json(200, {"counts": counts, "backend": "locate-anything-3b"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    _log(f"locate-anything-server on {HOST}:{PORT}")
    HTTPServer((HOST, PORT), H).serve_forever()
