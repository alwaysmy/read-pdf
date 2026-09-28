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
python scripts/extract_pdf.py scan.pdf --ov         # 本地轻量引擎：官方 PaddleOCR v6（模型已缓存），
                                                    # 进程内 CPU OCR，无 GPU/llama-server 也可用；det+rec 纯文本行，无版面

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
| ov（本地轻量） | 见下（后端自动择优） | ⚠️ 一般（纯文本行） | 无 GPU/llama-server 场景 |
| 云 PaddleOCR-VL-1.6 | ~9.3s | ✅ 与本地同 | 无 GPU 兜底 |

> **速度口径**：除 ov 行外为历史实测（小图 / 单页量级），本轮未复测。
> ov 行为 2026-09-24 本机实测 —— 小图 7 张（320×120 ~ 780×560）、整页 A4
> （150dpi、约 1275×1650、约 117 个识别行）。

### ov 后端自动择优

`--ov` 有三种后端，由 `defaults.ocr_backend` 控制（默认 `auto`，按 `gpu > openvino > cpu` 择优）：

| 后端 | 整页 A4 | 小图 | 识别质量 | 前置条件 |
|---|---|---|---|---|
| `gpu`（paddlepaddle-gpu） | **~2.0s** | 0.07s | ✅ 与 openvino 同级 | CUDA 版 paddlepaddle + 可用 GPU |
| `openvino`（CPU） | ~4.6s | 0.11s | ✅ 与 paddle 同级 | `pip install -r requirements-ov.txt`（运行时与模型已随仓库，无需另备） |
| `cpu`（paddlepaddle） | ~35s | 0.61s | ✅ 与 openvino 同级 | 无（兜底） |

`auto` 的选择顺序：`ocr_device: gpu` 且 paddle 有 CUDA 设备 → `gpu`；否则 OpenVINO 模型可用 → `openvino`；再否则 `cpu`。
可用 `ocr_backend: gpu|openvino|cpu` 强制指定。加载失败会逐级降级并在日志打印 `[ov] 后端: <name>`。

> **运行时与模型都随仓库分发。** `scripts/ppocr_openvino.py`（前后处理与 PaddleOCR
> 官方实现逐条对齐）和 `models/`（PP-OCRv6 small det/rec 的 ONNX + 字典，约 30 MB）
> 都在仓库内，clone 下来装好依赖即可用，无需另行准备模型。
> 想改用自备模型，把 `defaults.ocr_ov_dir` 指过去即可覆盖；
> 未装 `openvino` 包时 `auto` 会静默跳过 openvino 回退 `cpu`，不影响其他后端。
>
> **依赖声明注意**：`paddlex` 的检测后处理（`DBPostProcess`）在**运行时**要求
> `pyclipper` 与 `opencv-contrib-python`，但其 pip 元数据并未声明（实测 `Required-by` 为空），
> 因此两者已显式写进 `requirements.txt` —— 否则全新环境装完 paddleocr 后，文本检测会直接拒绝加载。

### 模型规格（`defaults.ocr_model_tier`）

PP-OCRv6 有 tiny / small / medium 三档（**无 large**），默认 `small`（即仓库内 `models/` 那一档）。
只作用于 paddle 后端；OpenVINO 后端目前只有 small 的 ONNX，配 medium 会被忽略并在日志提示。

| 输入 | `small`（默认） | `medium` |
|---|---|---|
| 干净 150dpi 整页 A4 | **2.67s**，conf 0.984/0.75 | 4.97s（1.9x），conf 0.983/0.80 |
| 劣质 96dpi 整页 A4 | 2.02s，conf 0.955/**0.32** | 4.40s，conf **0.978/0.63** |
| 极差 72dpi 整页 A4 | 1.93s，conf 0.952/**0.00** | 3.88s，conf 0.962/**0.46** |

干净文档用 `small` 即可（medium 慢约 2x 而基本无收益）；**扫描质量差、或遇手写 / 异体字时
切 `medium` 更划算** —— 96dpi 下 small 会产出 `Aallalble`、`T max.` 这类垃圾行，medium 则读对。
medium 权重约 132 MB（det 59 + rec 73），首次使用由 PaddleX 自动下载并缓存。

**OpenVINO 后端的前后处理已与 PaddleOCR 官方实现逐条对齐**：检测的缩放与
`DBPostProcess` 参数取自模型 `inference.yml`（`limit_side_len=736/min`、`thresh=0.2`、
`box_thresh=0.45`、`unclip_ratio=1.4`、不膨胀）；识别按官方 `RecResizeImg` 缩放后**零填充**
（而非拉伸）；字典按行读取并追加 `use_space_char` 空格；置信度取字符概率**均值**。
同一密排 A4 页实测两者均为 **117 行、conf 0.98**，残余差异只在个别字形
（`°C`/`℃`、大小写）与空格，个别处 OpenVINO 反而更准。

> 整页耗时随**识别行数**增长，与渲染 dpi 基本无关（CPU 下 dpi 100 与 150 同为 ~23s）。
> `enable_mkldnn` 在 Paddle 3.x + PP-OCRv6 上不可用
> （`NotImplementedError: ConvertPirAttribute2RuntimeAttribute`），这是 paddle CPU 端慢的根因。
