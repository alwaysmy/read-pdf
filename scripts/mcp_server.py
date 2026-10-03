"""readpdf-mcp — MCP server，调 read-pdf 本体 HTTP API.

用法:
  python scripts/mcp_server.py        # 只起 MCP server；本体在被调用时按需自动拉起
  python scripts/server.py            # 也可先手动起本体（MCP 检测到会直接复用）

环境变量:
  READPDF_SERVER_URL  (可选覆盖；默认读 engine_config.yaml 的 server 段)
  READPDF_API_KEY     (可选，本体设置了 Bearer key 时填)

MCP 工具:
  extract_pdf(pdf, pages?, engine?, source?, dpi?, output_dir?) → PDF 提取
  layout_pdf(pdf, pages?, device?, output_dir?)                → 版面分析
  list_engines()                                               → 引擎列表
  open_document(package_path)                                  → 已有文档包元数据
  read_document(package_path, pages?, max_chars?, cursor?)      → 有界文本及引用
  search_document(package_path, query, max_hits?)               → 已有文本搜索

文档工具仅读取 extract_pdf 输出的 .document.json；不自动提取、OCR 或调度缺失页。
"""
import json
import os
import pathlib
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

import requests

try:
    from pydantic import StrictInt
except ImportError:
    # HTTP-only use does not require the optional MCP SDK/Pydantic dependency.
    # Whenever FastMCP is installed, StrictInt prevents bool/string coercion.
    StrictInt = int


def _server_url():
    """优先 READPDF_SERVER_URL 环境变量；否则读 engine_config.yaml 的 server 段。"""
    env_url = os.environ.get("READPDF_SERVER_URL", "").strip().rstrip("/")
    if env_url:
        return env_url
    try:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        from engines import load_config
        srv = load_config().get("server") or {}
        return f"http://{srv.get('host', '127.0.0.1')}:{int(srv.get('port', 8123))}"
    except Exception:
        return "http://127.0.0.1:8123"


SERVER_URL = _server_url()


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


# ---------------------------------------------------------------------------
# 本体懒启动：调用工具时才检查，没起才拉起（不主动常驻，也不随 MCP 启动）
# ---------------------------------------------------------------------------
_START_LOCK = threading.Lock()
_BACKEND_READY = False


