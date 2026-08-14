# read-pdf 新用户配置指南

拿到仓库后，按本指南配置即可使用。**核心原则：代码不动，改 `engine_config.local.yaml` 指向自己的路径。**

---

## 一、安装 Python 依赖

需要 Python 3.10+（建议 3.11，与开发环境一致）。

```powershell
pip install "paddlepaddle-gpu"      # GPU 版；无 GPU 用 paddlepaddle（CPU）
pip install paddleocr paddlex
pip install PyMuPDF pdfplumber pdfmux
pip install pillow requests pyyaml
```

依赖清单见 `requirements.txt`（`pip install -r requirements.txt`）。

**注意**：`paddleocr` / `paddlex` 版本需 ≥3.x（本开发环境 3.7.0/3.7.2）。首次运行 paddle 会下载/编译一些组件，需联网。

---

## 二、准备 llama-server（本地引擎必需）

所有本地 OCR 引擎（hybrid/glm/dsocr）都通过 `llama-server` 加载 GGUF 模型。

1. 下载 llama.cpp Windows 二进制（CUDA 版）：https://github.com/ggml-org/llama.cpp/releases
   - 选 `llama-*-bin-win-cuda-*-x64.zip`，解压到任意目录（如 `D:\llm\llama-b9830-bin-win-cuda-13.3-x64\`）
2. 把目录路径填进 `engine_config.local.yaml`：
   ```yaml
   defaults:
     llama_dir: "D:/你的路径/llama-server 所在目录"
   ```

---

## 三、下载模型（按需，至少一个引擎）

模型放任意目录，路径填进 `engine_config.local.yaml`。

### 3.1 PaddleOCR-VL-1.6（hybrid 引擎 / 图像 PDF 默认）
- 模型：https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6-GGUF
- 文件：`PaddleOCR-VL-1.6-GGUF.gguf` + `PaddleOCR-VL-1.6-GGUF-mmproj.gguf`
- 国内可走镜像：`https://hf-mirror.com/PaddlePaddle/PaddleOCR-VL-1.6-GGUF`

### 3.2 GLM-OCR Q8_0（--glm / 公式表格保真）
- 模型：https://huggingface.co/ggml-org/GLM-OCR-GGUF
- 文件：`GLM-OCR-Q8_0.gguf`（~906MB）+ `mmproj-GLM-OCR-Q8_0.gguf`（~462MB）

### 3.3 DeepSeek-OCR Q8_0（--dsocr / 纯文本提速）
- 模型：https://huggingface.co/ggml-org/DeepSeek-OCR-GGUF
- 文件：`DeepSeek-OCR-Q8_0.gguf`（~2.9GB）+ `mmproj-DeepSeek-OCR-Q8_0.gguf`（~427MB）

### 3.4 版面分析模型（--layout）
- PaddleX 首次运行 `--layout` 会自动下载 PP-DocLayoutV3 到 `~/.paddlex/official_models/`，无需手动处理（需联网）。

---

## 四、配置本机路径（engine_config.local.yaml）

复制 `engine_config.local.example.yaml` → `engine_config.local.yaml`，按本机改：

```yaml
# engine_config.local.yaml（已 gitignore，不提交）
defaults:
  llama_dir: "D:/你的llama-server目录"   # 必改
  device: gpu                            # 无 GPU 改 cpu；或保持 gpu 让脚本自动回退

engines:
  hybrid:
    sources:
      local:
        server:
          model: "D:/你的路径/PaddleOCR-VL-1.6-GGUF.gguf"     # 必改
          mmproj: "D:/你的路径/PaddleOCR-VL-1.6-GGUF-mmproj.gguf"  # 必改
  glm:
    sources:
      local:
        server:
          model: "D:/你的路径/GLM-OCR-Q8_0.gguf"              # 用了才改
          mmproj: "D:/你的路径/mmproj-GLM-OCR-Q8_0.gguf"
  dsocr:
    sources:
      local:
        server:
          model: "D:/你的路径/DeepSeek-OCR-Q8_0.gguf"         # 用了才改
          mmproj: "D:/你的路径/mmproj-DeepSeek-OCR-Q8_0.gguf"
```

**只改路径，不要动结构**。没配的引擎运行时会有明确报错提示。

---

## 五、可选：配置云源（无 GPU 时兜底）

云源 = PaddleOCR AI Studio（官方，同款 PaddleOCR-VL-1.6 模型，无需本地 GPU）。

1. 注册/登录 AI Studio：https://aistudio.baidu.com
2. 获取访问 token（控制台 → 密钥管理 / 或官方文档）
3. 把 token 写进本机私有配置 engine_config.local.yaml（gitignore，不进仓库）：
   ```yaml
   engines:
     hybrid:
       sources:
         cloud:
           api_key: "你的token"
     paddle_vl:
       sources:
         cloud:
           api_key: "你的token"
   ```
4. 使用：`python scripts/extract_pdf.py book.pdf --source cloud`
   （或改 `engine_config.yaml` 里 hybrid 的 `default_source: cloud` 永久默认）

---

## 六、验证安装

```powershell
# 1. 引擎配置能加载（应列出 5 个引擎）
python -c "import sys; sys.path.insert(0,'scripts'); import engines; print(list(engines.load_config()['engines']))"

# 2. 文本 PDF（不需要任何模型/GPU）
python scripts/extract_pdf.py 你的文本PDF.pdf

# 3. 扫描 PDF（需 hybrid 引擎 + 模型）
python scripts/extract_pdf.py 你的扫描PDF.pdf --hybrid --pages 1-3

# 4. 版面分析
python scripts/extract_pdf.py 你的扫描PDF.pdf --layout --pages 1-3
```

---

## 常见问题

| 问题 | 解决 |
|---|---|
| `llama-server.exe not found` | `defaults.llama_dir` 指向 llama.cpp 解压目录 |
| `引擎 'x' 不在 engine_config.yaml` | 版本太旧，重新拉取 |
| 无 GPU 却配了 gpu | 自动告警回退 cpu；想禁用回退设 `gpu_fallback: false` |
| 云源 401 / api_key 未配置 | 在 `engine_config.local.yaml` 填 hybrid / paddle_vl 的 cloud api_key |
| huggingface 下载慢/失败 | 用 hf-mirror.com 镜像 |
