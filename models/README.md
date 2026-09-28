# models/ — PP-OCRv6 small 的 ONNX 与字典

`--ov` 的 OpenVINO 后端直接跑这里的文件（不依赖 PaddlePaddle）。随仓库分发，clone 即用；
想改用自备模型，把 `engine_config.local.yaml` 的 `defaults.ocr_ov_dir` 指过去即可覆盖。

| 文件 | 说明 |
|---|---|
| `PP-OCRv6_small_det_onnx/inference.onnx` | 文本检测（DB），输入 `x` NCHW，输出分割概率图 |
| `PP-OCRv6_small_rec_onnx/inference.onnx` | 文本识别（CTC），输入 `[N,3,48,W]`，输出 18385 类 |
| `PP-OCRv6_small_*/inference.yml` | 官方模型配置：含前后处理参数与 rec 的完整字符表 |
| `ppocr_keys_v6.txt` | 识别字典，18383 字（模型另按 `use_space_char` 追加空格，合 18385 类） |

**来源**：官方 PP-OCRv6 small 权重（PaddleOCR，Apache-2.0）的 ONNX 导出；`inference.yml`
为官方随模型发布。运行时 `scripts/ppocr_openvino.py` 的前后处理与官方实现逐条对齐，
参数取自这里的 `inference.yml`（检测 `thresh=0.2` / `box_thresh=0.45` / `unclip_ratio=1.4`、
`limit_side_len=736` + `limit_type=min`；识别 `image_shape=[3,48,320]`，缩放后零填充）。

**改动前务必注意**：根目录 `.gitattributes` 把 `*.onnx` 标记为 binary、
`ppocr_keys_v6.txt` 标记为 `-text`。字典逐字对应模型输出类别，且含 emoji——
一旦被行尾转换或被按**码点**切分，其后所有索引都会整体偏移，表现为空格位置出现乱码。
