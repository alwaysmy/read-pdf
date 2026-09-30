# -*- coding: utf-8 -*-
"""pdf-inspector vs 现状文本层路径 多样本矩阵测试（2026-09-30，全 CPU）

覆盖：发票/表单/datasheet双栏/Xilinx技术文档/中文手册/中文报告/教程/CAD图纸/英文说明书/扫描件

每个样本：
  1. fitz 底数（页数、文本层 chars——判定 text/scanned/mixed）
  2. pdf_inspector.classify_pdf（type/confidence/耗时）
  3. pdf_inspector.process_pdf 前 N 页（markdown + processing_time_ms + 逐页路由）
  4. 现状管线：extract_pdf.py --pages 1-N（pdfmux+pymupdf+pdfplumber 全输出，计墙钟）
质量指标：覆盖率（相对 fitz 文本层）、乱码数、表格计数、速度

输出：TEST_RESULTS/read-pdf-bench_20260930/pdf_matrix_<ts>.json + 各样本输出 md
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
N_PAGES = 10

SAMPLES = [
    ("invoice", "电子发票", r"D:\MyProjects\EmoeR_D\财务\2026\开具发票\2026.9\dzfp_26112000004138720891_合肥鲸鱼微电子有限公司_20260929133512.pdf"),
    ("form", "离职证明表单", r"C:\Users\AlwaysTS\Desktop\fjl_lizhizhengming.pdf"),
    ("datasheet", "datasheet双栏(lm5177)", r"D:\MyProjects\2_MyDesigns\USB_RemoteControlHUB\3_Docs\refs\datasheets\lm5177.pdf"),
    ("datasheet2", "datasheet(sy8205)", r"D:\MyProjects\2_MyDesigns\USB_RemoteControlHUB\3_Docs\refs\datasheets\sy8205fcc.pdf"),
    ("xilinx", "Xilinx PG054英文", r"C:\Users\AlwaysTS\Desktop\技术资料\FPGA与数字电路\pg054-7series-pcie-2022.pdf"),
    ("scpi", "SCPI中文手册", r"D:\MyProjects\EmoeR_D\研发中项目\EmoeCalibrator\Calibrator_Agent_Dev\客户操作手册\EmoeCalibrator_SCPI操作手册.pdf"),
    ("report", "中文校准报告", r"D:\MyProjects\EmoeR_D\研发中项目\EmoeCalibrator\Calibrator_Agent_Dev\分段校准可行性报告\分段校准可行性分析报告.pdf"),
    ("tutorial", "Wireshark中文教程", r"C:\Users\AlwaysTS\Desktop\USB_Capture\Wireshark基本用法.pdf"),
    ("cad", "CAD图纸(矢量文字)", r"D:\MyProjects\AI\StructuralDesign\out\enclosure_drawing.pdf"),
    ("manual_en", "ITECH英文说明书", r"D:\MyProjects\2_MyDesigns\1夹具冶具延长线转接板测试架\IT6100_USB_TTL_DB9\IT6122调研文档和通信接口\IT6122_Conn\5_docs\ITECH_IT8500plus_User_Guide2.pdf"),
    ("scan_book", "扫描书(微弱信号)", r"D:\llm\_archive\08_doc-processing\test_data\微弱信号检测_高晋占编著_清华大学出版社_2019_第3版.pdf"),
    ("scan_letter", "扫描信件(1958)", r"D:\llm\_archive\08_doc-processing\test_data\1958-05-27 Joan to Sid.pdf"),
]


def fitz_probe(path: str, n: int):
    doc = fitz.open(path)
    total = len(doc)
    take = min(n, total)
    chars = 0
    for i in range(take):
        chars += len(doc[i].get_text().strip())
    doc.close()
    return {"pages": total, "probed": take, "text_chars": chars}


def quality_metrics(md: str, ref_chars: int):
    stripped = re.sub(r"\s", "", md or "")
    return {
        "md_chars": len(md or ""),
        "md_chars_nospace": len(stripped),
        "coverage_vs_fitz": round(len(stripped) / ref_chars, 3) if ref_chars else None,
        "replacement_char": (md or "").count("\ufffd"),
        "md_tables": len(re.findall(r"^\|.*\|", md or "", re.M)),
        "has_pdfmux_section": False,
    }


def run_pipeline(path: str, n: int) -> dict:
    """现状管线 extract_pdf --pages 1-N（文本层分支），返回墙钟与输出统计"""
    pages = f"1-{n}"
    t0 = time.time()
    p = subprocess.run(
        [sys.executable, str(EXTRACT), path, "--pages", pages, "--output-dir", str(OUT_DIR)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
    )
    wall = time.time() - t0
    out = p.stdout or ""
    m = re.search(r"DONE: (\d+) bytes, (\d+) tables\s+\|\s+(.+)", out)
    stats = {"wall_s": round(wall, 2)}
    if m:
        stats["size_bytes"] = int(m.group(1))
        stats["tables"] = int(m.group(2))
        stats["out_path"] = m.group(3).strip()
        # 读输出：分段统计
        try:
            content = Path(stats["out_path"]).read_text(encoding="utf-8")
            stats["pymupdf_pages_markers"] = len(re.findall(r"<!-- PAGE \d+ -->", content))
            pdfmux_sec = ""
            mm = re.search(r"<!-- PDFMUX OUTPUT.*?-->\n(.*?)\n\n<!-- PYMUPDF", content, re.S)
            if mm:
                pdfmux_sec = mm.group(1)
            stats["pdfmux_section_chars"] = len(pdfmux_sec)
            stats["pdfmux_tables"] = len(re.findall(r"^\|.*\|", pdfmux_sec, re.M))
            stats["replacement_char"] = content.count("\ufffd")
        except Exception as e:
            stats["read_error"] = str(e)
    else:
        stats["error"] = (p.stderr or "")[-300:]
        stats["stdout_tail"] = out[-300:]
    return stats


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    results = []

    for tag, label, path in SAMPLES:
        if not Path(path).exists():
            results.append({"tag": tag, "label": label, "path": path, "error": "missing"})
            print(f"[{tag}] MISSING")
            continue
        row = {"tag": tag, "label": label, "path": path}
        try:
            # 1) fitz 底数
            probe = fitz_probe(path, N_PAGES)
            row["fitz"] = probe
            n = probe["probed"]

            # 2) classify
            t0 = time.time()
            cls = pdf_inspector.classify_pdf(path)
            row["classify"] = {
                "type": cls.pdf_type, "confidence": round(cls.confidence, 3),
                "pages": cls.page_count, "s": round(time.time() - t0, 2),
                "pages_needing_ocr": list(cls.pages_needing_ocr),
            }

            # 3) process 前 N 页
            t0 = time.time()
            res = pdf_inspector.process_pdf(path, pages=list(range(n)))
            row["process_wall_s"] = round(time.time() - t0, 2)
            md = res.markdown or ""
            row["process_reported_ms"] = res.processing_time_ms
            row["pi"] = quality_metrics(md, probe["text_chars"])
            row["pi"]["pages_needing_ocr"] = list(res.pages_needing_ocr)
            row["pi"]["ocr_reasons"] = [
                {"page": p.page, "reasons": list(p.reasons)} for p in res.ocr_reasons_by_page
            ]
            row["pi"]["cmap_gaps"] = len(res.cmap_gaps)
            row["pi"]["has_encoding_issues"] = bool(res.has_encoding_issues)
            # 保存 PI 输出
            pi_md = OUT_DIR / f"pi_{tag}_{ts}.md"
            pi_md.write_text(md, encoding="utf-8")

            # 4) 现状管线
            row["pipeline"] = run_pipeline(path, n)
        except Exception as e:
            row["error"] = f"{type(e).__name__}: {e}"
        results.append(row)
        # 实时落盘（防中断丢失）
        (OUT_DIR / f"pdf_matrix_{ts}.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        pi = row.get("pi", {})
        pl = row.get("pipeline", {})
        print(
            f"[{tag}] {label} | fitz={row.get('fitz', {}).get('text_chars')}ch "
            f"| cls={row.get('classify', {}).get('type')}/{row.get('classify', {}).get('s')}s "
            f"| PI: cov={pi.get('coverage_vs_fitz')} tbl={pi.get('md_tables')} "
            f"| pipe: {pl.get('wall_s')}s tbl={pl.get('tables')} "
            f"| {'ERR ' + str(row.get('error'))[:80] if row.get('error') else 'ok'}",
            flush=True,
        )

    print(f"SAVED: {OUT_DIR / f'pdf_matrix_{ts}.json'}")


if __name__ == "__main__":
    main()
