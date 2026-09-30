# -*- coding: utf-8 -*-
"""版面检测冷热分账，CPU vs GPU 对比（2026-09-30）
用法：python tests/layout_device_split_20260930.py [cpu|gpu|both]
输出：模型创建冷态 + 逐页热态推理 + 块数
"""
import sys
import tempfile
import time
from pathlib import Path

import fitz

PDF = Path(r"D:\llm\_archive\08_doc-processing\test_data\微弱信号检测_高晋占编著_清华大学出版社_2019_第3版.pdf")
PAGES = [4, 5, 6, 7, 8, 9]  # p5-10


def run(device: str):
    # 新进程保证冷态起点一致
    t0 = time.time()
    import sys as _s
    _s.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import extract_pdf
    from extract_pdf import extract_layout, _get_layout_model
    t_import = time.time() - t0

    # 重置模块级模型缓存，保证 device 真正切换
    extract_pdf._LAYOUT_MODEL = None

    t0 = time.time()
    _get_layout_model(device)
    t_model = time.time() - t0

    doc = fitz.open(PDF)
    imgs = []
    for pno in PAGES:
        pix = doc[pno].get_pixmap(dpi=150)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            tf.write(pix.tobytes())
            imgs.append(tf.name)
    doc.close()

    per_page = []
    blocks_total = 0
    for tmp, pno in zip(imgs, PAGES):
        t0 = time.time()
        blocks, stats = extract_layout(tmp, page_num=pno + 1, device=device)
        per_page.append(round(time.time() - t0, 3))
        blocks_total += len(blocks)
        if stats.get("error"):
            print(f"  ERROR: {stats['error']}")
        Path(tmp).unlink(missing_ok=True)

    warm = per_page[1:]  # 首页可能含额外初始化
    print(f"[{device}] import={round(t_import,2)}s  model_create_cold={round(t_model,2)}s")
    print(f"[{device}] per_page={per_page}  mean_all={round(sum(per_page)/len(per_page),3)}  "
          f"mean_warm={round(sum(warm)/len(warm),3) if warm else 'n/a'}")
    print(f"[{device}] blocks={blocks_total}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "both"
    for dev in (["cpu", "gpu"] if mode == "both" else [mode]):
        run(dev)
