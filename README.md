# read-pdf

PDF 提取 skill：文本层提取（pdfmux + pdfplumber）→ OCR 引擎（PaddleOCR Hybrid / GLM-OCR / DeepSeek-OCR）→ 版面分析（PP-DocLayoutV3）→ 抽取缓存。

## 功能

- **文本 PDF**：pdfmux + pdfplumber 双引擎（~0.85s/页）
- **图像 PDF（默认）**：PaddleOCR Hybrid（版面检测 + 识别后端；**后端由配置决定**，见下表下方说明）
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
| PaddleOCR Hybrid | ~2.5s（有能力的 GPU） | ✅ 最好 | 图像 PDF 默认 |
| GLM-OCR | ~2.1s | ✅ 好（编号规范） | 公式/数值表格 |
| DeepSeek-OCR | ~1.4s | ⚠️ 表格幻觉风险 | 纯文本扫描件提速 |

**Hybrid = 版面检测 + 识别后端**，版面固定用 PP-DocLayoutV3，识别后端由
`engines.hybrid.recognizer.backend` 决定：

| backend | 识别 | 前置条件 | 典型速度 |
|---|---|---|---|
| `llama-cpp` | PaddleOCR-VL GGUF（经 llama-server） | 空闲显存 ≥ 3.5GB | 强 GPU **~2.5s/页**；弱 GPU（如 T1000）30~50s/页 |
| `openvino` / `paddle` | PP-OCRv6（进程内） | 无（`openvino` 需装 `requirements-ov.txt`） | **~3s/页**（paddle-gpu + medium 档） |
| `auto`（默认） | 按 `candidates` 顺序探测取首个可用 | — | 取决于解析结果 |

> **整页耗时 = 版面检测 + 逐版面块的 VL 请求**，而**后者通常占大头**。本机（Quadro T1000，
> 密排 A4 第 1 页共 36 块，整页 40.9 s）实测：
>
> | 组成 | 实测 |
> |---|---|
> | 逐块 VL 请求 | 合计 **31.6 s（77%）**：36 次、均值 878 ms（prompt eval 22.4 s + 生成 9.2 s） |
> | 版面检测 PP-DocLayoutV3 | 热态 **约 3.2 s**（CPU 与 GPU 基本无差；只有冷启动首次 CPU 8.3 s / GPU 3.5 s） |
>
> 单次 VL 请求的耗时随显卡差很多：强 GPU（RTX 5070 Ti）**40~80 ms**，弱 GPU（T1000）**约 880 ms**。
> 强 GPU 上一页几十块约 2~3 s，加版面检测即 **2~6 s** 量级——与
> `references/test_log_2026-05-14.md` 的 6.7~7.4 s/页、首版 README 的 `~2.5s/页` 一致；
> 弱 GPU 单次请求就慢十几倍，整页才到 30~50 s。
>
> `defaults.layout_device` 选 `cpu` 还是 `gpu` **不改变结果**（实测两种模式的块数、标签、
> bbox、score 逐块完全一致，bbox 偏差 0.00 px），稳态速度也基本相同——它只影响冷启动的
> 首次加载。
>
> **`auto` 的候选顺序是质量优先（先 llama-cpp）**：PP-OCRv6 与 PaddleOCR-VL 不是一类东西——
> 前者是判别式检测+识别（出文本行），后者是生成式多模态模型（版面语义、表格/公式结构、
> 图表理解）。简单文本页上字符数可以一致，差异要到复杂版式才体现；
> **不要用"同页字符数相同"去论证两者可以互相替代**，也不要据此把 `paddle` 设成默认。

**GPU 不是 hybrid 的前提**——那只是历史上先实现了的后端。没有强 GPU 的机器把
`backend` 设为 `openvino`（Intel）或 `paddle`，或保持 `auto` 让它落到可用者；
固定值时失败即报错、不会静默换后端。实际生效的后端在结果 `recognizer` 字段里
（含 `fallback_from`，记录 auto 跳过了哪些及其原因）。
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
| `cpu`（paddlepaddle） | ~35s | 0.61s | ✅ 与 openvino 同级 | 无（兜底） |
| `openvino`（CPU） | ~4.6s | 0.11s | ✅ 与 paddle 同级 | **须显式配置**；另需 `pip install -r requirements-ov.txt`（运行时与模型已随仓库） |

**后端选择完全由配置决定，不做隐式择优**：`ocr_backend: auto`（默认）只按 `ocr_device` 选 paddle
后端 —— `gpu` → paddle-gpu，`cpu` → paddle-cpu；环境不支持 CUDA 时告警并回退 paddle-cpu。
可用 `ocr_backend: gpu|openvino|cpu` 强制指定。

> **OpenVINO 不会被 `auto` 自动选中。** 模型（`models/`，约 30 MB）和运行时
> （`scripts/ppocr_openvino.py`）虽随仓库分发，但 `auto` 不会因为"装了 openvino 包"
> 就改跑 OpenVINO —— 否则同一份配置在不同机器上会跑出不同后端。要用就显式写
> `ocr_backend: openvino`（有可用 OpenVINO 时 `auto` 会在日志里提示这一行）。
> 想改用自备模型，把 `defaults.ocr_ov_dir` 指过去即可覆盖。
> 加载失败会告警并回退 paddle-cpu，日志里打印 `[ov] 后端: <name>`。
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
