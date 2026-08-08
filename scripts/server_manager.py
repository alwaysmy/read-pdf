"""server_manager.py — 本地服务生命周期（llama-server 启停）.

设计见 docs/engine-decoupling-design_20260808.md：
- 从 engine_config.yaml 的 engines[].sources[].local.server 读配置（不硬编码）
- 设备检测与回退：defaults.device=gpu 但无 GPU → 告警 + 回退 cpu（gpu_fallback）
- 只管理本地源服务；云源（server:null）跳过
"""
import atexit
import os
import pathlib
import socket
import subprocess
import time

from engines import load_config

_started_servers = []  # list of (name, Popen)


def _detect_gpu():
    """Return True if nvidia-smi works (GPU available)."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                           capture_output=True, timeout=10)
        return r.returncode == 0 and r.stdout.decode(errors="ignore").strip() != ""
    except Exception:
        return False


def _resolve_device(cfg, name):
    """Resolve effective device with GPU fallback. Returns (device, warned)."""
    device = cfg.get("defaults", {}).get("device", "gpu")
    fallback = cfg.get("defaults", {}).get("gpu_fallback", True)
    if device == "gpu" and not _detect_gpu():
        if not fallback:
            raise RuntimeError(
                f"[server_manager] 配置 device=gpu 但未检测到 GPU，且 gpu_fallback=false——"
                f"请改 engine_config.local.yaml 的 defaults.device=cpu 或启用回退")
        print(f"[server_manager] WARNING: 引擎 '{name}' 配置 device=gpu 但未检测到 GPU，回退 CPU 运行", flush=True)
        return "cpu", True
    return device, False


def is_port_open(port, host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        try:
            s.connect((host, port))
            return True
        except OSError:
            return False


def ensure(name, server_cfg):
    """Ensure local server for engine is running (start if port not open)."""
    if server_cfg is None:
        return False  # cloud source / no server
    port = int(server_cfg.get("port", 0))
    if is_port_open(port):
        return False  # already running
    return start(name, server_cfg)


def start(name, server_cfg):
    """Start llama-server for engine. Returns Popen."""
    cfg = load_config()
    device, _ = _resolve_device(cfg, name)
    llama_dir = cfg.get("defaults", {}).get("llama_dir", "")
    exe = server_cfg.get("exe", "llama-server.exe")
    exe_path = os.path.join(llama_dir, exe) if llama_dir and not os.path.isabs(exe) else exe
    if not os.path.exists(exe_path):
        print(
            f"[server_manager] 找不到 llama-server: {exe_path}\n"
            f"  → 首次使用请按 docs/SETUP_GUIDE.md 配置：\n"
            f"    1) 下载 llama.cpp Windows 二进制\n"
            f"    2) 在 engine_config.local.yaml 的 defaults.llama_dir 填解压目录\n"
            f"    3) 若没有本地模型/GPU，可用云源: python scripts/extract_pdf.py x.pdf --source cloud（需 token）",
            flush=True)
        raise FileNotFoundError(exe_path)

    # 模型/投影文件存在性校验（提前给出友好提示）
    for fkey in ("model", "mmproj"):
        fpath = server_cfg.get(fkey, "")
        if fpath and not os.path.exists(fpath):
            print(
                f"[server_manager] 找不到引擎 '{name}' 的 {fkey}: {fpath}\n"
                f"  → 请按 docs/SETUP_GUIDE.md 下载模型，并在 engine_config.local.yaml 填正确路径",
                flush=True)
            raise FileNotFoundError(fpath)

    args = [exe_path, "-m", server_cfg["model"], "--mmproj", server_cfg["mmproj"],
            "--port", str(port := server_cfg.get("port", 0)), "--host", "127.0.0.1"]
    args += server_cfg.get("args", [])
    if device == "cpu":
        # CPU 模式：去掉 GPU 专属参数
        filtered = []
        skip_next = False
        for a in args:
            if skip_next:
                skip_next = False
                continue
            if a in ("-ngl", "--n-gpu-layers"):
                filtered += [a, "0"]
                continue
            filtered.append(a)
        args = filtered
        print(f"[server_manager] 引擎 '{name}' 以 CPU 模式启动", flush=True)

    print(f"[server_manager] 启动 {name} (port {port}, {device})...", flush=True)
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _started_servers.append((name, proc))

    # 等待就绪
    for _ in range(120):
        if is_port_open(port):
            print(f"[server_manager] {name} 就绪 (port {port})", flush=True)
            return proc
        if proc.poll() is not None:
            raise RuntimeError(f"[server_manager] {name} 启动失败 (exit {proc.returncode})")
        time.sleep(0.5)
    raise RuntimeError(f"[server_manager] {name} 启动超时 (port {port})")


def stop(name=None):
    """Stop server(s). name=None → stop all started by this session."""
    global _started_servers
    remaining = []
    for n, proc in _started_servers:
        if name is None or n == name:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            print(f"[server_manager] 已停止 {n}", flush=True)
        else:
            remaining.append((n, proc))
    _started_servers = remaining


def cleanup():
    stop()


atexit.register(cleanup)
