"""Split each engine compare markdown into per-page segments.

Mirrors extract_page() of tests/gen_compare_html_20260929.py (the exact script
that produced the compared HTML pages, so segments == what each screenshot
column rendered).

Output: tests/page_seg_<timestamp>/p<page>__<engine>.md
"""
import re
import time
from pathlib import Path

OUT_DIR = Path(r"D:\MyProjects\AI\ChatSpace\TEST_RESULTS\read-pdf-bench_20260929")
PAGES = [12, 13, 17, 20, 29, 34]
ENGINES = ["unlimited", "hybrid", "glm", "dsocr"]


def extract_page(md_text: str, page: int) -> str:
    parts = re.split(r"<!--\s*PAGE\s+(\d+)\s*-->", md_text)
    if len(parts) > 1:
        for i in range(1, len(parts), 2):
            if int(parts[i]) == page:
                return parts[i + 1].strip()
        return "PAGE NOT FOUND"
    return md_text.strip()


def main():
    ts = time.strftime("%Y%m%d_%H%M%S")
    dest = Path(__file__).with_name(f"page_seg_{ts}")
    dest.mkdir(exist_ok=True)
    for eng in ENGINES:
        p = OUT_DIR / f"compare_{eng}.md"
        text = p.read_text(encoding="utf-8") if p.exists() else ""
        total = len(text)
        for page in PAGES:
            seg = extract_page(text, page) if text else "(empty md)"
            (dest / f"p{page}__{eng}.md").write_text(seg, encoding="utf-8")
        print(f"{eng}: md_total_chars={total}")
    print(f"written: {dest}")


if __name__ == "__main__":
    main()
