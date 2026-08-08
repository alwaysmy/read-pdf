"""删除 extract_pdf.py 中的死代码 http_extract_text_first（重构后零调用）."""
import pathlib

p = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "extract_pdf.py"
text = p.read_text(encoding="utf-8")

start = text.index("def http_extract_text_first(")
# 找到前一个空行，保留 extract_glm 结尾
end_marker = "def extract_dsocr("
end = text.index(end_marker)
# 删除从 start 到 extract_dsocr 前的空行
removed = text[start:end]
# 去掉残留的多余空行（保留 2 个换行）
text = text[:start].rstrip() + "\n\n\n" + text[end:]
p.write_text(text, encoding="utf-8")
print(f"已删除 {len(removed)} 字符（http_extract_text_first 死代码）")

import subprocess, sys
r = subprocess.run([sys.executable, "-m", "py_compile", str(p)], capture_output=True, text=True)
print("py_compile:", "OK" if r.returncode == 0 else r.stderr[-300:])
