# read-pdf 解耦重构覆盖测试计划

日期：2026-08-08
目标：验证解耦重构（engines.py/server_manager.py/engine_config.yaml + extract_pdf.py 改造）
相对重构前（main 分支基线）未引入问题；同时发现遗留问题。

---

## 1. 覆盖度矩阵（功能 × 引擎 × 源）

### 1.1 引擎 × 源 × 调用路径

| 引擎 | local 源 | cloud 源 | 说明 |
|---|---|---|---|
| hybrid | ✅ 走 extract_hybrid（PaddleOCR 本地管线） | ✅ --source cloud → paddle_vl job 模式 | 本地是特殊路径（非 HTTP） |
| glm | ✅ engines.call → HTTP | ❌ 无云源（配置只有 local） | 云端 GLM 未接入（保留示例） |
| dsocr | ✅ engines.call → HTTP（text-first） | ❌ 无云源 | |
| paddle_vl | ❌ 只有 cloud | ✅ job 模式 | 云专用引擎 |
| text (pdfmux) | ✅ 无服务 | — | 不涉及引擎 |
| layout | ✅ PP-DocLayoutV3（cpu/gpu） | — | 独立模式 |

### 1.2 功能覆盖（CLI 参数路径）

| 功能 | 场景 | 验证点 |
|---|---|---|
| 文本 PDF | pdfmux+pdfplumber | 输出 .md，无服务启动 |
| 图像 PDF | hybrid 默认 / --glm / --dsocr | 引擎路由正确 |
| --pages | 单页/多页/范围 | 页数正确 |
| --layout | cpu/gpu 设备 | blocks/crops 数 |
| 缓存 | 首次/命中/refresh/no-cache | 0.0s 命中 + key 含 source |
| --source cloud | hybrid 切换 | 云输出特征 |
| 友好提示 | 路径不存在 | SETUP_GUIDE 指引 |
| --json | 结构化输出 | schema 正常 |

### 1.3 模块单元覆盖（已有）

- engines.py：配置加载/双源解析/ENV 展开/local 合并/未知引擎（unit_engines.py 6 项 ✅）
- server_manager.py：GPU 检测/设备解析/回退/云源跳过（unit_server_manager.py 5 项 ✅）

### 1.4 覆盖缺口（本次测试需补）

| 缺口 | 说明 |
|---|---|
| 友好提示（路径不存在） | 新增逻辑，未测 |
| text 路径（pdfmux）回归 | 解耦后未跑过文本 PDF |
| --json 输出回归 | 未在解耦后验证 |
| 多页批量 | 未在解耦后验证（>1 页） |
| 遗留问题排查 | 重构前已知：pyc 跟踪（已修）、tests/*_output 未忽略（已加 gitignore） |

---

## 2. 测试矩阵（本次执行）

| # | 测试 | 命令 | 预期 |
|---|---|---|---|
| T1 | 单元（engines） | python tests/unit_engines.py | 6 项全过 |
| T2 | 单元（server_manager） | python tests/unit_server_manager.py | 5 项全过 |
| T3 | 友好提示 | 临时改 llama_dir 为不存在路径跑 glm | 打印 SETUP_GUIDE 指引 + FileNotFoundError |
| T4 | 文本 PDF 回归 | 文本 PDF（T3 连接器手册）无引擎跑 | 输出 .md，不启服务 |
| T5 | glm 回归 | 扫描 PDF --glm 1 页 | 输出与基线一致 |
| T6 | dsocr 回归 | 扫描 PDF --dsocr 1 页 | 输出正常 |
| T7 | layout gpu 回归 | 扫描 PDF --layout --pages 1-2 gpu | blocks/crops 正常 |
| T8 | 缓存命中（含 source） | 同页同引擎二次 --json | total_time 0.0 + cache:hit |
| T9 | --json 回归 | glm --json | JSON schema 正常 |
| T10 | 多页批量 | --pages 5-7 | 3 页全处理 |
| T11 | --source cloud | hybrid --source cloud | 云特征输出 |
| T12 | 遗留问题扫描 | 见 §3 | 记录 |

## 3. 遗留问题排查清单（重构前已知 + 新发现）

- [ ] scripts/__pycache__ 是否已从 git 移除（main 已修；worktree 分支已同步）
- [ ] engine_config.local.example.yaml 是否提交、local.yaml 是否 gitignore
- [ ] README 是否指向 SETUP_GUIDE（已补）
- [ ] docs 设计文档是否与实现一致（v1.4 双源）
- [ ] 未跟踪的测试产物（tests/bench_* 等）是否已 gitignore
- [ ] SKILL.md 是否提到新配置（engine_config.yaml）——重构前 SKILL.md 讲的是 SERVERS/LLAMA_DIR，可能过时

## 4. 基线对比方法

- 基线：main 分支（重构前 extract_pdf.py，P1/P3 版）
- 对比：feat/decouple-engines（重构后）
- 指标：同 PDF 同页输出是否一致（glm/hybrid 各 1 页，diff 输出文件）

---

## 5. 执行结果（2026-08-08 全量）

| 套件 | 结果 | 耗时 |
|---|---|---|
| unit_engines.py | ✅ 6 项 | 0.1s |
| unit_server_manager.py | ✅ 5 项 | 0.2s |
| test_friendly_hint.py | ✅ 2 场景 | 0.2s |
| test_mcp_tools.py | ✅ 4 项（需本体服务） | ~20s |
| 聚合脚本 | tests/run_all_tests.py（一键全跑+存档） | |

**发现并修复**：
- MCP 字段错位：chars/layout_path 不存在 → size_bytes/tables/layout_json（extract_pdf.py layout JSON 补 total_blocks/total_crops）
- gitignore 误伤 bench 脚本（!tests/bench_*.py 白名单）

**基线对比**：glm p20 重构前后 3549B 哈希一致；hybrid 4183B 一致。
