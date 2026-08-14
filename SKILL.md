---
name: read-pdf
description: >-
  Extract text, tables, and structured data from PDF files. Use for reading,
  analyzing, or converting PDF documents. Supports text-layer PDFs (pdfmux +
  pdfplumber) and image/scanned PDFs (PaddleOCR Hybrid). Handles OCR, table
  extraction, formula recognition, and knowledge audit. Default output is
  Markdown (.md); use --json for JSON, --text-only for plain text (.txt).
when_to_use: >-
  When the user provides a PDF file and wants to read, extract, analyze, or
  convert its content. Triggers on: PDF file path, "读PDF", "提取文档",
  "识别PDF", "转文字", "扫描件", "提取表格", "PDF转Markdown", "看看文档",
  "看看手册", "看看PDF", "read this PDF", "parse PDF", "OCR this", 文档提取,
  PDF转换, 文档分析, 表格提取, 手册提取, 说明书提取, 合同提取, 发票提取,
  简历提取, 论文提取, 报告提取, "分析文档", "读取文件", "提取内容",
  "convert PDF", "analyze document", "extract table", "scanned PDF",
  "OCR document", "read manual", "extract datasheet", "parse invoice",
  "extract resume", "read paper". Also when an agent needs to ingest,
  understand, or extract structured data from any PDF document.
user-invocable: true
allowed-tools:
  - PowerShell
  - Read
  - Glob
---

# /read-pdf — Extract text from PDF files

Extract text from PDFs. Python scripts handle extraction; agent handles quality judgment and engine routing.

## Usage examples

```
/read-pdf D:\path\to\document.pdf
/read-pdf --pages 1-10 D:\path\to\document.pdf
/read-pdf --pages 5-10,20-25,30 D:\path\to\document.pdf   # 逗号分隔，跨段选页
/read-pdf --hybrid D:\path\to\document.pdf                  # 强制 PaddleOCR Hybrid
/read-pdf --glm D:\path\to\document.pdf                     # 备用：GLM-OCR Q8_0 direct
/read-pdf --audit D:\path\to\document.pdf                   # Qwen 知识审校（2-3 pages）
/read-pdf --force-ocr D:\path\to\document.pdf               # 扫描版带文本层时强制 OCR

# 备用：直接调脚本（如果 AI 不识别 $read-pdf 触发器）
# python $HOME/.agents/skills/read-pdf/scripts/extract_pdf.py file.pdf
```

---

## 引擎路由逻辑（agent 判断）

### 文本 PDF

**pdfmux + pdfplumber 双引擎**（默认同时输出）：
- **pdfmux**：从文本层重建结构，速度快（~0.85s/页），表格/多栏还原好
- **pdfplumber**：提取原始文本和表格，作为参考核对

PyMuPDF 提取几乎零成本（<0.01s/页），永远先跑一遍。agent 通读判断完整性。

发现内容缺失/乱序后，先确认 VRAM 空闲 >3GB（不够就先关掉非必要的 GPU 进程）。然后：

- **≤10 页**：别找了，直接 `--force-ocr --hybrid` 全扫
- **>10 页**：从已提取的文字中判断哪些章节需要 OCR（表格密集区、公式章节、引脚/寄存器定义、中文混排乱码段），只 OCR 关键部分。除非用户明确要求全部输出

### 页码对齐

PDF 文件内印刷页码（"第 42 页"）可能与物理页码不一致（扉页、目录占位）。内部全部用物理页码（1-based）。当用户提到的页码对不上时，先翻 2-3 页确认偏移量。

### 图像 PDF — 默认 PaddleOCR Hybrid

PaddleOCR Hybrid 覆盖 95% 场景，能保留版面结构、表标题、多栏排版和公式。GLM-OCR 仅作为备用引擎。

| 信号 | 判断 | 重跑命令 |
|------|------|---------|
| Hybrid 把公式/LaTeX 识别乱码或丢编号 | 换 GLM-OCR 验证 | `--glm` |
| Hybrid 整页输出乱序/大面积缺行 | 换引擎交叉验证 | `--glm` 重跑 |

#### 文本 PDF 的表格质量判断

脚本在每页文字后插入 `[TABLES]` 段（pdfplumber 检测到的表格）。agent 判断表格质量：

