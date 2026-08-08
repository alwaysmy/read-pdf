"""MCP server 工具函数验证（直接调函数，不经 MCP 协议）.
前置: 本体服务需在运行（scripts/server.py）。
用法: python tests/test_mcp_tools.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

TEXT_PDF = r"D:\MyProjects\6_Works\hd1\器件手册\连接器选型和定义\5 高速数据传输系列连接器选型手册.pdf"
SCAN_PDF = r"D:\MyProjects\整理中\文件整理工作所有的没整理文件都放在这里好了\202404\数字电子技术基础·系统方法--高清版 弗洛伊德 (Thomas L.Floyd)、 娄淑琴.pdf"


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

    # 2. extract_pdf（文本 PDF 1-2 页）
    r = mcp_server.extract_pdf(TEXT_PDF, pages="1-2")
    print(f"2. extract_pdf: status={r.get('status')} output={r.get('output')} size={r.get('size_bytes')} tables={r.get('tables')}")
    assert r.get("status") == "ok", f"extract 失败: {r}"
    assert r.get("size_bytes", 0) > 0, f"size_bytes 缺失: {r}"

    # 3. layout_pdf（扫描 PDF 1 页 gpu）
    r = mcp_server.layout_pdf(SCAN_PDF, pages="20", device="gpu")
    print(f"3. layout_pdf: status={r.get('status')} blocks={r.get('blocks')} crops={r.get('crops')} json={r.get('layout_json')}")
    assert r.get("status") == "ok", f"layout 失败: {r}"
    assert r.get("blocks", 0) > 0, f"blocks 缺失: {r}"
    assert r.get("layout_json"), f"layout_json 缺失: {r}"

    # 4. 错误路径（不存在的 pdf）
    r = mcp_server.extract_pdf("Z:/nonexistent.pdf")
    print(f"4. 错误路径: {r}")
    assert "error" in r, "应返回错误"

    print("\nMCP 工具函数全部通过 ✅")


if __name__ == "__main__":
    main()
