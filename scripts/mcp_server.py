"""readpdf-mcp — MCP server，调 read-pdf 本体 HTTP API.

用法（需先启动本体服务）:
  python scripts/server.py            # 启动本体
  uvx --from readpdf-mcp readpdf_mcp  # 或: python scripts/mcp_server.py

环境变量:
  READPDF_SERVER_URL  (默认 http://127.0.0.1:8123)
  READPDF_API_KEY     (可选，本体设置了 Bearer key 时填)

MCP 工具:
  extract_pdf(pdf, pages?, engine?, source?, dpi?, output_dir?) → PDF 提取
  layout_pdf(pdf, pages?, device?, output_dir?)                → 版面分析
  list_engines()                                               → 引擎列表
"""
import json
import os
import pathlib

import requests

SERVER_URL = os.environ.get("READPDF_SERVER_URL", "http://127.0.0.1:8123").rstrip("/")


def _api_key():
    """API key: env READPDF_API_KEY > ~/.readpdf/key（server 首次启动自动生成）. 与 server.py 一致."""
    env_key = os.environ.get("READPDF_API_KEY", "")
    if env_key:
        return env_key
    try:
        key_file = pathlib.Path.home() / ".readpdf" / "key"
        if key_file.exists():
            return key_file.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


API_KEY = _api_key()


def _headers():
    h = {"Content-Type": "application/json"}
    if API_KEY:
        h["Authorization"] = f"Bearer {API_KEY}"
    return h


def _post(path, body):
    r = requests.post(f"{SERVER_URL}{path}", json=body, headers=_headers(), timeout=900)
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}: {r.text[:300]}"}
    return r.json()


def _get(path):
    r = requests.get(f"{SERVER_URL}{path}", headers=_headers(), timeout=30)
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}: {r.text[:300]}"}
    return r.json()


# ---------------------------------------------------------------------------
# MCP 工具实现（供 mcp.run / FastMCP 包装）
# ---------------------------------------------------------------------------
def extract_pdf(pdf, pages=None, engine=None, source=None, dpi=None, output_dir=None):
    """从 PDF 提取文本/Markdown。engine: auto|hybrid|glm|dsocr; source: local|cloud."""
    body = {"pdf": pdf}
    if pages:
        body["pages"] = str(pages)
    if engine:
        body["engine"] = engine
    if source:
        body["source"] = source
    if dpi:
        body["dpi"] = int(dpi)
    if output_dir:
        body["output_dir"] = output_dir
    result = _post("/extract", body)
    if "error" in result:
        return result
    # 精简返回（避免刷屏）
    return {
        "status": result.get("status"),
        "output": result.get("file"),
        "engine": result.get("engine"),
        "size_bytes": result.get("size_bytes"),
        "tables": result.get("total_tables"),
        "time_s": result.get("time_s"),
    }


def layout_pdf(pdf, pages=None, device=None, output_dir=None):
    """版面分析：定位表格/示意图 → 裁剪存图 + 布局 JSON."""
    body = {"pdf": pdf}
    if pages:
        body["pages"] = str(pages)
    if device:
        body["device"] = device
    if output_dir:
        body["output_dir"] = output_dir
    result = _post("/layout", body)
    if "error" in result:
        return result
    return {
        "status": result.get("status"),
        "layout_json": result.get("layout_path"),
        "blocks": result.get("total_blocks"),
        "crops": result.get("total_crops"),
        "time_s": result.get("time_s"),
    }


def list_engines():
    """列出可用引擎及其服务源。"""
    result = _get("/engines")
    if "error" in result:
        return result
    return {"engines": result.get("engines", [])}


# ---------------------------------------------------------------------------
# MCP 接入：优先 FastMCP，降级 mcp.run
# ---------------------------------------------------------------------------
def main():
    try:
        from mcp.server.fastmcp import FastMCP
        mcp = FastMCP("readpdf")
        mcp.add_tool(extract_pdf)
        mcp.add_tool(layout_pdf)
        mcp.add_tool(list_engines)
        mcp.run()
    except ImportError:
        # 降级：mcp SDK
        from mcp.server import Server, stdio_server
        from mcp.server.models import InitializationOptions
        from mcp.types import Tool, TextContent

        server = Server("readpdf")
        TOOLS = [
            Tool(name="extract_pdf", description="从 PDF 提取文本/Markdown",
                 inputSchema={"type": "object", "properties": {
                     "pdf": {"type": "string", "description": "PDF 路径"},
                     "pages": {"type": "string", "description": "页码范围，如 1-10"},
                     "engine": {"type": "string", "description": "auto|hybrid|glm|dsocr"},
                     "source": {"type": "string", "description": "local|cloud"},
                 }, "required": ["pdf"]}),
            Tool(name="layout_pdf", description="版面分析：定位表格/示意图并裁剪",
                 inputSchema={"type": "object", "properties": {
                     "pdf": {"type": "string"}, "pages": {"type": "string"},
                     "device": {"type": "string", "description": "gpu|cpu"},
                 }, "required": ["pdf"]}),
            Tool(name="list_engines", description="列出引擎与服务源",
                 inputSchema={"type": "object", "properties": {}}),
        ]
        HANDLERS = {
            "extract_pdf": extract_pdf, "layout_pdf": layout_pdf, "list_engines": list_engines,
        }

        @server.list_tools()
        async def list_tools():
            return TOOLS

        @server.call_tool()
        async def call_tool(name, arguments):
            fn = HANDLERS.get(name)
            if not fn:
                raise ValueError(f"未知工具: {name}")
            result = fn(**arguments)
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

        async def run_async():
            async with stdio_server() as (r, w):
                await server.run(r, w, InitializationOptions(
                    server_name="readpdf", server_version="0.3.0",
                    capabilities={"tools": {}}))

        import asyncio
        asyncio.run(run_async())


if __name__ == "__main__":
    main()
