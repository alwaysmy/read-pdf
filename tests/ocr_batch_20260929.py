"""Batch OCR of all 6 compare screenshots with one model instance.

Output: tests/ocr_out_<timestamp>/<image_stem>.txt, rows "x0,y0,x1,y1 | text"
sorted by y then x. Timestamped directory to avoid overwrite.
"""
import time
from pathlib import Path

from paddleocr import PaddleOCR

SHOTS = Path(r"D:\MyProjects\AGENT方法库\skills\read-pdf\.openchamber\screenshots")
FILES = [
    "compare-page12-2026-09-29T09-37-18-070.jpg",
    "cmp-p13-2026-09-29T09-51-26-231.jpg",
    "cmp-p17-2026-09-29T09-54-27-229.jpg",
    "cmp-p20-2026-09-29T09-54-52-080.jpg",
    "cmp-p29-2026-09-29T09-57-53-452.jpg",
    "cmp-p34-2026-09-29T09-58-26-009.jpg",
]


def main():
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(__file__).with_name(f"ocr_out_{ts}")
    out_dir.mkdir(exist_ok=True)
    ocr = PaddleOCR(use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False)
    for name in FILES:
        t0 = time.time()
        result = ocr.predict(str(SHOTS / name))
        rows = []
        for page in result:
            for t, poly in zip(page.get("rec_texts"), page.get("rec_polys")):
                xs = [p[0] for p in poly]
                ys = [p[1] for p in poly]
                rows.append((min(ys), min(xs), max(xs), max(ys), t))
        rows.sort(key=lambda r: (r[0], r[1]))
        out_path = out_dir / f"{name.split('-2026')[0]}.txt"
        out_path.write_text(
            "\n".join(f"{int(r[1])},{int(r[0])},{int(r[2])},{int(r[3])} | {r[4]}"
                      for r in rows),
            encoding="utf-8")
        print(f"{name}: rows={len(rows)} {time.time()-t0:.1f}s -> {out_path}",
              flush=True)
    print("DONE")


if __name__ == "__main__":
    main()
