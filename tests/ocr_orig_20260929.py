"""OCR the original book page renders (150dpi) as ground truth for comparison.

Output: tests/ocr_orig_out_<timestamp>/p<page>.txt, rows "x0,y0,x1,y1 | text"
"""
import time
from pathlib import Path

from paddleocr import PaddleOCR

SRC = Path(r"D:\MyProjects\AI\ChatSpace\TEST_RESULTS\read-pdf-bench_20260929\sample_pages")
PAGES = [12, 13, 17, 20, 29, 34]


def main():
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(__file__).with_name(f"ocr_orig_out_{ts}")
    out_dir.mkdir(exist_ok=True)
    ocr = PaddleOCR(use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False)
    for page in PAGES:
        img = SRC / f"p{page}.png"
        if not img.exists():
            print(f"p{page}: MISSING")
            continue
        t0 = time.time()
        result = ocr.predict(str(img))
        rows = []
        for pg in result:
            for t, poly in zip(pg.get("rec_texts"), pg.get("rec_polys")):
                xs = [p[0] for p in poly]
                ys = [p[1] for p in poly]
                rows.append((min(ys), min(xs), max(xs), max(ys), t))
        rows.sort(key=lambda r: (r[0], r[1]))
        out_path = out_dir / f"p{page}.txt"
        out_path.write_text(
            "\n".join(f"{int(r[1])},{int(r[0])},{int(r[2])},{int(r[3])} | {r[4]}"
                      for r in rows),
            encoding="utf-8")
        print(f"p{page}: rows={len(rows)} {time.time()-t0:.1f}s -> {out_path}",
              flush=True)
    print("DONE")


if __name__ == "__main__":
    main()
