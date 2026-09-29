# -*- coding: utf-8 -*-
"""Hybrid llama-server 单页推理延迟分解测试（2026-09-29）

目的：拆解 extract_hybrid ~75s/页 的耗时归属（llama-server 推理 vs python 版面管线）。
方法：对已在 12336 运行的 hybrid 服务，复现管线同款请求（prompt="OCR:", image-first），
      单页连发 N 次，记录墙钟时延与 tokens/s。
输出：TEST_RESULTS/read-pdf-bench_20260929/hybrid_latency_<ts>.json
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
ENDPOINT = "http://127.0.0.1:12336/v1/chat/completions"
RUNS = 3


def call_once(img_b64: str) -> dict:
    payload = {
        "model": "hybrid",
        "max_tokens": 4096,
        "temperature": 0,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                {"type": "text", "text": "OCR:"},
            ],
        }],
    }
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer 12345"},
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
        "head": content[:120].replace("\n", " "),
    }


def main() -> int:
    img_b64 = base64.b64encode(IMG.read_bytes()).decode("ascii")
    results = []
    for i in range(RUNS):
        r = call_once(img_b64)
        results.append(r)
        print(f"run{i+1}: wall={r['wall_s']}s tokens={r['completion_tokens']} tok/s={r['tok_per_s']} chars={r['chars']}")
    out = {
        "ts": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "endpoint": ENDPOINT,
        "img": str(IMG),
        "runs": results,
        "wall_mean_s": round(sum(r["wall_s"] for r in results) / len(results), 2),
    }
    out_path = OUT_DIR / f"hybrid_latency_{out['ts']}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"SAVED: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
