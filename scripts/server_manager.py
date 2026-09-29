"""server_manager.py — 本地服务生命周期（llama-server 启停）.

设计见 docs/engine-decoupling-design_20260808.md：
- 从 engine_config.yaml 的 engines[].sources[].local.server 读配置（不硬编码）
- 设备检测与回退：defaults.device=gpu 但无 GPU → 告警 + 回退 cpu（gpu_fallback）
- 只管理本地源服务；云源（server:null）跳过
"""
import atexit
import glob
import os
import pathlib
import socket
import subprocess
import time

from engines import load_config

_started_servers = []  # list of (name, Popen)

# llama.cpp 的 CUDA 后端要能加载这三个运行库，否则**静默回落 CPU**
_CUDA_RUNTIME_PATTERNS = ("cudart64_*.dll", "cublas64_*.dll", "cublasLt64_*.dll")


def _cuda_loader_dirs(exe_path):
    """Windows DLL 加载器**真正**会搜索的目录：exe 同目录 + PATH."""
    dirs = [os.path.dirname(exe_path)]
    dirs += [d for d in (os.environ.get("PATH") or "").split(os.pathsep) if d]
    seen, out = set(), []
    for d in dirs:
        if d and d not in seen and os.path.isdir(d):
            seen.add(d)
            out.append(d)
    return out


def _cuda_toolkit_dirs():
    """CUDA Toolkit 的 bin 目录 —— 仅用于给出修复提示（加载器不搜索这里）."""
    dirs = []
    cuda_path = os.environ.get("CUDA_PATH")
    if cuda_path:
        dirs += [os.path.join(cuda_path, "bin", "x64"), os.path.join(cuda_path, "bin")]
    root = r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA"
    if os.path.isdir(root):
        for v in sorted(os.listdir(root), reverse=True):
            dirs += [os.path.join(root, v, "bin", "x64"), os.path.join(root, v, "bin")]
    return [d for d in dirs if os.path.isdir(d)]


def _find_cuda_runtime(exe_path):
    """检查 llama.cpp 能否**真正加载到** CUDA 运行库.

    返回 (可解析, {模式: 命中目录}, 缺失列表, 修复提示目录).

    为什么必须在启动前查：官方 Windows release 把**二进制**与 **CUDA 运行库**拆成两个
    zip（`llama-*-bin-win-cuda-*.zip` 与 `cudart-llama-bin-win-cuda-*.zip`）。只解压前者，
    会得到一个**能正常启动、日志无任何错误、却在 CPU 上算**的 llama-server ——
    实测同一张图 85s(CPU) vs 29s(GPU)。

    注意判定口径：只认 **exe 同目录与 PATH**（Windows 加载器的真实搜索路径）。
    装了 CUDA Toolkit、也设了 CUDA_PATH、但 bin 不在 PATH —— 这种情况**依然加载不到**，
    必须照常告警，只是提示可以更具体（直接告诉你 Toolkit 的 bin 在哪）。
    """
    loader = _cuda_loader_dirs(exe_path)
    where, missing = {}, []
    for pat in _CUDA_RUNTIME_PATTERNS:
        hit = None
        for d in loader:
            if glob.glob(os.path.join(d, pat)):
                hit = d
                break
        if hit:
            where[pat] = hit
        else:
            missing.append(pat)
    hint = None
    if missing:
        for d in _cuda_toolkit_dirs():
            if all(glob.glob(os.path.join(d, p)) for p in missing):
                hint = d
                break
    return (not missing), where, missing, hint


def _wants_gpu(args):
    """args 里是否要求 GPU 计算（-ngl/--n-gpu-layers 非 0）."""
    for i, a in enumerate(args):
        if a in ("-ngl", "--n-gpu-layers") and i + 1 < len(args):
            try:
                return int(args[i + 1]) != 0
            except ValueError:
                return False
    return False


_DEVICE_PROBE_CACHE = {}