| 信号 | 判断 | 操作 |
|------|------|------|
| Markdown 表格列对齐、数据正确 | 表格 OK | 保留 |
| 列错位、合并单元格破损、数据错列 | **表格损坏** | `--pages N-M --force-ocr --hybrid` |
| PyMuPDF 有表格内容但 pdfplumber 完全漏掉 | **表格遗漏** | `--pages N-M --force-ocr --hybrid` |
| 单元格内容跨行错位、多行单元格碎片化 | **表格损坏** | `--pages N-M --force-ocr --hybrid` |
| 数值出现在错误列 | **表格损坏** | `--pages N-M --force-ocr --hybrid` |

#### 批量表格失败：先分诊再重跑

当 `[TABLES]` 段超过 30% 为空或破损时，不要盲目全量重跑。按以下步骤：

1. **计数**：破损表格 / 总表格数，报告比例
2. **按内容信号排优先级**：
   - "引脚" / "Pin No." / "Pin Name" → 引脚配置表（**最高**）
   - "Address:" / "Register" / "Bit" / "Reset" → 寄存器映射（**最高**）
   - "Parameter" / "Min" / "Typ" / "Max" / "Unit" → 电气参数（**最高**）
   - "Package" / "Dimension" / "mm" / "mil" → 机械尺寸（中）
   - "Ordering" / "Part Number" → 订购信息（低）
3. **选择**：只对最关键的 3-5 页重跑
4. **报告**：告诉用户哪些页被重跑了、为什么

### 质量判定标准

- 公式编号是否保留 — Hybrid 通常能保留，丢失时切 `--glm` 验证
- 表格列是否对齐、数据是否在正确列
- 专业术语是否合理（物理意义、量纲）— 拿不准时调 Qwen 审校
- 手写/模糊区是否出乱码、内容是否不完整 — 有问题切 `--glm` 重跑
- 对照原文提及的图表编号（"图X"、"表X"），确认输出中包含对应内容

### 自动重跑规则

- **不要问用户要不要修，直接修。**
- 重跑页数 ≤5 页：逐页修
- 重跑页数 >5 页：选最关键的 3-5 页修，报告用户
- **Never overwrite originals**: 重跑前备份原输出到 `{pdf_name}_output/.pre-screen-backup/`。重跑结果更差（0 chars、乱码、短 50%+）时恢复备份。
- **Cross-check after re-run**: 比较重跑前后的 chars/page。如果备用引擎输出明显更差，保留旧版本并记录异常。

### 命令映射

| `/read-pdf` 参数 | 实际命令 |
|------|----------|
| `/read-pdf file.pdf` | `python $HOME/.agents/skills/read-pdf/scripts/extract_pdf.py file.pdf` |
| `--pages 5-10` | `--pages 5-10`（物理页码，1-based，含首尾） |
| `--hybrid` | `--hybrid`（强制 PaddleOCR Hybrid） |
| `--dsocr` | `--dsocr`（DeepSeek-OCR，目录/列表/纯文本扫描件快 27-43%） |
| `--glm` | `--glm`（GLM-OCR Q8_0，公式/数值表格保真） |
| `--audit` | `--audit`（同 `--html`） |
| `--html` | `--html`（同 `--audit`） |
| `--json` | `--json` |
| `--force-ocr` | `--force-ocr`（强制走 OCR，无视文本层） |
| `--text-only` | `--text-only`（文本-only 模式，输出 `{pdf_name}_output/{pdf_name}.txt`） |
| `--keep-servers` | `--keep-servers` |
| `--output-dir DIR` | `--output-dir DIR` |
| `--dpi N` | `--dpi N`（OCR 渲染 DPI，默认 150，低=快） |
| `--no-table` | `--no-table`（跳过 pdfplumber 表格） |
| `--pdfmux` | `--pdfmux`（强制启用 pdfmux，默认 auto） |
| `--no-pdfmux` | `--no-pdfmux`（禁用 pdfmux） |
| `--layout` | `--layout`（版面检测：PP-DocLayoutV3 定位表格/示意图 → 裁剪存图 + 布局 JSON） |
| `--layout-only` | `--layout-only`（只出布局 JSON + 裁剪图，不 OCR） |
| `--layout-min-score N` | `--layout-min-score N`（版面检测最小置信度，默认 0.3） |
| `--layout-device cpu\|gpu` | `--layout-device`（版面检测设备，默认 cpu，GPU 被 OCR 占用时可兜底） |
| `--no-cache` | `--no-cache`（禁用抽取缓存，默认开启） |
| `--refresh-cache` | `--refresh-cache`（强制重跑 OCR 并刷新缓存） |
| `--source local\|cloud` | `--source`（临时切换服务源；云源需 token，仅 hybrid 支持 cloud） |

