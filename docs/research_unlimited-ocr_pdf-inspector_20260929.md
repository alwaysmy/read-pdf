# 候选方案调研：Unlimited-OCR (vLLM) 与 firecrawl/pdf-inspector

- 调研日期：2026-09-29
- 状态：**调研 + 实测完成**（Unlimited-OCR llama.cpp 路线吞吐与 Q8_0 量化实验、四引擎六页质量对比、pdf-inspector 文本层接入测试，均见文末实测记录）
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

### 性能优化实验：Q8_0 量化（2026-09-29 第二轮）——**质量否决，保持 BF16**

Timing 分解（单请求，np4）：prompt eval 647ms/908tok（1402 tok/s）、decode 1503ms/676tok（449 tok/s，**占 70%**）、mmproj 编码 ~100ms。decode 为 memory-bound → 主攻量化。

| 方案 | 速度 | 显存 | 质量结果 |
|---|---|---|---|
| **BF16（现状）** | 正文 1.38s/页、难页 3.24s/页、并发 42.7 页/分 | 9.5GB | 基准，12 页全稳定 finish=stop |
| Q8_0 无惩罚 | 正文 2.13s/页（-18%→稳态1.14s）、难页 2.37s/页（-27%）、并发 48 页/分（+12%）、p12/p20/p29 内容零差异（bbox ±1px） | 7.0GB（-2.5GB） | **p7 稀疏页概率性循环**（serial 崩 4096 打满 / 并发正常 205tok —— 量化 logits 平坦化后处于循环边缘，调度抖动决定崩不崩） |
| Q8_0 + DRY(m1.5,a-l2) | 正文 1.13s/页 | 7.0GB | p7 修复（与 BF16 逐字一致），但 **p12 符号表尾部碎片化**（"1.38" 断行、"自由空间"→"由空间"） |
| Q8_0 + DRY(m2.0,a-l4) | 1.73s/页 | 7.0GB | p12 仍膨胀 43%（2763→4313ch）；**p7 幻觉**（编造财报"董事会信息披露"文本、"三"字填充） |
| Q8_0 + repeat-penalty 1.1 | — | 7.0GB | p7 丢内容（249 vs 360ch）；**p12 反而循环**（4096 打满 7444ch） |

**结论：Q8_0 提速 18-27%、省 2.5GB，但在本模型上破坏输出稳定性（循环/幻觉/丢内容三类退化轮流出现），任何惩罚补救都引入新伤害 —— 不满足"保证质量"前提，正式保持 BF16。** 无损空间已尽：flash-attn 日志报 `not supported by CUDA0`（sm_120 Blackwell，待 llama.cpp 后续版本），decode 449 tok/s 即当前无损水位。

### 四引擎六页质量对比（2026-09-29，回答"Unlimited-OCR 是否更好"）

样本：微弱信号检测教材 6 个代表页 —— p12 分栏符号表、p13/p17 目录页、p20/p29 表格+公式、p34 密集公式推导。四引擎 = Unlimited-OCR(BF16) / Hybrid(PaddleVL1.6+版面) / GLM-OCR / DeepSeek-OCR，同页并排 + 视觉审查（子代理读图交叉验证 + 逐字文本精读）。

| 排名 | 引擎 | 结论 |
|---|---|---|
| **1** | **GLM-OCR** | 6/6 页第一：目录页缩进+点线+页码零错、p34 公式齐全 LaTeX 正确、p20/p29 表格行列完整数值零错 |
| 2 | Hybrid | 数值/推导可靠；硬伤：p13 标题"目录"→"**日录**"、p12 右栏漏 5 条、`\cos` 丢反斜杠 |
| 3 | **Unlimited-OCR** | 召回最全（唯一带 bbox label、页眉页码几乎不漏）；但 p17 目录页码 336→**335**、p34 **(4) 节整块重复**+互相关嵌套断链、`<table>` 无行列标签结构散架 |
| 4 | DeepSeek-OCR | 错误性质最危险：表格**编造数值**（p20 吉时利行 4 处错值）、公式丢项（1/2π、1−cos）、SNIR→SNR 混淆 |

