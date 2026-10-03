# 扫描版面与表格：真实 CPU 增量

这轮在已有 PP-OCRv6/OpenVINO 文字识别之上，实际接通 PP-DocLayoutV3 的版面分析，重点改善扫描 PDF 的正文顺序、图片位置和有线表格。

## 已落地

- 复用 OpenVINO 跑 PaddlePaddle 官方 PP-DocLayoutV3 ONNX，免装 Paddle/CUDA；旧 Paddle 版面后端仍保留，必须通过配置明确选择
- 使用模型实际输出的阅读顺序；正文按区域组织，表格/图片放回检测到的位置，输出单独区域 PNG
- 带明确网格线的表格：从图像线条恢复行/列/可见合并单元格，再把现有 OCR 框映射进单元格。保留空值、零值、重复行；未能放入单元格的文本继续保留并告警
- Min/Typ/Max 没有完整竖线、但三个表头明确出现且对齐时，可生成基于表头位置的列候选，始终标记 table_columns_inferred_from_headers 和待核对状态，不把推断包装成直接观测
- 行内公式作为所属正文/表格的子区域保存，不再在页面末尾重复几十张小图；独立公式保留文字和区域图，普通 OCR 不伪装成 LaTeX
- 对实测发现的重复温度符号（例如 °℃）增加 suspicious_unit_symbol 告警，保留原始字符，不擅自改写
- Document Package 的块使用实际区域 bbox/坐标系，MCP 的读取/搜索可定位到表格区域

## 官方模型与安装

模型来源：[PaddlePaddle/PP-DocLayoutV3_onnx](https://huggingface.co/PaddlePaddle/PP-DocLayoutV3_onnx)，Apache-2.0；官方 [PaddleX 版面说明](https://paddlepaddle.github.io/PaddleX/latest/en/module_usage/tutorials/ocr_modules/layout_analysis.html)。模型下载约 131 MB，不随仓库或交付包重复分发。读取 model graph 不执行任何远程 Python 代码。

本轮使用仓库修订 46bbdf1 的 inference.onnx；下载字节的 SHA-256：

```
45bf71750b00739a41fc209f132eb104a4d6b5bb29483c9078164d8b87cf28ba
```

```bash
python -m pip install -r requirements-test.txt -r requirements-ov.txt
# 先按 CPU_PIPELINE_VALIDATION.md 禁用 OpenVINO 遥测
mkdir -p /your/model/PP-DocLayoutV3_onnx
curl -L https://huggingface.co/PaddlePaddle/PP-DocLayoutV3_onnx/resolve/46bbdf1/inference.onnx \
  -o /your/model/PP-DocLayoutV3_onnx/inference.onnx
curl -L https://huggingface.co/PaddlePaddle/PP-DocLayoutV3_onnx/resolve/46bbdf1/inference.yml \
  -o /your/model/PP-DocLayoutV3_onnx/inference.yml
```

把 `docs/config-cpu-layout.example.yaml` 合并到本机私有配置，设置实际绝对目录。不要覆盖现有凭据。运行时不自动下载模型，目录/模型错误会明确返回失败或降级警告。

```bash
# 真实扫描版面 + OCR + 结构化表格/图片
python scripts/extract_pdf.py scan.pdf --hybrid --json
# 只做版面定位与裁剪
python scripts/extract_pdf.py scan.pdf --layout-only --json
# 原生/扫描混合页自动分流
python scripts/extract_pdf.py mixed.pdf --json
```

`--ov` 仍是更轻的逐行文字识别，不自动升级为版面解析。无清晰网格或不满足条件的表格保留文字/原图并告警，避免生成看似完整但错误的表格。

## 实际验证

- 原创技术扫描页：实际 PP-DocLayoutV3 + PP-OCRv6，6 行 × 5 列与 30 个真值单元格完全一致，两个重复行、空值、正负号、小数保持
- 前三页原生文字、第4页扫描的混合文件：前三页继续直接提取，第4页生成真实表格与区域图
- TI ADS1115 Rev. E 手册第5物理页扫描化：得到 41×7 的候选结构，含可见合并单元格。抽查 offset 的 Min/Typ/Max 为 -3/±1/3，INL 仅 Max 列有 1，映射与原图一致。列是基于表头位置推断，仍明确告警
- CLI、HTTP /layout、HTTP /extract、MCP stdio tools/call 都实际运行布局和 OCR；缓存命中仍保留结构与图链接
- 本云 CPU 首次模型编译约1.5秒，单页布局推理约0.7秒；完整布局+OCR链路约4–6秒/这些样例，缓存约0.2秒。它增加了结构能力，也比只做行 OCR 更慢；不是通用性能基准
- 测试由 `tests/run_layout_pipeline_smoke.py` 复跑，模型测试由 `tests/test_doclayout_runtime.py`（设置 READPDF_LAYOUT_MODEL_DIR）复跑；依赖/权重缺失时明确 skip，不假装实测

本轮最终回归：99 个单项测试和 12 个聚合套件通过，含实际布局/识别权重测试；没有模型 mock 代替上述端到端验证。缺模型、公式未解析、表格歧义和空 OCR 的退化路径单独检查。

## 不承诺什么

这不是通用表格理解或数学识别器。无边框表、倾斜/断线表、复杂嵌套、跨页续表、多个/重复 Min/Typ/Max 表头、复杂公式仍需要专门模型或看图核对。布局模型也可能分错区域/顺序。O/0、温度符号等字符错误依然存在，标记不会代替校正；不通过自然语言或物理常识补数字。

第三方数据手册仅作本地验证，不放进交付包。交付中的 PDF/Markdown/图片示例使用原创资料。
