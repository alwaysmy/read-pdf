# -*- coding: utf-8 -*-
"""定向诊断（2026-09-30）：
1. arXiv：PI 是否在前 8 页内断页/漏右栏（对照 fitz 前 8 页基准）
2. scan_opamp 管线失败：抓完整 stderr
3. big_a320 管线失败：抓完整 stderr
"""
import glob
import re
import subprocess
import sys
from pathlib import Path

import fitz

OUT = Path(r"D:\MyProjects\AI\ChatSpace\TEST_RESULTS\read-pdf-bench_20260930")
EXTRACT = Path(r"D:\MyProjects\AGENT方法库\skills\read-pdf\scripts\extract_pdf.py")

# ---- 1) arXiv 前 8 页基准 ----
arxiv = str(OUT / "arxiv_1706.03762.pdf")
d = fitz.open(arxiv)
ref8 = ""
for i in range(8):
    ref8 += d[i].get_text()
total_pages = len(d)
d.close()
pi = sorted(OUT.glob("pi2_arxiv_*.md"))[-1].read_text(encoding="utf-8")
pl = Path(r"D:\MyProjects\AI\ChatSpace\TEST_RESULTS\read-pdf-bench_20260930")  # placeholder


def norm(s):
    return re.sub(r"\s", "", s)


print(f"arxiv total pages: {total_pages}; ref8 chars: {len(ref8)}; PI chars: {len(pi)}")
for p in ["Residual Dropout", "Label Smoothing", "beam search", "ablation",
          "Multi-Head Attention", "3.2", "Position-wise"]:
    print(f"  {p!r}: in ref8_pages={'Y' if norm(p) in norm(ref8) else '-'} "
          f"in PI={'Y' if norm(p) in norm(pi) else '-'}")
print("PI tail 200:", repr(pi[-200:]))
# PI 分页结构
print("PI headings:", re.findall(r"^#{1,3} .{0,50}", pi, re.M)[:15])

# ---- 2)/3) 管线完整 stderr ----
for tag, path, pages in [
    ("scan_opamp", r"C:\Users\AlwaysTS\Desktop\技术资料\模拟电路\运算放大器参数解析与LTspice应用仿真.pdf", "1-3"),
    ("big_a320", r"E:\手册与技术支持\设备资料与文档\A320操作手册\A320 FCOM 中文版__2012.09.13.pdf", "100-102"),
]:
    print(f"\n===== {tag} pipeline stderr (3 pages, fast) =====")
    p = subprocess.run(
        [sys.executable, str(EXTRACT), path, "--pages", pages,
         "--output-dir", str(OUT)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    err = p.stderr or ""
    # 只留 traceback 关键行
    lines = [l for l in err.splitlines()
             if re.search(r"Error|error|Exception|raise|File \"", l)]
    print(f"rc={p.returncode}")
    for l in lines[-12:]:
        print("  " + l[:180])
    if not lines:
        print("  stdout tail:", (p.stdout or "")[-300:])
