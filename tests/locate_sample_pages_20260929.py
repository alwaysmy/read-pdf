# -*- coding: utf-8 -*-
"""定位对比用样本页（2026-09-29）

在微弱信号检测教材中定位：
- 目录页（TOC）：含"目录"/"目 录"大字
- 分栏页：words x 坐标呈双峰（左右两栏）
- 表格/公式页：含表格线/公式符号密集

输出：TEST_RESULTS/read-pdf-bench_20260929/sample_pages_<ts>.json + 各页 PNG
"""
import json
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import fitz

PDF = Path(r"D:\llm\_archive\08_doc-processing\test_data\微弱信号检测_高晋占编著_清华大学出版社_2019_第3版.pdf")
OUT_DIR = Path(r"D:\MyProjects\AI\ChatSpace\TEST_RESULTS\read-pdf-bench_20260929")
SAMPLE_DIR = OUT_DIR / "sample_pages"

MATH_SYMBOLS = set("∑∫√≤≥≈≠±×÷∞αβγδεζηθλμσφψωΩ∂∇")


def classify_page(doc, pno):
    """返回该页的特征标签列表"""
    page = doc[pno]
    labels = []
    text = page.get_text()
    # 目录页
    if re.search(r"^\s*目\s*录\s*$", text, re.M) or re.search(r"^Contents\s*$", text, re.M | re.I):
        labels.append("toc_head")
    # 目录条目特征：多行 "章名 .... 页码" 结尾数字 + 大量点线
    toc_dots = text.count("......") + text.count("…") + len(re.findall(r"[^\s]\s*\.{3,}\s*\d+", text))
    if toc_dots >= 5:
        labels.append("toc_entries")
    # 分栏：words x 分布双峰
    words = page.get_text("words")  # x0,y0,x1,y1,word,...
    if len(words) > 80:
        xs = sorted(w[0] for w in words)
        mid = xs[len(xs) // 2]
        left = [x for x in xs if x < mid]
        right = [x for x in xs if x >= mid]
        # 左右簇内部紧凑 + 中间有明显空隙
        gap_center = page.rect.width * 0.5
        in_gap = sum(1 for x in xs if gap_center - 20 < x < gap_center + 20)
        density_ratio = 0
        if len(left) > 40 and len(right) > 40:
            # 统计 x 落在中缝 40px 内的比例（单栏页中缝也有字，双栏页接近 0）
            density_ratio = in_gap / len(xs)
        if density_ratio < 0.05 and len(left) > 60 and len(right) > 60:
            # 进一步验证两簇重心距离远
            lc = sum(left) / len(left)
            rc = sum(right) / len(right)
            if rc - lc > page.rect.width * 0.35:
                labels.append("two_column")
    # 表格：横线多 或 输出习惯（检测绘图线）
    drawings = page.get_drawings()
    hlines = 0
    for d in drawings:
        for item in d["items"]:
            if item[0] == "l":  # line
                p1, p2 = item[1], item[2]
                if abs(p1.y - p2.y) < 1 and abs(p1.x - p2.x) > page.rect.width * 0.2:
                    hlines += 1
    if hlines >= 4:
        labels.append("table_lines")
    # 公式：math 符号密度 或 行内分数/上下标特征
    math_cnt = sum(text.count(s) for s in MATH_SYMBOLS)
    if math_cnt >= 6:
        labels.append("math_symbols")
    # 章节首页
    if re.search(r"^\s*第\s*[0-9一二三四五六七八九十]+\s*章", text, re.M):
        labels.append("chapter_head")
    return labels


def main():
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(PDF)
    found = {}
    t0 = time.time()
    for pno in range(1, min(len(doc), 60) + 1):  # 前 60 页足够覆盖目录/前几章
        labels = classify_page(doc, pno)
        if labels:
            found[pno] = labels
    print(f"scanned 1..{min(len(doc),60)} in {time.time()-t0:.1f}s")

    # 每类选 1-2 个代表页，渲染 PNG
    picks = {}
    for want in ["toc_head", "toc_entries", "two_column", "table_lines", "math_symbols", "chapter_head"]:
        cand = [p for p, ls in found.items() if want in ls]
        picks[want] = cand[:2]

    selected = sorted({p for v in picks.values() for p in v})
    for pno in selected:
        pix = doc[pno - 1].get_pixmap(dpi=150)
        pix.save(SAMPLE_DIR / f"p{pno}.png")
    doc.close()

    out = {"ts": datetime.now().strftime("%Y%m%d_%H%M%S"),
           "pdf": str(PDF),
           "picks": picks,
           "all_found": {str(k): v for k, v in sorted(found.items())},
           "selected": selected}
    out_path = OUT_DIR / f"sample_pages_{out['ts']}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PICKS:")
    for k, v in picks.items():
        print(f"  {k}: {v}")
    print(f"SAVED: {out_path}")


if __name__ == "__main__":
    main()
