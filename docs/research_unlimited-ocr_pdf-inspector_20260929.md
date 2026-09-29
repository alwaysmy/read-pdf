# 候选方案调研：Unlimited-OCR (vLLM) 与 firecrawl/pdf-inspector

- 调研日期：2026-09-29
- 状态：调研完成；Unlimited-OCR 已本机实测（llama.cpp 路线，见文末实测记录）；pdf-inspector 未实测
- 历史记录核查：全盘文件名 + 文件内容搜索（`unlimited-ocr` / `pdf-inspector` / `firecrawl`）均为 0 命中，本机此前**没有**这两个方案的调研记录。

## 现有基线（对比参照）

| 路径 | 引擎 | 速度 | 备注 |
|---|---|---|---|
| 文本层 PDF | pdfmux + pdfplumber 双引擎 | ~0.85s/页 | 现默认 |
| 图像 PDF（默认） | PaddleOCR Hybrid（PP-DocLayoutV3 版面检测 + PaddleOCR-VL-1.6 GGUF VL 识别） | ~2.5s/页 | ~2.4GB VRAM，Markdown+HTML+bbox |
| 备用 | GLM-OCR / DeepSeek-OCR / PaddleOCR AI Studio 云 API | — | 降级兜底 |

---

## 方案 A：Unlimited-OCR + vLLM 部署

- 仓库：https://github.com/baidu/Unlimited-OCR （25.4k stars，MIT，2026-06-22 发布）
- 模型：`baidu/Unlimited-OCR`（HF），arXiv 2606.23050
- vLLM 官方 recipe：https://recipes.vllm.ai/baidu/Unlimited-OCR

### 官方事实

| 项 | 值 |
|---|---|
| 架构血统 | DeepSeek-OCR 系：DeepEncoder（SAM-ViT-B + CLIP-L）+ linear MLP projector，gundam 视觉栈（base_size=1024 / image_size=640 / crop，最多 32 local crops） |
| 语言 backbone | DeepSeek-V2 MoE（vLLM 文档标注 64 routed experts）；媒体口径总参 3B、激活 ~570M；vLLM recipe 元数据写 "dense 3B" —— **官方标注互有出入，实测时以 HF config.json 为准** |
| 参数规模（第三方评论口径） | ~4B MoE（官方媒体口径 3B 总参/570M 激活，待 config.json 核实） |
| 核心机制 | R-SWA（Reference Sliding Window Attention）：视觉 token 常驻、文本滑窗，KV cache 恒定 → 长文档解析速度不衰减；可一次喂 40+ 页 |
| OmniDocBench | v1.5 综合 93.23（DeepSeek-OCR 87.01 / DeepSeek-OCR2 89.17）；v1.6 综合 93.92（发布时 SOTA）；公式 CDM 92.61、表格 TEDS 90.93、文本编辑距离 0.038、读序编辑距离 0.045 |
| 参照 | PaddleOCR-VL-1.5（0.9B）OmniDocBench v1.5 达 94.5（2026-01 发布），榜单口径更高；本 skill 现用 VL-1.6 GGUF + hybrid 管线 |
| 许可 | MIT |

### vLLM 部署要点（不满足则输出为空，注意）

- 专用镜像：`vllm/vllm-openai:unlimited-ocr`（CUDA 13.0；Hopper 用 `-cu129`），架构未进稳定 pip wheel
- 必须注册 n-gram logits processor：`--logits_processors vllm.model_executor.models.unlimited_ocr:NGramPerReqLogitsProcessor`
- prompt 必须以字面 `<image>` 开头（如 `<image>document parsing.`），**无 chat template**
- `skip_special_tokens=False`；请求侧 `vllm_xargs: {ngram_size: 35, window_size: 128}`
- 建议 `--no-enable-prefix-caching --mm-processor-cache-gb 0`
- 显存：官方标 ≥8GB 即可 BF16；decode 侧 n-gram logits processor 防重复循环

### 第三方评论记录（2026-09-29 引述，**非本机实测，待验证**）

来源：网络社区评论，硬件为 RTX 4080 16GB（非本机）。本机实测环境为 **RTX 5070 Ti 16GB**。

