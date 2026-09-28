"""Extract text from PDF — auto-manages llama servers, outputs txt/md/json."""
import sys, os, pathlib, argparse, tempfile, base64
import json, time

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import fitz  # PyMuPDF


_vl_instances = {}


def ensure_server(name):
    """Ensure local server for engine is running (config-driven via engine_config.yaml)."""
    from engines import get_engine
    engine, src = get_engine(name)
    if src != "local":
        return  # 云源无需本地服务
    import server_manager
    server_manager.ensure(name, engine["sources"]["local"].get("server"))

# HTTP extraction backends
def _engines_call(name, img_path, prompt=None, source=None):
    """Route engine call through engines.py (config-driven local/cloud)."""
    import engines
    try:
        return engines.call(name, img_path, prompt=prompt, source=source)
    except KeyError as e:
        return "", {"error": str(e)}


# ---------------------------------------------------------------------------
# Engine-specific extractors
# ---------------------------------------------------------------------------
def extract_llama(img_path, source=None):
    """PaddleOCR-VL GGUF — more context detail."""
    return _engines_call("hybrid", img_path, prompt="OCR:", source=source)


def extract_glm(img_path, source=None):
    """GLM-OCR Q8_0 — primary image PDF engine, markdown + LaTeX."""
    return _engines_call("glm", img_path, source=source)


def extract_dsocr(img_path, source=None):
    """DeepSeek-OCR Q8_0 — text-first OCR, markdown + layout, fast (~0.8s/page)."""
    return _engines_call("dsocr", img_path, source=source)


