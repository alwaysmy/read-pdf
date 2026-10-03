# 真实 CPU 提取链路验证

本轮验证实际调用仓库自带的 PP-OCRv6 ONNX 检测/识别模型，既没有 mock OCR，也没有上传云端模型。目标是把现有 PDF → Markdown/图片链路跑通，并记录它真正能做、不能做的部分。

## 修复的实际阻断

- OpenVINO 模型/字典路径使用 Windows 反斜杠，在 Linux 找不到已存在的权重：改成 pathlib 跨平台拼接
- requirements-ov.txt 只声明 OpenVINO，缺 cv2/pyclipper 等前后处理依赖：补齐独立 CPU 依赖，无须 Paddle/CUDA
- 原生 PDF 中的图片没有写入 Markdown：默认保存每页原貌 PNG 和嵌入图像区域，并生成相对图片链接；源页 PNG 也保留矢量示意图/电路图
- hybrid 缺少版面模型仍显示 ok：现在标记 layout_unavailable；显式 ov 仅输出文字行，标记 structure_unavailable，不假称恢复表格/公式结构
- 损坏/加密 PDF 和异常 DPI：明确报错，不输出 Python traceback；DPI 限制 50–600
- 原服务器管理测试依赖用户的 GPU 默认设置：隔离测试配置，使 CPU 部署也能运行回归测试

图片路径随源版本隔离。`--no-images` 可跳过 PNG 和链接；`--dpi` 同时控制 OCR 与图片渲染。导出图片不是 PP-DocLayout 的语义版面检测，也没有承诺从扫描图自动裁出每张图/表。

## 最短 CPU 运行步骤

```bash
python -m venv .venv
# 激活 venv 后：
python -m pip install -r requirements-test.txt -r requirements-ov.txt
opt_in_out --opt_out
```

将 `docs/config-cpu-openvino.example.yaml` 的字段合并进自己的 `engine_config.local.yaml`，不要覆盖已有私有配置。然后：

```bash
python scripts/extract_pdf.py input.pdf --ov --json
# 混合文件按页自动分流（hybrid 缺版面模型时有明确警告）：
python scripts/extract_pdf.py mixed.pdf --json
python scripts/server.py
# 另一个终端：
python tests/run_all_tests.py
```

新增的 CPU wheel 下载约 121 MB，本次完整测试 venv 约 359 MB；仓库已有约 30 MB 权重，无新增大模型下载。

## 遥测与严格离线验证

[OpenVINO 官方文档](https://docs.openvino.ai/2024/about-openvino/additional-resources/telemetry.html)说明可用 `opt_in_out --opt_out` 停止遥测。当前遥测库首次执行 opt-out 本身可能发一次状态变化事件；要求从第一步就零外联时，应在隔离测试 HOME 中先写入上游的 DECLINED 状态，再调用该命令确认：

```python
from openvino_telemetry.utils.opt_in_checker import OptInChecker, ConsentCheckResult
checker = OptInChecker()
assert checker.update_result(ConsentCheckResult.DECLINED)
assert checker.check(enable_opt_in_dialog=False) == ConsentCheckResult.DECLINED
```

测试脚本已在自己的临时 HOME 中完成这一步，保存的官方 consent 值是 `0`，不会改用户的 HOME 配置。本轮还对整个测试进程树增加了仅允许 localhost 的 Python socket 审计防护，运行完成后外部连接尝试记录为 0。原始联网遥测试探被拦截后没有放行或重试。

## 可复跑的真实测试

```bash
python tests/run_real_pipeline_smoke.py --output /tmp/readpdf-real
# 对自己的或已下载的技术 PDF，额外测试物理页 1、5 及第 5 页扫描化版本：
python tests/run_real_pipeline_smoke.py --output /tmp/readpdf-real \
  --technical-pdf /path/to/technical.pdf
```

生成的原生/扫描/混合/96dpi PDF 是原创测试资料，包含中英文、Min/Typ/Max 表格、零值/空值/重复行、符号/小数、简单公式和图。真值写在 ground_truth.json。所有模板都经实际像素检查；不是用字符串假装 PDF。

另测试了 [TI ADS1115 官方数据手册 Rev. E](https://www.ti.com/lit/ds/symlink/ads1115.pdf) 的物理页 1、5，以及把第 5 页渲染成纯扫描 PDF 后的真实 OCR。不把整份第三方手册纳入仓库或交付样例。

## 一次运行结果（本云 CPU，非吞吐基准）

| 场景 | 实际墙钟时间 | 输出/检查 |
|---|---:|---|
| 原生 2 页 | 0.35 s | 表格 cells 与真值一致；2 个重复行保留；3 张 PNG |
| 150dpi 扫描页 | 1.69 s | 653 字符；中英文和 7 个指定数值锚点全部命中；1 张原页 PNG |
| 同扫描页缓存 | 0.14 s | 无再次 OCR；输出一致 |
| 3 页文本 + 第 4 页扫描 | 2.00 s | 前三页 text，第4页 OpenVINO；缺版面模型告警 |
| 96dpi 扫描页 | 1.58 s | 本样例全部检查锚点命中；不代表低清资料普遍准确 |
| HTTP 真实扫描提取 | 1.78 s | 实际 subprocess → 模型 → Markdown/PNG |
| MCP 适配器真实扫描提取 | 1.68 s | 实际 HTTP 提取，后续 read/search 成功 |
| MCP stdio 真实 tools/call | 2.11 s | 包括启动/握手；实际调用 extract_pdf 做扫描 OCR |
| TI 原生物理页 1、5 | 0.82 s | 5,227 字符、9 个候选表格、2 张原页 PNG |
| TI 第 5 页纯扫描 | 3.23 s | 2,137 字符，保留表格原图；结构未恢复告警 |

原生表格候选数量不是准确率。OCR confidence 也不是最终正确率。

## 明确剩余问题

- OpenVINO 轻量后端输出行文字，扫描表格的列/合并单元格及复杂公式结构未恢复。TI 密集表格中行顺序存在歧义
- 对原图逐项查看，发现温度符号出现 `°℃` 等重复/替代；单独字体测试还出现 O/0 混淆。高模型 confidence 不能排除这些错误
- 原生多栏、复杂合并表格与字体编码也不保证完全正确。源页链接用于回看证据，不能替代内容核对
- PP-DocLayout、PaddleOCR-VL、GLM/DeepSeek、GPU 性能本轮未安装或验证；没有购买云服务，也没有新增通用队列/知识库功能

结论：现有轻量 CPU 文本/图片提取链路已能真实运行；扫描复杂表格/公式仍应升级结构模型或人工/Agent 看图核对后入库。