**直接回答：Unlimited-OCR 不是质量第一** —— 正文页与 Hybrid 打平、结构页（目录/表格/公式）被 GLM 反超。其真实优势 = 最全召回 + label/bbox 结构 + 最高吞吐（42.7 页/分），适合"吞吐优先 + 后处理兜结构"场景；弱项（复杂布局）与调研预期一致。

审查报告：`tests/ocr_engine_visual_review_20260929_183735.md`（含 4 项"无法确认"标注）；并排对比页 `TEST_RESULTS/read-pdf-bench_20260929/compare_p{12,13,17,20,29,34}.html`。

### pdf-inspector 文本层接入实测（v1.23.0，2026-09-29）

样本：`5 高速数据传输系列连接器选型手册.pdf`（261 页文本层）+ 合成 Mixed（3 文本页+3 扫描页）。

| 项 | 结果 |
|---|---|
| 分类 | scanned 0.076s/0.95 ✓；text_based 全书 16.8s/0.62（**全量扫描，需缓存分类结果**）；Mixed 合成 → `mixed` ✓ 0.003s |
| 逐页路由 | 扫描页 `scanned` 准确 ✓；**文本页 `suspected_garbled_text` 误报**（cmap_gaps 空、fitz 原文无 PUA/U+FFFD 乱码，pua=0/repl=0）—— 接入时该类路由须先做文本层质量复检，否则文本页被误送去 OCR 失去速度优势 |
| 表格质量 | **明显优于现状**：首页 8 列表格列对齐正确；pdfmux+pdfplumber 同表**结构散架**（表头错、列内容错位重复） |
| 内容覆盖 | 完整（后段产品型号全有）；现状 pdfmux 输出**系统性 2.4× 膨胀**（合并单元格重复展开 + 页眉计入，"航天电器"×44） |
| 速度 | 纯提取 ~2.3s/15页（0.15s/页，剥离 detect 后）vs pdfmux 管线 45.1s/15页（3.0s/页）→ **约 20 倍**；但 `detect_pdf` 每次调用隐含全书扫描 15.8s，须自行缓存 |
| 小瑕疵 | pdf-inspector 输出末尾一处乱码标题（`### ????`） |

**结论：证实纸面判断（优先级 1）** —— 表格/速度/覆盖三项全胜现状，接入时注意：① 分类与 detect 结果缓存；② `suspected_garbled_text` 路由复检；③ 页眉页脚不提取（与现状输出口径有差异）。

### pdf-inspector 多样本矩阵测试（2026-09-30，12 样本，全 CPU）

样本覆盖 9 类：电子发票、离职证明表单、datasheet×2（双栏）、Xilinx PG054 英文、SCPI 中文手册、中文校准报告、Wireshark 教程、CAD 图纸、ITECH 英文说明书、扫描书、扫描信件。脚本 `tests/bench_pdf_matrix_20260930.py`，数据 `TEST_RESULTS/read-pdf-bench_20260930/pdf_matrix_*.json`。

| 维度 | pdf-inspector | 现状管线（pdfmux+pymupdf+pdfplumber） | 判定 |
|---|---|---|---|
| 分类 | 12/12 正确（9 text_based / 2 scanned / 1 image_based），耗时 0-0.13s | 无此能力 | PI 胜；连接器手册 garbled 误报今早 0 例（**个案而非普遍**） |
| 速度（前 10 页） | **process 4-240ms** | 3.4-53.9s（Wireshark 53.9s、扫描书 48.9s） | **PI 快 1-3 个数量级** |
| 常规正文覆盖 | 96-102%（相对 fitz 文本层），9/10 关键短语与现状并列命中 | 9/10 | 平手偏 PI |
| 表格（拉线表） | datasheet 161 行 / SCPI 77 行 / 报告 66 行 | pdfplumber 同页 **0 表** / 1 / 6 | PI 明显强（pdfplumber 拉线表大量漏） |
| **非常规文本层** | **发票、离职证明表单、CAD 图纸 → markdown 空输出且无任何告警**（11ms 空手而归） | 分别出 1883 / 1009 / 1986 bytes（fitz 底数 343/192/995ch） | **现状胜，PI 硬伤** |
| 表格噪声 | 双栏 datasheet 有 4 行正文被误包进表格（过度表格化） | 正文干净但表格漏 | 各有瑕疵 |

