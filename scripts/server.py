"""read-pdf 本体 HTTP 服务（阶段 1）.

架构：Flask API → subprocess 调用 extract_pdf.py（零侵入复用 CLI）。
端点：POST /extract, POST /layout, GET /engines, GET/POST /config, GET /health
默认 http://127.0.0.1:8123（host/port 在 engine_config.yaml 的 server 段配置，仅本机）；可选 READPDF_API_KEY 做 Bearer 认证。
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

from flask import Flask, jsonify, request

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "extract_pdf.py"
def _server_defaults():
    """host/port 来自 engine_config.yaml 的 server 段（缺省时用内置默认值）。"""
    try:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from engines import load_config
        srv = load_config().get("server") or {}
        return srv.get("host", "127.0.0.1"), int(srv.get("port", 8123))
    except Exception:
        return "127.0.0.1", 8123


HOST, PORT = _server_defaults()


def _get_api_key():
    """API key: env READPDF_API_KEY > ~/.readpdf/key（首次自动生成）. 强制认证."""
    env_key = os.environ.get("READPDF_API_KEY", "")
    if env_key:
        return env_key
    key_dir = pathlib.Path.home() / ".readpdf"
    key_file = key_dir / "key"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    # 首次运行：生成随机 key 并持久化
    import secrets
    key_dir.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(24)
    key_file.write_text(key, encoding="utf-8")
    print(f"[server] 已生成 API key: {key}（保存到 {key_file}，客户端需 Bearer 认证）", flush=True)
    return key


API_KEY = _get_api_key()

app = Flask(__name__)


def _check_auth():
    auth = request.headers.get("Authorization", "")
    return auth == f"Bearer {API_KEY}"


def _run_cli(args, timeout=900):
    """Run extract_pdf.py subprocess, return (ok, result_dict).

    输出用临时文件承接，不用管道：受限沙箱下子进程管道（CreatePipe）会被拒绝，
    原先的 capture_output=True 会让 /extract、/layout 一律 500。文件重定向不受此限。
    """
    cmd = [sys.executable, str(SCRIPT)] + args
    with tempfile.TemporaryDirectory(prefix="readpdf_cli_") as td:
        out_p = pathlib.Path(td) / "stdout.txt"
        err_p = pathlib.Path(td) / "stderr.txt"
        try:
            with open(out_p, "w", encoding="utf-8", errors="replace") as fo, \
                 open(err_p, "w", encoding="utf-8", errors="replace") as fe:
                proc = subprocess.run(cmd, stdout=fo, stderr=fe, timeout=timeout)
        except subprocess.TimeoutExpired:
            # subprocess.run 内部已 kill 子进程
            return False, {"error": f"处理超时（>{timeout}s），已终止", "timeout": True}
        stdout = out_p.read_text(encoding="utf-8", errors="replace")
        stderr = err_p.read_text(encoding="utf-8", errors="replace")
    # extract_pdf.py --json 打印多行 JSON；提取第一个 { 到最后一个 } 的完整块
    result = None
    first_brace = stdout.find("{")
    last_brace = stdout.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        try:
            result = json.loads(stdout[first_brace:last_brace + 1])
        except json.JSONDecodeError:
            result = None
    if result is None and proc.returncode != 0:
        return False, {"error": (stderr or stdout)[-500:]}
    if result is None:
        # 退出码 0 但没解析出 JSON → 异常，返回 500 级错误（不再静默 raw）
        return False, {"error": f"输出解析失败（returncode={proc.returncode}）: {(stderr or stdout)[-500:]}"}
    return proc.returncode == 0, result


# 输入校验（防 CLI flag 注入 / DoS）
ENGINE_WHITELIST = {"auto", "hybrid", "glm", "dsocr", "ov"}
SOURCE_CHOICES = {"local", "cloud"}
DPI_RANGE = (50, 600)


def _validate_body(body):
    """校验请求体，返回 (error_msg, None) 或 (None, 规范化后的 body)."""
    eng = body.get("engine", "auto")
    if eng not in ENGINE_WHITELIST:
        return f"engine 必须是 {sorted(ENGINE_WHITELIST)} 之一，got '{eng}'", None
    src = body.get("source")
    if src is not None and src not in SOURCE_CHOICES:
        return f"source 必须是 {sorted(SOURCE_CHOICES)} 之一，got '{src}'", None
    dpi = body.get("dpi")
    if dpi is not None:
        try:
            dpi = int(dpi)
        except (TypeError, ValueError):
            return f"dpi 必须是整数，got '{dpi}'", None
        if not (DPI_RANGE[0] <= dpi <= DPI_RANGE[1]):
            return f"dpi 超出范围 {DPI_RANGE}（防渲染内存爆炸），got {dpi}", None
        body["dpi"] = dpi
    od = body.get("output_dir")
    if od is not None:
        p = pathlib.Path(od)
        if p.is_absolute() and not str(p).startswith("\\\\"):
            pass  # 绝对本地路径允许（Windows UNC 排除）
        elif ".." in od.split("/") or ".." in od.split("\\"):
            return f"output_dir 不允许路径穿越: {od}", None
    return None, body


@app.route("/health", methods=["GET"])
def health():
    if not _check_auth():
        return jsonify({"error": "unauthorized"}), 401
    gpu = False
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                           capture_output=True, timeout=5)
        gpu = r.returncode == 0
    except Exception:
        pass
    return jsonify({"status": "ok", "version": "0.3.0", "gpu": gpu})


@app.route("/extract", methods=["POST"])
def extract():
    if not _check_auth():
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(force=True, silent=True) or {}
    err, body = _validate_body(body)
    if err:
        return jsonify({"error": err}), 400
    pdf = body.get("pdf")
    if not pdf or not pathlib.Path(pdf).exists():
        return jsonify({"error": f"pdf 不存在: {pdf}"}), 400
    args = [pdf]
    if body.get("pages"):
        args += ["--pages", str(body["pages"])]
    eng = body.get("engine")
    if eng and eng != "auto":
        args += [f"--{eng}"]
    if body.get("source"):
        args += ["--source", body["source"]]
    if body.get("dpi"):
        args += ["--dpi", str(body["dpi"])]
    if body.get("output_dir"):
        args += ["--output-dir", str(body["output_dir"])]
    args += ["--json"]
    t0 = time.time()
    ok, result = _run_cli(args)
    if not ok:
        return jsonify(result), 500
    result["time_s"] = round(time.time() - t0, 1)
    return jsonify(result)


@app.route("/layout", methods=["POST"])
def layout():
    if not _check_auth():
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(force=True, silent=True) or {}
    err, body = _validate_body(body)
    if err:
        return jsonify({"error": err}), 400
    pdf = body.get("pdf")
    if not pdf or not pathlib.Path(pdf).exists():
        return jsonify({"error": f"pdf 不存在: {pdf}"}), 400
    args = [pdf, "--layout"]
    if body.get("pages"):
        args += ["--pages", str(body["pages"])]
    device = body.get("device")
    if device:
        if device not in ("gpu", "cpu"):
            return jsonify({"error": f"device 必须是 gpu|cpu，got '{device}'"}), 400
        args += ["--layout-device", device]
    if body.get("output_dir"):
        args += ["--output-dir", str(body["output_dir"])]
    args += ["--json"]
    t0 = time.time()
    ok, result = _run_cli(args)
    if not ok:
        return jsonify(result), 500
    result["time_s"] = round(time.time() - t0, 1)
    return jsonify(result)


@app.route("/engines", methods=["GET"])
def engines():
    if not _check_auth():
        return jsonify({"error": "unauthorized"}), 401
    import engines as eng_mod
    cfg = eng_mod.load_config()
    out = []
    for name, e in cfg.get("engines", {}).items():
        srcs = list(e.get("sources", {}).keys())
        default = e.get("default_source", "local")
        port = None
        local = e.get("sources", {}).get("local", {}).get("server")
        if local:
            port = local.get("port")
        out.append({
            "name": name, "default_source": default, "sources": srcs, "port": port,
        })
    return jsonify({"engines": out})


@app.route("/config", methods=["GET", "POST"])
def config():
    if not _check_auth():
        return jsonify({"error": "unauthorized"}), 401
    local_path = REPO_ROOT / "engine_config.local.yaml"
    main_path = REPO_ROOT / "engine_config.yaml"
    if request.method == "GET":
        # 脱敏返回：local.yaml 里可能含真实 token，api_key 掩码
        def _mask(text):
            import re
            return re.sub(r"(api_key\s*:\s*[\"']?)([^\"'\s]+)", lambda m: m.group(1) + "***", text or "")
        return jsonify({
            "main_config": _mask(main_path.read_text(encoding="utf-8")) if main_path.exists() else "",
            "local_config": _mask(local_path.read_text(encoding="utf-8")) if local_path.exists() else "",
            "main_path": str(main_path), "local_path": str(local_path),
        })
    # POST: 写 local.yaml（校验 YAML + 危险字段白名单）
    body = request.get_json(force=True, silent=True) or {}
    content = body.get("config")
    if not content:
        return jsonify({"error": "缺少 config 字段"}), 400
    try:
        import yaml
        cfg = yaml.safe_load(content)  # 校验
    except Exception as e:
        return jsonify({"error": f"YAML 无效: {e}"}), 400
    # 白名单校验：禁止覆盖会改变进程启动的字段（防 RCE）
    BANNED_KEYS = ("exe", "llama_dir", "args", "command")
    def _check_banned(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                p = f"{path}.{k}" if path else k
                if k in BANNED_KEYS:
                    raise ValueError(f"禁止通过 API 修改字段: {p}（会改变进程启动，请直接编辑 engine_config.local.yaml）")
                _check_banned(v, p)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                _check_banned(v, f"{path}[{i}]")
    try:
        _check_banned(cfg or {})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    local_path.write_text(content, encoding="utf-8")
    # 刷新 engines 缓存，使新配置立即生效
    try:
        import engines as eng_mod
        eng_mod.load_config(force=True)
    except Exception:
        pass
    return jsonify({"status": "ok", "path": str(local_path)})


if __name__ == "__main__":
    print(f"read-pdf server: http://{HOST}:{PORT}", flush=True)
    app.run(host=HOST, port=PORT, debug=False)
