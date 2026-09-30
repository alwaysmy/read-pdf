"""Pairwise similarity check for compare-page screenshots.

Purpose: decide whether repeated read() calls returning the same picture is a
tool replay artifact or whether two different screenshot files really show the
same rendered page.

Method: resize each image to 128x128 grayscale, compute mean absolute
difference (MAD, 0-255) between every pair. MAD < ~3 => visually near-identical.

Output: tests/img_similarity_diag_<timestamp>.txt (timestamped to avoid overwrite)
"""
import sys
import time
from itertools import combinations
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("PIL not available")

SHOTS = Path(r"D:\MyProjects\AGENT方法库\skills\read-pdf\.openchamber\screenshots")
FILES = [
    "compare-page12-2026-09-29T09-37-18-070.jpg",
    "cmp-p13-2026-09-29T09-51-26-231.jpg",
    "cmp-p17-2026-09-29T09-54-27-229.jpg",
    "cmp-p20-2026-09-29T09-54-52-080.jpg",
    "cmp-p29-2026-09-29T09-57-53-452.jpg",
    "cmp-p34-2026-09-29T09-58-26-009.jpg",
]


def load_gray(name: str):
    img = Image.open(SHOTS / name).convert("L").resize((128, 128))
    return list(img.getdata())


def mad(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def main():
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = Path(__file__).with_name(f"img_similarity_diag_{ts}.txt")
    imgs = {n: load_gray(n) for n in FILES}
    lines = ["pairwise MAD (0-255, <3 = near-identical):"]
    for a, b in combinations(FILES, 2):
        lines.append(f"  {mad(imgs[a], imgs[b]):8.3f}  {a}  <->  {b}")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\nwritten: {out_path}")


if __name__ == "__main__":
    main()
