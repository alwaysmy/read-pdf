# PDF 可靠性与按需读取：第一阶段

本阶段基于 `c2ad6a1b5e39275728413fcf76205895b06f460e`，保留现有 CLI 参数和 3 个 MCP 工具，增加可追溯文档包与 3 个只读工具。没有引入队列、数据库或新的 OCR 模型。

## 已实现

1. **按请求页判断文本/扫描混合文档**：检查每个选中页的文字、图像覆盖及空白信号，不再以文件前 3 页代表整本书。自动模式保留可用文本，仅对需要 OCR 的页调用引擎；明确指定 OCR 引擎仍对全部选中页生效。稀疏原生文字不会单凭 `<100` 字符被强制 OCR，空白页明确标记 `blank`。
2. **内容身份与缓存**：完整源 PDF 的 SHA-256 + 物理页 + pipeline 指纹；指纹纳入源、实际后端、档位、相关有效配置、prompt、token 限制。缓存以原子 JSON 同时保存文字与质量/来源信息。旧 `.txt` 缓存视为 miss，`--refresh-cache` 更新、`--no-cache` 完全绕过；命中后不渲染、不启动 OCR 服务。
3. **表格保真**：保留重复行、零值、空值和超出首行宽度的列；Markdown 转义换行与管线符。提取异常产生 `table_extraction_failed`，不会无声消失。文档包保留原始二维 cells 和可读取/检索的 table block。
4. **截断与失败可见**：OpenAI-compatible GLM/DeepSeek/llama 路径和 Qwen 保留 `finish_reason`、`usage`、`model`；`length` 保留部分正文并标记 `completion_truncated`。缓存命中仍保留标记。空输出、模型初始化错误、表格失败都有页级状态/问题。
5. **最小 Document Package 1.0**：常规 Markdown/HTML 提取旁写 `.document.json`，含内容身份、页尺寸/旋转/物理页/印刷页标签、正文和表格块、引擎/后端来源、质量标记、覆盖和实际墙钟耗时。未知 bbox 为 `null`，验证状态为 `unverified`，不伪造布局精度或置信度。
6. **有界读取/搜索**：`open_document`、`read_document`、`search_document` 读取已经生成的 package。返回正文/片段和 revision/page/block 引用，保留完整覆盖和告警；游标检查源版本、pipeline、内容及页选择。未处理/失败/已知截断页不会被当成全文无匹配。

## 使用

先正常提取需要的页：

```bash
python scripts/extract_pdf.py manual.pdf --pages 1-4,20 --json
```

JSON 保留 `file`、`pages`、`status` 等字段，并新增 `package_path`、`revision_id`、`doc_id`、`coverage`、`quality_flags`、`page_statuses`。MCP 的 `extract_pdf` 也返回这些信息。

MCP 调用示例（`package_path` 使用上述实际返回值）：

```python
open_document(package_path="...document.json")
read_document(package_path="...document.json", pages="20", max_chars=8000)
search_document(package_path="...document.json", query="INL", max_hits=20)
```

HTTP 对应 `POST /document/open`、`/document/read`、`/document/search`，JSON 参数同上，沿用服务的 Bearer 认证。`read_document` 的 `next_cursor` 必须携带同一 package 和相同页选择继续请求；可修改字符预算。读取上限 100,000 字符、搜索上限 100 条，每个 snippet 最多 320 字符。工具不会自动 OCR，也不接受原始 PDF 代替 package。

## 状态和兼容性

- `status: ok` 表示未检测到已实现规则中的问题，不是内容准确率或专家审核保证
- 页级 `ok`、`blank`、`needs_review`、`failed` 与 `quality_flags`、`issues` 一起使用
- `processed_pages` 包含已有可读取候选的页；已知 token 截断仍可部分读取，但检索完整性为 false
- `unprocessed_pages` 包括未请求页及失败/无法按页对齐的页；`failed_pages` 单独列出实际失败
- `--audit --batch` 保留旧 HTML 结果，但跨页输出作为一次 `unaligned_candidates` 保存。没有页对齐证据时不将所有内容伪挂到第一页，也不虚称第二页已完整提取
- 当前没有独立逻辑文档目录，`doc_id == revision_id`；将不同修订归到同一本手册属于后续工作
- CLI 原 Markdown 路径保留为最新结果的便利别名；package 的正文 artifact 使用 revision/pipeline 限定路径，避免同名新 PDF 污染旧包引用。相同源和 pipeline 的刷新会更新该结果，旧游标会失效
- 原生正文由 PyMuPDF 提取，表格由 pdfplumber 提取。pdfmux 改为独立 `.pdfmux.md` 诊断文件，避免两个全文拼入同一正文。可用 `--no-pdfmux` 禁用；缺少它不会阻止规范结果
- `--text-only`、`--layout`/`--layout-only` 保持原有专用输出，此阶段不自动生成 Document Package；layout-only 不再先启动 OCR
- CLI/HTTP 保留原有成功/警告约定；消费方应检查覆盖与状态，不能只看进程退出码

## 验证

不需要 GPU、llama-server 或模型权重的回归环境：

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows: .venv\Scripts\activate
python -m pip install -r requirements-test.txt
python tests/run_all_tests.py --offline
```

完整 HTTP/MCP 验证：先启动 `python scripts/server.py`，另一个终端执行 `python tests/run_all_tests.py`。已有私有配置/凭据不应写入版本库。

本次云端验证包括（Python 3.12.14；PyMuPDF 1.26.6、pdfplumber 0.11.9、Flask 3.1.3、MCP 1.29.0）：

- 新增 64 个确定性回归测试：22 个提取、10 个 completion、32 个 reader/API；8 个聚合套件均通过（真实扫描 layout 子项明确跳过）

- 原版 8 个 P0 场景先失败（6 个 assertion failure、2 个异常），修改后通过
- 生成真实 PDF：前 3 页文字 + 第 4 页扫描图、同名不同内容、空白页、原生文本及页选择
- OCR 由确定性 mock 驱动；只检验路由/缓存/质量状态与结果保真，不代表模型识别准确率
- HTTP 真正启动在临时 localhost 端口，旧提取和新 open/read/search 走实际请求；MCP stdio 握手、工具列表、工具调用验证
- 未配置真实扫描样本、Paddle/GLM/DeepSeek 模型或 GPU，因此真实 layout/OCR/GPU benchmark 没有运行；历史 README 性能数字未重新验证

## 后续阶段（未实现）

1. 原生 `open_document(pdf)` 注册、目录、页面按需补算、多个页段结果的版本化合并；原图/区域证据与 inspect_region
2. SQLite 作业/逐页 checkpoint、幂等提交、有界 worker、取消及进程树终止、失败重试与断点恢复
3. 真实技术 PDF 金标：表格结构、单位/上下标、公式与跨页引用；对低质量隐藏 OCR 层、全图+图注等复杂页校准路由规则
4. 更精细 block bbox/阅读顺序与实际模型 revision；上传/路径授权/磁盘配额等远程安全边界。当前仍定位单用户本地服务，不能直接暴露公网

本阶段没有实现通用乱码检测、语义纠错、跨版本文档匹配、区域重新识别或完整批处理系统。图像覆盖是保守启发式，不是经过金标校准的置信度。pipeline 包含配置但不会读取/哈希数 GB 模型文件；在原路径静默替换权重应提升 pipeline 版本或刷新缓存。
