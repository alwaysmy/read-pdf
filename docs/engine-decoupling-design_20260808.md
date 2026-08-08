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
  engine_config.yaml      # [新] 引擎配置 YAML（本地默认 + 云端示例；可被本机覆盖文件补充）
  engine_config.local.yaml # [可选, gitignore] 本机私有覆盖（换路径/端口/密钥，不提交）
```

### 数据流

**核心抽象：一切引擎都是「url + key 的 server」**——本地引擎和云端引擎本质相同，区别只在于 local 模式需要先确保服务在跑。

```
engines.call("glm", img, prompt)
  ├─ 读配置: endpoint / api_key / message_order / output_format
  ├─ if mode == "local":
  │     server_manager.ensure("glm")   # 唯一多出的环节：检查本地服务，没起就启动
  │     （云引擎跳过此步，直接连远程 url）
  └─ POST {endpoint}/chat/completions   # 本地云端走同一 HTTP 调用路径
```

**要点**：
- `server_manager.ensure()` = 检查端口 → 没服务就 `llama-server` 启动 → 等就绪（与现状逻辑一致，只是独立成模块）
- 云端引擎 `server: null`，ensure 直接跳过 → 天然支持"本机零配置直接调云 API"
- `extract_pdf.py` 永远不直接知道端口/进程/模型路径——它只拿 `engines.call()` 的返回值

---

## 3. engine_config.yaml 格式设计（YAML）

**选型理由**：与 `agents/openai.yaml` 统一、支持注释、嵌套引擎配置可读性好（对比 JSON/TOML 详见 §3.4）。

```yaml
# read-pdf 引擎配置
defaults:
  llama_dir: "D:/llm/llama-b9830-bin-win-cuda-13.3-x64"   # llama-server 目录

engines:
  hybrid:                 # PaddleOCR Hybrid — 图像 PDF 默认（质量最稳）
    mode: local
    endpoint: "http://127.0.0.1:12336/v1"
    api_key: "12345"
    prompt: ""
    max_tokens: 4096
    message_order: image-first
    output_format: markdown   # text|markdown|html
    server:                   # 仅 local 引擎有；cloud 为 null
      exe: llama-server.exe
      model: "D:/llm/PaddlePaddle/PaddleOCR-VL-1.6-GGUF/PaddleOCR-VL-1.6-GGUF.gguf"
      mmproj: "D:/llm/PaddlePaddle/PaddleOCR-VL-1.6-GGUF/PaddleOCR-VL-1.6-GGUF-mmproj.gguf"
      port: 12336
      args: ["-ngl","100","--no-mmap","--no-warmup","-c","32768","-t","8","-np","1"]

  glm:                    # GLM-OCR Q8_0 — 公式/数值表格保真
    mode: local
    endpoint: "http://127.0.0.1:12335/v1"
    api_key: "12345"
    prompt: "Text Recognition:"
    max_tokens: 4096
    message_order: image-first
    output_format: markdown
    server:
      exe: llama-server.exe
      model: "D:/llm/ggml-org/GLM-OCR-GGUF/GLM-OCR-Q8_0.gguf"
      mmproj: "D:/llm/ggml-org/GLM-OCR-GGUF/mmproj-GLM-OCR-Q8_0.gguf"
      port: 12335
      args: ["-ngl","100","--no-mmap","--no-warmup","-c","16384","-t","8","-np","1"]

  dsocr:                  # DeepSeek-OCR — 纯文本扫描件提速（快 45%）
    mode: local
    endpoint: "http://127.0.0.1:12337/v1"
    api_key: "12345"
    prompt: "OCR markdown"
    max_tokens: 8192
    message_order: text-first    # DeepSeek 要求 text 在前
    output_format: markdown
    server:
      exe: llama-server.exe
      model: "D:/llm/ggml-org/DeepSeek-OCR/DeepSeek-OCR-Q8_0.gguf"
      mmproj: "D:/llm/ggml-org/DeepSeek-OCR/mmproj-DeepSeek-OCR-Q8_0.gguf"
      port: 12337
      args: ["-ngl","100","--no-mmap","--no-warmup","-c","8192","-t","8","-np","1"]

  baidu_ocr:              # 百度 OCR — 云引擎（验证云模式）
    mode: cloud
    endpoint: "https://aip.baidubce.com/rest/2.0/ocr/v1/accurate_basic"
    api_key: "${BAIDU_API_KEY}"       # 环境变量注入，不进仓库
    api_secret: "${BAIDU_SECRET_KEY}"
    auth_endpoint: "https://aip.baidubce.com/oauth/2.0/token"
    output_format: text               # 纯文本行（无 Markdown/公式）
    server: null

  cloud_glm:              # 云端 GLM（配置示例，本期不启用）
    mode: cloud
    endpoint: "https://api.bigmodel.cn/api/paas/v4/chat/completions"
    api_key: "${ZHIPU_API_KEY}"
    output_format: markdown
    server: null

