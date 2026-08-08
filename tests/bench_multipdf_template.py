"""多 PDF 综合测试（P1/P2/P3）— 跑多个样本交叉验证.
用法: python tests/bench_multipdf.py <pdf1> <pdf2> ... --pages 1-3 --out-dir tests/bench_multi
"""
import argparse
import json
import os
import pathlib
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from extract_pdf import (  # noqa: E402
    extract_glm, extract_dsocr, extract_layout, ensure_server,
)

TAG = time.strftime("%Y%m%d_%H%M%S")


def probe_pdf(pdf_path):
    import fitz
    doc = fitz.open(str(pdf_path))
    info = {"pages": len(doc)}
    chars = [len(doc[i].get_text().strip()) for i in range(min(3, len(doc)))]
    info["first3_chars"] = chars
    doc.close()
    return info


def run_engine(name, fn, img_path, retries=2):
    for attempt in range(retries):
        t0 = time.time()
        text, stats = fn(img_path)
        dt = time.time() - t0
        if text or attempt >= retries - 1:
            return {"engine": name, "time_s": round(dt, 2), "chars": len(text),
                    "error": stats.get("error")}
        time.sleep(2)
    return {"engine": name, "time_s": 0.0, "chars": 0, "error": "failed"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdfs", nargs="+")
    ap.add_argument("--pages", default="1-3")
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--out-dir", default="tests/bench_multi")
    ap.add_argument("--engines", default="glm,dsocr", help="comma list of engines")
    args = ap.parse_args()

    import fitz
    engines = [e.strip() for e in args.engines.split(",") if e.strip()]
    for e in engines:
        if e == "glm":
            ensure_server("glm")
        elif e == "dsocr":
            ensure_server("dsocr")

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    page_nums = []
    for part in args.pages.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            page_nums += list(range(int(a) - 1, int(b)))
        else:
            page_nums.append(int(part) - 1)

    report = {"tag": TAG, "dpi": args.dpi, "pdfs": []}
    for pdf_str in args.pdfs:
        pdf = pathlib.Path(pdf_str)
        info = probe_pdf(pdf)
        doc = fitz.open(str(pdf))
        pdf_entry = {"path": str(pdf), "name": pdf.name, "probe": info, "pages": []}
        for pn in page_nums:
            if pn >= len(doc):
                continue
            page = doc[pn]
            pix = page.get_pixmap(dpi=args.dpi)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                pix.save(tmp_path)
                # P1 layout
                blocks, lstats = extract_layout(tmp_path, page_num=pn + 1, min_score=0.3, device="cpu")
                page_entry = {"page": pn + 1,
                              "layout": {"blocks": len(blocks),
                                         "crops": sum(1 for b in blocks if b.get("crop")),
                                         "error": lstats.get("error")}}
                # P2 engines
                for eng in engines:
                    fn = extract_glm if eng == "glm" else extract_dsocr if eng == "dsocr" else None
                    if fn:
                        page_entry[eng] = run_engine(eng, fn, tmp_path)
                pdf_entry["pages"].append(page_entry)
                print(f"{pdf.name} p{pn+1}: layout={page_entry['layout']['blocks']} blocks, "
                      f"glm={page_entry.get('glm', {}).get('time_s')}s, "
                      f"dsocr={page_entry.get('dsocr', {}).get('time_s')}s", flush=True)
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
        doc.close()
        report["pdfs"].append(pdf_entry)

    report_path = out_dir / f"bench_multipdf_{TAG}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告: {report_path}", flush=True)


if __name__ == "__main__":
    main()
