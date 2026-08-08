"""Extract text from PDF — auto-manages llama servers, outputs txt/md/json."""
import sys, os, pathlib, argparse, tempfile, base64
import json, time, socket, subprocess, atexit, signal

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import fitz  # PyMuPDF

# ---------------------------------------------------------------------------
# Server auto-management
# ---------------------------------------------------------------------------
LLAMA_DIR = r"D:\llm\llama-b9830-bin-win-cuda-13.3-x64"
LLAMA_SERVER = os.path.join(LLAMA_DIR, "llama-server.exe")

SERVERS = {
    "llama": {  # PaddleOCR-VL GGUF — alternative, more context detail
        "port": 12336,
        "args": [
            LLAMA_SERVER,
            "-m", r"D:\llm\PaddlePaddle\PaddleOCR-VL-1.6-GGUF\PaddleOCR-VL-1.6-GGUF.gguf",
            "--mmproj", r"D:\llm\PaddlePaddle\PaddleOCR-VL-1.6-GGUF\PaddleOCR-VL-1.6-GGUF-mmproj.gguf",
            "--port", "12336", "--host", "127.0.0.1",
            "-ngl", "100", "--no-mmap", "--no-warmup",
            "-c", "32768", "-n", "32768", "-t", "8", "-np", "1",
            "--api-key", "12345",
        ],
    },
    "glm": {  # GLM-OCR Q8_0 — primary image PDF engine
        "port": 12335,
        "args": [
            LLAMA_SERVER,
            "-m", r"D:\llm\ggml-org\GLM-OCR-GGUF\GLM-OCR-Q8_0.gguf",
            "--mmproj", r"D:\llm\ggml-org\GLM-OCR-GGUF\mmproj-GLM-OCR-Q8_0.gguf",
            "--port", "12335", "--host", "127.0.0.1",
            "-ngl", "100", "--no-mmap", "--no-warmup",
            "-c", "16384", "-n", "16384", "-t", "8", "-np", "1",
            "--api-key", "12345",
        ],
    },
    "dsocr": {  # DeepSeek-OCR Q8_0 — text-first multimodal OCR (P2)
        "port": 12337,
        "args": [
            LLAMA_SERVER,
            "-m", r"D:\llm\ggml-org\DeepSeek-OCR\DeepSeek-OCR-Q8_0.gguf",
            "--mmproj", r"D:\llm\ggml-org\DeepSeek-OCR\mmproj-DeepSeek-OCR-Q8_0.gguf",
            "--port", "12337", "--host", "127.0.0.1",
            "-ngl", "100", "--no-mmap", "--no-warmup",
            "-c", "8192", "-n", "8192", "-t", "8", "-np", "1",
            "--api-key", "12345",
        ],
    },
    "qwen": {  # Qwen3.6-35B-A3B — knowledge audit
        "port": 12334,
        "args": [
            LLAMA_SERVER,
            "-m", r"D:\llm\HauhauCS\Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive\Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-IQ4_NL.gguf",
            "--mmproj", r"D:\llm\HauhauCS\Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive\mmproj-Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-f16.gguf",
            "--port", "12334", "--host", "127.0.0.1",
            "-ngl", "100", "-ncmoe", "32", "--no-mmap", "--no-warmup",
            "-fa", "on", "-fit", "on",
            "--cache-type-k", "q8_0", "--cache-type-v", "q8_0",
            "--no-context-shift",
            "--spec-type", "ngram-mod", "--spec-ngram-mod-n-max", "16", "--spec-ngram-mod-n-min", "8",
            "-c", "131072", "-n", "131072", "-t", "8", "-np", "1",
            "--api-key", "12345",
        ],
        "env": {"LLAMA_CHAT_TEMPLATE_KWARGS": '{"enable_thinking":false}'},
    },
}

_started_servers = []
_vl_instances = {}


def is_port_open(port, host="127.0.0.1"):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False


