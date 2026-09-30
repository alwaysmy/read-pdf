# -*- coding: utf-8 -*-
"""第二批结果深挖（2026-09-30）：
A. 现状管线失败样本的错误详情（A320 / scan_opamp / enc_user）
B. arXiv 双栏 PI cov=0.784 抽查——PI 是否漏右侧栏/公式
C. 旋转页 cov=0.748 抽查
"""
import glob
import json
import re
from pathlib import Path

OUT = Path(r"D:\MyProjects\AI\ChatSpace\TEST_RESULTS\read-pdf-bench_20260930")
j = sorted(OUT.glob("pdf_matrix2_*.json"))[-1]
rows = {r["tag"]: r for r in json.loads(j.read_text(encoding="utf-8"))}

# ---- A. 管线错误详情 ----
print("=" * 30, "A. pipeline errors", "=" * 30)
for tag in ["big_a320", "scan_opamp", "enc_user", "enc_owner"]:
    pl = rows.get(tag, {}).get("pipeline") or {}
    err = pl.get("error", "")
    # 去掉噪声路径，抓 traceback 关键行
    key = [l for l in err.splitlines() if "Error" in l or "error" in l or "raise" in l]
    print(f"[{tag}] wall={pl.get('wall_s')}s bytes={pl.get('size_bytes')}")
    for l in key[-4:]:
        print(f"    {l.strip()[:160]}")

# ---- B. arXiv 双栏抽查 ----
print("=" * 30, "B. arxiv bilingual-column check", "=" * 30)
pi_ar = sorted(OUT.glob("pi2_arxiv_*.md"))[-1].read_text(encoding="utf-8")
pl_ar = Path(rows["arxiv"]["pipeline"]["out_path"]).read_text(encoding="utf-8")
# arXiv 论文特征短语（两栏内容都要有）
PHRASES = [
    "Attention is all you need",
    "Scaled Dot-Product Attention",
    "Multi-Head Attention",
    "Recurrent Neural Networks",
    "Transformer",
    "The Transformer follows",
    "encoder and decoder",
    "position-wise feed-forward",
    "Residual Dropout",
    "Label Smoothing",
    "WMT 2014 English-German",
    "BLEU",
    "beam search",
    "ablation studies",
]


def norm(s):
    return re.sub(r"\s", "", s)


a, b = norm(pi_ar), norm(pl_ar)
hp = hq = 0
for p in PHRASES:
    x, y = norm(p) in a, norm(p) in b
    hp += x
    hq += y
    if x != y:
        print(f"  DIFF {p!r}: PI={'Y' if x else '-'} PIPE={'Y' if y else '-'}")
print(f"phrase hits: PI={hp}/{len(PHRASES)} PIPE={hq}/{len(PHRASES)}")
# PI 是否只出了一栏：检查后半关键词
print(f"PI chars={len(pi_ar)} PIPE chars={len(pl_ar)}")

# ---- C. 旋转页抽查 ----
print("=" * 30, "C. rotate check", "=" * 30)
pi_rt = sorted(OUT.glob("pi2_rotate_*.md"))[-1].read_text(encoding="utf-8")
pl_rt = Path(rows["rotate"]["pipeline"]["out_path"]).read_text(encoding="utf-8")
for p in ["SCPI", "发送", ":SOUR", "测量"]:
    print(f"  {p!r}: PI={norm(p) in norm(pi_rt)} PIPE={norm(p) in norm(pl_rt)}")
print(f"PI chars={len(pi_rt)} (rot pages 90/180/270 in first 3)")
print("PI head:", repr(pi_rt[:200]))