def extract_qwen(img_path, source=None):
    """Qwen 35B — knowledge audit, HTML output (single page). source 参数仅为兼容统一调用约定。"""
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
    import engines as _eng
    endpoint, api_key = _eng.get_endpoint("qwen")
    import requests
    try:
        resp = requests.post(
            endpoint.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
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


def extract_hybrid(img_path, source=None):
    """PaddleOCR Hybrid — Python layout detection + GGUF VL, structured blocks."""
    try:
        from paddleocr import PaddleOCRVL
        import engines as _eng
        endpoint, api_key = _eng.get_endpoint("hybrid", source or "local")
        key = ('llama-cpp-server', endpoint.rstrip('/'), api_key)
        if key not in _vl_instances:
            _vl_instances[key] = PaddleOCRVL(
                vl_rec_backend='llama-cpp-server',
                vl_rec_server_url=endpoint.rstrip('/'),
                vl_rec_api_key=api_key,
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


_OV = {}


def _ov_config():
    """--ov 相关配置（engine_config(.local).yaml 的 defaults 段）."""
    try:
        import engines as _eng
        return _eng.load_config().get("defaults") or {}
    except Exception:
        return {}


def _ov_dir():
    """--ov 的 OpenVINO 模型目录（含 PP-OCRv6 ONNX 与字典）.

    优先 defaults.ocr_ov_dir（外置/自备模型）；缺省用仓库内 models/。
    运行时脚本 ppocr_openvino.py 随仓库分发（scripts/）。
    """
    d = str(_ov_config().get("ocr_ov_dir") or "").strip()
    if d:
        return d
    return str(pathlib.Path(__file__).resolve().parent.parent / "models")


def _ov_openvino_ready():
    """OpenVINO 后端可用性：openvino 能导入，且模型目录里有 v6 的 det/rec ONNX."""
    try:
        import openvino  # noqa: F401
    except Exception:
        return False
    d = _ov_dir()
    if not d:
        return False
    return all(os.path.exists(os.path.join(d, sub, "inference.onnx"))
               for sub in ("PP-OCRv6_small_det_onnx", "PP-OCRv6_small_rec_onnx"))


def _ov_backend():
    """--ov 后端，默认 auto 择优：gpu(paddle+CUDA) > openvino(CPU) > cpu(paddle).

    - defaults.ocr_backend 可强制 gpu|openvino|cpu
    - ocr_device 非 gpu 时先看 OpenVINO，避免为探测 CUDA 白付一次 paddle 导入
    - 整页 A4 密排实测：gpu ~2.0s / openvino ~2.9s / paddle-cpu ~35s
    """
    d = _ov_config()
    forced = str(d.get("ocr_backend") or "auto").strip().lower()
    if forced in ("gpu", "openvino", "cpu"):
        return forced
    if str(d.get("ocr_device") or "cpu").strip().lower() == "gpu":
        try:
            import paddle
            if paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() >= 1:
                return "gpu"
            print("[ov] ocr_device=gpu 但 paddle 非 CUDA 版或无可用设备，继续找后备后端", flush=True)
        except Exception as e:
            print(f"[ov] 检测 GPU 可用性失败（{e}），继续找后备后端", flush=True)
    if _ov_openvino_ready():
        return "openvino"
    return "cpu"


def _ov_load_openvino():
    """加载 OpenVINO 后端：运行时随仓库分发，模型/字典走 defaults.ocr_ov_dir."""
    os.environ["OCR_OV_DIR"] = _ov_dir()      # 运行时据此解析模型与字典路径
    here = str(pathlib.Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)              # 仓库副本优先于外部同名模块
    import cv2
    import ppocr_openvino as po
    from openvino import Core
    cfg = po.MODELS["v6"]
    core = Core()
    det_m = core.read_model(cfg["det"])
    det_m.reshape([1, 3, -1, -1])
    rec_m = core.read_model(cfg["rec"])
    rec_m.reshape([1, 3, cfg["rec_height"], -1])
    return {"kind": "openvino", "po": po, "cv2": cv2, "cfg": cfg,
            "det": core.compile_model(det_m, "CPU"),
            "rec": core.compile_model(rec_m, "CPU"),
            "chars": po.load_char_dict(cfg["dict"])}


def _ov_paddle(dev):
    from paddleocr import PaddleOCR
    return PaddleOCR(
        use_doc_orientation_classify=False, use_doc_unwarping=False,
        use_textline_orientation=False, enable_mkldnn=False,
        text_detection_model_name="PP-OCRv6_small_det",
        text_recognition_model_name="PP-OCRv6_small_rec",
        device=dev,
    )


def _ov_ensure():
    """Lazy-load --ov 后端（进程内，不需要 llama-server）；失败时逐级降级."""
    global _OV
    if _OV:
        return _OV
    backend = _ov_backend()
    print(f"[ov] 后端: {backend}", flush=True)
    if backend == "openvino":
        try:
            _OV = _ov_load_openvino()
            return _OV
        except Exception as e:
            print(f"[ov] OpenVINO 后端加载失败（{e}），回退 paddle cpu", flush=True)
            backend = "cpu"
    dev = "gpu" if backend == "gpu" else "cpu"
    try:
        ocr = _ov_paddle(dev)
    except Exception as e:
        if dev != "gpu":
            raise
        print(f"[ov] paddle gpu 初始化失败（{e}），回退 cpu", flush=True)
        dev, ocr = "cpu", _ov_paddle("cpu")
    _OV = {"kind": "paddle", "ocr": ocr, "device": dev}
    return _OV


# 与 PaddleOCR 默认 text_rec_score_thresh 对齐：低于此分数的识别结果丢弃，
# 否则 OpenVINO 后端会把图标/线条误检出的低置信噪声（〇 / OO / ( 等）混进正文
_OV_REC_SCORE_THRESH = 0.5


def _ov_via_openvino(ov, img_path):
    """OpenVINO 后端推理：逐行输出，不做行合并（与 PaddleOCR 的 rec_texts 口径一致）."""
    po, cv2 = ov["po"], ov["cv2"]
    img = cv2.imread(str(img_path))
    if img is None:
        return "", {"error": f"cannot read image {img_path}"}
    rows = po.ocr_image(img, ov["det"], ov["rec"], None, ov["chars"], ov["cfg"], rotate=False)
    kept = [r for r in rows if r["conf"] >= _OV_REC_SCORE_THRESH]
    stats = {"engine": "ov-openvino", "lines_raw": len(rows), "lines_kept": len(kept)}
    if kept:
        import numpy as np
        s = np.array([r["conf"] for r in kept])
        stats["confidence"] = {"mean": round(float(s.mean()), 2), "min": round(float(s.min()), 2)}
    return "\n".join(r["text"] for r in kept).replace("\ufffd", " "), stats


def extract_ov(img_path, source=None):
    """本地 OCR 引擎：官方 PP-OCRv6（det+rec，纯文本行，无版面/VL；不需要 llama-server）.

    后端由 _ov_backend() 择优：GPU Paddle ≈2.0s / OpenVINO CPU ≈2.9s / Paddle CPU ≈35s
    （整页 A4 密排，本机实测）。
    """
    ov = _ov_ensure()
    if ov["kind"] == "openvino":
        return _ov_via_openvino(ov, img_path)
    result = next(iter(ov["ocr"].predict(str(img_path))), None)
    if result is None:
        return "", {"error": "paddle predict returned nothing"}
    texts = list(result.get("rec_texts") or [])
    scores = list(result.get("rec_scores") or [])
    stats = {"engine": "paddle-v6", "device": ov.get("device", "cpu")}
    if scores:
        import numpy as np
        s = np.array(scores, dtype=float)
        stats["confidence"] = {"mean": round(float(s.mean()), 2), "min": round(float(s.min()), 2)}
    return "\n".join(t.replace("\ufffd", " ") for t in texts), stats


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
    folder.mkdir(parents=True, exist_ok=True)
    imgs = None
    if suffix == "md":
        imgs = folder / "imgs"
        imgs.mkdir(parents=True, exist_ok=True)
    name = f"{pdf_name}_{page_suffix}" if page_suffix else pdf_name
    out_path = folder / f"{name}.{suffix}"
    return folder, out_path, imgs


# ---------------------------------------------------------------------------
# Extraction cache (P3: Kimi 抽取-注入解耦 — 缓存复用避免重复 OCR)
# ---------------------------------------------------------------------------
def cache_get(cache_dir, key):
    """Read cached extraction if exists, else None."""
    path = cache_dir / f"{key}.txt"
    if path.exists():
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return None
    return None


def cache_put(cache_dir, key, text):
    """Write extraction result to cache (timestamps in filename to avoid overwrites)."""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / f"{key}.txt"
        path.write_text(text, encoding="utf-8")
        return True
    except Exception:
        return False


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
    p.add_argument("--ov", action="store_true",
                   help="本地 PP-OCRv6（进程内 OCR，无需 llama-server/GPU；det+rec 纯文本行，无版面）")
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
    p.add_argument("--no-cache", action="store_true", help="Disable extraction cache (default: cache enabled)")
    p.add_argument("--refresh-cache", action="store_true", help="Force re-OCR and refresh cache (ignore existing cache)")
    p.add_argument("--source", default=None, choices=["local", "cloud"], help="Temporarily switch service source (overrides engine default_source)")
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
        try:
            import server_manager
            server_manager.set_keep_servers(True)
        except ImportError:
            pass

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
    # 前置校验：--source cloud 只对 hybrid（走 paddle_vl）有效；glm/dsocr 无云源
    if args.source == "cloud" and (args.glm or args.dsocr):
        print(f"ERROR: 引擎 'glm|dsocr' 没有 cloud 源（engine_config.yaml 仅配置 local），无法 --source cloud", flush=True)
        sys.exit(1)
    if args.text_only:
        engine = "text"
    elif args.audit or args.html:
        engine = "audit"
        ensure_server("qwen")
    elif args.hybrid:
        engine = "hybrid"
        ensure_server("hybrid")  # PaddleOCR GGUF server needed for hybrid VL (config-driven)
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
        ensure_server("hybrid")  # deprecated alias → hybrid engine
    elif args.ov:
        engine = "ov"  # 本地 PP-OCRv6，无需 ensure_server
    elif use_ocr:
        engine = "hybrid"  # default: PaddleOCR Hybrid (layout + GGUF VL)
        ensure_server("hybrid")
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
        layout_errors = []
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
                if stats.get("error"):
                    # 版面模型/依赖缺失时 extract_layout 返回空 blocks + error。
                    # 必须记下来，否则调用方无法区分"该页没有表格/图"与"模型根本没加载"
                    layout_errors.append({"page": page_num + 1, "error": stats["error"]})
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
            "status": "error" if layout_errors else "ok",
            "errors": layout_errors,
            "file": str(pdf_path),
            "engine": "PP-DocLayoutV3",
            "dpi": args.dpi,
            "min_score": args.layout_min_score,
            "total_time": round(time.time() - t_start, 1),
            "layout_path": str(layout_path),
            "total_blocks": sum(len(p["blocks"]) for p in all_pages),
            "total_crops": crop_index,
            "pages": all_pages,
        }
        with open(str(layout_path), "w", encoding="utf-8") as f:
            json.dump(layout_result, f, ensure_ascii=False, indent=2)
        n_crops = crop_index
        n_blocks = sum(len(p["blocks"]) for p in all_pages)
        print(f"DONE: layout JSON {layout_path}  |  {n_blocks} blocks, {n_crops} crops", flush=True)
        if layout_errors:
            print(f"ERROR: 版面分析失败 {len(layout_errors)} 页（首条）：{layout_errors[0]['error']}", flush=True)
        if args.json:
            print(json.dumps(layout_result, ensure_ascii=False, indent=2), flush=True)
        sys.exit(1 if layout_errors else 0)

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
        if args.source == "cloud":
            # --source cloud: hybrid 切到云端 PaddleOCR-VL（同款模型 job 模式）
            extract_fn = lambda img, source=None: _engines_call("paddle_vl", img, source="cloud")
        else:
            extract_fn = extract_hybrid
        suffix = "md"
    elif engine == "audit":
        extract_fn = extract_qwen
        suffix = "html"
    elif engine == "ov":
        extract_fn = extract_ov
        suffix = "md"

    # 解析生效源（供缓存 key 与校验用）
    effective_source = args.source
    if engine in ("hybrid", "llama") and args.source == "cloud":
        effective_source = "cloud"  # hybrid cloud 走 paddle_vl（云）
    elif engine in ("glm", "dsocr", "hybrid") and args.source is None:
        try:
            import engines as _eng
            _, effective_source = _eng.get_engine(engine, None)
        except KeyError:
            effective_source = "local"

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

                # Extract batch (with cache if enabled)
                use_cache = not args.no_cache and not args.refresh_cache
                cache_dir = None
                # --refresh-cache: 跳过读取但仍写回新结果（刷新缓存语义）
                if not args.no_cache and engine != "audit":
                    cache_dir = out_folder / ".cache"
                if len(batch) > 1:
                    # Multi-page (audit) — no cache; 空输出重试（与单页一致）
                    text, stats = "", {}
                    for attempt in range(3):
                        t0 = time.time()
                        text, stats = extract_qwen_multi(tmp_paths)
                        dt = time.time() - t0
                        if text:
                            break
                        if attempt < 2:
                            time.sleep(2)
                else:
                    page_num = batch[0]
                    # v2：v1 的 key 未区分 ov 后端（官方 Paddle 与 OpenVINO 共用），
                    # 可能残留 OpenVINO 写下的产物；换 key 避免把旧结果当 Paddle 复用
                    key = f"{pdf_path.stem}_p{page_num+1}_{engine}_{effective_source}_d{args.dpi}_v2"
                    cached = cache_get(cache_dir, key) if (use_cache and cache_dir) else None
                    if cached is not None:
                        text, stats = cached, {"cache": "hit"}
                        dt = 0.0
                    else:
                        text, stats = "", {}
                        for attempt in range(3):
                            t0 = time.time()
                            text, stats = extract_fn(tmp_paths[0], source=args.source)
                            dt = time.time() - t0
                            if text:
                                break
                            if attempt < 2:
                                time.sleep(2)
                        if text and cache_dir:
                            cache_put(cache_dir, key, text)
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
                if stats.get("cache"):
                    page_info["cache"] = "hit"
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
