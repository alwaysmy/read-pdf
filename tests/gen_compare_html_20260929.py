# -*- coding: utf-8 -*-
"""生成四引擎对比 HTML（原页 PNG + unlimited/hybrid/glm/dsocr 并排，2026-09-29）"""
from pathlib import Path
import html as html_mod

OUT_DIR = Path(r"D:\MyProjects\AI\ChatSpace\TEST_RESULTS\read-pdf-bench_20260929")
PAGES = [12, 13, 17, 20, 29, 34]
ENGINES = ["unlimited", "hybrid", "glm", "dsocr"]

COLORS = {"unlimited": "#e3f2fd", "hybrid": "#e8f5e9", "glm": "#fff3e0", "dsocr": "#fce4ec"}


def extract_page(md_text: str, page: int) -> str:
    """从引擎 md 中切出指定页（分页标记可能不同格式）"""
    markers = [f"<!-- PAGE {page} -->", f"<!-- PAGE {page} -->\n", f"## Page {page}", f"### Page {page}"]
    # 通用：按 <!-- PAGE n --> 切
    import re
    parts = re.split(r"<!--\s*PAGE\s+(\d+)\s*-->", md_text)
    # parts: [前言, num1, body1, num2, body2, ...]
    if len(parts) > 1:
        for i in range(1, len(parts), 2):
            if int(parts[i]) == page:
                return parts[i + 1].strip()
        return "PAGE NOT FOUND"
    return md_text.strip()


def main():
    engines_md = {}
    for eng in ENGINES:
        p = OUT_DIR / f"compare_{eng}.md"
        engines_md[eng] = p.read_text(encoding="utf-8") if p.exists() else ""

    sections = []
    for page in PAGES:
        cells = []
        img = OUT_DIR / "sample_pages" / f"p{page}.png"
        if not img.exists():
            # 渲染一份
            import fitz
            doc = fitz.open(r"D:\llm\_archive\08_doc-processing\test_data\微弱信号检测_高晋占编著_清华大学出版社_2019_第3版.pdf")
            img.parent.mkdir(parents=True, exist_ok=True)
            doc[page - 1].get_pixmap(dpi=150).save(img)
            doc.close()
        cells.append(
            f'<div class="cell orig"><h3>原页 p{page}</h3>'
            f'<a href="sample_pages/p{page}.png" target="_blank"><img src="sample_pages/p{page}.png"></a></div>'
        )
        for eng in ENGINES:
            body = extract_page(engines_md[eng], page)
            body_html = html_mod.escape(body)
            cells.append(
                f'<div class="cell" style="background:{COLORS[eng]}"><h3>{eng}</h3>'
                f'<pre>{body_html}</pre></div>'
            )
        sections.append((page, f'<section><h2>Page {page}</h2><div class="grid">{"".join(cells)}</div></section>'))

    def build(page_sections, title_suffix=""):
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>四引擎对比 20260929{title_suffix}</title>
<style>
body{{font-family:system-ui,sans-serif;margin:16px}}
.grid{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;align-items:start}}
.cell{{border:1px solid #999;border-radius:6px;padding:6px;min-width:0}}
.cell h3{{margin:2px 0 6px;font-size:14px;text-align:center}}
.cell img{{width:100%;height:auto}}
.cell pre{{white-space:pre-wrap;word-break:break-all;font-size:11px;line-height:1.45;margin:0;
  max-height:75vh;overflow-y:auto}}
section{{margin-bottom:36px}}
h2{{font-size:18px;border-bottom:2px solid #333}}
</style></head><body>
<h1>四引擎对比（微弱信号检测教材，150dpi）— 2026-09-29</h1>
{"".join(s for _, s in page_sections)}
</body></html>"""

    out = OUT_DIR / "compare_engines.html"
    out.write_text(build(sections), encoding="utf-8")
    print(f"SAVED: {out}")

    # 每页单独文件（浏览器逐页截图用）
    for page, sec in sections:
        single = OUT_DIR / f"compare_p{page}.html"
        single.write_text(build([(page, sec)], f" p{page}"), encoding="utf-8")
        print(f"SAVED: {single}")


if __name__ == "__main__":
    main()
