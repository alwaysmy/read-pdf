# -*- coding: utf-8 -*-
"""拼接 Unlimited-OCR 每页输出为单文件（按页序，取每页最新一次生成）"""
from pathlib import Path
import glob
import re

OUT_DIR = Path(r"D:\MyProjects\AI\ChatSpace\TEST_RESULTS\read-pdf-bench_20260929")
PAGES = [12, 13, 17, 20, 29, 34]

parts = []
for pno in PAGES:
    cands = glob.glob(str(OUT_DIR / f"unlimited_p{pno}_*.md"))
    if not cands:
        print(f"MISSING p{pno}")
        continue
    # 文件名含 HHMMSS，取最大（最新）
    latest = max(cands, key=lambda s: int(re.search(r"_(\d{6})\.md$", s).group(1)))
    text = Path(latest).read_text(encoding="utf-8")
    parts.append(f"<!-- PAGE {pno} -->\n\n{text}")
    print(f"p{pno}: {Path(latest).name} {len(text)} chars")

out = OUT_DIR / "compare_unlimited.md"
out.write_text("\n\n---\n\n".join(parts), encoding="utf-8")
print(f"SAVED: {out}")