输出默认写入当前目录的 `{pdf_name}_output/{pdf_name}.md`（`{pdf_name}` = PDF 文件名去 `.pdf`，如 `report.pdf` → `report_output/report.md`）。用 `--output-dir DIR` 可改输出目录。脚本跑完后用 Read 工具打开此文件判断提取质量。
`--pages` 用物理页码（PDF 文件内第 N 页），不是印刷页码。

---

## 引擎速查

| 引擎 | 速度 | VRAM | 输出 | 何时用 |
|------|:--:|:--:|------|--------|
| **pdfmux + pdfplumber** | **~0.85s** | **0** | Markdown+文本层 | **默认（文本 PDF）** |
| **PaddleOCR Hybrid** | **~2.5s** | **~2.4GB** | Markdown+HTML+bbox | **默认（图像 PDF）** |
| GLM-OCR Q8_0 | ~2.1s | ~2.5GB | .md+LaTeX+编号 | 公式/数值表格保真 |
| DeepSeek-OCR Q8_0（`--dsocr`） | ~1.5s | ~3.9GB | Markdown+结构化列表 | 目录/列表/纯文本扫描件（快 27-43%） |
| Qwen 35B | ~48s | ~5.1GB | HTML | 知识审校 |

### 关键引擎说明

**Qwen 是多模态审校，不是纯文本审校。** ~48s/页太慢不做批量。价值在于能**同时看到原图 + OCR 文本**，对照判断。纯文本审校 agent 自己就能做。需要 Qwen 时才调。

`--audit` 固定用 "正确排版输出这一页内容，用HTML格式，不要任何解释和前言。" 做 HTML 提取。但对于审校场景，agent 可以自己构造 prompt 发给 Qwen（/v1/chat/completions），把原页图片 + OCR 提取文本一起喂进去做交叉验证。prompt 怎么写取决于你要验证什么——表格对齐、公式正确性、术语是否误读，不强求固定格式。
**PaddleOCR Hybrid 是默认引擎。** 版面检测 + VL 识别一体化，能处理文本、表格、公式、多栏排版。不要单独用裸 PaddleOCR-VL GGUF，缺了 Python 管线的版面检测（layout detection → block label → bbox），等于自废武功。

**DeepSeek-OCR（`--dsocr`）是速度备选引擎，注意幻觉风险。** 实测比 GLM-OCR 快 27-43%（文本层越多越快），是**目录/列表/纯文本扫描件的结构化强者**（能把目录完整还原成 Markdown 表格，GLM 会漏项）；但**数值表格/公式是弱项**——会丢公式下标、可能整行重复产生幻觉。路由建议：
- 目录页、列表页、纯文本扫描件 → `--dsocr`（快 + 结构好）
- 数学公式、数值表格 → `--glm`（保真）

**`--layout` 版面检测模式（PP-DocLayoutV3）。** 定位表格/示意图区域 → 按 bbox 裁剪存图 → 输出 `{name}_output/layout/{name}_layout.json`（label+bbox+score+page）+ `layout/crops/*.png`。用途：PDF→EPUB 重排、元素提取、版面分析。默认 `--layout-device cpu`（GPU 被 OCR 占用时兜底）。

**抽取缓存（默认开启）。** 每页 OCR 结果缓存到 `{name}_output/.cache/`（key 含 PDF 名/页码/引擎/源/DPI，自动失效），二次处理直接读缓存免 OCR（实测 total_time 0.0s）。`--no-cache` 禁用，`--refresh-cache` 强制重跑。

