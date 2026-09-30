# -*- coding: utf-8 -*-
"""本机 hybrid 管线分账（2026-09-30，进程内冷热分离）
A. 版面检测：模型创建(冷) vs 逐页推理(热) —— paddlex PP-DocLayoutV3 CPU
B. 逐块 VL：llama-server 日志里每次请求的 timing（hybrid 管线逐块请求证据）
"""
import json
import re
import tempfile
import time
from pathlib import Path

import fitz

PDF = Path(r"D:\llm\_archive\08_doc-processing\test_data\微弱信号检测_高晋占编著_清华大学出版社_2019_第3版.pdf")
PAGES = [4, 5, 6, 7, 8, 9]  # p5-10 (0-based)

# ---- A. 版面检测进程内分账 ----
t_all = time.time()
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from extract_pdf import extract_layout, _get_layout_model  # noqa: E402

t0 = time.time()
_get_layout_model("cpu")
t_model = time.time() - t0

doc = fitz.open(PDF)
per_page = []
blocks_total = 0
for pno in PAGES:
    pix = doc[pno].get_pixmap(dpi=150)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tf.write(pix.tobytes())
        tmp = tf.name
    t0 = time.time()
    blocks, _ = extract_layout(tmp, page_num=pno + 1, device="cpu")
    per_page.append(round(time.time() - t0, 3))
    blocks_total += len(blocks)
    Path(tmp).unlink(missing_ok=True)
doc.close()

print("=== A. layout (in-process, CPU) ===")
print(f"model_create_cold_s: {round(t_model, 2)}")
print(f"per_page_warm_s: {per_page}  mean={round(sum(per_page)/len(per_page), 3)}")
print(f"blocks: {blocks_total} ({round(blocks_total/len(PAGES),1)}/page)")

# ---- B. llama-server 日志逐块请求计数 ----
print()
print("=== B. llama-server hybrid log: per-request timings ===")
logs = sorted(Path(tempfile.gettempdir()).glob("llama_hybrid_*.log"),
              key=lambda p: p.stat().st_mtime, reverse=True)
for lg in logs[:3]:
    txt = lg.read_text(encoding="utf-8", errors="replace")
    # 每次请求的 print_timing: prompt eval + eval
    tasks = re.findall(r"task (\d+) \| prompt eval time =\s+([\d.]+) ms / +(\d+) tokens", txt)
    evals = re.findall(r"task (\d+) \|\s+eval time =\s+([\d.]+) ms / +(\d+) tokens", txt)
    if not tasks:
        continue
    pt = [(float(m), int(n)) for _, m, n in tasks]
    et = [(float(m), int(n)) for _, m, n in evals]
    print(f"{lg.name}: requests={len(pt)}")
    print(f"  prompt_eval ms: {[round(x[0]) for x in pt][:20]}")
    print(f"  decode ms: {[round(x[0]) for x in et][:20]}")
    print(f"  total per-req ms: {[round(a[0]+b[0]) for a, b in zip(pt, et)][:20]}")
    break
