# -*- coding: utf-8 -*-
"""第二批穷尽矩阵测试（2026-09-30，全 CPU）——补齐：LaTeX双栏论文/千页大书×2/旋转页/
owner加密/user加密(不可读)/双语混排/跨页续表手册/大扫描书

输出：TEST_RESULTS/read-pdf-bench_20260930/pdf_matrix2_<ts>.json
"""
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import fitz
import pdf_inspector

OUT_DIR = Path(r"D:\MyProjects\AI\ChatSpace\TEST_RESULTS\read-pdf-bench_20260930")
EXTRACT = Path(r"D:\MyProjects\AGENT方法库\skills\read-pdf\scripts\extract_pdf.py")

# (tag, label, path, pages)  pages: 0-based 页段
SAMPLES = [
    ("arxiv", "arXiv双栏LaTeX论文",
     str(OUT_DIR / "arxiv_1706.03762.pdf"), list(range(8))),
    ("big_davinci", "千页大书DaVinci(4234p)",
     r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Documents\DaVinci Resolve.pdf",
     list(range(10))),
    ("big_a320", "千页大书A320 FCOM(8138p,中段)",
     r"E:\手册与技术支持\设备资料与文档\A320操作手册\A320 FCOM 中文版__2012.09.13.pdf",
     list(range(99, 109))),
    ("rotate", "旋转页(90/180/270)",
     str(OUT_DIR / "synth_rotate_20260930.pdf"), list(range(6))),
    ("enc_owner", "加密owner-only(免密可读)",
     str(OUT_DIR / "synth_enc_owner_20260930.pdf"), list(range(6))),
    ("enc_user", "加密user-pw(不可读)",
     str(OUT_DIR / "synth_enc_user_20260930.pdf"), list(range(6))),
    ("bilingual", "双语混排(中英交替12p)",
     str(OUT_DIR / "synth_bilingual_20260930.pdf"), list(range(12))),
    ("table_book", "跨页续表(2023器件大手册)",
     r"D:\MyProjects\6_Works\JWS_ce8\1、输入文件\器件手册0218\2023大手册.pdf",
     list(range(10))),
    ("scan_opamp", "大扫描书(运算放大器198p)",
     r"C:\Users\AlwaysTS\Desktop\技术资料\模拟电路\运算放大器参数解析与LTspice应用仿真.pdf",
     list(range(10))),
]


def fitz_probe(path: str, pages):
    try:
        doc = fitz.open(path)
    except Exception as e:
        return {"error": f"open: {type(e).__name__}: {e}"}
    info = {"pages": len(doc), "needs_pass": bool(doc.needs_pass)}
    if doc.needs_pass:
        doc.close()
        return info
    chars = 0
    ok_pages = 0
    try:
        for i in pages:
            if i < len(doc):
                chars += len(doc[i].get_text().strip())
                ok_pages += 1
    except Exception as e:
        info["text_error"] = str(e)
    info.update({"probed": ok_pages, "text_chars": chars})
    doc.close()
    return info


def quality_metrics(md: str, ref_chars: int):
    stripped = re.sub(r"\s", "", md or "")
    return {
        "md_chars": len(md or ""),
        "coverage_vs_fitz": round(len(stripped) / ref_chars, 3) if ref_chars else None,
        "replacement_char": (md or "").count("\ufffd"),
        "md_table_rows": len(re.findall(r"^\|.*\|", md or "", re.M)),
    }


def run_pipeline(path: str, pages) -> dict:
    page_arg = ",".join(str(p + 1) for p in pages) if len(pages) <= 12 else \
        f"{pages[0]+1}-{pages[-1]+1}"
    t0 = time.time()
    try:
        p = subprocess.run(
            [sys.executable, str(EXTRACT), path, "--pages", page_arg,
             "--output-dir", str(OUT_DIR)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
        )
    except subprocess.TimeoutExpired:
        return {"wall_s": round(time.time() - t0, 1), "error": "timeout 900s"}
    wall = time.time() - t0
    out = p.stdout or ""
    stats = {"wall_s": round(wall, 2)}
    m = re.search(r"DONE: (\d+) bytes, (\d+) tables\s+\|\s+(.+)", out)
    if m:
        stats["size_bytes"] = int(m.group(1))
        stats["tables"] = int(m.group(2))
        stats["out_path"] = m.group(3).strip()
        try:
            content = Path(stats["out_path"]).read_text(encoding="utf-8")
            stats["page_markers"] = len(re.findall(r"<!-- PAGE \d+ -->", content))
            stats["replacement_char"] = content.count("\ufffd")
        except Exception as e:
            stats["read_error"] = str(e)
    else:
        stats["error"] = (p.stderr or out or "")[-400:]
    return stats


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    results = []

    for tag, label, path, pages in SAMPLES:
        if not Path(path).exists():
            results.append({"tag": tag, "label": label, "path": path, "error": "missing"})
            print(f"[{tag}] MISSING", flush=True)
            continue
        row = {"tag": tag, "label": label, "path": path,
               "pages0": [pages[0], pages[-1]]}
        try:
            # 1) fitz 底数
            row["fitz"] = fitz_probe(path, pages)
            if row["fitz"].get("needs_pass"):
                print(f"[{tag}] {label} | needs_pass=True（fitz 拒绝）", flush=True)

            # 2) classify（大书全量扫描耗时=实测点）
            t0 = time.time()
            try:
                cls = pdf_inspector.classify_pdf(path)
                row["classify"] = {"type": cls.pdf_type,
                                   "confidence": round(cls.confidence, 3),
                                   "pages": cls.page_count,
                                   "s": round(time.time() - t0, 2),
                                   "pages_needing_ocr": list(cls.pages_needing_ocr)[:20]}
            except Exception as e:
                row["classify"] = {"error": f"{type(e).__name__}: {e}",
                                   "s": round(time.time() - t0, 2)}

            # 3) process
            t0 = time.time()
            try:
                res = pdf_inspector.process_pdf(path, pages=pages)
                row["process_wall_s"] = round(time.time() - t0, 2)
                md = res.markdown or ""
                ref = (row["fitz"] or {}).get("text_chars") or 0
                row["pi"] = quality_metrics(md, ref)
                row["pi"]["process_reported_ms"] = res.processing_time_ms
                row["pi"]["routes"] = [(p.page, list(p.reasons))
                                       for p in res.ocr_reasons_by_page][:15]
                (OUT_DIR / f"pi2_{tag}_{ts}.md").write_text(md, encoding="utf-8")
            except Exception as e:
                row["pi"] = {"error": f"{type(e).__name__}: {e}",
                             "wall_s": round(time.time() - t0, 2)}

            # 4) 现状管线
            row["pipeline"] = run_pipeline(path, pages)
        except Exception as e:
            row["error"] = f"{type(e).__name__}: {e}"
        results.append(row)
        (OUT_DIR / f"pdf_matrix2_{ts}.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

        pi = row.get("pi") or {}
        pl = row.get("pipeline") or {}
        cl = row.get("classify") or {}
        print(f"[{tag}] {label} | cls={cl.get('type')}/{cl.get('s')}s "
              f"| PI: chars={pi.get('md_chars')} cov={pi.get('coverage_vs_fitz')} "
              f"err={str(pi.get('error'))[:60]} "
              f"| pipe: {pl.get('wall_s')}s bytes={pl.get('size_bytes')} "
              f"err={str(pl.get('error'))[:60]}", flush=True)

    print(f"SAVED: {OUT_DIR / f'pdf_matrix2_{ts}.json'}")


if __name__ == "__main__":
    main()