def start_server(name):
    cfg = SERVERS[name]
    if is_port_open(cfg["port"]):
        print(f"[server] {name} already running on port {cfg['port']}", flush=True)
        return
    # Check VRAM before starting
    try:
        import subprocess as _sp
        out = _sp.check_output(
            "nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits",
            shell=True, text=True
        )
        free_mb = int(out.strip())
        if free_mb < 3072:
            print(f"[server] WARNING: only {free_mb} MiB VRAM free (need >3GB). Server may fail.", flush=True)
    except Exception:
        pass
    print(f"[server] starting {name} on port {cfg['port']}...", flush=True)
    proc_env = os.environ.copy()
    if cfg.get("env"):
        proc_env.update(cfg["env"])
    proc = subprocess.Popen(
        cfg["args"],
        env=proc_env,
        creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0,
    )
    _started_servers.append((name, proc))
    # Wait for HTTP server to be fully ready (not just port open)
    for _this in range(60):
        if is_port_open(cfg["port"]):
            try:
                import requests
                r = requests.get(f"http://127.0.0.1:{cfg['port']}/health", timeout=2)
                if r.status_code == 200:
                    print(f"[server] {name} ready", flush=True)
                    return
            except Exception:
                pass
        time.sleep(2)
    print(f"[server] WARNING: {name} health check failed after 120s", flush=True)


def ensure_server(name):
    if not is_port_open(SERVERS[name]["port"]):
        start_server(name)


def stop_all_servers():
    for name, proc in _started_servers:
        print(f"[server] stopping {name}...", flush=True)
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    _started_servers.clear()


def cleanup():
    stop_all_servers()
    _vl_instances.clear()


atexit.register(cleanup)

# ---------------------------------------------------------------------------
# HTTP extraction backends
# ---------------------------------------------------------------------------
def http_extract(port, prompt, img_path, temp=0, max_tokens=4096):
    """Generic HTTP extraction via llama-server."""
    with open(img_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    import requests
    try:
        resp = requests.post(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            headers={"Authorization": "Bearer 12345"},
            json={
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                        {"type": "text", "text": prompt},
                    ],
                }],
                "temperature": temp,
                "max_tokens": max_tokens,
            },
            timeout=180,
        )
        if resp.status_code != 200:
            return "", {"error": f"HTTP {resp.status_code}"}
        content = resp.json()["choices"][0]["message"]["content"]
        return content, {}
    except Exception as e:
        return "", {"error": str(e)}


# ---------------------------------------------------------------------------
# Engine-specific extractors
# ---------------------------------------------------------------------------
def extract_llama(img_path):
    """PaddleOCR-VL GGUF — more context detail."""
    return http_extract(12336, "OCR:", img_path, temp=0, max_tokens=4096)


def extract_glm(img_path):
    """GLM-OCR Q8_0 — primary image PDF engine, markdown + LaTeX."""
    return http_extract(12335, "Text Recognition:", img_path, temp=0, max_tokens=4096)


def http_extract_text_first(port, prompt, img_path, temp=0, max_tokens=8192):
    """HTTP extraction for text-first models (DeepSeek-OCR): text BEFORE image."""
    with open(img_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    import requests
    try:
        resp = requests.post(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            headers={"Authorization": "Bearer 12345"},
            json={
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                    ],
                }],
                "temperature": temp,
                "max_tokens": max_tokens,
            },
            timeout=180,
        )
        if resp.status_code != 200:
            return "", {"error": f"HTTP {resp.status_code}"}
        content = resp.json()["choices"][0]["message"]["content"]
        return content, {}
    except Exception as e:
        return "", {"error": str(e)}


def extract_dsocr(img_path):
    """DeepSeek-OCR Q8_0 — text-first OCR, markdown + layout, fast (~0.8s/page)."""
    return http_extract_text_first(12337, "OCR markdown", img_path, temp=0, max_tokens=8192)


def extract_qwen(img_path):
    """Qwen 35B — knowledge audit, HTML output (single page)."""
    text, stats = _qwen_raw([img_path])
    return _qwen_postprocess(text), stats


def extract_qwen_multi(img_paths):
    """Qwen 35B — knowledge audit, HTML output (multi-page, cross-page context)."""
    prompt = f"以下 {len(img_paths)} 页是连续的文档内容，正确排版输出全文，用HTML格式，不要任何解释和前言，保持跨页表格/段落的连续性。"
    text, stats = _qwen_raw(img_paths, prompt)
    return _qwen_postprocess(text), stats


