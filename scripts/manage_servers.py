"""Server lifecycle — 由 engine_config.yaml 驱动（engines[].sources[].local.server）.

Usage:
    python manage_servers.py status
    python manage_servers.py start glm|hybrid|dsocr|qwen   # 常驻（本进程退出后服务保留）
    python manage_servers.py stop                          # 停止本 skill 管理的引擎（按端口）
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from engines import load_config
from server_manager import is_port_open, start, stop, set_keep_servers


def _servers():
    """Return {name: {"port": int, "server_cfg": dict}} for engines with local server."""
    cfg = load_config()
    out = {}
    for name, eng in (cfg.get("engines") or {}).items():
        for src in (eng.get("sources") or {}).values():
            sc = src.get("server")
            if sc:
                out[name] = {"port": int(sc.get("port", 0)), "server_cfg": sc}
    return out


def _kill_by_port(port):
    """按端口结束监听进程（跨进程停止：服务可能是上一次 start 遗留的）。只杀本 skill 配置端口上的进程。"""
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=15).stdout
    except Exception:
        return False
    killed = False
    for line in out.splitlines():
        m = re.search(rf":{port}\b.*LISTENING\s+(\d+)\s*$", line)
        if m:
            pid = m.group(1)
            subprocess.run(["taskkill", "/F", "/PID", pid],
                           capture_output=True, timeout=30)
            print(f"  已按端口 {port} 停止 PID {pid}")
            killed = True
    return killed


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    target = sys.argv[2] if len(sys.argv) > 2 else None
    servers = _servers()

    if cmd == "start":
        if target in servers:
            # 常驻：本进程退出时保留服务（不随 atexit 清理）
            set_keep_servers(True)
            start(target, servers[target]["server_cfg"])
        else:
            print(f"Unknown engine: {target}. Available: {', '.join(servers) or 'none'}")
    elif cmd == "stop":
        stop()  # 本进程启动的
        for name, cfg in servers.items():
            _kill_by_port(cfg["port"])  # 历史进程（上一次 start 遗留）
        print("stop 完成")
    elif cmd == "status":
        for name, cfg in servers.items():
            status = "RUNNING" if is_port_open(cfg["port"]) else "STOPPED"
            print(f"  {name:10s} :{cfg['port']:<5d}  {status}")
    else:
        print(f"Unknown command: {cmd}. Usage: status | start <engine> | stop")
