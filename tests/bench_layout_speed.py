"""PP-DocLayoutV3 版面分析速度实测 — 多页连续测，区分加载/推理.
用法: python tests/bench_layout_speed.py <pdf> --pages 20-29 --device cpu --out-dir tests/bench_layout_speed
"""
import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from extract_pdf import extract_layout  # noqa: E402

TAG = time.strftime("%Y%m%d_%H%M%S")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--pages", default="20-29", help="e.g. 20-29")
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--device", default="cpu", choices=["cpu", "gpu"])
    ap.add_argument("--out-dir", default="tests/bench_layout_speed")
    args = ap.parse_args()

    import fitz
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Parse pages
    page_nums = []
    for part in args.pages.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            page_nums += list(range(int(a) - 1, int(b)))
        else:
            page_nums.append(int(part) - 1)

    doc = fitz.open(args.pdf)
    results = []
    t_load_start = time.time()
    # 首次调用含模型加载
    for idx, pn in enumerate(page_nums):
        pix = doc[pn].get_pixmap(dpi=args.dpi)
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as t:
            tmp = t.name
        try:
            pix.save(tmp)
            t0 = time.time()
            blocks, stats = extract_layout(tmp, page_num=pn + 1, min_score=0.3, device=args.device)
            dt = time.time() - t0
            results.append({"page": pn + 1, "time_s": round(dt, 3), "blocks": len(blocks),
                            "error": stats.get("error")})
            tag = "含模型加载" if idx == 0 else ""
            print(f"page {pn+1}: {dt:.3f}s  {len(blocks)} blocks  {tag}", flush=True)
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass
    doc.close()

    # 统计：去掉首次（加载）后的均值
    infer_times = [r["time_s"] for r in results[1:]]
    avg = sum(infer_times) / len(infer_times) if infer_times else 0
    report = {
        "tag": TAG, "pdf": pathlib.Path(args.pdf).name, "device": args.device, "dpi": args.dpi,
        "pages": results,
        "first_load_s": results[0]["time_s"] if results else None,
        "avg_infer_s_per_page": round(avg, 3),
    }
    rp = out_dir / f"layout_speed_{TAG}.json"
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n首次(含加载): {report['first_load_s']}s  稳定后均值: {avg:.3f}s/页")
    print(f"报告: {rp}", flush=True)


if __name__ == "__main__":
    main()