def _qwen_raw(img_paths, prompt=None):
    """Call Qwen server with one or more images."""
    if prompt is None:
        prompt = "正确排版输出这一页内容，用HTML格式，不要任何解释和前言。"
    with open(img_paths[0], "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    content = [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}}]
    # Append additional pages
    for p in img_paths[1:]:
        with open(p, "rb") as f:
            b2 = base64.b64encode(f.read()).decode()
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b2}"}})
    content.append({"type": "text", "text": prompt})
    import requests
    try:
        resp = requests.post(
            "http://127.0.0.1:12334/v1/chat/completions",
            headers={"Authorization": "Bearer 12345"},
            json={"messages": [{"role": "user", "content": content}], "temperature": 0, "max_tokens": 8192},
            timeout=300,
        )
        if resp.status_code != 200:
            return "", {"error": f"HTTP {resp.status_code}"}
        return resp.json()["choices"][0]["message"]["content"], {}
    except Exception as e:
        return "", {"error": str(e)}


def _qwen_postprocess(text):
    """Strip code blocks and inject MathJax."""
    text = text.strip()
    if text.startswith("```html"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    MATHJAX = (
        '<script>\n'
        'MathJax = { tex: { inlineMath: [["$", "$"], ["\\\\(", "\\\\)"]], displayMath: [["$$", "$$"], ["\\\\[", "\\\\]"]] } };\n'
        '</script>\n'
        '<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>\n'
    )
    text = text.strip()
    if text.startswith("<html"):
        if "<head>" in text:
            text = text.replace("<head>", "<head>\n" + MATHJAX, 1)
        elif "<body>" in text:
            text = text.replace("<body>", "<body>\n" + MATHJAX, 1)
        else:
            text = MATHJAX + text
    else:
        text = MATHJAX + text
    return text


def extract_hybrid(img_path):
    """PaddleOCR Hybrid — Python layout detection + GGUF VL, structured blocks."""
    try:
        from paddleocr import PaddleOCRVL
        key = ('llama-cpp-server', 'http://127.0.0.1:12336/v1', '12345')
        if key not in _vl_instances:
            _vl_instances[key] = PaddleOCRVL(
                vl_rec_backend='llama-cpp-server',
                vl_rec_server_url='http://127.0.0.1:12336/v1',
                vl_rec_api_key='12345',
                use_layout_detection=True,
                use_chart_recognition=False,
                use_seal_recognition=False,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
            )
        vl = _vl_instances[key]
        result = vl.predict(img_path)
        res = result[0].json['res']
        blocks = []
        for item in res.get('parsing_res_list', []):
            label = item.get('block_label', 'text')
            content = item.get('block_content', '').strip()
            bbox = item.get('block_bbox', [])
            bbox_str = f'bbox={bbox}' if bbox else ''
            if content:
                if label == 'header':
                    blocks.append(f'<!-- {bbox_str} -->\n### {content}')
                elif label == 'title':
                    blocks.append(f'<!-- {bbox_str} -->\n## {content}')
                elif label == 'display_formula':
                    blocks.append(f'$${content}$$ <!-- {bbox_str} -->')
                elif label == 'formula_number':
                    blocks.append(f'({content}) <!-- {bbox_str} -->')
                else:
                    blocks.append(f'{content} <!-- {bbox_str} -->')
        text = '\n\n'.join(blocks)
        return text, {}
    except Exception as e:
        return "", {"error": str(e)}


def extract_paddle_vl(img_path):
    """PaddleOCRVL native — best formula formatting."""
    from paddleocr import PaddleOCRVL
    pipeline = PaddleOCRVL(use_seal_recognition=False, use_chart_recognition=False,
                           use_doc_orientation_classify=False, use_doc_unwarping=False)
    output = pipeline.predict(str(img_path))
    result = next(iter(output), None)
    if result is None:
        return "", {}
    md = result.markdown
    if isinstance(md, dict):
        return md.get("markdown_texts", "") or "", {}
    return str(md) if md else "", {}


def extract_ocr(img_path):
    """PP-OCRv5 traditional — zero hallucination, plain text."""
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(lang="ch", use_textline_orientation=True)
    output = ocr.predict(str(img_path))
    result = next(iter(output), None)
    if result is None:
        return "", {}
    texts = result.get("rec_texts", [])
    scores = result.get("rec_scores", [])
    stats = {}
    if scores:
        import numpy as np
        s_arr = np.array(scores)
        stats = {"confidence": {"mean": float(s_arr.mean()), "min": float(s_arr.min())}}
    return "\n".join(texts), stats


def extract_pdfmux(pdf_path, pages=None):
    """pdfmux — text-layer structure reconstruction, fast and accurate."""
    try:
        from pdfmux import extract_text
        text = extract_text(str(pdf_path), quality="standard")
        return text, {}
    except Exception as e:
        return "", {"error": str(e)}


# ---------------------------------------------------------------------------
# Layout analysis (P1: PicoDet-S_layout_3cls / PP-DocLayoutV3)
# ---------------------------------------------------------------------------
_LAYOUT_MODEL = None


def _get_layout_model(device="cpu"):
    """Lazy-load PaddleX PP-DocLayoutV3 (PicoDet 版面检测)."""
    global _LAYOUT_MODEL
    if _LAYOUT_MODEL is None:
        import paddlex as pdx
        _LAYOUT_MODEL = pdx.create_model('PP-DocLayoutV3', device=device)
    return _LAYOUT_MODEL


# table/figure 等可裁剪元素；text/header/footer 等文本元素不裁剪
_CROP_LABELS = {"table", "figure", "formula", "image", "chart", "seal", "stamp", "figure_caption", "table_caption"}


def extract_layout(img_path, page_num=1, min_score=0.3, device="cpu"):
    """PaddleX PP-DocLayoutV3 版面检测 — 返回结构化 blocks（label + bbox + score）."""
    try:
        model = _get_layout_model(device)
        result = model.predict(str(img_path))
        res = next(iter(result), None)
        if res is None:
            return [], {}
        blocks = []
        for box in res.get("boxes", []):
            label = box.get("label", "text")
            score = float(box.get("score", 0.0))
            if score < min_score:
                continue
            coord = box.get("coordinate") or []
            if len(coord) == 4:
                bbox = [int(v) for v in coord]  # [x0, y0, x1, y1]
            else:
                pts = box.get("polygon_points")
                if pts is not None and len(pts) >= 4:
                    xs = [float(p[0]) for p in pts]
                    ys = [float(p[1]) for p in pts]
                    bbox = [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]
                else:
                    continue
            blocks.append({
                "label": label,
                "score": round(score, 3),
                "bbox": bbox,
                "crop": label in _CROP_LABELS,
            })
        return blocks, {}
    except Exception as e:
        return [], {"error": str(e)}


# ---------------------------------------------------------------------------
# Text PDF helpers
# ---------------------------------------------------------------------------
def extract_page_text(page):
    return page.get_text().strip()


def format_table_md(table):
    if not table or len(table) < 1:
        return ""
    rows = []
    seen = set()
    for row in table:
        row_str = " | ".join(str(c).replace("\n", "<br>") if c else "" for c in row)
        if row_str in seen:
            continue
        seen.add(row_str)
        rows.append(row)
    if len(rows) < 2:
        return " | ".join(rows[0]) if rows else ""
    header = rows[0]
    cols = len(header)
    sep = "|".join(["---"] * cols)
    md = f"| {' | '.join(header)} |\n|{sep}|\n"
    for row in rows[1:]:
        padded = list(row) + [""] * (cols - len(row))
        md += f"| {' | '.join(padded[:cols])} |\n"
    return md


# ---------------------------------------------------------------------------
# Output folder
# ---------------------------------------------------------------------------
def make_output_folder(pdf_name, suffix, output_dir=None, page_suffix=""):
    """Create {pdf}_output/ folder. Returns (folder_path, output_path, imgs_path).

    page_suffix: if set (e.g. "p1-10"), appended to filename to prevent --pages overwrites.
    """
    base = pathlib.Path(output_dir) if output_dir else pathlib.Path.cwd()
    folder = base / f"{pdf_name}_output"
    folder.mkdir(exist_ok=True)
    imgs = None
    if suffix == "md":
        imgs = folder / "imgs"
        imgs.mkdir(exist_ok=True)
    name = f"{pdf_name}_{page_suffix}" if page_suffix else pdf_name
    out_path = folder / f"{name}.{suffix}"
    return folder, out_path, imgs


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser(description="Extract text from PDF — auto-manages llama servers")
    p.add_argument("pdf_path", help="Path to the PDF file")
    p.add_argument("--pages", help="Page range, e.g. '1-10'")
    p.add_argument("--dpi", type=int, default=150, help="Render DPI for OCR (default: 150, lower=faster)")
    p.add_argument("--force-ocr", action="store_true", help="Use OCR even if text detected")
    p.add_argument("--glm", action="store_true", help="GLM-OCR Q8_0 (primary, ~4s/page, LaTeX+formulas)")
    p.add_argument("--dsocr", action="store_true", help="DeepSeek-OCR Q8_0 (text-first multimodal, ~0.8s/page, markdown)")
    p.add_argument("--hybrid", action="store_true", help="PaddleOCR Hybrid (Python layout + GGUF VL, ~8s/page)")
    p.add_argument("--ocr", action="store_true", help="[DEPRECATED] PP-OCRv5 (use --hybrid instead)")
    p.add_argument("--audit", action="store_true", help="Qwen 35B knowledge audit (use on 2-3 key pages)")
    p.add_argument("--html", action="store_true", help="Same as --audit (more intuitive name)")
    p.add_argument("--no-table", action="store_true", help="Skip pdfplumber table extraction")
    p.add_argument("--pdfmux", action="store_true", help="Use pdfmux for text PDF structure (default: auto)")
    p.add_argument("--no-pdfmux", action="store_true", help="Disable pdfmux for text PDF")
    p.add_argument("--text-only", action="store_true", help="Text-only mode: force text engine, print bare page text to stdout (form-feed delimited, pdftotext-compatible)")
    p.add_argument("--json", action="store_true", help="Output structured JSON (prints to stdout)")
    p.add_argument("--output-dir", help="Output directory")
    p.add_argument("--batch", action="store_true", help="Send all --pages as one request (audit engine, cross-page context)")
    p.add_argument("--keep-servers", action="store_true", help="Keep llama servers running after extraction")
    p.add_argument("--layout", action="store_true", help="Layout analysis: detect table/figure regions, crop screenshots, output layout JSON (PP-DocLayoutV3)")
    p.add_argument("--layout-only", action="store_true", help="Layout analysis only: skip OCR, just output layout JSON + crops (implies --layout)")
    p.add_argument("--layout-min-score", type=float, default=0.3, help="Layout detection min score (default 0.3)")
    p.add_argument("--layout-device", default="cpu", choices=["cpu", "gpu"], help="Layout detection device (default cpu, GPU 被 OCR 服务占用时用 CPU)")
    # --- Deprecated ---
    p.add_argument("--vl", action="store_true", help="[DEPRECATED] PaddleOCRVL native (use --hybrid instead)")
    p.add_argument("--llama", action="store_true", help="[DEPRECATED] PaddleOCR-VL GGUF (use --hybrid instead)")
    return p.parse_args()


def main():
    args = parse_args()
    pdf_path = pathlib.Path(args.pdf_path)
    if not pdf_path.exists():
        print(f"ERROR: file not found: {pdf_path}", flush=True)
        sys.exit(1)

    if args.keep_servers:
        atexit.unregister(cleanup)

    doc = fitz.open(str(pdf_path))
    total_pages = len(doc)

    if args.pages:
        # Support comma-separated ranges: "5-10,20-25" or "3,7,15-18"
        page_nums = set()
        for part in args.pages.split(","):
            part = part.strip()
            if not part:
                continue  # skip empty segments (e.g. trailing comma)
            try:
                if "-" in part:
                    r = part.split("-")
                    if len(r) != 2 or not r[0] or not r[1]:
                        print(f"ERROR: invalid page range: '{part}' (expected N-M)", flush=True)
                        sys.exit(1)
                    start = int(r[0])
                    end = int(r[1])
                    if start < 1:
                        print(f"ERROR: page numbers start at 1, got '{part}'", flush=True)
                        sys.exit(1)
                    if start > total_pages:
                        print(f"ERROR: start page {start} exceeds total pages {total_pages}", flush=True)
                        sys.exit(1)
                    if end > total_pages:
                        print(f"WARNING: end page {end} exceeds total pages {total_pages}, truncating", flush=True)
                        end = total_pages
                    if start > end:
                        print(f"ERROR: start page {start} > end page {end}", flush=True)
                        sys.exit(1)
                    page_nums.update(range(start - 1, end))
                else:
                    n = int(part)
                    if n < 1 or n > total_pages:
                        print(f"ERROR: page {n} out of range (1-{total_pages})", flush=True)
                        sys.exit(1)
                    page_nums.add(n - 1)
            except ValueError:
                print(f"ERROR: invalid page number: '{part}'", flush=True)
                sys.exit(1)
        page_nums = sorted(page_nums)
        if not page_nums:
            print("ERROR: no valid pages selected", flush=True)
            sys.exit(1)
    else:
        page_nums = list(range(total_pages))

    requested_pages = len(page_nums)
    # Build page suffix for output filename (prevents --pages overwrites)
    if args.pages:
        # Compact: contiguous range → p5-10, comma → p5-10_20-25
        suffix_parts = []
        seg_start = page_nums[0]
        seg_end = page_nums[0]
        for pn in page_nums[1:]:
            if pn == seg_end + 1:
                seg_end = pn
            else:
                suffix_parts.append(f"{seg_start+1}-{seg_end+1}" if seg_start != seg_end else str(seg_start+1))
                seg_start = seg_end = pn
        suffix_parts.append(f"{seg_start+1}-{seg_end+1}" if seg_start != seg_end else str(seg_start+1))
        page_suffix = "p" + ("_".join(suffix_parts)[:80])  # cap length
    else:
        page_suffix = ""

    # Detect text vs image
    detection_info = {"method": "chars_per_page", "threshold": 100}
    if args.force_ocr:
        use_ocr = True
        detection_info["forced"] = True
    else:
        sample_size = min(3, total_pages)
        sample_chars = sum(len(doc[i].get_text().strip()) for i in range(sample_size))
        avg_chars = sample_chars / sample_size
        use_ocr = avg_chars < 100
        detection_info["avg_chars"] = round(avg_chars, 0)
        detection_info["sample_size"] = sample_size
        detection_info["is_image_pdf"] = use_ocr

    # Determine engine + ensure servers
    if args.text_only:
        engine = "text"
    elif args.audit or args.html:
        engine = "audit"
        ensure_server("qwen")
    elif args.hybrid:
        engine = "hybrid"
        ensure_server("llama")  # PaddleOCR GGUF server needed for hybrid VL
    elif args.vl:
        engine = "vl"
        print("Engine: PaddleOCRVL (native, ~84s/page)", flush=True)
    elif args.glm:
        engine = "glm"
        ensure_server("glm")
    elif args.dsocr:
        engine = "dsocr"
        ensure_server("dsocr")
    elif args.llama:
        engine = "llama"
        ensure_server("llama")
    elif args.ocr:
        engine = "ocr"
    elif use_ocr:
        engine = "hybrid"  # default: PaddleOCR Hybrid (layout + GGUF VL)
        ensure_server("llama")
    else:
        engine = "text"

    print(f"PDF: {pdf_path.name}  |  {total_pages}p  |  pages {len(page_nums)} selected  |  engine={engine}", flush=True)

    # --- Text-only mode: bare page text to .txt file ---
    if args.text_only:
        out_folder, out_path, _unused_imgs = make_output_folder(pdf_path.stem, "txt", args.output_dir, page_suffix)
        with open(str(out_path), "w", encoding="utf-8") as f:
            for page_num in page_nums:
                page = doc[page_num]
                text = extract_page_text(page)
                f.write(text)
                f.write("\f")
        doc.close()
        print(f"DONE: {out_path.stat().st_size} bytes  |  {out_path}", flush=True)
        sys.exit(0)

    # --- Layout analysis mode (P1: PP-DocLayoutV3, no OCR needed) ---
    if args.layout or args.layout_only:
        out_folder, out_path, _unused_imgs = make_output_folder(pdf_path.stem, "layout", args.output_dir, page_suffix)
        layout_dir = out_folder / "layout"
        crops_dir = layout_dir / "crops"
        layout_dir.mkdir(exist_ok=True)
        crops_dir.mkdir(exist_ok=True)
        layout_path = layout_dir / f"{pdf_path.stem}_layout.json"
        all_pages = []
        crop_index = 0
        t_start = time.time()
        for idx, page_num in enumerate(page_nums):
            page = doc[page_num]
            pix = page.get_pixmap(dpi=args.dpi)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                pix.save(tmp_path)
                blocks, stats = extract_layout(tmp_path, page_num=page_num + 1, min_score=args.layout_min_score, device=args.layout_device)
                page_blocks = []
                for b in blocks:
                    b["page"] = page_num + 1
                    if b.pop("crop", False):
                        # Crop element region from rendered page
                        x0, y0, x1, y1 = b["bbox"]
                        crop_name = f"page{page_num+1:04d}_crop{crop_index:03d}_{b['label']}.png"
                        crop_path = crops_dir / crop_name
                        try:
                            import PIL.Image
                            img = PIL.Image.open(tmp_path)
                            img.crop((x0, y0, x1, y1)).save(str(crop_path))
                            b["crop_path"] = str(crop_path)
                            crop_index += 1
                        except Exception as ce:
                            b["crop_error"] = str(ce)
                    page_blocks.append(b)
                all_pages.append({"page": page_num + 1, "blocks": page_blocks})
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
            progress = (idx + 1) * 100 // requested_pages
            if progress % 20 == 0 or progress == 100:
                print(f"  {progress}% ({idx + 1}/{requested_pages})", flush=True)
        doc.close()
        layout_result = {
            "status": "ok",
            "file": str(pdf_path),
            "engine": "PP-DocLayoutV3",
            "dpi": args.dpi,
            "min_score": args.layout_min_score,
            "total_time": round(time.time() - t_start, 1),
            "pages": all_pages,
        }
        with open(str(layout_path), "w", encoding="utf-8") as f:
            json.dump(layout_result, f, ensure_ascii=False, indent=2)
        n_crops = crop_index
        n_blocks = sum(len(p["blocks"]) for p in all_pages)
        print(f"DONE: layout JSON {layout_path}  |  {n_blocks} blocks, {n_crops} crops", flush=True)
        if args.json:
            print(json.dumps(layout_result, ensure_ascii=False, indent=2), flush=True)
        sys.exit(0)

    # --- Text path ---
    if engine == "text":
        use_plumber = not args.no_table
        use_pdfmux = not args.no_pdfmux
        total_tables = 0
        out_folder, out_path, _unused_imgs = make_output_folder(pdf_path.stem, "md", args.output_dir, page_suffix)
        pages_data = []

        # Extract pdfmux content for selected pages
        pdfmux_content = ""
        if use_pdfmux:
            try:
                if args.pages:
                    # Create sub-PDF for selected pages
                    sub_doc = fitz.open()
                    for p in page_nums:
                        sub_doc.insert_pdf(doc, from_page=p, to_page=p)
                    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                        sub_path = tmp.name
                    sub_doc.save(sub_path)
                    sub_doc.close()
                    pdfmux_content, _unused = extract_pdfmux(sub_path)
                    try:
                        os.unlink(sub_path)
                    except Exception:
                        pass
                else:
                    pdfmux_content, _unused = extract_pdfmux(pdf_path)
            except Exception:
                pass

        with open(str(out_path), "w", encoding="utf-8") as f:
            if pdfmux_content:
                f.write("<!-- PDFMUX OUTPUT (structured, from text layer) -->\n\n")
                f.write(pdfmux_content)
                f.write("\n\n<!-- PYMUPDF + PDFPLUMBER REFERENCE -->\n")

            for idx, page_num in enumerate(page_nums):
                t0 = time.time()
                page = doc[page_num]
                text = extract_page_text(page)
                f.write(f"\n\n<!-- PAGE {page_num + 1} -->\n\n")
                f.write(text)

                tables_found = 0
                if use_plumber:
                    try:
                        import pdfplumber
                        with pdfplumber.open(str(pdf_path)) as p:
                            tables = p.pages[page_num].extract_tables()
                        if tables:
                            f.write("\n\n[TABLES]\n\n")
                            for t in tables:
                                f.write(format_table_md(t))
                                f.write("\n")
                            tables_found = len(tables)
                            total_tables += tables_found
                    except Exception:
                        pass

                dt = time.time() - t0
                pages_data.append({
                    "page": page_num + 1,
                    "engine": "text",
                    "time": round(dt, 1),
                    "chars": len(text),
                    "tables": tables_found,
                })

                progress = (idx + 1) * 100 // requested_pages
                if progress % 10 == 0 or progress == 100:
                    print(f"  {progress}% ({idx + 1}/{requested_pages})", flush=True)

        doc.close()
        result = {"status": "ok", "file": str(out_path), "size_bytes": out_path.stat().st_size,
                  "total_tables": total_tables, "pages": pages_data}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        else:
            print(f"DONE: {out_path.stat().st_size} bytes, {total_tables} tables  |  {out_path}", flush=True)
        return

    # --- Image/OCR path ---
    if engine == "glm":
        extract_fn = extract_glm
        suffix = "md"
    elif engine == "dsocr":
        extract_fn = extract_dsocr
        suffix = "md"
    elif engine == "vl":
        extract_fn = extract_paddle_vl
        suffix = "md"
    elif engine == "llama":
        extract_fn = extract_llama
        suffix = "md"
    elif engine == "hybrid":
        extract_fn = extract_hybrid
        suffix = "md"
    elif engine == "audit":
        extract_fn = extract_qwen
        suffix = "html"
    elif engine == "ocr":
        extract_fn = extract_ocr
        suffix = "md"

    out_folder, out_path, _unused_imgs = make_output_folder(pdf_path.stem, suffix, args.output_dir, page_suffix)
    pages_data = []

    page_nums = sorted(page_nums)  # already a set from comma parsing, or range
    batch_size = len(page_nums) if (engine == "audit" and args.batch) else 1
    if args.batch and engine != "audit":
        print(f"WARNING: --batch is only effective with --audit, ignored for {engine}", flush=True)

    with open(str(out_path), "w", encoding="utf-8") as f:
        i = 0
        while i < len(page_nums):
            # Collect batch_size pages
            batch = page_nums[i:i + batch_size]
            tmp_paths = []
            try:
                for page_num in batch:
                    page = doc[page_num]
                    pix = page.get_pixmap(dpi=args.dpi)
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                        tmp_path = tmp.name
                    pix.save(tmp_path)
                    tmp_paths.append(tmp_path)

                # Extract batch
                if len(batch) > 1:
                    t0 = time.time()
                    text, stats = extract_qwen_multi(tmp_paths)
                    dt = time.time() - t0
                else:
                    text, stats = "", {}
                    for attempt in range(3):
                        t0 = time.time()
                        text, stats = extract_fn(tmp_paths[0])
                        dt = time.time() - t0
                        if text:
                            break
                        if attempt < 2:
                            time.sleep(2)
            finally:
                for tp in tmp_paths:
                    try:
                        os.unlink(tp)
                    except Exception:
                        pass

            if text:
                page_label = f"<!-- PAGES {batch[0]+1}-{batch[-1]+1} -->" if len(batch) > 1 else f"<!-- PAGE {batch[0]+1} -->"
                f.write(f"\n\n{page_label}\n\n")
                f.write(text)
                f.flush()

            for page_num in batch:
                page_info = {
                    "page": page_num + 1,
                    "engine": engine,
                    "time": round(dt / len(batch), 1),
                    "chars": len(text) // len(batch),
                }
                if stats.get("confidence"):
                    page_info["confidence"] = stats["confidence"]
                if stats.get("error"):
                    page_info["error"] = stats["error"]
                pages_data.append(page_info)

            progress = (i + len(batch)) * 100 // requested_pages
            print(f"  {progress}% ({i + len(batch)}/{requested_pages})", flush=True)
            i += len(batch)

    doc.close()

    # Collect issues
    issues = []
    for pd_page in pages_data:
        if pd_page["chars"] < 30:
            issues.append(f"page {pd_page['page']}: low content ({pd_page['chars']} chars)")
        if pd_page.get("error"):
            issues.append(f"page {pd_page['page']}: {pd_page['error']}")

    out_size = out_path.stat().st_size
    total_time = sum(p["time"] for p in pages_data)

    result = {
        "status": "ok" if not issues else "warn",
        "file": str(out_path),
        "size_bytes": out_size,
        "engine": engine,
        "detection": detection_info,
        "total_time": round(total_time, 1),
        "pages": pages_data,
    }
    if issues:
        result["issues"] = issues

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    else:
        print(f"DONE: {out_size} bytes  |  {engine}  |  {out_path}", flush=True)
        for issue in issues:
            print(f"  {issue}", flush=True)


if __name__ == "__main__":
    main()
