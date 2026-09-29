# -*- coding: utf-8 -*-
"""Unlimited-OCR (llama.cpp BF16) 单页延迟与输出冒烟测试（2026-09-29）

用法：python tests/bench_unlimited_ocr_latency_20260929.py [runs]
输出：TEST_RESULTS/read-pdf-bench_20260929/unlimited_latency_<ts>.json + 页面输出 md
"""
import base64
import json
import sys
import time
from datetime import datetime
from pathlib import Path
import urllib.request

IMG = Path(r"D:\MyProjects\AI\ChatSpace\TEST_RESULTS\read-pdf-bench_20260929\page5.png")
OUT_DIR = Path(r"D:\MyProjects\AI\ChatSpace\TEST_RESULTS\read-pdf-bench_20260929")
ENDPOINT = "http://127.0.0.1:12338/v1/chat/completions"


def call_once(img_b64: str) -> dict:
    payload = {
        "model": "unlimited-ocr",
        "max_tokens": 8192,
        "temperature": 0,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                {"type": "text", "text": "document parsing."},
            ],
        }],
    }
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer none"},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    dt = time.time() - t0
    content = body["choices"][0]["message"]["content"] or ""
    usage = body.get("usage", {})
    return {
        "wall_s": round(dt, 2),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "tok_per_s": round(usage.get("completion_tokens", 0) / dt, 1) if dt > 0 else None,
        "chars": len(content),
        "content": content,
    }


def main() -> int:
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    img_b64 = base64.b64encode(IMG.read_bytes()).decode("ascii")
    results = []
    content = ""
    for i in range(runs):
        r = call_once(img_b64)
        content = r.pop("content")
        results.append(r)
        print(f"run{i+1}: wall={r['wall_s']}s ptok={r['prompt_tokens']} ctok={r['completion_tokens']} tok/s={r['tok_per_s']} chars={r['chars']}")
    out = {
        "ts": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "endpoint": ENDPOINT,
        "prompt": "document parsing.",
        "runs": results,
        "wall_mean_s": round(sum(r["wall_s"] for r in results) / len(results), 2),
    }
    out_path = OUT_DIR / f"unlimited_latency_{out['ts']}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path = OUT_DIR / f"unlimited_page5_{out['ts']}.md"
    md_path.write_text(content, encoding="utf-8")
    print(f"SAVED: {out_path}")
    print(f"SAVED: {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
