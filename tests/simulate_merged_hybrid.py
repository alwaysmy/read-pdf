"""模拟改造后 Hybrid 输出：所有块（含空块）+ 裁剪图.
验证：一次检测+识别，不重复、不丢上下文，空块 label/bbox 可输出、可裁剪。
"""
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from extract_pdf import ensure_server  # noqa: E402


def main():
    import os
    import fitz
    import PIL.Image
    from paddleocr import PaddleOCRVL

    pdf = r"D:\MyProjects\整理中\文件整理工作所有的没整理文件都放在这里好了\202404\数字电子技术基础·系统方法--高清版 弗洛伊德 (Thomas L.Floyd)、 娄淑琴.pdf"
    out = pathlib.Path(__file__).resolve().parent / "bench_layout_compare" / "merged_test"
    out.mkdir(parents=True, exist_ok=True)

    ensure_server("llama")
    doc = fitz.open(pdf)
    pix = doc[19].get_pixmap(dpi=150)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as t:
        tmp = t.name
    try:
        pix.save(tmp)
        vl = PaddleOCRVL(
            vl_rec_backend="llama-cpp-server",
            vl_rec_server_url="http://127.0.0.1:12336/v1",
            vl_rec_api_key="12345",
            use_layout_detection=True,
            use_chart_recognition=False,
            use_seal_recognition=False,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
        )
        res = vl.predict(tmp)[0].json["res"]
        items = res.get("parsing_res_list", [])
        img = PIL.Image.open(tmp)
        crop_count = 0
        blocks_out = []
        for it in items:
            label = it.get("block_label", "text")
            content = (it.get("block_content") or "").strip()
            bbox = it.get("block_bbox")
            entry = {"label": label, "bbox": bbox, "has_content": bool(content), "content_len": len(content)}
            blocks_out.append(entry)
            if label in ("table", "image", "chart", "figure", "seal") and bbox and len(bbox) == 4:
                x0, y0, x1, y1 = bbox
                img.crop((x0, y0, x1, y1)).save(str(out / f"crop{crop_count}_{label}.png"))
                crop_count += 1
        print(f"总块数: {len(blocks_out)}  裁剪数: {crop_count}")
        for b in blocks_out:
            print(f"  {b['label']:<14} bbox={b['bbox']}  content={'有' if b['has_content'] else '空'}({b['content_len']})")
        print(f"\n裁剪图目录: {out}")
        for f in sorted(out.glob("crop*.png")):
            print(f"  {f.name} ({f.stat().st_size} bytes)")
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


if __name__ == "__main__":
    main()