**回答"是否直接替换 pdfmux"**：
1. **接口同形状但非换函数** —— 现状输出是三段拼接（`<!-- PDFMUX OUTPUT -->` 结构化段 + pymupdf `<!-- PAGE n -->` 分页段 + pdfplumber `[TABLES]` 段），下游依赖分页标记。正确替换姿势 = 用 PI 的 `pages` 参数逐页提取拼 `<!-- PAGE n -->`，整体替代三段。
2. **非无脑全替** —— 三类反例（发票/表单/CAD）证明必须加**守门回退**：markdown 为空或覆盖率低于阈值（对照 fitz 快速底数）→ 回退现有 pymupdf 路径。PI 空输出静默无告警是接入时最大的坑。
3. 综合定位：**PI 作主提取器 + 分类路由 + 空输出回退**，而非全面替代；拉线表格场景 PI 显著补短板。

**本轮仍未覆盖**（"各种 PDF"的边界）：加密 PDF、LaTeX 双栏论文、跨页续表书籍、双语混排、旋转页、千页级大书 —— 如需穷尽可第二批补测。

### 实测脚本与数据（留痕）

- `tests/bench_hybrid_latency_20260929.py` — Hybrid 单请求延迟分解
- `tests/bench_unlimited_ocr_latency_20260929.py` — Unlimited 单页冒烟
- `tests/bench_unlimited_batch_20260929.py` — 串行/并发批量测速
- `tests/diff_q8_bf16_20260929.py` — Q8_0 vs BF16 逐页 diff（量化质量验证）
- `tests/locate_sample_pages_20260929.py` / `tests/make_contact_sheet_20260929.py` — 样本页定位（扫描书视觉法）
- `tests/gen_compare_html_20260929.py` / `tests/merge_unlimited_compare_20260929.py` — 四引擎并排对比页
- `tests/bench_pdfinspector_20260929.py` / `tests/check_garbled_20260929.py` — pdf-inspector 分类/提取/garbled 核验
- `tests/bench_pdf_matrix_20260930.py` / `tests/show_matrix_20260930.py` / `tests/spotcheck_datasheet_20260930.py` / `tests/phrase_check_20260930.py` — 12 样本矩阵测试与抽查
- `TEST_RESULTS/read-pdf-bench_20260930/` — 矩阵 JSON + 各样本 PI/管线输出
- `tests/ocr_engine_visual_review_20260929_183735.md` — 四引擎视觉审查报告（子代理交叉验证产出）
- `TEST_RESULTS/read-pdf-bench_20260929/`（ChatWorkspace）— JSON/MD/日志输出

## 待实测清单（2026-09-29）

- [x] pdf-inspector：`pip install` 后对现有文本层测试样本跑 `process_pdf`，比对 markdown 质量与耗时（质量/速度全胜现状，见实测记录）
- [x] pdf-inspector：Mixed 文档逐页路由结果核对（扫描页准确；文本页 garbled 误报需复检）
- [x] Unlimited-OCR 冒烟：llama.cpp BF16 跑通（替代 vLLM docker 路线），吞吐已测（1.38s/页串行、42.7 页/分 @16并发 np4）
- [x] Unlimited-OCR：与四引擎同样本对比（目录页/分栏页/表格公式页专项）——**GLM 综合第一，Unlimited 非质量最优**
- [x] Unlimited-OCR：性能优化（Q8_0 量化实验，质量否决保持 BF16）
- [ ] Unlimited-OCR：raw label 后处理策略 PoC（`<|det|>` 标签被 server 过滤，需补包装）
- [ ] HF `config.json` 核实实际参数量（官方口径 3B/4B/MoE 不一）
- [ ] Unlimited-OCR 集成进 engine_config（现为手动起服务，端口 12338）
- [ ] pdf-inspector 接入文本层路径（分类缓存 + garbled 路由复检 + 页眉口径对齐）
