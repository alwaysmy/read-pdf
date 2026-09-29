# -*- coding: utf-8 -*-
"""lm5177 关键内容存在性对照：PI vs 现状管线（2026-09-30）"""
import json
import re
from pathlib import Path

OUT = Path(r"D:\MyProjects\AI\ChatSpace\TEST_RESULTS\read-pdf-bench_20260930")
j = sorted(OUT.glob("pdf_matrix_*.json"))[-1]
rows = {r["tag"]: r for r in json.loads(j.read_text(encoding="utf-8"))}
pi = sorted(OUT.glob("pi_datasheet_*.md"))[-1].read_text(encoding="utf-8")
pipe = Path(rows["datasheet"]["pipeline"]["out_path"]).read_text(encoding="utf-8")


def norm(s):
    return re.sub(r"\s", "", s)


pi_n, pipe_n = norm(pi), norm(pipe)
PHRASES = [
    "four switch buck-boost controller",
    "quiescent currents",
    "switching frequency remains the same",
    "Power over ethernet",
    "Medical PSU",
    "RT or SYNC pin",
    "average current monitor",
    "Efficiency vs Input Voltage",
    "Input Voltage (V)",
    "falling",
]
print(f"{'phrase':45} {'PI':>4} {'PIPE':>5}")
hit_pi = hit_pipe = 0
for p in PHRASES:
    a, b = norm(p) in pi_n, norm(p) in pipe_n
    hit_pi += a
    hit_pipe += b
    print(f"{p:45} {'Y' if a else '-':>4} {'Y' if b else '-':>5}")
print(f"\n{hit_pi}/{len(PHRASES)} vs {hit_pipe}/{len(PHRASES)}")

# 表格噪声检查：PI 输出中含长正文的表格行数（cell>200字符）
noisy = 0
for line in pi.splitlines():
    if line.startswith("|") and len(line) > 300:
        noisy += 1
print(f"PI long table lines (>300ch, suspected over-tabularization): {noisy}")