# 引擎路由：默认排序（agent 可按场景覆盖）
routing:
  text_pdf: ["pdfmux", "pdfplumber"]        # 文本层 PDF
  image_pdf: ["hybrid", "glm", "dsocr"]     # 图像 PDF 默认优先级
  image_pdf_cloud: ["hybrid", "baidu_ocr"]  # 无 GPU 时的云兜底链（可选启用）
  quality_fallback: ["glm"]                 # 公式/表格质量兜底
```

### 3.1 关键设计点

| 项 | 说明 |
|---|---|
| `mode: local\|cloud` | local 需 `server_manager` 启服务；cloud 直接请求远程，**不发本地进程** |
| `message_order: image-first\|text-first` | GLM 系 image 在前；DeepSeek-OCR 系 text 在前 |
| `output_format: text\|markdown\|html` | 返回值格式。text（如百度 OCR）需自行转 md |
| `api_key: ${ENV_VAR}` | 云端密钥从环境变量读，不进仓库 |
| `server: null` | 云端引擎无本地服务段 |
| `routing` | 默认引擎排序配置化；`image_pdf` 默认仍 hybrid |
| `LLAMA_DIR` | 移到 `defaults.llama_dir`，`server_manager` 用它拼 exe 路径 |

### 3.2 默认引擎排序（解耦后与现状对比）

| 场景 | 现状（代码写死） | 解耦后（routing 配置） |
|---|---|---|
| 文本 PDF | pdfmux+pdfplumber | `routing.text_pdf`（默认不变） |
| 图像 PDF | **hybrid**（代码写死） | `routing.image_pdf`（默认仍 hybrid，但可配） |
| 无 GPU 机器 | 无云兜底 | `routing.image_pdf_cloud` = hybrid→baidu_ocr 自动降级 |
| 公式/表格质量 | agent 手动 `--glm` | `routing.quality_fallback` = glm |

**原则不变**：默认 Hybrid（质量最稳），routing 只是把可选顺序暴露为配置，agent 决策 + 配置兜底结合。

### 3.3 本机覆盖（engine_config.local.yaml，gitignore）

```yaml
# 本机私有覆盖（不提交，改路径/端口/密钥）
engines:
  glm:
    server:
      model: "D:/my/models/GLM-OCR-Q8_0.gguf"
      port: 12335
```

- 提交 `engine_config.local.example.yaml` 作为模板（含占位符，不含真实密钥）
- 加载顺序：`engine_config.yaml` → 合并 `engine_config.local.yaml`（本地优先）

### 3.4 配置格式选型（YAML vs JSON vs TOML）

| 维度 | JSON | YAML | TOML |
|---|---|---|---|
| 注释 | ❌ | ✅ | ✅ |
| 嵌套引擎配置 | ✅ | ✅ 最佳 | ⚠️ 层级深难写 |
| Python 依赖 | 标准库 | PyYAML（paddle 生态已有） | tomllib（3.11+） |
| 与 agents/openai.yaml 统一 | ❌ | ✅ | ❌ |
| 可读性 | 一般 | 最好 | 好 |

**结论**：YAML（与现有 openai.yaml 统一 + 注释 + 嵌套友好）。

---

## 4. 模块职责

### engines.py
- `load_config()`：读 `engine_config.yaml` + 合并 `engine_config.local.yaml`（本地覆盖优先）；`${ENV}` 展开
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
- `engine_config.yaml` 作为新配置源头，`SERVERS` 字典删除后由它接管

---

## 7. 实现步骤（待确认后执行）

```
1. 建 engine_config.yaml + engine_config.local.example.yaml(模板, 提交) + engine_config.local.yaml(gitignore) + engines.py + server_manager.py
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
| 本机覆盖配置失效 | local.yaml 显式合并逻辑 + 加载日志打印生效引擎配置 |

