# Hybrid VL（llama.cpp）GPU 生效性测试记录

**日期**：2026-09-30
**范围**：`hybrid` 引擎的 `llama-cpp` 后端（PaddleOCR-VL GGUF 经 llama-server）在两台机器上的
GPU 生效性、速度基线，以及 CUDA 后端起不来时的表现与防护。

---

## 一、核心结论

**"有显卡 + 装了 CUDA Toolkit" ≠ "llama.cpp 在用 GPU"。** llama.cpp 在 CUDA 后端加载失败时
**不报错、不提示，直接静默在 CPU 上算**（慢 3 倍以上），而日志里连一个 `CUDA` 字都不会出现。

可靠的判据只有一个：

```
<llama_dir>/llama-server.exe --list-devices
```

- 输出 `CUDA0: <显卡名> (<总显存> MiB, <空闲> MiB free)` → GPU 可用
- 输出 `(none)` 或为空 → **后端没加载起来**，此时不管显卡多好都在跑 CPU

不要用以下方式判断：

| 判据 | 为什么不可靠 |
|---|---|
| `nvidia-smi` 的 `memory.used` | 显存被占用可能只是 CUDA context 或别的进程；实测 CPU 回落下显存照样涨 |
| 日志里搜 `CUDA` / `offloaded` | 当前构建在默认 verbosity(3) 下根本不打印这些行；后端加载失败更是被刻意抑制 |
| 检查 `cudart64_*.dll` 是否存在 | 通配符会命中**主版本不对**的库（要 12 却有 13），得到假阳性 |

运行中若要确认"确实在算 GPU"，看 **SM 频率 / 功耗 / 利用率**（不是显存）：

```
nvidia-smi --query-gpu=utilization.gpu,clocks.sm,power.draw --format=csv,noheader
```

GPU 工作时应看到 SM 频率上到千兆级、功耗显著抬升；CPU 回落时是 P8 / 225~300 MHz / 约 8~15 W。

---

## 二、两种失败模式（都已实测复现）

### 模式 A：CUDA 运行库不在加载路径

官方 Windows release 把**二进制**与 **CUDA 运行库**拆成两个 zip：

- `llama-b<build>-bin-win-cuda-<ver>-x64.zip` —— 只有 `ggml-cuda.dll` 等
- `cudart-llama-bin-win-cuda-<ver>-x64.zip` —— `cudart64_*.dll` / `cublas64_*.dll` / `cublasLt64_*.dll`

只解压前者，就会得到一个能正常启动、日志干净、却在 CPU 上算的 llama-server。

后端 DLL 的查找范围**只有 exe 所在目录与当前工作目录**，`PATH` 不参与；但
`cudart64_*` / `cublas64_*` 是 `ggml-cuda.dll` 的**依赖**，按 Windows 常规规则解析（exe 同目录 → `PATH`）。
所以"装了 CUDA Toolkit"还不够——**bin 必须在 `PATH` 里，或把三个 DLL 拷到 exe 旁边**。

> 远程机（RTX 5070 Ti）就是这个模式：CUDA Toolkit v13.4 装着，但 bin 不在任何 `PATH` 里。
> 把 `...\CUDA\v13.4\bin\x64` 加入用户 `PATH` 后，`--list-devices` 立刻列出 CUDA0。

### 模式 B：CUDA 主版本与构建不匹配

`ggml-cuda.dll` 链接的是**某个具体主版本**的 CUDA 运行时。用通配符查"有没有 cudart"会漏掉这一点：

```
D:\llm\llama\ggml-cuda.dll 的导入表：
  [MISS] cudart64_12.dll      ← 构建要的是 CUDA 12
  [MISS] cublas64_12.dll
  [OK  ] nvcuda.dll
```

本机（Quadro T1000）装的是 CUDA **13**.x（提供 `cudart64_13.dll`），而该构建要 **12** →
`LoadLibrary("ggml-cuda.dll")` 失败 → 无可用设备 → CPU。
修法是把**对应主版本**的 cudart zip 解到 exe 目录（本例放 CUDA 12.4 的三个 DLL）。

查构建到底要哪个主版本：读 `ggml-cuda.dll` 的导入表（`pefile` 或任何 PE 工具），
或直接看该构建来自哪个 `bin-win-cuda-<ver>` 包。

---

## 三、实测数据

### 3.1 修复前后（本机 Quadro T1000 4GB）

| 指标 | 修复前（静默 CPU） | 修复后（GPU） | 倍数 |
|---|---|---|---|
| `--list-devices` | `(none)` | `CUDA0: Quadro T1000 (4095 MiB, 3296 MiB free)` | — |
| 运行中显存 | 0 MiB | 1771 ~ 2491 MiB | — |
| SM 频率 / 功耗 | 300 MHz / 8 W | 1545~1680 MHz / 47~51 W | — |
| prompt eval | 87.5 tok/s | 280~292 tok/s | **3.3×** |
| eval（生成） | 36~54 tok/s | 128~131 tok/s | **约 3×** |
| 单页 A4（P6SMB 数据手册首页） | 112.7 s | 13.1 ~ 45.1 s | 约 2.5~8.6× |

本机环境：Quadro T1000（compute 7.5 / Turing）、驱动 582.08、CUDA Toolkit v13.3 与 v13.4、
llama.cpp build 10295（需 CUDA 12 运行库）。测试输入：`p6smb.pdf` 第 1 页，150 dpi 渲染。

