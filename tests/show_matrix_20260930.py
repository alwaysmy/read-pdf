# -*- coding: utf-8 -*-
"""矩阵结果汇总打印 + 空输出核查（2026-09-30）"""
import glob
import json
from pathlib import Path

OUT = Path(r"D:\MyProjects\AI\ChatSpace\TEST_RESULTS\read-pdf-bench_20260930")
j = sorted(OUT.glob("pdf_matrix_*.json"))[-1]
rows = json.loads(j.read_text(encoding="utf-8"))

hdr = f"{'tag':12} {'type':11} {'pi_ms':>7} {'pipe_s':>7} {'pi_chars':>8} {'fitz':>6} {'pi_tbl_rows':>11} {'pipe_tbl':>8} {'pipe_bytes':>10}"
print(hdr)
for r in rows:
    pi = r.get("pi") or {}
    pl = r.get("pipeline") or {}
    cls = r.get("classify") or {}
    print(f"{r['tag']:12} {str(cls.get('type')):11} "
          f"{str(r.get('process_reported_ms')):>7} {str(pl.get('wall_s')):>7} "
          f"{str(pi.get('md_chars')):>8} {str((r.get('fitz') or {}).get('text_chars')):>6} "
          f"{str(pi.get('md_tables')):>11} {str(pl.get('tables')):>8} {str(pl.get('size_bytes')):>10}")

print()
for tag in ["invoice", "form", "cad"]:
    fs = sorted(OUT.glob(f"pi_{tag}_*.md"))
    if fs:
        c = fs[-1].read_text(encoding="utf-8")
        print(f"--- {tag} PI md ({len(c)}ch): {c[:400]!r}")
        print()

# 逐页路由明细
print("=== OCR routes (classify) ===")
for r in rows:
    cls = r.get("classify") or {}
    routes = cls.get("pages_needing_ocr")
    if routes:
        print(f"  {r['tag']}: {routes[:10]}{'...' if len(routes) > 10 else ''}")
