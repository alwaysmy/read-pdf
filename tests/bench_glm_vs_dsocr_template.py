"""GLM-OCR vs DeepSeek-OCR 对比测试（P2）— 同页双引擎输出对比 + 耗时统计.
用法: python bench_glm_vs_dsocr_<时间戳>.py <pdf> --pages 1-3 --out-dir <dir>
"""
import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from extract_pdf import (  # noqa: E402
    extract_glm, extract_dsocr, ensure_server, stop_all_servers,
)

TAG = time.strftime("%Y%m%d_%H%M%S")


def run_one(name, fn, img_path, retries=3):
    """Run extractor with timing; returns (text, stats)."""
    for attempt in range(retries):
        t0 = time.time()
        text, stats = fn(img_path)
        dt = time.time() - t0
        if text or attempt >= retries - 1:
            return text, {"engine": name, "time_s": round(dt, 2), **stats}
        time.sleep(2)
    return "", {"engine": name, "time_s": 0.0, "error": "all retries failed"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf_path")
    ap.add_argument("--pages", default="1-3")
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--out-dir", default="tests/bench")
    args = ap.parse_args()

    import fitz
    pdf = pathlib.Path(args.pdf_path)
    doc = fitz.open(str(pdf))

    # Parse pages
    page_nums = []
    for part in args.pages.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            page_nums += list(range(int(a) - 1, int(b)))
        else:
            page_nums.append(int(part) - 1)

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Start both servers
    print("启动 GLM-OCR (12335) + DeepSeek-OCR (12337)...", flush=True)
    ensure_server("glm")
    ensure_server("dsocr")

    results = []
    try:
        for idx, pn in enumerate(page_nums):
            page = doc[pn]
            pix = page.get_pixmap(dpi=args.dpi)
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                pix.save(tmp_path)
                print(f"\n=== PAGE {pn + 1} ===", flush=True)
                glm_text, glm_stats = run_one("glm", extract_glm, tmp_path)
                print(f"  GLM: {glm_stats['time_s']}s, {len(glm_text)} chars", flush=True)
                ds_text, ds_stats = run_one("dsocr", extract_dsocr, tmp_path)
                print(f"  DS : {ds_stats['time_s']}s, {len(ds_text)} chars", flush=True)
                results.append({
                    "page": pn + 1,
                    "glm": {"time_s": glm_stats["time_s"], "chars": len(glm_text),
                            "error": glm_stats.get("error")},
                    "dsocr": {"time_s": ds_stats["time_s"], "chars": len(ds_text),
                              "error": ds_stats.get("error")},
                })
                # Save outputs with timestamp
                (out_dir / f"page{pn+1:04d}_glm_{TAG}.md").write_text(glm_text, encoding="utf-8")
                (out_dir / f"page{pn+1:04d}_dsocr_{TAG}.md").write_text(ds_text, encoding="utf-8")
            finally:
                try:
                    import os
                    os.unlink(tmp_path)
                except Exception:
                    pass
    finally:
        doc.close()

    report = {
        "tag": TAG,
        "pdf": str(pdf),
        "pages": results,
        "glm_total_s": round(sum(r["glm"]["time_s"] for r in results), 2),
        "dsocr_total_s": round(sum(r["dsocr"]["time_s"] for r in results), 2),
    }
    report_path = out_dir / f"bench_glm_vs_dsocr_{TAG}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告: {report_path}", flush=True)


if __name__ == "__main__":
    main()
