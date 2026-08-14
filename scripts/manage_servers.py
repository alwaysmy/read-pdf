"""Server lifecycle — 由 engine_config.yaml 驱动（engines[].sources[].local.server）.

Usage:
    python manage_servers.py status
    python manage_servers.py start glm|hybrid|dsocr|qwen
    python manage_servers.py stop
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from engines import load_config
from server_manager import is_port_open, start, stop


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


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    target = sys.argv[2] if len(sys.argv) > 2 else None
    servers = _servers()

    if cmd == "start":
        if target in servers:
            start(target, servers[target]["server_cfg"])
        else:
            print(f"Unknown engine: {target}. Available: {', '.join(servers) or 'none'}")
    elif cmd == "stop":
        stop()
    elif cmd == "status":
        for name, cfg in servers.items():
            status = "RUNNING" if is_port_open(cfg["port"]) else "STOPPED"
            print(f"  {name:10s} :{cfg['port']:<5d}  {status}")
    else:
        print(f"Unknown command: {cmd}. Usage: status | start <engine> | stop")