## 8.5 引擎实测对比（2026-08-08，设计依据）

同页（《微弱信号检测》p20，公式+数值表格）三引擎实测：

| 维度 | PaddleOCR Hybrid | GLM-OCR | DeepSeek-OCR |
|---|---|---|---|
| 公式（下标保真） | ✅ `$SNR_{p}$`、`$$\frac{...}{...}$$` | ✅ `$SNR_{\mathrm{p}}$` | ❌ `SNR` 丢下标、`SNR_r` 误识 |
| 数值表格 | ✅ HTML `<table>` 数据正确、无幻觉 | ✅ Markdown 表正确 | ❌ 整行重复幻觉 |
| 表头 | ✅ | ✅ | ❌ 丢失 |
| bbox 注释 | ✅ 每块带 | ❌ | ❌ |
| 章节标题 | ✅ `### 第1章` | ⚠️ 部分 | ✅ 页码+标题 |
| 速度/页 | ~2.5s | ~2.1s | **~1.4s（最快）** |

**结论**：公式/表格质量 **Hybrid ≈ GLM > DeepSeek**；速度 **DeepSeek > GLM > Hybrid**。Hybrid 表格带 HTML+bbox 略优，GLM 公式编号格式更规范。默认引擎维持 Hybrid（质量最稳），DS 仅作纯文本扫描件提速备选。

## 8.6 版面分析与 OCR 合并 — 修正说明（2026-08-08）

**问题**：曾设想"`--layout` 检测 → 裁剪 → 单送 VL 识别"的两级流水线。实测后废弃。

**实测证据**：
- PaddleOCR-VL Hybrid 的 `parsing_res_list` **本来就含空块**（检测到但无识别内容的块，如 image/chart）——同页 31 块中有 5 个空块，label+bbox 都在
- 丢失的只是 `extract_hybrid()` 的 `if content:` 输出过滤，**版面检测与识别本就是同一管线一体完成**

**修正结论**：
- **不需要"合并两个流程"**——它们是同一个流程（PP-DocLayoutV3 检测 → VL 识别）
- **正确做法**：改 `extract_hybrid()` 输出——去掉 `if content:` 过滤，同时输出所有块（label+bbox+content）+ table/image/chart 裁剪图 → 一次搞定"位置+内容+截图"
- **原两级流水线方案的风险**：重复检测（--layout 一遍 + Hybrid 内部一遍）+ 裁剪丢页面上下文 → 准确率下降，已废弃
- `--layout` 独立模式保留：纯版面分析、CPU 可跑、不启动服务（轻量场景）

**实施**：见 §7 实现步骤补充——`extract_hybrid()` 输出改造（合并项）。

## 9. 决策记录与待办

**已决策（2026-08-08）：**
- ✅ 配置格式：**YAML**（与 agents/openai.yaml 统一，§3.4 有对比）
- ✅ 云引擎：本期**只做 baidu_ocr 验证**（云模式框架 + 真实调用），cloud_glm 保留配置示例不启用
- ✅ 本机覆盖：`engine_config.local.yaml` **放仓库但 gitignore**，提交 `engine_config.local.example.yaml` 模板
- ✅ **配置集中原则**：所有配置（引擎/路由/服务参数）集中在 `read-pdf/` 下，不撒到用户目录——小工具易维护

**待办：**
- [ ] 傅师傅注册百度智能云 OCR → 提供 API Key/Secret Key → 填入 `engine_config.local.yaml` 或环境变量 → 真测 baidu_ocr 引擎
