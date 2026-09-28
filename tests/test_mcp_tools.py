"""MCP server 工具函数验证（直接调函数，不经 MCP 协议）.
前置: 本体服务需在运行（scripts/server.py）。
用法: python tests/test_mcp_tools.py

测试素材来源：
  1. 文本页 —— 运行时用 PyMuPDF 现生成一个，无需外部文件；
  2. 扫描页（版面检测用）—— 真实扫描件无法现造，用环境变量
     `READPDF_TEST_SCAN_PDF` 指定；未提供则**跳过该步**并明确标注，不算失败。
"""
import os
import pathlib
import sys
import tempfile

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))


def make_text_pdf() -> str:
    """生成一个最小文本层 PDF，使 extract 路径可脱离外部素材自测.

    注意页均字符数必须 >100 —— `extract_pdf.py` 用 `avg_chars < 100` 判定是否为
    扫描件；字符太少会被正当地当成扫描页而转走 OCR 引擎（进而要求启动 llama-server）。
    """
    import fitz

    path = pathlib.Path(tempfile.mkdtemp(prefix="readpdf_test_")) / "sample_text.pdf"
    lines = [
        "read-pdf MCP self-test page.",
        "This page carries a real text layer, so it must be handled by the",
        "text engine rather than OCR. The detection heuristic in extract_pdf.py",
        "treats a page as scanned when it averages fewer than 100 characters,",
        "so this fixture deliberately inserts well over that threshold.",
        "The quick brown fox jumps over the lazy dog. 0123456789.",
    ]
    doc = fitz.open()
    page = doc.new_page()
    for i, line in enumerate(lines):
        page.insert_text((72, 100 + i * 22), line, fontsize=11)
    doc.save(str(path))
    doc.close()
    return str(path)


def main():
    # 0. mcp SDK 可用性
    try:
        import mcp  # noqa: F401
        print("0. mcp SDK OK")
    except ImportError as e:
        print(f"0. mcp SDK 不可用（将走降级路径）: {e}")

    import mcp_server

    # 1. list_engines
    r = mcp_server.list_engines()
    names = [e["name"] for e in r.get("engines", [])]
    print("1. list_engines:", names)
    assert names, "list_engines 未返回引擎"

    # 2. extract_pdf（文本层）
    text_pdf = os.environ.get("READPDF_TEST_TEXT_PDF") or make_text_pdf()
    r = mcp_server.extract_pdf(text_pdf, pages="1")
    print(f"2. extract_pdf: status={r.get('status')} output={r.get('output')} "
          f"size={r.get('size_bytes')} tables={r.get('tables')}")
    assert r.get("status") == "ok", f"extract 失败: {r}"
    assert r.get("size_bytes", 0) > 0, f"size_bytes 缺失: {r}"

    # 3. layout_pdf（需真实扫描件，缺失则跳过）
    scan_pdf = os.environ.get("READPDF_TEST_SCAN_PDF", "")
    if scan_pdf and os.path.exists(scan_pdf):
        r = mcp_server.layout_pdf(scan_pdf, pages="1", device="cpu")
        print(f"3. layout_pdf: status={r.get('status')} blocks={r.get('blocks')} "
              f"crops={r.get('crops')} json={r.get('layout_json')}")
        assert r.get("status") == "ok", f"layout 失败: {r}"
        assert r.get("blocks", 0) > 0, f"blocks 缺失: {r}"
        assert r.get("layout_json"), f"layout_json 缺失: {r}"
    else:
        print("3. layout_pdf: SKIP（未提供 READPDF_TEST_SCAN_PDF，或文件不存在）")

    # 4. 错误路径（不存在的 pdf）
    r = mcp_server.extract_pdf("Z:/nonexistent.pdf")
    print(f"4. 错误路径: {r}")
    assert "error" in r, "应返回错误"

    print("\nMCP 工具函数全部通过 ✅")


if __name__ == "__main__":
    main()