**服务模式（本体 HTTP + MCP）。** 可独立运行：`python scripts/server.py`（host/port 在 `engine_config.yaml` 的 `server` 段配置，默认 8123；首次启动自动生成 Bearer key 存 `~/.readpdf/key`）→ MCP 客户端经 `mcp_server.py` 接入，工具 `extract_pdf`/`layout_pdf`/`list_engines`。详见 `docs/server-design_20260808.md`。配置（引擎/双源/路由/端口）集中在 `engine_config.yaml`，本机覆盖用 `engine_config.local.yaml`。

### 默认流程

1. 脚本自动检测文本/图像 PDF（--glm/--hybrid 等引擎 flag 可强制覆盖检测结果）
2. 文本 PDF → pdfmux + pdfplumber（~0.85s/页）；图像 PDF → PaddleOCR Hybrid（~2.5s/页）
3. agent 读取 `{pdf_name}_output/{pdf_name}.md`，检查内容完整性、表格、公式
4. 有问题按信号表重跑（最多 5 页），VRAM 够就不要犹豫
5. 专业文档挑 2-3 页 Qwen 终审

### 使用限制

- 除非用户明确要求，OCR 一律用 temp=0（temp>0 会引入随机差异，同页多次输出不一致）
- 禁止用 Qwen 做批量 OCR（~48s/页）
- 禁止在对话中硬编码引擎参数（如 `-ngl`、`-c`、`--port`），这些统一在 `engine_config.yaml` 里管理

## 设计原则

- **脚本做机械，agent 做判断** — 脚本不判质量
- **直走最优** — 不预筛，图像 PDF 直走 PaddleOCR Hybrid
- **不等人** — 发现问题自动修
- **证据驱动** — 参数和定位基于实测

## 服务启动

> 引擎服务由脚本自动管理（`server_manager.py` 按 `engine_config.yaml` 启停，冷启动等 /health 就绪）。
> 手动排障参数已统一收敛到 `engine_config.yaml` 各引擎的 `sources.local.server` 段（exe/model/mmproj/port/args/env）；本机覆盖改 `engine_config.local.yaml`。`python manage_servers.py status` 可查各引擎端口状态。

### GLM-OCR Q8_0（备用引擎）

参数见 `engine_config.yaml` → `engines.glm.sources.local.server`（exe/model/mmproj/port/args）。

### PaddleOCR-VL GGUF（Hybrid 管线默认 VL 后端）

参数见 `engine_config.yaml` → `engines.hybrid.sources.local.server`（exe/model/mmproj/port/args）。

### Qwen 35B（知识审校）

参数见 `engine_config.yaml` → `engines.qwen.sources.local.server`（含 `env` 段的 LLAMA_CHAT_TEMPLATE_KWARGS）。

**HTML 输出保留原始排版。** `--audit`（或等价的 `--html`）输出 Qwen 的 HTML，保留 `<div>` `<table>` 结构，适合复杂排版。默认逐页发。加 `--batch` 把 `--pages` 选中页一次性发给 Qwen 做跨页理解。`--pages` 支持逗号分隔（`5-10,20-25`）。多段跨页用 `--keep-servers` 分多次调用。

### 路径找不到时

如果 llama-server.exe 或模型文件路径不存在，提示用户检查并更新 `engine_config.local.yaml`（`defaults.llama_dir` 和引擎 `model`/`mmproj` 路径），详见 `docs/SETUP_GUIDE.md`。

### VRAM 检查

```powershell
nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader,nounits
```
空闲 >3GB 才能安全启动 OCR 引擎。

### 服务生命周期

- **一次只启一个引擎。** 脚本自动管理时会先关旧再启新，不会同时跑多个。Hybrid（Python 管线 + llama-server ≈ 2.4–3GB）或 Qwen（≈ 5.1GB），8GB 卡够用。所有 OCR 引擎都需要 GPU，CPU 模式不支持，除非用户明确要求且没有 GPU。如果手动同时开，先 `nvidia-smi` 确认空闲 > 总和。
- **taskkill 必须经用户允许才能执行，且只杀自己启动的。** 脚本已自动管理 PID（`proc.pid`）。agent 手动查 PID：`netstat -ano | findstr ":端口"` 最后一列。禁止 `/IM llama-server.exe` 通杀。