def _is_local_url(url):
    """仅当本体地址在本机时才允许自动拉起（远端共享本体不该由本进程启动）."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host in ("127.0.0.1", "localhost", "::1")


def _backend_alive(timeout=2.0):
    """任何 HTTP 响应（含 401）都说明端口上已有服务在监听."""
    try:
        requests.get(f"{SERVER_URL}/health", headers=_headers(), timeout=timeout)
        return True
    except requests.exceptions.RequestException:
        return False


def _ensure_backend(wait_s=45.0):
    """确保本体在跑；没跑才启动.

    日志写 ~/.readpdf/server.log。子进程 stdio 用 DEVNULL/文件而非管道：受限沙箱会
    拒绝 CreatePipe。解释器用 sys.executable，保证与 MCP server 同一环境（--ov 依赖）。
    """
    global _BACKEND_READY
    if _BACKEND_READY and _backend_alive():
        return
    with _START_LOCK:
        if _backend_alive():
            _BACKEND_READY = True
            return
        if not _is_local_url(SERVER_URL):
            raise RuntimeError(
                f"本体未运行，且 READPDF_SERVER_URL 非本机地址，无法自动启动: {SERVER_URL}")
        script = pathlib.Path(__file__).resolve().parent / "server.py"
        if not script.exists():
            raise RuntimeError(f"找不到本体脚本: {script}")
        log_dir = pathlib.Path.home() / ".readpdf"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "server.log"
        popen_kwargs = {}
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with open(log_path, "a", encoding="utf-8", errors="replace") as log:
            subprocess.Popen([sys.executable, str(script)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=log, **popen_kwargs)
        deadline = time.time() + wait_s
        while time.time() < deadline:
            if _backend_alive(timeout=1.0):
                _BACKEND_READY = True
                return
            time.sleep(0.5)
        raise RuntimeError(f"已尝试启动本体，但 {wait_s:.0f}s 内未就绪；日志: {log_path}")


def _post(path, body):
    _ensure_backend()
    r = requests.post(f"{SERVER_URL}{path}", json=body, headers=_headers(), timeout=900)
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}: {r.text[:300]}"}
    return r.json()


def _get(path):
    _ensure_backend()
    r = requests.get(f"{SERVER_URL}{path}", headers=_headers(), timeout=30)
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}: {r.text[:300]}"}
    return r.json()


# ---------------------------------------------------------------------------
# MCP 工具实现（供 mcp.run / FastMCP 包装）
# ---------------------------------------------------------------------------
def extract_pdf(pdf, pages=None, engine=None, source=None, dpi=None, output_dir=None):
    """从 PDF 提取文本/Markdown。engine: auto|hybrid|glm|dsocr|ov; source: local|cloud."""
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
    summary = {
        "status": result.get("status"),
        "output": result.get("file"),
        "engine": result.get("engine"),
        "size_bytes": result.get("size_bytes"),
        "tables": result.get("total_tables"),
        "time_s": result.get("time_s"),
    }
    # Completeness and warnings must never be hidden by the compact response.
    for field in ("package_path", "doc_id", "revision_id", "coverage", "issues",
                  "quality_flags", "page_statuses", "pages", "page_results"):
        if field in result:
            summary[field] = result[field]
    return summary


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


def open_document(package_path: str):
    """Inspect existing Document Package JSON metadata. Extract a PDF first; no OCR is run."""
    return _post("/document/open", {"package_path": package_path})


def read_document(package_path: str, pages: str | list[StrictInt] | None = None,
                  max_chars: StrictInt = 8000, cursor: str | None = None):
    """Read existing package text with citations, 1..100000 chars, full coverage/quality.

    pages uses 1-based physical numbers/ranges (e.g. '1,3-5') or an integer array.
    Follow next_cursor with the same package/pages; never automatically runs OCR.
    """
    return _post("/document/read", {"package_path": package_path, "pages": pages,
                                    "max_chars": max_chars, "cursor": cursor})


def search_document(package_path: str, query: str, max_hits: StrictInt = 20):
    """Literal case-insensitive search of existing package text, 1..100 hits.

    query is 1..256 characters; each hit has at most 320 snippet characters.
    Coverage and unsearched pages accompany no-match results. Never runs OCR.
    """
    return _post("/document/search", {"package_path": package_path, "query": query,
                                      "max_hits": max_hits})


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
        mcp.add_tool(open_document)
        mcp.add_tool(read_document)
        mcp.add_tool(search_document)
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
                     "engine": {"type": "string", "description": "auto|hybrid|glm|dsocr|ov"},
                     "source": {"type": "string", "description": "local|cloud"},
                 }, "required": ["pdf"]}),
            Tool(name="layout_pdf", description="版面分析：定位表格/示意图并裁剪",
                 inputSchema={"type": "object", "properties": {
                     "pdf": {"type": "string"}, "pages": {"type": "string"},
                     "device": {"type": "string", "description": "gpu|cpu"},
                 }, "required": ["pdf"]}),
            Tool(name="list_engines", description="列出引擎与服务源",
                 inputSchema={"type": "object", "properties": {}}),
            Tool(name="open_document", description="Inspect existing Document Package JSON; no extraction/OCR",
                 inputSchema={"type": "object", "properties": {
                     "package_path": {"type": "string"},
                 }, "required": ["package_path"]}),
            Tool(name="read_document", description="Bounded existing package text with citations and complete coverage/quality; no OCR",
                 inputSchema={"type": "object", "properties": {
                     "package_path": {"type": "string"},
                     "pages": {"anyOf": [{"type": "string"}, {"type": "array", "items": {
                         "type": "integer", "minimum": 1}}, {"type": "null"}]},
                     "max_chars": {"type": "integer", "minimum": 1, "maximum": 100000, "default": 8000},
                     "cursor": {"type": ["string", "null"]},
                 }, "required": ["package_path"]}),
            Tool(name="search_document", description="Literal case-insensitive search of existing package text; bounded snippets, no OCR",
                 inputSchema={"type": "object", "properties": {
                     "package_path": {"type": "string"},
                     "query": {"type": "string", "minLength": 1, "maxLength": 256},
                     "max_hits": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                 }, "required": ["package_path", "query"]}),
        ]
        HANDLERS = {
            "extract_pdf": extract_pdf, "layout_pdf": layout_pdf, "list_engines": list_engines,
            "open_document": open_document, "read_document": read_document,
            "search_document": search_document,
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
