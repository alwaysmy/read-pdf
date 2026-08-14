"""MCP stdio 握手自测：直接向 mcp_server.py 发 initialize + tools/list.
验证 MCP 协议层可用（不经 Reasonix 会话）。
"""
import json
import pathlib
import subprocess
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

MCP = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "mcp_server.py"


def send(proc, msg):
    data = json.dumps(msg) + "\n"
    proc.stdin.write(data)
    proc.stdin.flush()


def read_msg(proc):
    line = proc.stdout.readline()
    if not line:
        return None
    return json.loads(line)


def main():
    proc = subprocess.Popen([sys.executable, str(MCP)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, encoding="utf-8")

    send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "selftest", "version": "1.0"}}})
    r = read_msg(proc)
    print("1. initialize:", r.get("result", {}).get("serverInfo") if r else r)
    assert r and "result" in r, f"initialize 失败: {r}"

    send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    r = read_msg(proc)
    tools = [t["name"] for t in (r.get("result", {}).get("tools", []) if r else [])]
    print("2. tools/list:", tools)
    assert "extract_pdf" in tools and "layout_pdf" in tools and "list_engines" in tools, f"工具缺失: {tools}"

    send(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "list_engines", "arguments": {}}})
    r = read_msg(proc)
    content = r.get("result", {}).get("content", []) if r else []
    text = content[0].get("text", "") if content else ""
    print("3. tools/call list_engines:", text[:120])
    assert "hybrid" in text, f"list_engines 结果异常: {text[:200]}"

    proc.terminate()
    print("\nMCP stdio 协议自测全部通过 ✅")


if __name__ == "__main__":
    main()