| 项 | 评论内容 |
|---|---|
| 配置 | gpu_utilization=0.9，vLLM 部署，f16 |
| 并发 16 页 | 30 页/分（吞吐 ≈ 0.5s/页） |
| 并发 20 页 | 无上下文溢出，速度无提升（16 为甜点） |
| 输出格式 | 解析格式稳定保证，后处理简单（vibe coding 级别即可） |
| 覆盖元素 | 公式、表格、图片、标题、页眉、页脚、页码均可解析 |
| raw 文件 | vLLM 导出 raw 可按 label 自定义后处理策略 |
| 定位 | 正文 parsing 质量 top1 |
| 弱项 | 复杂布局（花哨目录页、动态分栏）需视觉理解，后训练特化后 VQA/视觉理解退化；参数才 4B 还是 MoE |

### 已知弱项

- **复杂布局页面**（排版花哨的目录页、动态分栏页）：这类页面需要视觉理解能力；Unlimited-OCR 后训练将能力特化为解析，VQA / 视觉理解明显退化。
- 本 skill 测试语料以技术书 / 教材扫描件为主（目录页、分栏页常见），弱项命中率可能不低 —— 实测时须专项覆盖。

---

## 方案 B：firecrawl/pdf-inspector

- 仓库：https://github.com/firecrawl/pdf-inspector （19.4k stars，MIT，553 commits）
- 形态：**Rust 库**，绑定 Python / Node.js / 浏览器 WASM / CLI（`pdf2md`、`detect-pdf`）
- `pip install pdf-inspector` / `npm install @firecrawl/pdf-inspector`

### 定位与能力

面向"文本层 PDF 快速本地提取 + 智能路由"，**不是 VLM 方案**：

| 能力 | 细节 |
|---|---|
| 智能分类 | TextBased / Scanned / ImageBased / Mixed，10-50ms（采样内容流，可配 Sample(8)/EarlyExit/Full），返回置信度 + `pages_needing_ocr` 逐页路由 |
| 文本提取 | 位置感知（字体、X/Y、自动多栏阅读顺序）、旋转文本保真、CID 字体 ToUnicode CMap、编码异常自动标记 |
| Markdown | H1-H4（字号层级）、粗斜体、列表、代码块（等宽字体）、表格、URL、连字符重组、TOC 点线折叠、首字下沉合并 |
| 表格 | 双模式：绘图算子矩形检测（union-find）+ 文本对齐启发式；跨页续表 |
| 选择性 OCR | 本地 PP-OCRv6 Small（仅对路由页渲染 OCR），PDFium + ONNX Runtime 外部依赖，干净文本 PDF 不加载 OCR 运行时 |
| 速度 | 文本层 PDF 单文档 <200ms；opendataloader-bench 200 docs 全量 **0.470s**（M4 Pro） |

### Benchmark（opendataloader-bench，200 PDFs，无 OCR，分数 0-1）

| Engine | Overall | Reading Order | Tables (TEDS) | Headings | Speed |
|---|---|---|---|---|---|
| **pdf-inspector** | **0.875** | **0.915** | **0.814** | 0.788 | **0.470s** |
| liteparse | 0.873 | 0.913 | 0.693 | **0.811** | 0.750s |
| opendataloader | 0.831 | 0.902 | 0.489 | 0.739 | 2.569s |
| pymupdf4llm | 0.735 | 0.886 | 0.401 | 0.424 | 17.117s |
| markitdown | 0.589 | 0.844 | 0.273 | 0.000 | 16.165s |

注意：该 benchmark 仅覆盖**文本层 PDF**（OCR 关闭），扫描件质量不在其优势范围。

### 已知弱项

- 扫描件 OCR 仅 PP-OCRv6 Small（det+rec 老管线），远弱于现有 PaddleOCR Hybrid 的 VL 识别；
- 无视觉理解 / 版面语义能力，复杂版面靠启发式（多栏检测、字号聚类），花哨排版同样吃力。

---

## 与现有方案对比（纸面结论，未实测）

### 1. pdf-inspector → 文本层路径（vs pdfmux + pdfplumber）

