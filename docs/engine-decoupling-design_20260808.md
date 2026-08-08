# read-pdf 引擎解耦设计文档（v1）

- 日期：2026-08-08
- 分支：`feat/decouple-engines`
- 状态：**设计稿，未实现**（傅师傅确认后开发）

---

## 1. 背景与问题

当前 `extract_pdf.py` 单文件耦合了三件事：

1. **服务启停**：`SERVERS` 字典（含 `LLAMA_DIR`、模型路径、端口、`api-key`）+ `start_server/ensure_server/stop_all_servers`
2. **API 调用**：`http_extract`/`http_extract_text_first` 硬编码端口（12334/12335/12336/12337）
3. **业务逻辑**：CLI 解析、页面渲染、引擎路由、输出组装、缓存、版面检测

问题：
- 引擎只能在**本机本地**跑（模型路径/端口写死）
- 想切换云 API 必须改代码
- 本机配置（如换模型路径、换端口）无法单独调整而不动代码
- 文件已 900+ 行，维护困难

**目标**：服务启停与 API 调用解耦；调用方只认 **endpoint URL**；本地/云端引擎可混用、可独立切换；本机配置独立于代码。

---

## 2. 目标架构

```
scripts/
  extract_pdf.py          # 业务主流程（CLI、渲染、路由、输出、缓存）—— 不碰进程/端口细节
  engines.py              # [新] 引擎注册表 + 统一 API 调用层（只认 endpoint URL）
  server_manager.py       # [新] 本地服务生命周期（llama-server 启停）；云端引擎跳过
  engine_config.json      # [新] 引擎配置（本地默认 + 云端示例；可被本机覆盖文件补充）
  engine_config.local.json # [可选, gitignore] 本机私有覆盖（换路径/端口/密钥，不提交）
```

### 数据流

```
extract_pdf.py --glm
  └─ engines.get("glm")            # 从 config 读: mode/endpoint/api_key
       └─ if mode == "local":
            server_manager.ensure("glm")   # 确保 llama-server 已启动
       └─ engines.call("glm", img, prompt) # POST {endpoint}/chat/completions
```

**核心原则**：`extract_pdf.py` 永远不直接知道端口/进程/模型路径——它只拿 `engines.call()` 的返回值。

---

## 3. engine_config.json 格式设计

```json
{
  "$schema": "./engine_config.schema.json",
  "engines": {
    "glm": {
      "mode": "local",
      "endpoint": "http://127.0.0.1:12335/v1",
      "api_key": "12345",
      "prompt": "Text Recognition:",
      "max_tokens": 4096,
      "message_order": "image-first",
      "server": {
        "exe": "llama-server.exe",
        "model": "D:/llm/ggml-org/GLM-OCR-GGUF/GLM-OCR-Q8_0.gguf",
        "mmproj": "D:/llm/ggml-org/GLM-OCR-GGUF/mmproj-GLM-OCR-Q8_0.gguf",
        "port": 12335,
        "args": ["-ngl","100","--no-mmap","--no-warmup","-c","16384","-t","8","-np","1"]
      }
    },
    "dsocr": {
      "mode": "local",
      "endpoint": "http://127.0.0.1:12337/v1",
      "api_key": "12345",
      "prompt": "OCR markdown",
      "max_tokens": 8192,
      "message_order": "text-first",
      "server": { ... }
    },
    "baidu_ocr": {
      "mode": "cloud",
      "endpoint": "https://aip.baidubce.com/rest/2.0/ocr/v1/accurate_basic",
      "api_key": "${BAIDU_API_KEY}",
      "api_secret": "${BAIDU_SECRET_KEY}",
      "auth_endpoint": "https://aip.baidubce.com/oauth/2.0/token",
      "server": null
    },
    "cloud_glm": {
      "mode": "cloud",
      "endpoint": "https://api.bigmodel.cn/api/paas/v4/chat/completions",
      "api_key": "${ZHIPU_API_KEY}",
      "server": null
    }
  },
  "defaults": {
    "llama_dir": "D:/llm/llama-b9830-bin-win-cuda-13.3-x64"
  }
}
```

### 关键设计点

| 项 | 说明 |
|---|---|
| `mode: local\|cloud` | local 需 `server_manager` 启服务；cloud 直接请求远程，**不发本地进程** |
| `message_order: image-first\|text-first` | GLM 系 image 在前；DeepSeek-OCR 系 text 在前（现有 `http_extract_text_first` 的逻辑） |
| `api_key: ${ENV_VAR}` | 云端密钥从环境变量读，不进仓库（安全） |
| `server: null` | 云端引擎无本地服务段 |
| `engine_config.local.json` | 本机覆盖：合并进主配置，改路径/端口/加引擎不提交 |
| `LLAMA_DIR` | 移到 `defaults.llama_dir`，`server_manager` 用它拼 exe 路径 |

### 本机覆盖示例（engine_config.local.json，gitignore）

