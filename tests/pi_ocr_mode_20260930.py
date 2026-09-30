# -*- coding: utf-8 -*-
"""PI 自带 OCR 模式测试（process_pdf_with_ocr，CPU PP-OCRv6，2026-09-30）
对扫描书前 3 页跑，验证 PI 在图像页的 OCR 能力（穷尽其能力边界）。
"""
import json
import os
import time
from datetime import datetime
from pathlib import Path

# PDFium 依赖：用 pypdfium2_raw 自带 DLL
os.environ.setdefault(
    "PDFIUM_LIB_PATH",
    r"C:\Users\AlwaysTS\AppData\Local\Programs\Python\Python311\Lib\site-packages\pypdfium2_raw\pdfium.dll",
)
# ONNX Runtime：显式指向官方共享版（否则可能加载到不兼容的同名 DLL）
os.environ.setdefault(
    "ORT_DYLIB_PATH",
    r"C:\Users\AlwaysTS\AppData\Local\Programs\Python\Python311\Lib\site-packages\onnxruntime\capi\onnxruntime.dll",
)
# ONNX Runtime：指定标准 pip 共享库（PI 自动探测到的 dll 不导出 C API）
os.environ.setdefault(
    "ORT_DYLIB_PATH",
    r"C:\Users\AlwaysTS\.workbuddy\binaries\python\envs\default\Lib\site-packages\onnxruntime\capi\onnxruntime.dll",
)

import pdf_inspector

OUT = Path(r"D:\MyProjects\AI\ChatSpace\TEST_RESULTS\read-pdf-bench_20260930")
SCAN = r"C:\Users\AlwaysTS\Desktop\技术资料\模拟电路\运算放大器参数解析与LTspice应用仿真.pdf"

t0 = time.time()
try:
    r = pdf_inspector.process_pdf_with_ocr(SCAN, page_numbers=[1, 2, 3])
    wall = time.time() - t0
    print(f"OK wall={wall:.1f}s type={type(r).__name__}")
    attrs = [a for a in dir(r) if not a.startswith("_")]
    print("attrs:", attrs)
    md = getattr(r, "markdown", "") or ""
    print(f"markdown: {len(md)} chars")
    print("HEAD:", repr(md[:400]))
    # OCR 相关字段
    for a in ["ocr_pages", "ocr_reasons_by_page", "pages_needing_ocr",
              "processing_time_ms", "pdf_type"]:
        if hasattr(r, a):
            v = getattr(r, a)
            print(f"{a}: {str(v)[:200]}")
    (OUT / f"pi_ocr_scanopamp_{datetime.now().strftime('%H%M%S')}.md").write_text(
        md, encoding="utf-8")
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")
    # 备选签名探测
    import inspect
    print("sig:", inspect.signature(pdf_inspector.process_pdf_with_ocr))
