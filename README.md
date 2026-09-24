# read-pdf

PDF 提取 skill：文本层提取（pdfmux + pdfplumber）→ OCR 引擎（PaddleOCR Hybrid / GLM-OCR / DeepSeek-OCR）→ 版面分析（PP-DocLayoutV3）→ 抽取缓存。

## 功能

- **文本 PDF**：pdfmux + pdfplumber 双引擎（~0.85s/页）
- **图像 PDF（默认）**：PaddleOCR Hybrid（版面检测 + VL 识别，~2.5s/页）
- **备选 OCR**：GLM-OCR（公式/数值表格保真）、DeepSeek-OCR（纯文本扫描件提速 ~45%）
- **版面分析**：`--layout` 定位表格/示意图 → 裁剪存图 + 布局 JSON（PP-DocLayoutV3，GPU 0.06s/页）
- **抽取缓存**：默认开启，二次处理免 OCR（0.0s）
- **云源**：PaddleOCR AI Studio 云 API（同款模型，无 GPU 兜底）

## 快速开始

> ⚠️ **新用户必读**：本工具依赖本地 llama-server + GGUF 模型（或云源），**不能 clone 即用**。
> 完整安装/配置步骤见 **[docs/SETUP_GUIDE.md](docs/SETUP_GUIDE.md)**（装依赖 → 下模型 → 改 `engine_config.local.yaml` → 验证）。

```powershell
# 文本 PDF（无需模型/GPU，clone 后装好依赖即可用）
python scripts/extract_pdf.py book.pdf

# 图像 PDF（默认 hybrid 引擎）
python scripts/extract_pdf.py scan.pdf --pages 1-10
```

## 服务模式（本体 + MCP，阶段 1）

read-pdf 可独立运行为 HTTP 服务，供 MCP 客户端 / 插件调用（详见 `docs/server-design_20260808.md`）：

```powershell
# 1. 启动本体服务（默认 http://127.0.0.1:8123，端口见 engine_config.yaml 的 server 段）
python scripts/server.py

# 2. 以 MCP server 接入任意 MCP 客户端
python scripts/mcp_server.py
```

MCP 工具：`extract_pdf` / `layout_pdf` / `list_engines`。

# 图像 PDF（默认 hybrid）
python scripts/extract_pdf.py scan.pdf

# 指定引擎
python scripts/extract_pdf.py scan.pdf --glm        # 公式/表格保真
python scripts/extract_pdf.py scan.pdf --dsocr      # 纯文本扫描件提速
python scripts/extract_pdf.py scan.pdf --hybrid     # 默认混合引擎
python scripts/extract_pdf.py scan.pdf --ov         # 本地轻量引擎：官方 PaddleOCR v6（缓存模型），
                                                    # 无 GPU/llama-server 也可用；无 paddle 时自动回退 OpenVINO v6
python scripts/extract_pdf.py scan.pdf --ov --fast  # 强制 OpenVINO v6 后端（~5x 快，密排小字质量略降）

# 版面分析（表格/示意图定位+裁剪）
python scripts/extract_pdf.py scan.pdf --layout --pages 1-10

# 切云源（需 token）
python scripts/extract_pdf.py scan.pdf --source cloud
```

输出默认写入 `{pdf_name}_output/{pdf_name}.md`，版面分析在 `{pdf_name}_output/layout/`。

## 配置

引擎配置集中在 `engine_config.yaml`（本地/云双源），本机私有覆盖用 `engine_config.local.yaml`（gitignore）。详见 `docs/engine-decoupling-design_20260808.md`。

## 引擎对比（实测）

| 引擎 | 速度 | 公式/表格 | 定位 |
|---|---|---|---|
| pdfmux+pdfplumber | ~0.85s | 文本层 | 文本 PDF 默认 |
| PaddleOCR Hybrid | ~2.5s | ✅ 最好 | 图像 PDF 默认 |
| GLM-OCR | ~2.1s | ✅ 好（编号规范） | 公式/数值表格 |
| DeepSeek-OCR | ~1.4s | ⚠️ 表格幻觉风险 | 纯文本扫描件提速 |
| ov（本地轻量） | ~1-2s | ⚠️ 一般（纯文本行） | 无 GPU/llama-server 场景 |
| 云 PaddleOCR-VL-1.6 | ~9.3s | ✅ 与本地同 | 无 GPU 兜底 |
