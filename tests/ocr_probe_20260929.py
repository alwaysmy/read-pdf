"""OCR probe: run paddleocr on one compare screenshot, dump text with coords.

Purpose: recover per-column engine text from the screenshot when image read()
is unreliable. Output rows are "x0,y0,x1,y1 | text" sorted by y then x, so
column membership (unlimited / hybrid / glm / dsocr) can be derived from x.

Usage: python ocr_probe_20260929.py <image_path> [out_txt]
Output: tests/ocr_probe_<image_stem>_<timestamp>.txt (timestamped, no overwrite)
"""
import sys
import time
from pathlib import Path

from paddleocr import PaddleOCR


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: ocr_probe_20260929.py <image_path> [out_txt]")
    img_path = Path(sys.argv[1])
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).with_name(
        f"ocr_probe_{img_path.stem}_{ts}.txt")

    ocr = PaddleOCR(use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False)
    result = ocr.predict(str(img_path))
    rows = []
    for page in result:
        texts = page.get("rec_texts")
        polys = page.get("rec_polys")
        for t, poly in zip(texts, polys):
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            rows.append((min(ys), min(xs), max(xs), max(ys), t))
    rows.sort(key=lambda r: (r[0], r[1]))
    lines = [f"{int(r[1])},{int(r[0])},{int(r[2])},{int(r[3])} | {r[4]}" for r in rows]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"rows={len(rows)} written: {out_path}")


if __name__ == "__main__":
    main()