| 维度 | 现状 | pdf-inspector | 判断 |
|---|---|---|---|
| 速度 | ~0.85s/页 | <200ms/整文档（文本层） | **显著更快** |
| 阅读顺序/多栏 | pdfplumber 无语义版面 | 自动多栏 reading order | **更强** |
| 表格 | 文本层拉线表格一般 | 矩形+启发式双模式（TEDS 0.814） | **更强** |
| 分类路由 | 粗粒度（文本层判定） | 4 类分类 + **逐页 OCR 路由**（Mixed 文档每页决定走文本还是 OCR） | **新增能力，混合文档是现方案盲区** |
| 集成成本 | 已有 | pip 即装，API 简单（`process_pdf` 返回 type + markdown） | 低 |

**初步判断：值得优先实测替换文本层路径**，即使不全量替换，其分类器 + 逐页路由也可作为 pipeline 前置分诊。

### 2. Unlimited-OCR → 图像路径（vs PaddleOCR Hybrid）

| 维度 | 现状（PaddleOCR Hybrid） | Unlimited-OCR + vLLM | 判断 |
|---|---|---|---|
| 吞吐 | ~2.5s/页（本地管线逐页） | 评论：30 页/分 @并发16（4080 vLLM）；**本机实测：42.7 页/分 @并发16（5070 Ti llama.cpp）** | 快约 5-7 倍 |
| 正文质量 | VL-1.6 + 版面检测，现方案最稳 | OmniDocBench v1.6 93.92 SOTA 口径，公式/表格/页眉页脚页码全解析 | 纸面更强 |
| 复杂布局（目录页/动态分栏） | 版面检测模型逐块处理，表现稳定 | **弱项**（后训练特化牺牲 VQA/视觉理解） | 现方案可能反超 |
| 后处理 | 管线输出 Markdown+HTML+bbox | raw + label 可自定义后处理策略 | 灵活性更高 |
| 部署 | 本地 GGUF + Python，无常驻服务 | **vLLM 常驻服务**（专用 docker 镜像 + 特定 prompt/decode 配方） | 成本更高，需守配方 |
| 显存 | ~2.4GB | ≥8GB 官方下限（16G 单卡 + gpu_util 0.9 已实测跑通） | 与现有 llama-server 等共存需注意显存预算 |

**初步判断：值得实测，但不建议直接替换默认** —— 弱项（复杂布局）恰好命中本 skill 的教材/技术书语料；适合大批量吞吐优先的场景，或按页型路由（正文页走 Unlimited-OCR、目录/花哨布局页回退 Hybrid）。

### 综合建议（待实测验证）

1. **优先级 1**：pdf-inspector 接入文本层路径试验（成本最低、收益确定性最高，附赠分类路由能力）。
2. **优先级 2**：Unlimited-OCR vLLM 冒烟 + 小样本对比，专项覆盖目录页 / 分栏页；验证 raw label 后处理管线。
3. 两者互补而非互斥：pdf-inspector 管文本层 + 分诊，Unlimited-OCR 管正文扫描页吞吐，复杂布局页保留现 Hybrid 引擎 —— 三路由混合是纸面上的最优形态。

## 本机实测记录（2026-09-29，RTX 5070 Ti 16GB，llama.cpp 路线）

**路线变更：不用 docker/vLLM，改用本地 llama.cpp**（傅师傅指示）。llama.cpp b10639 已支持 `deepseek2-ocr` 架构（PR #24969），HF 现成 GGUF：`vimalnakrani/unlimited-ocr-gguf`（BF16 语言模型 5.47GB + mmproj F16 0.77GB，走 hf-mirror 镜像下载）。

### 关键用法结论（缺一则输出异常）

