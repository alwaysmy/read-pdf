# -*- coding: utf-8 -*-
"""常规样本质量抽查：lm5177 datasheet 同内容段 PI vs 现状管线（2026-09-30）"""
import glob
import json
import re
from pathlib import Path

OUT = Path(r"D:\MyProjects\AI\ChatSpace\TEST_RESULTS\read-pdf-bench_20260930")
j = sorted(OUT.glob("pdf_matrix_*.json"))[-1]
rows = {r["tag"]: r for r in json.loads(j.read_text(encoding="utf-8"))}

pi_path = sorted(OUT.glob("pi_datasheet_*.md"))[-1]
pi = pi_path.read_text(encoding="utf-8")
pipe_path = Path(rows["datasheet"]["pipeline"]["out_path"])
pipe = pipe_path.read_text(encoding="utf-8")

# PI 里找一个表格段
m = re.search(r"\|[^\n]+\n\|[|-][^\n]+\n(?:\|[^\n]+\n){3,}", pi)
print("=== PI table sample ===")
print(m.group(0)[:800] if m else "(no table)")

# 管线输出中同表关键词查找（PI 表头关键词）
kw = "ABS"  # lm5177 是电池充电芯片，常见关键词；先从 PI 表格里取词
if m:
    cells = [c.strip() for c in m.group(0).split("\n")[0].split("|") if c.strip()]
    kw = cells[0][:20] if cells else "Table"
idx = pipe.find(kw)
print(f"\n=== PIPE around keyword {kw!r} ===")
print(pipe[max(0, idx - 200):idx + 600] if idx >= 0 else f"(keyword {kw!r} not in pipe output)")

# PI 正文段
m2 = re.search(r"\n([A-Z][^\n]{80,400})\n", pi)
print("\n=== PI prose sample ===")
print(m2.group(1)[:400] if m2 else "(none)")
if m2:
    idx2 = pipe.find(m2.group(1)[:60])
    print("\n=== PIPE same prose ===")
    print("FOUND" if idx2 >= 0 else "NOT FOUND in pipe")
