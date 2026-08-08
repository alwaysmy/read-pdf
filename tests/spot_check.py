"""多 PDF 质量抽查 — 对比 GLM vs DeepSeek 对同一页的输出（表格/公式场景）.
用法: python tests/spot_check.py <pdf> --page N
"""
import argparse
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from extract_pdf import extract_glm, extract_dsocr, ensure_server  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--page", type=int, default=5)
    ap.add_argument("--dpi", type=int, default=150)
    args = ap.parse_args()

    import fitz
    ensure_server("glm")
    doc = fitz.open(args.pdf)
    pix = doc[args.page - 1].get_pixmap(dpi=args.dpi)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as t:
        tmp = t.name
    try:
        pix.save(tmp)
        g, _ = extract_glm(tmp)
        d, _ = extract_dsocr(tmp)
        print("=" * 60)
        print(f"PDF: {pathlib.Path(args.pdf).name}  PAGE {args.page}")
        print(f"GLM {len(g)} chars | DSOCR {len(d)} chars")
        print("=" * 60)
        print("\n--- GLM 前 18 行 ---")
        print("\n".join(g.splitlines()[:18]))
        print("\n--- DSOCR 前 18 行 ---")
        print("\n".join(d.splitlines()[:18]))
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


if __name__ == "__main__":
    main()
