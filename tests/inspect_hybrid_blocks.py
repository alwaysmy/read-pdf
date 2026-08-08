"""检查 PaddleOCR-VL Hybrid 原始结果：parsing_res_list 是否含空 content 块.
用法: python tests/inspect_hybrid_blocks.py <pdf> --page 20
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from extract_pdf import ensure_server  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--page", type=int, default=20)
    ap.add_argument("--dpi", type=int, default=150)
    args = ap.parse_args()

    import fitz
    ensure_server("llama")

    doc = fitz.open(args.pdf)
    pix = doc[args.page - 1].get_pixmap(dpi=args.dpi)
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as t:
        tmp = t.name
    try:
        pix.save(tmp)
        from paddleocr import PaddleOCRVL
        vl = PaddleOCRVL(
            vl_rec_backend='llama-cpp-server',
            vl_rec_server_url='http://127.0.0.1:12336/v1',
            vl_rec_api_key='12345',
            use_layout_detection=True,
            use_chart_recognition=False,
            use_seal_recognition=False,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
        )
        result = vl.predict(tmp)
        res = result[0].json['res']
        items = res.get('parsing_res_list', [])
        print(f"parsing_res_list 总数: {len(items)}")
        empty = [it for it in items if not (it.get('block_content') or '').strip()]
        nonempty = [it for it in items if (it.get('block_content') or '').strip()]
        print(f"  有内容块: {len(nonempty)}")
        print(f"  空内容块(检测到但无识别内容): {len(empty)}")
        print("\n=== 空内容块明细（label + bbox） ===")
        for it in empty:
            print(f"  label={it.get('block_label')!r}  bbox={it.get('block_bbox')}")
        print("\n=== 有内容块 label 分布 ===")
        from collections import Counter
        cnt = Counter(it.get('block_label', 'text') for it in nonempty)
        for k, v in cnt.items():
            print(f"  {k}: {v}")
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


if __name__ == "__main__":
    main()
