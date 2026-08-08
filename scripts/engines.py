"""engines.py — 引擎注册表 + 统一 API 调用层（解耦：只认 endpoint URL）.

设计见 docs/engine-decoupling-design_20260808.md：
- 每引擎 local/cloud 双源（sources.local + sources.cloud + default_source）
- 切换服务源 = 换 endpoint/key/server，引擎行为（prompt/message_order）不变
- 本地源走 OpenAI 兼容 HTTP；云源（PaddleOCR AI Studio）走 job 异步模式
"""
import base64
import json
import os
import pathlib
import time

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_CONFIG_PATH = _REPO_ROOT / "engine_config.yaml"
_LOCAL_CONFIG_PATH = _REPO_ROOT / "engine_config.local.yaml"

_cache = None


def _expand_env(value):
    """Expand ${ENV_VAR} placeholders from environment.
    未定义的变量 → 抛 ValueError（可诊断），而非返回异常 dict。"""
    if isinstance(value, str) and "${" in value:
        import re
        for m in re.finditer(r"\$\{([^}]+)\}", value):
            var = m.group(1)
            if var not in os.environ:
                raise ValueError(f"环境变量 {var} 未设置（可设到 engine_config.local.yaml 或系统环境变量）")
        for k in os.environ:
            value = value.replace(f"${{{k}}}", os.environ[k])
    return value


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
    """Load engine_config.yaml + merge engine_config.local.yaml. Cached."""
    global _cache
    if _cache is not None and not force:
        return _cache
    try:
        import yaml
    except ImportError:
        raise RuntimeError("需要 PyYAML: pip install pyyaml")
    cfg = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    if _LOCAL_CONFIG_PATH.exists():
        local = yaml.safe_load(_LOCAL_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        cfg = _merge_dict(cfg, local)
    _cache = cfg
    return cfg


def get_engine(name, source=None):
    """Resolve engine config with effective source. Returns (engine_cfg, source_name)."""
    cfg = load_config()
    engine = cfg["engines"].get(name)
    if engine is None:
        raise KeyError(f"引擎 '{name}' 不在 engine_config.yaml 中")
    src = source or engine.get("default_source", "local")
    if src not in engine.get("sources", {}):
        raise KeyError(f"引擎 '{name}' 没有 '{src}' 源（可用: {list(engine.get('sources', {}))}）")
    return engine, src


def get_endpoint(name, source=None):
    """Return (endpoint, api_key) for the effective source."""
    engine, src = get_engine(name, source)
    src_cfg = engine["sources"][src]
    endpoint = _expand_env(src_cfg.get("endpoint", ""))
    api_key = _expand_env(src_cfg.get("api_key", ""))
    return endpoint, api_key


def ensure_local_server(name, server_manager):
    """Ensure local server is running (only for local source)."""
    engine, src = get_engine(name)
    if src == "local":
        server_manager.ensure(name, engine["sources"]["local"].get("server"))


# ---------------------------------------------------------------------------
# HTTP 调用（本地源：OpenAI 兼容）
# ---------------------------------------------------------------------------
def call_local(engine, src_cfg, img_path, prompt, temp=0, max_tokens=8192):
    """POST OpenAI-compatible chat/completions to local endpoint."""
    import requests
    endpoint = _expand_env(src_cfg.get("endpoint"))
    api_key = _expand_env(src_cfg.get("api_key", ""))
    with open(img_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    message_order = engine.get("message_order", "image-first")
    if message_order == "text-first":
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
        ]
    else:  # image-first（GLM 系）
        content = [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
            {"type": "text", "text": prompt},
        ]
    url = endpoint.rstrip("/") + "/chat/completions"
    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "messages": [{"role": "user", "content": content}],
                "temperature": temp,
                "max_tokens": max_tokens,
            },
            timeout=180,
        )
        if resp.status_code != 200:
            return "", {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        return resp.json()["choices"][0]["message"]["content"], {}
    except Exception as e:
        return "", {"error": str(e)}


# ---------------------------------------------------------------------------
# 云源调用（PaddleOCR AI Studio：job 异步模式）
# ---------------------------------------------------------------------------
def call_cloud_aistudio(engine, src_cfg, file_path, max_wait_s=300):
    """PaddleOCR AI Studio job 模式：提交 → 轮询 → 拉 JSONL markdown."""
    import requests
    try:
        endpoint = _expand_env(src_cfg.get("endpoint"))
        api_key = _expand_env(src_cfg.get("api_key"))
    except ValueError as e:
        return "", {"error": str(e)}
    model = src_cfg.get("model", "PaddleOCR-VL-1.6")
    optional = src_cfg.get("optional_payload") or {}
    headers = {"Authorization": f"bearer {api_key}"}

    try:
        # 提交
        file_str = str(file_path)
        if file_str.startswith("http"):
            headers["Content-Type"] = "application/json"
            payload = {"fileUrl": file_str, "model": model, "optionalPayload": optional}
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=60)
        else:
            data = {"model": model, "optionalPayload": json.dumps(optional)}
            with open(file_str, "rb") as f:
                resp = requests.post(endpoint, headers=headers, data=data, files={"file": f}, timeout=120)
        if resp.status_code != 200:
            return "", {"error": f"cloud submit HTTP {resp.status_code}: {resp.text[:300]}"}
        job_id = resp.json().get("data", {}).get("jobId")
        if not job_id:
            return "", {"error": f"cloud submit 响应无 jobId: {resp.text[:300]}"}
    except requests.exceptions.RequestException as e:
        return "", {"error": f"cloud 提交网络异常: {e}"}
    except ValueError as e:
        return "", {"error": f"cloud 响应解析失败: {e}"}

    try:
        # 轮询
        t0 = time.time()
        while time.time() - t0 < max_wait_s:
            try:
                r = requests.get(f"{endpoint}/{job_id}", headers=headers, timeout=60)
                data = r.json().get("data", {})
            except (requests.exceptions.RequestException, ValueError) as e:
                time.sleep(5)
                continue  # 网络抖动重试轮询
            state = data.get("state")
            if state == "done":
                jsonl_url = data.get("resultUrl", {}).get("jsonUrl")
                if not jsonl_url:
                    return "", {"error": "cloud job done 但无 resultUrl"}
                break
            if state == "failed":
                return "", {"error": f"cloud job failed: {data.get('errorMsg')}"}
            time.sleep(5)
        else:
            return "", {"error": "cloud job timeout"}

        jr = requests.get(jsonl_url, timeout=60)
        if jr.status_code != 200:
            return "", {"error": f"cloud 结果下载 HTTP {jr.status_code}"}
        lines = jr.text.strip().split("\n")
        texts = []
        for line in lines:
            if not line.strip():
                continue
            try:
                result = json.loads(line)["result"]
            except (json.JSONDecodeError, KeyError) as e:
                continue  # 跳过坏行
            for res in result.get("layoutParsingResults", []):
                texts.append(res["markdown"]["text"])
        if not texts:
            return "", {"error": "cloud job 完成但无 layoutParsingResults"}
        return "\n\n".join(texts), {"source": "cloud", "job_id": job_id}
    except requests.exceptions.RequestException as e:
        return "", {"error": f"cloud 轮询/下载网络异常: {e}"}
    except Exception as e:
        return "", {"error": f"cloud 处理异常: {type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------
def call(name, img_path, prompt=None, temp=0, max_tokens=None, source=None, server_manager=None):
    """Unified engine call. source=None → engine.default_source."""
    try:
        engine, src = get_engine(name, source)
        src_cfg = engine["sources"][src]
        prompt = prompt if prompt is not None else engine.get("prompt", "")
        max_tokens = max_tokens or engine.get("max_tokens", 4096)

        if src == "local":
            if server_manager is not None:
                ensure_local_server(name, server_manager)
            return call_local(engine, src_cfg, img_path, prompt, temp=temp, max_tokens=max_tokens)
        else:  # cloud
            # 目前只支持 PaddleOCR AI Studio job 模式
            return call_cloud_aistudio(engine, src_cfg, img_path)
    except ValueError as e:
        return "", {"error": str(e)}
    except KeyError as e:
        return "", {"error": str(e)}
    except Exception as e:
        return "", {"error": f"{type(e).__name__}: {e}"}