def _probe_llama_devices(exe_path, timeout=25):
    """跑 `<llama-server> --list-devices`，看 llama.cpp **自己**认到哪些设备.

    返回 (是否有 CUDA 设备 | None 表示无法判定, 原始输出)。按 exe 路径缓存。

    这是"llama.cpp 能不能真用上 GPU"的权威判据，一次覆盖所有失败模式：
      - CUDA 运行库缺失
      - **CUDA 主版本与构建不匹配**（构建要 cudart64_12，机器却只装了 13）
      - 显卡架构不在该构建的 kernel 列表里
      - 驱动太旧
    以上情况 llama.cpp **都不报错**，只是静默回落到 CPU —— `--list-devices` 会显示
    `(none)`，而只查 DLL 是否存在的粗检会把主版本不匹配误判为"可用"。
    """
    if exe_path in _DEVICE_PROBE_CACHE:
        return _DEVICE_PROBE_CACHE[exe_path]
    result = (None, "")
    try:
        r = subprocess.run([exe_path, "--list-devices"],
                           capture_output=True, timeout=timeout)
        out = (r.stdout or b"").decode(errors="replace") + \
              (r.stderr or b"").decode(errors="replace")
        if r.returncode == 0:
            has_cuda = any(l.strip().startswith("CUDA") for l in out.splitlines())
            result = (has_cuda, out)
        else:
            result = (None, out)  # 该 build 不支持 --list-devices，无法据此判定
    except Exception as e:
        result = (None, f"{type(e).__name__}: {e}")
    _DEVICE_PROBE_CACHE[exe_path] = result
    return result


def _warn_no_device(name, exe_path, probe_out):
    """llama.cpp 认不到任何 CUDA 设备时的告警（不中断：用户可能确实想用 CPU）."""
    toolkit = r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA"
    vers = sorted(os.listdir(toolkit)) if os.path.isdir(toolkit) else []
    print(
        f"[server_manager] 引擎 '{name}' 配置了 GPU（-ngl），但 llama.cpp 没有可用的 CUDA 设备，"
        f"将【静默在 CPU 上运行】——慢数倍且无任何报错。\n"
        f"  llama-server --list-devices 输出：\n"
        + "".join(f"      {l}\n" for l in probe_out.strip().splitlines()[:6]) +
        f"  → 常见原因与对策（本机已装 CUDA Toolkit: {', '.join(vers) or '无'}）：\n"
        f"     1) **CUDA 主版本不匹配**：构建要 cudart64_12.dll 之类，而机器只装了别的版本。\n"
        f"        查构建到底要哪版：看 {os.path.dirname(exe_path)} 下 ggml-cuda.dll 的导入表；\n"
        f"        修法：把对应版本的 cudart/cublas DLL 放到该目录（官方 release 的\n"
        f"        `cudart-llama-bin-win-cuda-<版本>-x64.zip` 就是这些 DLL，与主包是两个 zip）\n"
        f"     2) 运行库不在加载路径：装好 Toolkit 还不够，bin 必须进 PATH，或把 DLL 拷到\n"
        f"        {os.path.dirname(exe_path)}\n"
        f"     3) 显卡架构不在该构建的 kernel 列表里（老卡尤其常见）：换支持该架构的构建\n"
        f"     判定命令：{exe_path} --list-devices",
        flush=True)


def _warn_missing_cuda(name, exe_path, missing, hint):
    """CUDA 运行库加载不到时给出可操作的告警（不中断：用户可能确实想用 CPU）."""
    print(
        f"[server_manager] 引擎 '{name}' 配置了 GPU（-ngl），但 CUDA 运行库加载不到："
        f"{', '.join(missing)}\n"
        f"  → llama.cpp 会【静默回落到 CPU】：能正常启动、日志不报错，但实测同一张图"
        f" 85s(CPU) vs 29s(GPU)。\n"
        f"  → 判定口径是 Windows 加载器的真实搜索路径（exe 同目录 + PATH）；"
        f"只装了 CUDA Toolkit 但 bin 不在 PATH 同样加载不到。\n"
        f"  → 修法（任一即可）：\n"
        f"     1) 把 CUDA 的 bin 目录加进 PATH"
        + (f"（本机检测到：{hint}）" if hint else "") + "\n"
        f"     2) 把 cudart64_*.dll / cublas64_*.dll / cublasLt64_*.dll 拷到 {os.path.dirname(exe_path)}\n"
        f"     3) 官方 release 的二进制包与 cudart- 运行库包是【两个】zip，两个都要解压\n"
        f"     4) 或在 engine_config.local.yaml 里给该引擎的 server 加 "
        f'env: {{"PATH": "<CUDA bin 目录>;%PATH%"}}',
        flush=True)


