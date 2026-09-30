# -*- coding: utf-8 -*-
"""pdf-inspector 文本层接入测试（2026-09-29）

1. classify_pdf：文本层/扫描件分类判定
2. process_pdf：前 15 页 markdown + 耗时（vs extract_pdf 的 pdfmux/pdfplumber 路径）
输出：TEST_RESULTS/read-pdf-bench_20260929/pdfinspector_<ts>.json + md
"""
import json
import time
from datetime import datetime
from pathlib import Path

import pdf_inspector

TEXT_PDF = r"D:\MyProjects\6_Works\hd1\器件手册\连接器选型和定义\5 高速数据传输系列连接器选型手册.pdf"
SCAN_PDF = r"D:\llm\_archive\08_doc-processing\test_data\微弱信号检测_高晋占编著_清华大学出版社_2019_第3版.pdf"
OUT_DIR = Path(r"D:\MyProjects\AI\ChatSpace\TEST_RESULTS\read-pdf-bench_20260929")
PAGES = list(range(15))  # 前 15 页


def jdump(obj):
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)[:2000]
    except Exception as e:
        return f"<{e}>"


def main():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = {"ts": ts, "pages": PAGES}

    # 1. classify
    for tag, pdf in [("text", TEXT_PDF), ("scan", SCAN_PDF)]:
        t0 = time.time()
        try:
            cls = pdf_inspector.classify_pdf(pdf)
            report[f"classify_{tag}"] = {"elapsed_s": round(time.time() - t0, 3), "result": jdump(cls)}
            print(f"classify {tag}: {time.time()-t0:.3f}s -> {str(cls)[:300]}")
        except Exception as e:
            report[f"classify_{tag}"] = {"error": str(e)}
            print(f"classify {tag} FAILED: {e}")

    # 2. process_pdf（文本层样本前 15 页）
    t0 = time.time()
    res = pdf_inspector.process_pdf(TEXT_PDF, pages=PAGES)
    elapsed = time.time() - t0
    print(f"process_pdf: {elapsed:.3f}s")
    report["process_elapsed_s"] = round(elapsed, 3)

    # 结果结构探测
    print("type:", type(res))
    if hasattr(res, "__dict__"):
        print("fields:", list(vars(res).keys()))
    md_all = []
    if isinstance(res, dict):
        print("keys:", list(res.keys()))
    # 尝试通用取 markdown
    def collect_md(r):
        if r is None:
            return []
        if isinstance(r, str):
            return [r]
        if hasattr(r, "markdown") and r.markdown:
            return [r.markdown]
        if isinstance(r, dict):
            if "markdown" in r and isinstance(r["markdown"], str):
                return [r["markdown"]]
            out = []
            for v in r.values():
                out.extend(collect_md(v))
            return out
        if hasattr(r, "__dict__"):
            out = []
            for v in vars(r).values():
                out.extend(collect_md(v))
            return out
        if isinstance(r, (list, tuple)):
            out = []
            for v in r:
                out.extend(collect_md(v))
            return out
        return []

    mds = collect_md(res)
    print(f"collected md fragments: {len(mds)}, total chars: {sum(len(m) for m in mds)}")
    out_md = OUT_DIR / f"pdfinspector_text_{ts}.md"
    out_md.write_text("\n\n".join(mds), encoding="utf-8")
    print(f"SAVED: {out_md}")

    report["md_fragments"] = len(mds)
    report["md_chars"] = sum(len(m) for m in mds)
    report["result_repr"] = jdump(res)
    out_json = OUT_DIR / f"pdfinspector_{ts}.json"
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"SAVED: {out_json}")


if __name__ == "__main__":
    main()
