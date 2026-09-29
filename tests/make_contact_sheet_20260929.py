# -*- coding: utf-8 -*-
"""渲染前 N 页缩略图并拼 contact sheet（2026-09-29，扫描书无文本层，视觉定位样本页）"""
import sys
from pathlib import Path
import fitz
from PIL import Image, ImageDraw

PDF = Path(r"D:\llm\_archive\08_doc-processing\test_data\微弱信号检测_高晋占编著_清华大学出版社_2019_第3版.pdf")
OUT_DIR = Path(r"D:\MyProjects\AI\ChatSpace\TEST_RESULTS\read-pdf-bench_20260929")
THUMB_W = 280
COLS = 5
ROWS = 4


def sheet(start: int, count: int, tag: str):
    doc = fitz.open(PDF)
    cells = []
    for pno in range(start, start + count):
        if pno > len(doc):
            break
        pix = doc[pno - 1].get_pixmap(dpi=50)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        h = int(THUMB_W * img.height / img.width)
        img = img.resize((THUMB_W, h))
        canvas = Image.new("RGB", (THUMB_W, h + 18), "white")
        canvas.paste(img, (0, 18))
        d = ImageDraw.Draw(canvas)
        d.text((4, 2), f"p{pno}", fill="red")
        cells.append(canvas)
    doc.close()
    if not cells:
        return
    cell_h = max(c.height for c in cells)
    rows = (len(cells) + COLS - 1) // COLS
    out = Image.new("RGB", (THUMB_W * COLS, cell_h * rows), "gray")
    for i, c in enumerate(cells):
        out.paste(c, ((i % COLS) * THUMB_W, (i // COLS) * cell_h))
    path = OUT_DIR / f"contact_{tag}_p{start}-{start+count-1}.png"
    out.save(path)
    print(f"SAVED: {path}")


if __name__ == "__main__":
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    sheet(start, count, sys.argv[3] if len(sys.argv) > 3 else "a")