```json
{
  "engines": {
    "glm": { "server": { "model": "D:/my/models/GLM-OCR-Q8_0.gguf" } }
  }
}
```

---

## 4. 模块职责

### engines.py
- `load_config()`：读 `engine_config.json` + 合并 `engine_config.local.json`（本地覆盖优先）；`${ENV}` 展开
- `get(name)`：返回引擎配置（mode/endpoint/prompt/message_order）
- `call(name, img_path, prompt=None, temp=0)`：
  - local：先 `server_manager.ensure(name)`，再 POST OpenAI 兼容格式
  - cloud-baidu：先换 token（缓存），POST 表单（`image=base64`）
  - cloud-openai：直接 POST OpenAI 格式
  - 返回 `(text, stats)`
- 保持 `extract_glm()/extract_dsocr()/extract_qwen()/extract_hybrid()` 函数签名兼容（内部改调 `call()`）

### server_manager.py
- 从 `engines` 配置读 `server` 段（不在自己硬编码）
- `ensure(name)` / `stop(name)` / `stop_all()` / `cleanup()`（atexit）
- `is_port_open()` / `start_server()` 逻辑从 extract_pdf.py 平移

### extract_pdf.py（改造）
- 删除 `SERVERS`/`LLAMA_DIR`/`http_extract`/`http_extract_text_first`（移到 engines/server_manager）
- `ensure_server("glm")` 调用改为 `server_manager.ensure("glm")` 或直接由 `engines.call()` 内部处理
- 其余（渲染/路由/输出/缓存/layout）不动

---

## 5. 百度 OCR 云引擎接入细节（验证云模式的样本）

参考官方文档（https://cloud.baidu.com/doc/OCR/s/1k3h7y3db）：

1. **鉴权**：`GET https://aip.baidubce.com/oauth/2.0/token?grant_type=client_credentials&client_id=${BAIDU_API_KEY}&client_secret=${BAIDU_SECRET_KEY}` → 返回 `access_token`（缓存，约 30 天有效）
2. **调用**：`POST https://aip.baidubce.com/rest/2.0/ocr/v1/accurate_basic?access_token=<token>`，表单参数 `image=<base64>`（URL 编码）
3. **响应**：`words_result[]`（`words` + `probability{average,variance,min}`）——置信度结构与本地 PaddleOCR 一致，可直接映射到现有 `stats["confidence"]`
4. **免费额度**：官方免费测试资源（注册领取），适合验证云模式
5. **注意**：百度 OCR 是"纯文本行"输出（无 Markdown/版面结构），定位为**文本层/扫描纯文本兜底**，不等同 GLM 的结构化输出

---

## 6. 向后兼容与迁移

- `extract_pdf.py` 的 CLI 参数（`--glm/--hybrid/--dsocr/--audit` 等）**全部不变**
- 引擎函数签名不变（`extract_glm(img_path) -> (text, stats)`）
- 老行为默认保持：本地引擎配置与现有 SERVERS 完全一致（同路径同端口）
- `engine_config.json` 作为新配置源头，`SERVERS` 字典删除后由它接管

---

## 7. 实现步骤（待确认后执行）

```
1. 建 engine_config.json + engine_config.local.json(示例, gitignore) + engines.py + server_manager.py
2. extract_pdf.py 改造：
   - 删 SERVERS/LLAMA_DIR/http_extract/http_extract_text_first
   - ensure_server 调用 → server_manager
   - extract_* 函数 → engines.call()
3. 语法检查 + 本地回归：GLM 跑 1 页（确认与现有输出一致）
4. 云模式验证：baidu_ocr 引擎跑 1 页（确认不启本地服务、token 流程通、输出可解析）
5. 混合验证：同 PDF 本地 GLM + 云 baidu_ocr 各 1 页（确认互不干扰）
6. 提交 + 更新 SKILL.md（引擎配置说明 + 云引擎用法）
```

## 8. 风险与边界

| 风险 | 对策 |
|---|---|
| 云端 API 密钥泄露 | `${ENV}` 占位 + `.gitignore` 本地配置；README 提示 |
| 百度 OCR 无版面/公式 | 定位为文本兜底引擎，SKILL.md 说明适用场景 |
| 大改动影响现有流程 | 引擎函数签名不变；本地回归测试保底；worktree 分支开发，cherry-pick 决策 |
| 本机覆盖配置失效 | local.json 显式合并逻辑 + 加载日志打印生效引擎配置 |

## 9. 待傅师傅确认

- [ ] 引擎配置用 JSON（本方案）还是 YAML？（现有 `agents/openai.yaml` 是 YAML，可统一）
- [ ] 云引擎本期是否只做 baidu_ocr 一个（验证云模式）+ 保留 cloud_glm 配置示例但不启用？
- [ ] `engine_config.local.json` 放仓库（gitignore）还是放用户目录（如 `~/.config/read-pdf/`）？