def _detect_gpu():
    """Return True if nvidia-smi works (GPU available)."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                           capture_output=True, timeout=10)
        return r.returncode == 0 and r.stdout.decode(errors="ignore").strip() != ""
    except Exception:
        return False


def _query_free_vram_mib():
    """查询 GPU 空闲显存（MiB）。无 GPU/查询失败返回 None。"""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, timeout=10)
        if r.returncode != 0:
            return None
        return int(r.stdout.decode(errors="ignore").strip().splitlines()[0])
    except Exception:
        return None


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

    # 模型/投影文件校验（提前给出友好提示）
    # 空值必须一并拦下：engine_config.yaml 里这些键是占位空串（机器专属值在
    # engine_config.local.yaml），若放过去，会先撞上显存检查或 args 取值失败，
    # 报出与真实原因无关的错误。
    for fkey in ("model", "mmproj"):
        fpath = str(server_cfg.get(fkey) or "").strip()
        if not fpath:
            print(
                f"[server_manager] 引擎 '{name}' 未配置 {fkey}\n"
                f"  → 模型路径属机器专属配置，请写进 engine_config.local.yaml 的\n"
                f"    engines.{name}.sources.local.server.{fkey}\n"
                f"    字段清单见 engine_config.local.example.yaml，下载来源见 docs/SETUP_GUIDE.md",
                flush=True)
            raise RuntimeError(f"[server_manager] {name} 未配置 {fkey}")
        if not os.path.exists(fpath):
            print(
                f"[server_manager] 找不到引擎 '{name}' 的 {fkey}: {fpath}\n"
                f"  → 请按 docs/SETUP_GUIDE.md 下载模型，并在 engine_config.local.yaml 填正确路径",
                flush=True)
            raise FileNotFoundError(fpath)

    # GPU 可用性预检：CUDA 后端起不来时 llama.cpp 会静默回落 CPU（不报错、慢数倍）
    # 先用 llama.cpp 自己的设备列表判定（权威，覆盖版本不匹配/架构不支持等所有情况），
    # 该 build 不支持 --list-devices 时再退回运行库是否存在（粗检，可能假阳性）
    # 用 server_cfg 里的 args —— 完整 args 要到显存检查之后才拼出来
    if _wants_gpu(server_cfg.get("args", [])):
        _has_dev, _probe_out = _probe_llama_devices(exe_path)
        if _has_dev is False:
            _warn_no_device(name, exe_path, _probe_out)
        elif _has_dev is None:
            _cuda_ok, _cuda_where, _cuda_missing, _cuda_hint = _find_cuda_runtime(exe_path)
            if not _cuda_ok:
                _warn_missing_cuda(name, exe_path, _cuda_missing, _cuda_hint)

    # 启动前显存检查（SKILL.md 规则：空闲 >3GB 才能安全启动 OCR 引擎）
    _vram_required = int(server_cfg.get("vram_required_mib", 3000))
    _vram_free = _query_free_vram_mib()
    if _vram_free is not None and _vram_free < _vram_required:
        print(
            f"[server_manager] 引擎 '{name}' 未启动：GPU 空闲显存 {_vram_free} MiB < 需要 {_vram_required} MiB\n"
            f"  → 按 SKILL.md 规则，启动前须空闲 >3GB。请关闭占用显存的程序"
            f"（ComfyUI/浏览器/视频等），再重试。\n"
            f"    查看占用: nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader",
            flush=True)
        raise RuntimeError(f"[server_manager] {name} 启动前显存检查未通过（空闲 {_vram_free} MiB < {_vram_required} MiB）")

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
    import tempfile as _tf
    _err_file = _tf.NamedTemporaryFile(prefix=f"llama_{name}_", suffix=".log", delete=False)
    proc_env = os.environ.copy()
    if server_cfg.get("env"):
        proc_env.update(server_cfg["env"])
    # stdout 也要收进日志：llama.cpp 的设备列表、"offloaded N layers to GPU"、
    # 逐请求 token 速率全在 stdout，丢掉它等于丢掉了 GPU 是否生效的唯一直接证据
    proc = subprocess.Popen(args, stdout=_err_file, stderr=subprocess.STDOUT, env=proc_env)
    _started_servers.append((name, proc, _err_file.name))

    def _tail_error_log():
        """读取引擎 stderr 日志尾部（诊断启动失败）。"""
        try:
            with open(_err_file.name, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            return "".join(lines[-15:])
        except Exception:
            return ""

    def _vram_hint():
        """检测显存是否不足，给出行动建议。"""
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                capture_output=True, timeout=10)
            free_mib = int(r.stdout.decode(errors="ignore").strip().splitlines()[0])
            if free_mib < 4000:
                return (
                    f"\n  ⚠ 当前 GPU 空闲显存仅 {free_mib} MiB（OCR 引擎需 ≥3GB）。\n"
                    f"  → 请先关闭占用显存的程序（ComfyUI/浏览器/视频等），或运行:\n"
                    f"    nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader")
        except Exception:
            pass
        return ""

    # 等待就绪：先等端口，再等 /health（模型加载完成）——避免冷启动前几页失败
    import requests as _req
    port_open = False
    for _ in range(120):
        if is_port_open(port):
            port_open = True
            break
        if proc.poll() is not None:
            raise RuntimeError(
                f"[server_manager] {name} 启动失败 (exit {proc.returncode})\n"
                f"  日志尾部:\n{_tail_error_log()}{_vram_hint()}")
        time.sleep(0.5)
    if not port_open:
        raise RuntimeError(f"[server_manager] {name} 启动超时 (port {port})")
    # 端口已监听 → 等 /health 200（模型真正加载完）
    for _ in range(240):  # 最多 120s
        try:
            r = _req.get(f"http://127.0.0.1:{port}/health", timeout=2)
            if r.status_code == 200:
                print(f"[server_manager] {name} 就绪 (port {port})", flush=True)
                return proc
        except Exception:
            pass
        if proc.poll() is not None:
            # 启动失败：打印 stderr 尾部帮助诊断
            raise RuntimeError(
                f"[server_manager] {name} 启动失败 (exit {proc.returncode})\n"
                f"  日志尾部:\n{_tail_error_log()}{_vram_hint()}")
        time.sleep(0.5)
    raise RuntimeError(f"[server_manager] {name} /health 超时 (port {port})")


_keep_servers = False


def set_keep_servers(flag):
    """Global switch: when True, cleanup() won't stop engines (keep-alive for reuse)."""
    global _keep_servers
    _keep_servers = bool(flag)


def stop(name=None):
    """Stop server(s). name=None → stop all started by this session."""
    global _started_servers
    remaining = []
    for entry in _started_servers:
        n, proc = entry[0], entry[1]
        err_file = entry[2] if len(entry) > 2 else None
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
            if err_file:
                # 保留日志：里面有 llama.cpp 的逐请求 token 速率（判断 GPU 是否真在算、
                # 以及 offload 是否生效的直接证据），删掉等于把唯一的性能证据丢掉
                print(f"[server_manager] 运行日志保留在 {err_file}", flush=True)
        else:
            remaining.append(entry)
    _started_servers = remaining


def cleanup():
    if _keep_servers:
        print(f"[server_manager] keep_servers=true，保留 {len(_started_servers)} 个引擎常驻", flush=True)
        return
    stop()


atexit.register(cleanup)
