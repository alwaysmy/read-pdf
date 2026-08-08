# read-pdf 借鉴点对比实现报告

- 日期：2026-08-08
- 分支：`feat/borrow-layout-screenshot`（worktree: `read-pdf-wt-borrow`）
- 基于：main `0e8223f`
- 目的：验证帖子 1（PicoDet 版面检测+元素截图）、帖子 2（DeepSeek-OCR 本地识别）及调研可本地落地项，对比后决定是否并入 main

---

## 一、实现清单

| 编号 | 借鉴点 | 来源 | 状态 | commit |
|---|---|---|---|---|
| P1 | 版面检测 + 元素截图（PP-DocLayoutV3/PicoDet 系） | 帖子1 | ✅ 实现+验证 | `a059e18`, `6af5604` |
| P2 | DeepSeek-OCR 本地引擎接入 | 帖子2 | ✅ 实现+验证 | `a9f2c6c`, `5e3495f` |
| P3 | 抽取结果缓存复用 | Kimi 调研 | ✅ 实现+验证 | `c1d5f30` |

## 二、P1 版面检测 + 元素截图

**实现**：`extract_layout()`（PaddleX PP-DocLayoutV3，PicoDet 系列版面模型，本地已有缓存无需下载）
- 新增参数：`--layout` / `--layout-only` / `--layout-min-score` / `--layout-device cpu|gpu`
- 输出：`{name}_output/layout/{name}_layout.json`（label+bbox+score+page）+ `layout/crops/*.png`
- 布局 JSON 对齐智谱 GLM-OCR schema：label（text/formula/table/image/chart/seal…）+ 归一化 bbox

**实测**（《数字电子技术基础·系统方法》扫描版 541 页，纯扫描 0 字符/页）：

| 指标 | 结果 |
|---|---|
| 3 页 blocks | 83 个（text 44 / image 8 / chart 2 / display_formula 7 / figure_title 10…） |
| 裁剪元素 | 10 张（image + chart），bbox 命中准确（图+标题配对） |
| CPU 模式 | ✅ 验证通过（帖子"CPU 就能跑"论断成立，GPU 被 OCR 占用时兜底） |
| 速度 | 单页版面检测 ms 级（GPU 快于 CPU，CPU 可接受） |

## 三、P2 DeepSeek-OCR vs GLM-OCR 对比

**实现**：SERVERS 加 `dsocr`（端口 12337）、`http_extract_text_first()`（text 前 image 后——DeepSeek-OCR 特有顺序）、`extract_dsocr()`（prompt "OCR markdown"）、`--dsocr` 参数。

**速度对比**（《微弱信号检测》扫描版 3 页，dpi 150）：

| 页 | GLM | DeepSeek | 差值 |
|---|---|---|---|
| 20 | 2.39s / 1620 chars | 1.87s / 1703 chars | DS 快 22% |
| 21 | 1.96s / 1139 chars | 1.55s / 1129 chars | DS 快 21% |
| 22 | 2.16s / 1315 chars | 1.66s / 1344 chars | DS 快 23% |
| 合计 | 6.51s / 4074 chars | **5.08s / 4176 chars** | DS 快 22% |

**质量对比**（同页含公式+表格）：

| 维度 | GLM | DeepSeek | 胜者 |
|---|---|---|---|
| 公式保真（下标） | `$SNR_{\mathrm{o}}$` 保下标 | `SNR_r` 下标丢/误识 | 🟢 GLM |
| 表格精度 | 末行数据正确 | **幻觉**（整行重复 10^-6×6） | 🟢 GLM |
| 表头保留 | "表1-1 检测的最高分辨率" ✅ | 丢失 | 🟢 GLM |
| 标点 | 全角保留 | 转半角 | 🟢 GLM |
| 章节结构 | 无页码标题 | 带 "#### 第1章" | 🟡 DS |

**VRAM 实测**：DeepSeek-OCR 进程 WorkingSet ~3.9GB（Q8_0 + mmproj 全 GPU），RTX 5070 Ti 总占用 12.2GB（含 KV cache，`-c 8192`）。

**结论**：GLM-OCR 保持默认主引擎（公式/表格质量优先）；DeepSeek-OCR 作 `--dsocr` 速度备选（快 22%，适用纯文本扫描件）。DeepSeek 幻觉问题与 llama.cpp 官方文档警告一致。

## 四、P3 抽取缓存（Kimi 借鉴）

**实现**：`cache_get/cache_put`，缓存目录 `{name}_output/.cache/`，key=`{pdf_stem}_p{page}_{engine}_d{dpi}`（引擎/DPI/页码变化自动失效）。
- 参数：`--no-cache`（禁用）/ `--refresh-cache`（强制重跑）
- `--json` 输出 `cache: "hit"` 标记

**实测**：

| 场景 | total_time | 说明 |
|---|---|---|
| 首次 OCR | 3.4s | 写缓存 |
| 二次同页同引擎 | **0.0s** | cache hit |
| --refresh-cache | 3.4s | 强制重跑 |

## 五、决策建议

| 项 | 建议 | 理由 |
|---|---|---|
| P1 `--layout` | **建议并入 main** | 打开 PDF→EPUB/重排/元素提取新场景，CPU 可跑，与现有引擎零冲突 |
| P2 `--dsocr` | **建议并入 main**（作备选） | 引擎已工作，质量不如 GLM 但速度快，纯文本扫描件有用；幻觉风险记录在 SKILL.md |
| P3 缓存 | **建议并入 main** | 零成本收益大，二次运行免 OCR，默认开启 |

## 六、未做（明确排除）

- 云 API（百度 OCR v6 / 云端 GLM-OCR / 云视觉交叉验证）——违反"本地部署"边界
- `--json` 段落级 schema 细化——并入 P1 布局 JSON 已部分覆盖

## 七、测试留痕

- `tests/bench_glm_vs_dsocr_template.py` — 对比脚本（可复用）
- `tests/bench/bench_glm_vs_dsocr_20260808_104116.json` — 对比数据
- `tests/bench/page0020~22_{glm,dsocr}_20260808_104116.md` — 双引擎逐页输出
- P1 布局 JSON + crops 已在 tests/ 归档
