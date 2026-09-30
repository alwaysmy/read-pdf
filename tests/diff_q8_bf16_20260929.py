# -*- coding: utf-8 -*-
"""BF16 vs Q8_0 逐页输出 diff（2026-09-29，量化质量验证）

BF16 批次时间戳 1713xx（17:13），Q8_0 批次 1844xx（18:44）。
"""
import difflib
import glob
import json
import re
from pathlib import Path

OUT_DIR = Path(r"D:\MyProjects\AI\ChatSpace\TEST_RESULTS\read-pdf-bench_20260929")
PAGES = [12, 13, 17, 20, 29, 34]
REPORT = []


def pick(pages_ts_range: dict, pno: int, lo: int, hi: int) -> str:
    cands = []
    for s in glob.glob(str(OUT_DIR / f"unlimited_p{pno}_*.md")):
        m = re.search(r"_(\d{6})\.md$", s)
        ts = int(m.group(1))
        if lo <= ts <= hi:
            cands.append((ts, s))
    if not cands:
        return ""
    return max(cands)[1]


lines_out = []
for pno in PAGES:
    bf16_path = pick(None, pno, 171300, 171400)
    q8_path = pick(None, pno, 184400, 184500)
    if not bf16_path or not q8_path:
        lines_out.append(f"p{pno}: MISSING bf16={bool(bf16_path)} q8={bool(q8_path)}")
        continue
    a = Path(bf16_path).read_text(encoding="utf-8")
    b = Path(q8_path).read_text(encoding="utf-8")
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    # 按行 diff 统计
    al, bl = a.splitlines(), b.splitlines()
    diff = list(difflib.unified_diff(al, bl, lineterm=""))
    changed = [l for l in diff if (l.startswith("+") or l.startswith("-"))
               and not l.startswith("+++") and not l.startswith("---")]
    lines_out.append(f"p{pno}: bf16={len(a)}ch q8={len(b)}ch ratio={ratio:.4f} changed_lines={len(changed)}")
    # 展示前几条差异（每行截断）
    for l in changed[:6]:
        lines_out.append(f"    {l[:160]}")

report = "\n".join(lines_out)
(OUT_DIR / "q8_vs_bf16_diff_20260929.txt").write_text(report, encoding="utf-8")
print(report)
print("SAVED:", OUT_DIR / "q8_vs_bf16_diff_20260929.txt")
