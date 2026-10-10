"""readpdf_env.py — 运行环境解析 + 入口自导向（bootstrap）.

为什么要有这个文件：入口脚本（extract_pdf.py / server.py / mcp_server.py /
manage_servers.py）**不依赖调用方用哪个 python 启动**。各入口脚本在 import 任何
第三方库之前调用 ``ensure_interpreter()``：若当前解释器不是配置指定的解释器，
就用目标解释器重新执行本脚本，并透传 stdin/stdout/stderr 与退出码。于是
``python scripts/extract_pdf.py x.pdf`` 这样裸写的命令在任何 python 下都能敲——
脚本自己会跳到配置的解释器（本机 py312），不会再出现
``ModuleNotFoundError: No module named 'pdfmux'`` 这类"python 不对"的故障。

配置（深合并，模式同 engine_config.yaml）：
    readpdf.json        入库，可移植默认值
    readpdf.local.json  本机私有覆盖（gitignore），如本机 py312 绝对路径
解析优先级（python.path = "auto" 时按 python.auto 列表取第一个满足 require 的）：
    env:NAME            环境变量（如 env:READPDF_PYTHON）
    runtime/...         相对仓库根的路径（预留：解压完整 python 发行版到
                        runtime/python 即自包含，见 docs/SETUP_GUIDE.md）
    path                在 PATH 上找 python
显式设置 python.path 时优先用它，版本超出 require 只告警不拦截（配置即意图）。

CLI：
    python scripts/readpdf_env.py check   # 解析结果 + 版本 + 依赖体检
    python scripts/readpdf_env.py which   # 只打印解析出的解释器路径
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "readpdf.json"
LOCAL_CONFIG_PATH = REPO_ROOT / "readpdf.local.json"
ENV_VAR = "READPDF_PYTHON"
BOOTSTRAP_ENV = "READPDF_BOOTSTRAPPED"
DEFAULT_AUTO = ["env:READPDF_PYTHON", "runtime/python/python.exe", "path"]
DEFAULT_REQUIRE = ">=3.10,<3.14"  # paddlepaddle 无 3.14 wheel

# check 命令体检的关键依赖（import 名, pip 名, 用途）
_KEY_DEPS = [
    ("fitz", "pymupdf", "PDF 渲染/文本层"),
    ("pdfplumber", "pdfplumber", "文本层参考 + 表格"),
    ("pdfmux", "pdfmux", "文本 PDF 结构重建"),
    ("yaml", "pyyaml", "engine_config 加载"),
    ("requests", "requests", "引擎 HTTP 调用"),
]

_cache = None


# ---------------------------------------------------------------------------
# 配置加载（只用标准库，保证裸 python 也能解析）
# ---------------------------------------------------------------------------
def _merge_dict(base, override):
    """Deep merge: override wins."""
    out = dict(base)
    for k, v in (override or {}).items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _merge_dict(out[k], v)
        else:
            out[k] = v
    return out


def load_config(force=False):
    """Load readpdf.json + merge readpdf.local.json. Cached."""
    global _cache
    if _cache is not None and not force:
        return _cache
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except Exception as e:
            raise RuntimeError(f"{CONFIG_PATH} 解析失败（JSON 语法错误？）: {e}")
    if LOCAL_CONFIG_PATH.exists():
        try:
            local = json.loads(LOCAL_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except Exception as e:
            raise RuntimeError(f"{LOCAL_CONFIG_PATH} 解析失败（JSON 语法错误？）: {e}")
        cfg = _merge_dict(cfg, local)
    _cache = cfg
    return cfg


# ---------------------------------------------------------------------------
# 版本比较（简易区间："'>=3.10,<3.14'"，支持 >= <= > < == != 与裸版本号"3.10"）
# ---------------------------------------------------------------------------
def _ver_tuple(v):
    parts = []
    for p in str(v).strip().split(".")[:3]:
        digits = "".join(c for c in p if c.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def _satisfies(version, require):
    if not require:
        return True
    for clause in str(require).split(","):
        clause = clause.strip()
        if not clause:
            continue
        for op in (">=", "<=", "==", "!=", ">", "<"):
            if clause.startswith(op):
                bound = clause[len(op):].strip()
                a, b = _ver_tuple(version), _ver_tuple(bound)
                ok = {
                    ">=": a >= b, "<=": a <= b, "==": a == b,
                    "!=": a != b, ">": a > b, "<": a < b,
                }[op]
                if not ok:
                    return False
                break
        else:  # 裸版本号：等价 ==
            if _ver_tuple(version) != _ver_tuple(clause):
                return False
    return True


def version_of(exe):
    """返回 '3.12.13' 形式的版本号；无法执行返回 None。"""
    try:
        out = subprocess.run(
            [str(exe), "-c", "import sys;print('%d.%d.%d'%sys.version_info[:3])"],
            capture_output=True, text=True, timeout=30,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip().splitlines()[-1].strip()
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# 解释器解析
# ---------------------------------------------------------------------------
def _candidate_paths(item):
    """auto 列表项 -> 候选绝对路径列表（可能为空）。"""
    if isinstance(item, str) and item.startswith("env:"):
        v = os.environ.get(item[4:].strip())
        return [v] if v else []
    p = str(item)
    path = pathlib.Path(p)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return [str(path)]


def resolve():
    """解析目标解释器。

    Returns (exe_path|None, tried)。tried 是诊断信息列表（每项含 src/path/ok/reason）。
    """
    cfg = load_config()
    py = cfg.get("python") or {}
    require = py.get("require") or DEFAULT_REQUIRE
    tried = []

    path = py.get("path", "auto")
    if path and path != "auto":
        cand = str(path)
        info = {"src": "配置显式 python.path", "path": cand}
        p = pathlib.Path(cand)
        if not p.is_absolute():
            p = REPO_ROOT / p
        exe = str(p)
        if not p.exists():
            info.update(ok=False, reason="文件不存在")
            tried.append(info)
            return None, tried
        info.update(ok=True, version=version_of(exe), path=exe)
        tried.append(info)
        return exe, tried

    for item in py.get("auto") or DEFAULT_AUTO:
        if item == "path":
            found = shutil.which("python")
            cands = [found] if found else []
            src = "PATH"
        else:
            cands = _candidate_paths(item)
            src = item
        for cand in cands:
            if not cand:
                continue
            p = pathlib.Path(cand)
            exe = str(p if p.is_absolute() else (REPO_ROOT / p))
            info = {"src": src, "path": exe}
            if not p.exists() and not (REPO_ROOT / p).exists():
                info.update(ok=False, reason="不存在")
                tried.append(info)
                continue
            v = version_of(exe)
            if v is None:
                info.update(ok=False, reason="无法执行（损坏或非 python）")
                tried.append(info)
                continue
            if not _satisfies(v, require):
                info.update(ok=False, reason=f"版本 {v} 不满足 {require}")
                tried.append(info)
                continue
            info.update(ok=True, version=v)
            tried.append(info)
            return exe, tried
    return None, tried


def _format_error(tried):
    lines = [
        "[readpdf_env] 错误：没有找到可用的 Python 解释器（要求 "
        f"{load_config().get('python', {}).get('require') or DEFAULT_REQUIRE}）。",
        "尝试过：",
    ]
    for t in tried:
        lines.append(f"  - [{t.get('src')}] {t.get('path')}"
                     + (f" —— {t.get('reason')}" if not t.get("ok") else ""))
    lines += [
        "解决方法（二选一）：",
        "  1. 在 readpdf.local.json 写上解释器绝对路径：",
        '       {"python": {"path": "D:\\\\path\\\\to\\\\python.exe"}}',
        "  2. 把完整 python 发行版解压到仓库 runtime/python/（自包含，见 docs/SETUP_GUIDE.md）",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 入口自导向
# ---------------------------------------------------------------------------
def ensure_interpreter():
    """确保本进程跑在配置指定的解释器里；否则用它重跑本脚本并退出（透传退出码）。

    在入口脚本顶部、import 任何第三方库之前调用。返回时保证已在目标解释器中
    （或目标不可用但当前解释器可接受时带告警继续）。
    """
    try:
        cfg = load_config()
    except RuntimeError as e:
        print(f"[readpdf_env] {e}", file=sys.stderr)
        sys.exit(2)

    target, tried = resolve()
    if target is None:
        print(_format_error(tried), file=sys.stderr)
        sys.exit(2)

    require = (cfg.get("python") or {}).get("require") or DEFAULT_REQUIRE
    v = version_of(target)
    if v and require and not _satisfies(v, require):
        print(f"[readpdf_env] 警告：目标解释器 {target} 版本 {v} 不在要求范围 {require}"
              "（paddlepaddle 无 3.14 wheel，OCR 引擎可能不可用；纯文本/渲染不受影响）",
              file=sys.stderr)

    cur = pathlib.Path(sys.executable).resolve()
    tgt = pathlib.Path(target).resolve()
    if cur == tgt:
        return target  # 已经在目标解释器里

    if os.environ.get(BOOTSTRAP_ENV) == "1":
        # 已经重定向过一次仍不匹配：不循环重跑（避免死循环），带告警继续，
        # 让目标环境自己报错更可诊断。
        print(f"[readpdf_env] 警告：已重定向过但仍运行在 {cur}（目标 {tgt}），"
              "检查 readpdf.local.json 的 python.path 是否指回了自身。", file=sys.stderr)
        return target

    script = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if not script or not os.path.exists(script):
        print(f"[readpdf_env] 错误：找不到入口脚本 {script!r}，无法自导向。",
              file=sys.stderr)
        sys.exit(2)

    env = dict(os.environ)
    env[BOOTSTRAP_ENV] = "1"
    proc = subprocess.run([str(tgt), script] + list(sys.argv[1:]), env=env)
    sys.exit(proc.returncode)


# ---------------------------------------------------------------------------
# CLI：check / which
# ---------------------------------------------------------------------------
def _deps_report(exe):
    """在目标解释器里体检关键依赖，返回行列表。"""
    code = (
        "mods = %r\n"
        "import importlib\n"
        "for m in mods:\n"
        "    try:\n"
        "        mod = importlib.import_module(m)\n"
        "        ver = getattr(mod, '__version__', None) or getattr(mod, 'version', '?')\n"
        "        print('OK|%%s|%%s' %% (m, ver))\n"
        "    except Exception as e:\n"
        "        print('MISSING|%%s|%%s' %% (m, e))\n"
    ) % ([d[0] for d in _KEY_DEPS],)
    try:
        out = subprocess.run([str(exe), "-c", code], capture_output=True,
                             text=True, timeout=120)
    except Exception as e:
        return [f"  （依赖体检失败：{e}）"]
    by_mod = {d[0]: d for d in _KEY_DEPS}
    lines = []
    for raw in (out.stdout or "").splitlines():
        parts = raw.split("|", 2)
        if len(parts) != 3:
            continue
        status, mod, info = parts
        pip_name, purpose = by_mod.get(mod, (mod, ""))[1], by_mod.get(mod, (mod, ""))[2]
        mark = "OK " if status == "OK" else "MISSING"
        lines.append(f"  [{mark}] {mod:<12}({pip_name}) {info}  — {purpose}")
    return lines


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "check"

    if cmd == "which":
        target, _ = resolve()
        if not target:
            print(_format_error(_), file=sys.stderr)
            return 2
        print(target)
        return 0

    if cmd != "check":
        print(__doc__)
        return 1

    cfg = load_config()
    print(f"[readpdf_env] 配置文件 : {CONFIG_PATH}")
    print(f"[readpdf_env] 本机覆盖 : "
          f"{LOCAL_CONFIG_PATH if LOCAL_CONFIG_PATH.exists() else '（无 readpdf.local.json）'}")
    target, tried = resolve()
    print(f"[readpdf_env] 解析结果 : {target or '（未找到）'}")
    for t in tried:
        tag = "OK " if t.get("ok") else "FAIL"
        extra = t.get("version") or t.get("reason") or ""
        print(f"    [{tag}] [{t.get('src')}] {t.get('path')} {extra}")
    if not target:
        print(_format_error(tried), file=sys.stderr)
        return 2
    v = version_of(target)
    print(f"[readpdf_env] 版本     : {v}")
    cur = pathlib.Path(sys.executable).resolve()
    same = cur == pathlib.Path(target).resolve()
    print(f"[readpdf_env] 当前进程 : {sys.executable} -> "
          + ("即目标解释器" if same else "入口将自动重定向到目标解释器"))
    if cfg.get("routing"):
        print(f"[readpdf_env] routing  : agent_vision_max_pages="
              f"{(cfg.get('routing') or {}).get('agent_vision_max_pages')}")
    print("[readpdf_env] 依赖体检（在目标解释器中）：")
    for line in _deps_report(target):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
