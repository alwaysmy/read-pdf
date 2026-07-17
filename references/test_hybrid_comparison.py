# PaddleOCR Hybrid 测试脚本（2026-05-14）

# 前提：需要 PaddleOCR-VL GGUF server 在 :12335 运行
# python server.py start

import sys, time, json
sys.path.insert(0, r'D:\MyProjects\AGENT方法库\skills\paddlepaddle_llama')
from pipeline import HybridPipeline

pipe = HybridPipeline()
images = [
    r"d:\llm\test_data\1958-04-23 Joan to Sid_p1.jpg",
    r"d:\llm\test_data\PDF测试页.png",
    r"d:\llm\test_data\pdf_pages\page_030.png",
]

for img in images:
    print(f"\n{'='*60}")
    print(f"Testing: {img}")
    result = pipe.extract(img, format="json")
    print(f"Time: {result['time_s']}s, Blocks: {result['block_count']}, Layout boxes: {result['layout_boxes']}")
    print(f"Labels: {[b['label'] for b in result['blocks']]}")

# Native comparison
from paddleocr import PaddleOCRVL
vl_native = PaddleOCRVL(use_layout_detection=True, use_chart_recognition=False, use_seal_recognition=False, use_doc_orientation_classify=False, use_doc_unwarping=False)

for img in images:
    t0 = time.time()
    r = vl_native.predict(img)
    t = time.time() - t0
    blocks = len(r[0].json['res']['parsing_res_list'])
    print(f"Native {img}: {t:.1f}s, {blocks} blocks")
