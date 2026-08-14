"""合并后验证：主仓库 read-pdf 的 mcp_server.py 能否正常连本体服务."""
import pathlib
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))


def main():
    import mcp_server

    r = mcp_server.list_engines()
    names = [e["name"] for e in r.get("engines", [])]
    print("list_engines:", names)
    assert "hybrid" in names and "paddle_vl" in names, f"引擎列表异常: {names}"

    TEXT_PDF = r"D:\MyProjects\6_Works\hd1\器件手册\连接器选型和定义\5 高速数据传输系列连接器选型手册.pdf"
    r = mcp_server.extract_pdf(TEXT_PDF, pages="1")
    print(f"extract_pdf: status={r.get('status')} size={r.get('size_bytes')}")
    assert r.get("status") == "ok", f"extract 失败: {r}"

    print("\n合并后主仓库 MCP 验证通过 ✅")


if __name__ == "__main__":
    main()
