"""PP-DocLayoutV3(独立) vs PaddleOCR-VL Hybrid(内置) 版面检测对比.
用法: python tests/bench_layout_compare.py <pdf> --page 20 --out-dir tests/bench_layout_compare
"""
import argparse
import json
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from extract_pdf import extract_layout, extract_hybrid  # noqa: E402
from extract_pdf import ensure_server  # noqa: E402

TAG = time.strftime("%Y%m%d_%H%M%S")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--page", type=int, default=20)
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--out-dir", default="tests/bench_layout_compare")
    args = ap.parse_args()

    import fitz
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(args.pdf)
    pix = doc[args.page - 1].get_pixmap(dpi=args.dpi)
    img_path = out_dir / f"page{args.page:03d}.png"
    pix.save(str(img_path))
    doc.close()

    report = {"pdf": args.pdf, "page": args.page, "dpi": args.dpi, "tag": TAG}

    # 1) 独立 PP-DocLayoutV3（CPU）
    t0 = time.time()
    blocks, lstats = extract_layout(str(img_path), page_num=args.page, min_score=0.3, device="cpu")
    report["layout_v3"] = {
        "time_s": round(time.time() - t0, 2),
        "blocks": len(blocks),
        "labels": sorted(set(b["label"] for b in blocks)),
        "crops": sum(1 for b in blocks if b.get("crop")),
        "error": lstats.get("error"),
    }
    print(f"PP-DocLayoutV3: {len(blocks)} blocks, {report['layout_v3']['time_s']}s, "
          f"labels={report['layout_v3']['labels']}", flush=True)

    # 2) PaddleOCR-VL Hybrid（GPU，内置版面检测）
    ensure_server("llama")
    t0 = time.time()
    hybrid_text, hstats = extract_hybrid(str(img_path))
    report["hybrid"] = {
        "time_s": round(time.time() - t0, 2),
        "chars": len(hybrid_text),
        "error": hstats.get("error"),
    }
    # Hybrid 输出里的 bbox 数 = 检测到的有内容块数
    import re
    bboxes = re.findall(r"bbox=\[", hybrid_text)
    report["hybrid"]["content_blocks"] = len(bboxes)
    print(f"Hybrid: {len(bboxes)} content blocks, {report['hybrid']['time_s']}s, "
          f"{len(hybrid_text)} chars", flush=True)

    report_path = out_dir / f"layout_compare_{TAG}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告: {report_path}", flush=True)


if __name__ == "__main__":
    main()