1. **image-first**：`content` 数组图片必须放第一位（media marker 落 prompt 开头，与 vLLM 配方 `<image>` 开头同源）。text 在前 → 199 字符后陷入重复循环（`人工智能技术的研究与应用` 循环数百次直至打满 max_tokens）。
2. **不传 `--chat-template deepseek-ocr`**：llama.cpp b10639 server 的 OpenAI 路径下该模板丢失 media marker → HTTP 400 `Failed to tokenize prompt`。`mtmd-cli` 路径正常（CLI 自动注入 marker），server 路径请留空模板。
3. **n-gram 防循环**：vLLM 的 `NGramPerReqLogitsProcessor` 在 llama.cpp 无等价物；`repetition_penalty 1.08` 止不住循环（反而更早崩）。**正确 prompt 顺序下模型自然 EOS（finish=stop），无需额外抑制** —— 循环是 prompt 错误的症状，不是常态风险。
4. 特殊 token `<|det|>`/`<|/det|>` 被 server 过滤，坐标以 `label [x1,y1,x2,y2]` 裸露形式输出；label 驱动的后处理需自行包装。

### 实测吞吐（BF16，微弱信号检测教材 150dpi，页 5-20）

| 场景 | 配置 | 结果 |
|---|---|---|
| 串行 | np=1 | **1.38 s/页**（6 页 8.3s，单页 0.85-1.7s，全部 finish=stop） |
| 16 并发（排队） | np=1 | 28.3 页/分（33.9s / 16 页） |
| 16 并发（真并发） | **np=4, ctx 24576** | **42.7 页/分**（22.5s / 16 页，ok=16） |
| 显存 | np=4 | 9.5 GB（BF16 + mmproj + 4 槽 KV） |
| 对照第三方评论 | 4080 vLLM f16 | 30 页/分 @16 并发 → 本机数据**不虚**，且更高 |

### 质量初查（页 5 正文页，与 Hybrid 同页对比）

- 正文内容与 PaddleOCR Hybrid 输出**逐字一致**（该页纯文本），无识别错误。
- 格式体系不同：unlimited 为 `label [bbox]内容`（label 驱动），hybrid 为 Markdown + `<!-- bbox=... -->` 注释。
- 单页 tokens：unlimited ~550-680（带 bbox），hybrid ~585；页 7（内容稀疏页）205 tokens。
- 表格/公式页与复杂布局页（目录页/分栏页，评论所述弱项）**尚未覆盖**，待专项实测。

### 本机 Hybrid 基线复测（同日，附带修复）

| 项 | 结果 |
|---|---|
| 修复 1 | `defaults.llama_dir` 指向已删除的 `llama-b9830` → engine_config.local.yaml 覆盖为 `llama-b10639-bin-win-cuda-13.3-x64` |
| 修复 2 | llama.cpp CUDA build 找不到 `cublas64_13.dll` → **静默 CPU 回退**（10.74s/页、GPU 0%）；CUDA v13.4 `bin\x64` 未在 PATH → 已加入用户 PATH + 启动 shell 显式注入 |
| 修复后端到端 | **2.32s/页**（差分法：12页 48s vs 6页 34.1s），与历史 2.5s/页基线吻合 |
| 修复前实测 | 10.74s/页（CPU 回退）、首请求 62.5s（CUDA JIT） |

### 实测脚本与数据（留痕）

- `tests/bench_hybrid_latency_20260929.py` — Hybrid 单请求延迟分解
- `tests/bench_unlimited_ocr_latency_20260929.py` — Unlimited 单页冒烟
- `tests/bench_unlimited_batch_20260929.py` — 串行/并发批量测速
- `TEST_RESULTS/read-pdf-bench_20260929/`（ChatWorkspace）— JSON/MD/日志输出

## 待实测清单（2026-09-29）

- [ ] pdf-inspector：`pip install` 后对现有文本层测试样本跑 `process_pdf`，比对 markdown 质量与耗时
- [ ] pdf-inspector：Mixed 文档逐页路由结果人工核对
- [x] Unlimited-OCR 冒烟：llama.cpp BF16 跑通（替代 vLLM docker 路线），吞吐已测（1.38s/页串行、42.7 页/分 @16并发 np4）
- [ ] Unlimited-OCR：与 PaddleOCR Hybrid 同样本对比（正文页 + **目录页 + 分栏页**分组统计，弱项专项）
- [ ] Unlimited-OCR：raw label 后处理策略 PoC（`<|det|>` 标签被 server 过滤，需补包装）
- [ ] HF `config.json` 核实实际参数量（官方口径 3B/4B/MoE 不一）
- [ ] Unlimited-OCR 集成进 engine_config（现为手动起服务，端口 12338）