同一页的耗时区间较宽（13.1 ~ 45.1 s），因为 VL 是自回归生成，输出长度会波动
（实测同一输入得到过 3508 与 5081 字符两种结果）。**比较速度应以 llama.cpp 的 tok/s 为准**，
不要用单次墙钟。

### 3.2 远程（RTX 5070 Ti 16GB）

| 项 | 结果 |
|---|---|
| `--list-devices`（修 PATH 前） | 无 CUDA 设备；SM 225 MHz / 15 W / 显存 0 |
| `--list-devices`（修 PATH 后） | `CUDA0: NVIDIA GeForce RTX 5070 Ti (16275 MiB, 15037 MiB free)` |
| 运行中 | SM 2490~2842 MHz、功耗 139 W |
| prompt eval / eval | **5138 tok/s / 459 tok/s** |
| 单页 A4（同 `p1.png` 输入） | 55.8 s（5083 字符） |

> 修复前做过的"换构建比速度"这类对比全部无效——当时所有 CUDA 构建都在 CPU 上跑，才会
> 呈现 82~86 s 且彼此无差异。

### 3.3 两台机器横向对比（同输入 `p1.png`，同为 CLI 全流程）

| 指标 | Quadro T1000（本机） | RTX 5070 Ti（远程） | 比值 |
|---|---|---|---|
| prompt eval | 280~292 tok/s | 5138 tok/s | 18× |
| eval（生成） | 128~131 tok/s | 459 tok/s | 3.6× |
| 单页 A4 全流程 | 45.1 s | 55.8 s | **0.8×（更慢）** |

**GPU 快 3.6 倍，整页却更慢** —— 说明瓶颈不在 GPU。该页产生了约 37 次逐版面块的 VL 请求，
prompt eval 合计与请求开销主导了总时间（远程单次请求 `total time` 多落在 40~80 ms 量级，
累计即为数十秒）。**要缩短整页时间，方向是减少/合并逐块请求，而不是换更快的显卡。**


---

## 四、附带发现：`NO_PROXY` 里的方括号 IPv6 会让 httpx 直接崩

`hybrid` 的 VL 客户端走 PaddleX → OpenAI SDK → **httpx**。httpx 把 `NO_PROXY` 每一项拼成
`all://*<host>` 模式，加上 `*` 前缀后它不再把方括号识别为 IPv6 字面量，转而把 `:1]` 当端口：

```
NO_PROXY=localhost,127.0.0.1,::1,[::1]   → httpx.InvalidURL: Invalid port: ':1]'
```

后果是**任何 httpx 客户端都构造不出来**，表现为 hybrid 直接失败（`chars=0`，错误信息只有那句
`Invalid port`）。实测各种写法的差异：

| `NO_PROXY` | httpx 客户端 |
|---|---|
| `localhost,127.0.0.1,::1,[::1]` | 失败 |
| `localhost,127.0.0.1,[::1]` | 失败 |
| `localhost,127.0.0.1,::1` | 正常 |
| `localhost,127.0.0.1` | 正常 |

**带方括号的才触发，裸 `::1` 没问题。** 注意 curl 接受 `[::1]` 写法，所以这类 `NO_PROXY`
在实际环境里很常见。

---

## 五、代码改动

1. **`server_manager` 收全 llama-server 输出**：原先把 stdout 丢给 `DEVNULL`，而 llama.cpp 的
   逐请求 token 速率等诊断信息就在 stdout。现在 stdout + stderr 一起写日志，且**停止服务时不再删除
   日志**（改为打印路径），保留性能证据。
2. **启动前 GPU 可用性预检**：`-ngl` 非 0 时跑一次 `llama-server --list-devices`。
   没有 CUDA 设备就明确告警（指出"静默回落 CPU"+ 三条常见原因与修法）；该 build 不支持
   `--list-devices` 时退回运行库粗检。按 exe 路径缓存，不重复探测。
3. **`NO_PROXY` 防护**：构造 VL 客户端前，把本进程 `NO_PROXY`/`no_proxy` 里方括号 IPv6 项剔除，
   并提示一次。只改本进程环境，不动调用者环境。

---

## 六、复现命令

```powershell
# 1) 判据：llama.cpp 自己认到哪些设备
<llama_dir>\llama-server.exe --list-devices

# 2) 构建到底要哪个 CUDA 主版本
python -c "import pefile; pe=pefile.PE(r'<llama_dir>\ggml-cuda.dll', fast_load=True); pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']]); print([e.dll.decode() for e in pe.DIRECTORY_ENTRY_IMPORT])"

# 3) 运行中确认真在算 GPU（看频率与功耗，不是显存）
nvidia-smi --query-gpu=utilization.gpu,clocks.sm,power.draw --format=csv,noheader

# 4) 端到端
python scripts/extract_pdf.py <pdf> --hybrid --pages 1 --json --output-dir <out>
#    服务日志路径会在停止时打印，里面有逐请求 tok/s
```

## 七、留痕

- 测试脚本：`TEST_SCRIPTS\`（本机 `D:\ChatWorkspace\TEST_SCRIPTS\`，远程同名目录）
- 原始输出：`D:\ChatWorkspace\TEST_RESULTS\local_vl_manual\`（CPU 基线）、
  `local_vl_gpu\`（GPU）、`e2e_after_fix\`、`e2e_log_check\`
- 服务日志：`%TEMP%\llama_hybrid_*.log`（含逐请求 `prompt eval time` / `eval time`）
