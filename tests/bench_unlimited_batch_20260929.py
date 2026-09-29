# -*- coding: utf-8 -*-
"""Unlimited-OCR (llama.cpp BF16) 批量测速（2026-09-29）

阶段1：渲染指定页为 PNG
阶段2：串行处理 N 页，测稳态 s/页（对齐 hybrid 基线口径）
阶段3（--concurrency C）：并发 C 路发全部页，测吞吐 页/分（验证第三方评论 30 页/分 @4080 vLLM）

用法：
  python tests/bench_unlimited_batch_20260929.py --pages 5-10 --mode serial
  python tests/bench_unlimited_batch_20260929.py --pages 5-20 --mode concurrent --concurrency 16

输出：TEST_RESULTS/read-pdf-bench_20260929/unlimited_batch_<mode>_<ts>.json + 每页 md
"""
import argparse
import base64
import json
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

PDF = Path(r"D:\llm\_archive\08_doc-processing\test_data\微弱信号检测_高晋占编著_清华大学出版社_2019_第3版.pdf")
OUT_DIR = Path(r"D:\MyProjects\AI\ChatSpace\TEST_RESULTS\read-pdf-bench_20260929")
IMG_DIR = OUT_DIR / "pages_render"
ENDPOINT = "http://127.0.0.1:12338/v1/chat/completions"
MAX_TOKENS = 4096


def render_pages(page_numbers: list) -> dict:
    import fitz
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    paths = {}
    doc = fitz.open(PDF)
    for pno in page_numbers:
        pix = doc[pno - 1].get_pixmap(dpi=150)
        p = IMG_DIR / f"p{pno}.png"
        pix.save(p)
        paths[pno] = p
    doc.close()
    print(f"rendered {len(paths)} pages in {time.time()-t0:.1f}s")
    return paths


def call_page(pno: int, img_path: Path) -> dict:
    img_b64 = base64.b64encode(img_path.read_bytes()).decode("ascii")
    payload = {
        "model": "unlimited-ocr",
        "max_tokens": MAX_TOKENS,
        "temperature": 0,
        "messages": [{
            "role": "user",
            "content": [
                # image-first：media marker 必须在 prompt 开头（vLLM 配方 <image> 开头）
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
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"page": pno, "error": f"HTTP {e.code}: {e.read().decode()[:200]}", "wall_s": round(time.time()-t0, 2)}
    dt = time.time() - t0
    content = body["choices"][0]["message"]["content"] or ""
    md_path = OUT_DIR / f"unlimited_p{pno}_{datetime.now().strftime('%H%M%S')}.md"
    md_path.write_text(content, encoding="utf-8")
    return {
        "page": pno,
        "wall_s": round(dt, 2),
        "finish": body["choices"][0].get("finish_reason"),
        "completion_tokens": body["usage"].get("completion_tokens"),
        "prompt_tokens": body["usage"].get("prompt_tokens"),
        "chars": len(content),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", required=True, help="e.g. 5-10")
    ap.add_argument("--mode", choices=["serial", "concurrent"], default="serial")
    ap.add_argument("--concurrency", type=int, default=16)
    args = ap.parse_args()

    # 支持混合格式："5-10" / "12,13" / "5-10,12"
    page_numbers = []
    for part in args.pages.split(","):
        if "-" in part:
            a, b = part.split("-")
            page_numbers.extend(range(int(a), int(b) + 1))
        else:
            page_numbers.append(int(part))
    paths = render_pages(page_numbers)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    results = []
    if args.mode == "serial":
        # 预热 1 次（llama-server CUDA JIT 首请求）
        call_page(page_numbers[0], paths[page_numbers[0]])
        t0 = time.time()
        for pno in page_numbers:
            r = call_page(pno, paths[pno])
            results.append(r)
            print(f"p{pno}: wall={r.get('wall_s')}s ctok={r.get('completion_tokens')} "
                  f"finish={r.get('finish')} chars={r.get('chars')}")
        total = time.time() - t0
        print(f"SERIAL total={total:.1f}s  per_page={total/len(page_numbers):.2f}s")
        summary = {"total_s": round(total, 2),
                   "per_page_s": round(total / len(page_numbers), 2)}
    else:
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futs = {pool.submit(call_page, p, paths[p]): p for p in page_numbers}
            for f in as_completed(futs):
                r = f.result()
                results.append(r)
                print(f"p{r['page']}: wall={r.get('wall_s')}s finish={r.get('finish')}")
        total = time.time() - t0
        ok = [r for r in results if "error" not in r]
        ppm = len(ok) / total * 60
        print(f"CONCURRENT n={args.concurrency} total={total:.1f}s ok={len(ok)} "
              f"throughput={ppm:.1f} pages/min")
        summary = {"concurrency": args.concurrency, "total_s": round(total, 2),
                   "ok": len(ok), "pages_per_min": round(ppm, 1)}

    out = {"ts": ts, "mode": args.mode, "endpoint": ENDPOINT,
           "summary": summary, "results": sorted(results, key=lambda r: r["page"])}
    out_path = OUT_DIR / f"unlimited_batch_{args.mode}_{ts}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"SAVED: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
