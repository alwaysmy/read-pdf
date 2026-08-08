# read-pdf 本体服务化设计（阶段 1：HTTP API + MCP）

日期：2026-08-08
分支：feat/decouple-engines
状态：设计 + 实现中

---

## 1. 目标

把 read-pdf 从"被 CLI/skill 调用"升级为"本体独立运行"，前端多样化：

```
read-pdf 本体（常驻服务）←── MCP server ←── 任何 MCP 客户端
        ↑                    └── skill（现状，不变）
        │                    └── CLI（现状，不变）
        └── tray 托盘（常驻指示，后续）
```

## 2. 架构决策

### 2.1 API 层调用方式：子进程隔离（不重构 CLI）

**决策**：Flask API 收到请求 → `subprocess` 调用 `extract_pdf.py` → 返回结果。

理由：
- **零侵入**：完全复用现有 CLI 逻辑（parse_args → main），不重构
- **隔离性好**：OCR 引擎异常/内存问题不影响服务进程
- **并发安全**：每个请求独立进程，无共享状态
- **成本**：每次请求多 ~1-2s 进程启动（可接受，OCR 本身 2s+）

替代方案（不采用）：把 main() 重构为可调用函数——侵入大、风险高、违背"零回归"原则。

### 2.2 技术栈

- **Flask**（已装）：轻量，单文件即可
- **MCP**：参考官方 `paddleocr-mcp`（uvx + paddleocr_mcp 模式）
- **tray**：pystray（后续阶段）

### 2.3 端口与安全

- 默认 `127.0.0.1:8123`（仅本机）
- API key 可选（`READPDF_API_KEY` 环境变量，设置后需 Bearer 认证）
- 云 token 仍走 `PADDLEOCR_MCP_AISTUDIO_ACCESS_TOKEN`（不暴露）

---

## 3. HTTP API 设计

### 3.1 `POST /extract` — PDF 提取（核心）

```json
// 请求
{
  "pdf": "C:/path/book.pdf",        // 必填
  "pages": "1-10",                  // 可选，默认全部
  "engine": "auto|hybrid|glm|dsocr",// 可选，默认 auto（文本层→pdfmux，图像→hybrid）
  "source": "local|cloud",          // 可选，默认引擎默认源
  "dpi": 150,                       // 可选
  "output_dir": "C:/out"            // 可选，默认 {pdf}_output
}

// 响应 200
{
  "status": "ok",
  "output": "C:/out/book_output/book.md",
  "engine": "hybrid",
  "pages": 10,
  "chars": 12345,
  "time_s": 25.3
}
```

### 3.2 `POST /layout` — 版面分析

```json
// 请求
{ "pdf": "...", "pages": "1-10", "device": "gpu|cpu", "output_dir": "..." }

// 响应
{ "status": "ok", "layout_json": "C:/out/book_output/layout/book_layout.json",
  "blocks": 312, "crops": 45, "time_s": 3.2 }
```

### 3.3 `GET /engines` — 引擎状态（tray/UI 用）

```json
// 响应
{ "engines": [
    { "name": "hybrid", "default_source": "local", "sources": ["local","cloud"],
      "status": "ready|stopped", "port": 12336 },
    ...
] }
```

### 3.4 `GET/POST /config` — 配置读写（UI 用）

- `GET /config` → 返回 engine_config.yaml 内容
- `POST /config` → 写 engine_config.local.yaml（校验 YAML）
- 权限：仅本机 + 可选 API key

### 3.5 `GET /health` — 健康检查

```json
{ "status": "ok", "version": "0.3.0", "gpu": true }
```

---

## 4. MCP server 设计

参考官方 `paddleocr-mcp`（uvx 模式）：
- 包名：`readpdf-mcp`
- 工具：`extract_pdf(pdf, pages, engine, source)` → 调本体 API
- 工具：`layout_pdf(pdf, pages, device)` → 调本体 API
- 工具：`list_engines()` → 调本体 API
- 配置：`READPDF_SERVER_URL`（默认 http://127.0.0.1:8123）+ `READPDF_API_KEY`

### MCP 注册（.mcp.json 示例）

```json
{
  "mcpServers": {
    "readpdf": {
      "command": "uvx",
      "args": ["--from", "readpdf-mcp", "readpdf_mcp"],
      "env": { "READPDF_SERVER_URL": "http://127.0.0.1:8123" }
    }
  }
}
```

---

## 5. 文件结构（新增）

```
scripts/
  server.py          # [新] Flask 本体服务（/extract /layout /engines /config /health）
  mcp_server.py      # [新] MCP server（uvx 入口，调本体 API）
  extract_pdf.py     # 不变（被 server.py 子进程调用）
```

---

## 6. 实现步骤

```
1. scripts/server.py: Flask app
   - POST /extract → subprocess extract_pdf.py --json → 解析返回
   - POST /layout  → subprocess extract_pdf.py --layout --json
   - GET /engines  → engines.load_config 汇总
   - GET/POST /config → 读/写 local.yaml
   - GET /health
2. 测试：curl 调 /extract（文本 PDF）+ /layout + /engines + /health
3. scripts/mcp_server.py: MCP 工具（调 API）
4. 测试：MCP 工具清单 + extract 调用
5. 更新 README + SKILL.md（服务模式说明）
```

---

## 7. 后续（阶段 2，不在本期）

- tray 常驻（pystray + 系统托盘图标）
- 配置 UI（Web 页或系统设置）
- 插件形态（Claude Code plugin 等）

---

## 8. 风险

| 风险 | 对策 |
|---|---|
| 子进程启动 ~1-2s | 可接受（OCR 本身 2s+）；后续可加常驻 worker 池 |
| 无认证暴露 | 默认仅 127.0.0.1 + 可选 Bearer key |
| MCP 工具参数化 | 用 schema 描述，客户端自动填 |
