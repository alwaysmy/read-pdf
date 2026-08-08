"""删除 extract_pdf.py 中的死代码 http_extract（重构后零调用）."""
import pathlib

p = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "extract_pdf.py"
text = p.read_text(encoding="utf-8")

# 定位 http_extract 定义到 _engines_call 定义之间（含注释块）
start = text.index("def http_extract(port")
# 包含前面的注释块
block_start = text.rfind("# ---", 0, start)
if block_start != -1 and text[block_start:start].count("\n") <= 4:
    start = block_start
end = text.index("def _engines_call(")

removed = text[start:end]
text = text[:start] + text[end:]
p.write_text(text, encoding="utf-8")
print(f"已删除 {len(removed)} 字符（http_extract 死代码 + 注释块）")

# 校验
import subprocess, sys
r = subprocess.run([sys.executable, "-m", "py_compile", str(p)], capture_output=True, text=True)
print("py_compile:", "OK" if r.returncode == 0 else r.stderr[-300:])
