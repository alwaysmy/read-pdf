"""PP-OCRv6 det/rec on OpenVINO —— 独立 CPU 推理运行时（随 read-pdf 仓库分发）.

不依赖 PaddlePaddle：直接跑 PP-OCRv6 的 ONNX 导出，用 OpenVINO 在 CPU 上推理。
前后处理与 PaddleOCR 官方实现逐条对齐：检测用 DetResizeForTest(limit_side_len=736,
limit_type="min") + DBPostProcess（thresh/box_thresh/unclip_ratio 取自模型
inference.yml），识别用 RecResizeImg 的缩放+零填充，解码用 CTCLabelDecode 的
字典口径（按行读 + use_space_char 追加空格）与置信度均值。

模型与字典在 `<repo>/models/`（本文件位于 `<repo>/scripts/`），可直接运行；
用环境变量 OCR_OV_DIR 可指向别处覆盖（read-pdf 侧由 defaults.ocr_ov_dir 注入）。
"""

import argparse
import json
import math
import os
import pathlib
import sys
import time

import cv2
import numpy as np
import pyclipper
from openvino import Core


def default_base() -> str:
    """模型目录：优先 OCR_OV_DIR，缺省用仓库内 models/."""
    env = os.environ.get("OCR_OV_DIR", "").strip()
    if env:
        return env
    return str(pathlib.Path(__file__).resolve().parent.parent / "models")


BASE = default_base()
MODELS = {
    "v6": {
        "name": "PP-OCRv6 small",
        "det": str(pathlib.Path(BASE) / "PP-OCRv6_small_det_onnx" / "inference.onnx"),
        "cls": None,
        "rec": str(pathlib.Path(BASE) / "PP-OCRv6_small_rec_onnx" / "inference.onnx"),
        "dict": str(pathlib.Path(BASE) / "ppocr_keys_v6.txt"),
        "rec_height": 48,
        "dict_offset": 0,
        "dict_trim": 0,
    },
}
DEFAULT_MODEL = "v6"

# 检测参数对齐模型 inference.yml 的 PostProcess 与 DetResizeForTest 默认值。
# 原实现（max-side 960 / thresh 0.3 / 无 box_thresh / 自创 unclip / 无条件 dilate）
# 与官方不一致：噪声框会混进正文，裁剪几何也偏，识别随之劣化。
DET_LIMIT_SIDE_LEN = 736     # DetResizeForTest 默认 limit_side_len
DET_LIMIT_TYPE = "min"       # 默认 limit_type：短边不足则放大（而非压缩长边）
DET_MAX_SIDE_LIMIT = 4000
DET_THRESH = 0.2             # yml PostProcess.thresh
DET_BOX_THRESH = 0.45        # yml PostProcess.box_thresh
DET_MAX_CANDIDATES = 3000    # yml PostProcess.max_candidates
DET_UNCLIP_RATIO = 1.4       # yml PostProcess.unclip_ratio
DET_USE_DILATION = False
DET_MIN_SIZE = 3
CLS_SIZE = 48


def load_char_dict(path):
    """按行读字典，并追加 use_space_char 的空格。

    不要用 list(char_str) 按码点切分：国旗等 emoji 由 2 个码点组成（🇩🇪 = 2 个
    regional indicator），会被拆成两个条目，导致其后所有索引整体偏移 —— 表现为
    空格类落到 emoji 上（输出里出现 U+1F55E 之类），而常见汉字/字母仍正确。
    字典 18383 字 + blank + 空格 = 18385，与 PP-OCRv6 rec 的输出类数一致。
    """
    with open(path, "r", encoding="utf-8") as f:
        chars = [line.rstrip("\n") for line in f]
    chars = [c for c in chars if c != ""]
    return ["blank"] + chars + [" "]


def order_points(pts):
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def preprocess_det(img):
    """对齐 PaddleOCR DetResizeForTest(limit_side_len=736, limit_type='min') + NormalizeImage.

    要点：短边不足则**放大**到 736（而非压缩长边）；尺寸圆整到 32 的倍数；不做 pad。
    返回 (NCHW tensor, (源高, 源宽))。
    """
    h, w = img.shape[:2]
    ratio = 1.0
    if min(h, w) < DET_LIMIT_SIDE_LEN:
        ratio = float(DET_LIMIT_SIDE_LEN) / (h if h < w else w)
    resize_h, resize_w = int(h * ratio), int(w * ratio)
    if max(resize_h, resize_w) > DET_MAX_SIDE_LIMIT:
        ratio = float(DET_MAX_SIDE_LIMIT) / max(resize_h, resize_w)
        resize_h, resize_w = int(resize_h * ratio), int(resize_w * ratio)
    resize_h = max(int(round(resize_h / 32) * 32), 32)
    resize_w = max(int(round(resize_w / 32) * 32), 32)
    if (resize_h, resize_w) != (h, w):
        img = cv2.resize(img, (resize_w, resize_h))
    x = img.astype(np.float32)
    x = (x / 255.0 - np.array([0.485, 0.456, 0.406], np.float32)) / np.array(
        [0.229, 0.224, 0.225], np.float32
    )
    return np.expand_dims(x.transpose(2, 0, 1), 0).astype(np.float32), (h, w)


def _get_mini_boxes(contour):
    """官方 DBPostProcess.get_mini_boxes 的等价实现。"""
    bounding_box = cv2.minAreaRect(contour)
    points = sorted(list(cv2.boxPoints(bounding_box)), key=lambda p: p[0])
    idx_1, idx_2, idx_3, idx_4 = 0, 1, 2, 3
    if points[1][1] > points[0][1]:
        idx_1, idx_4 = 0, 1
    else:
        idx_1, idx_4 = 1, 0
    if points[3][1] > points[2][1]:
        idx_2, idx_3 = 2, 3
    else:
        idx_2, idx_3 = 3, 2
    box = [points[idx_1], points[idx_2], points[idx_3], points[idx_4]]
    return box, min(bounding_box[1])


def _box_score_fast(bitmap, _box):
    """官方 DBPostProcess.box_score_fast：框内均值分数（噪声框过滤的依据）。"""
    h, w = bitmap.shape[:2]
    box = _box.copy()
    xmin = max(0, min(math.floor(box[:, 0].min()), w - 1))
    xmax = max(0, min(math.ceil(box[:, 0].max()), w - 1))
    ymin = max(0, min(math.floor(box[:, 1].min()), h - 1))
    ymax = max(0, min(math.ceil(box[:, 1].max()), h - 1))
    mask = np.zeros((ymax - ymin + 1, xmax - xmin + 1), dtype=np.uint8)
    box[:, 0] = box[:, 0] - xmin
    box[:, 1] = box[:, 1] - ymin
    cv2.fillPoly(mask, box.reshape(1, -1, 2).astype(np.int32), 1)
    return cv2.mean(bitmap[ymin:ymax + 1, xmin:xmax + 1], mask)[0]


def _unclip(box, unclip_ratio):
    """官方 DBPostProcess.unclip：pyclipper 多边形外扩。"""
    area = cv2.contourArea(box)
    length = cv2.arcLength(box, True)
    distance = area * unclip_ratio / length
    offset = pyclipper.PyclipperOffset()
    offset.AddPath(box, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
    try:
        return np.array(offset.Execute(distance))
    except ValueError:
        return np.array(offset.Execute(distance)[0])


def postprocess_det(prob, src_h, src_w):
    """对齐官方 DBPostProcess.boxes_from_bitmap（quad / score_mode=fast）。

    返回 [(box(4,2) float32, xmin, ymin, xmax, ymax)]。
    """
    pred = prob[0, 0]
    mask = pred > DET_THRESH          # use_dilation=False：不做膨胀
    height, width = mask.shape
    width_scale = float(src_w) / width
    height_scale = float(src_h) / height
    contours, _ = cv2.findContours(
        (mask * 255).astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
    )
    out = []
    for contour in contours[: DET_MAX_CANDIDATES]:
        points, sside = _get_mini_boxes(contour)
        if sside < DET_MIN_SIZE:
            continue
        points = np.array(points)
        score = _box_score_fast(pred, points.reshape(-1, 2))
        if DET_BOX_THRESH > score:    # 关键：按框均值分数过滤噪声
            continue
        box = _unclip(points, DET_UNCLIP_RATIO).reshape(-1, 1, 2)
        box, sside = _get_mini_boxes(box)
        if sside < DET_MIN_SIZE + 2:
            continue
        box = np.array(box)
        for i in range(box.shape[0]):
            box[i, 0] = max(0, min(round(box[i, 0] * width_scale), src_w))
            box[i, 1] = max(0, min(round(box[i, 1] * height_scale), src_h))
        box = box.astype(np.float32)
        xmin = max(int(box[:, 0].min()), 0)
        ymin = max(int(box[:, 1].min()), 0)
        xmax = min(int(box[:, 0].max()), src_w - 1)
        ymax = min(int(box[:, 1].max()), src_h - 1)
        if xmax <= xmin or ymax <= ymin:
            continue
        out.append((box, xmin, ymin, xmax, ymax))
    return out


def crop_box(img, box, xmin, ymin, xmax, ymax):
    bw = np.linalg.norm(box[1] - box[0])
    bh = np.linalg.norm(box[3] - box[0])
    if bw < 3 or bh < 3:
        return None
    dst = np.array(
        [[0, 0], [bw - 1, 0], [bw - 1, bh - 1], [0, bh - 1]], dtype=np.float32
    )
    M = cv2.getPerspectiveTransform(box, dst)
    return cv2.warpPerspective(img, M, (int(bw), int(bh)))


def preprocess_cls(crop):
    img = cv2.resize(crop, (CLS_SIZE, CLS_SIZE), interpolation=cv2.INTER_LINEAR)
    img = img.astype(np.float32)
    img = (img / 255.0 - 0.5) / 0.5
    return np.expand_dims(np.transpose(img, (2, 0, 1)), 0).astype(np.float32)


REC_BASE_WIDTH = 320      # 模型 rec_image_shape = [3, 48, 320]
REC_MAX_WIDTH = 3200


def preprocess_rec(crop, rec_height):
    """对齐 PaddleOCR RecResizeImg.resize_norm_img。

    关键：短行按比例缩放到 resized_w 后**零填充**到 img_w，而不是拉伸。
    原实现直接 resize 到 img_w，短文本行的宽高比被拉扯，损害识别准确率。
    """
    h, w = crop.shape[:2]
    if h < 8:
        return None
    max_wh_ratio = max(REC_BASE_WIDTH / rec_height, w / float(h))
    img_w = int(rec_height * max_wh_ratio)
    if img_w > REC_MAX_WIDTH:
        img_w = resized_w = REC_MAX_WIDTH
        resized = cv2.resize(crop, (resized_w, rec_height), interpolation=cv2.INTER_LINEAR)
    else:
        ratio = w / float(h)
        resized_w = (img_w if math.ceil(rec_height * ratio) > img_w
                     else int(math.ceil(rec_height * ratio)))
        resized = cv2.resize(crop, (resized_w, rec_height), interpolation=cv2.INTER_LINEAR)
    resized = resized.astype(np.float32).transpose(2, 0, 1) / 255.0
    resized -= 0.5
    resized /= 0.5
    padded = np.zeros((3, rec_height, img_w), dtype=np.float32)
    padded[:, :, 0:resized_w] = resized
    return np.expand_dims(padded, 0).astype(np.float32)


def decode_rec(pred, char_list, dict_offset=0, dict_trim=0):
    """CTC 贪心解码；置信度取**选中字符概率的均值**（对齐 PaddleOCR CTCLabelDecode）。

    原实现取 min，导致同一份结果报出的置信度系统性低于 PaddleOCR，是口径差异而非质量差异。
    """
    ind = np.argmax(pred, axis=-1)
    text = []
    scores = []
    last = -1
    limit = len(char_list) - dict_trim
    for i in range(ind.shape[0]):
        idx = int(ind[i])
        if idx == 0 or idx == last:
            last = idx
            continue
        k = idx - dict_offset
        if 0 <= k < limit:
            text.append(char_list[k])
            scores.append(float(pred[i, idx]))
        last = idx
    if not text:
        return "", 0.0
    return "".join(text), float(np.mean(scores))


def recognize_box(img, box, xmin, ymin, xmax, ymax, rec_compiled, char_list, cls_compiled, cfg):
    crop = crop_box(img, box, xmin, ymin, xmax, ymax)
    if crop is None:
        return None
    if cls_compiled is not None:
        cls_out = cls_compiled(preprocess_cls(crop))[cls_compiled.output(0)]
        if int(np.argmax(cls_out[0])) == 1:
            crop = cv2.rotate(crop, cv2.ROTATE_180)
    rec_in = preprocess_rec(crop, cfg["rec_height"])
    if rec_in is None:
        return None
    rec_out = rec_compiled(rec_in)[rec_compiled.output(0)]
    text, conf = decode_rec(
        rec_out[0], char_list, cfg["dict_offset"], cfg["dict_trim"]
    )
    if not text:
        return None
    h, w = img.shape[:2]
    box = np.clip(box, [0, 0], [w - 1, h - 1])
    return {
        "box": [[float(v) for v in p] for p in box.tolist()],
        "text": text,
        "conf": round(conf, 4),
        "y": int(box[:, 1].min()),
        "x": int(box[:, 0].min()),
    }


def map_back_rotated(result, rot, H, W):
    """Map a result detected on an image rotated `rot`*90 degrees
    (cv2.ROTATE_90_CLOCKWISE) back to the original coordinate space (H x W)."""
    def inv(p, r):
        x, y = p
        if r == 1:
            return (y, H - 1 - x)
        if r == 2:
            return (W - 1 - x, H - 1 - y)
        return (W - 1 - y, x)

    pts = np.array([[inv(p, rot) for p in result["box"]]], dtype=np.float32)
    box = pts[0]
    result["box"] = [[float(v) for v in p] for p in box.tolist()]
    result["x"] = int(box[:, 0].min())
    result["y"] = int(box[:, 1].min())
    return result


def run_det(img, rot, det_compiled):
    work = img
    if rot == 1:
        work = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    elif rot == 2:
        work = cv2.rotate(img, cv2.ROTATE_180)
    elif rot == 3:
        work = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    det_in, (src_h, src_w) = preprocess_det(work)
    det_out = det_compiled(det_in)[det_compiled.output(0)]
    return postprocess_det(det_out, src_h, src_w)


def ocr_image(img, det_comp, rec_comp, cls_comp, char_list, cfg, rotate):
    H, W = img.shape[:2]
    best = []
    for rot in range(4):
        boxes = run_det(img, rot, det_comp)
        results = []
        for box, xmin, ymin, xmax, ymax in boxes:
            r = recognize_box(img, box, xmin, ymin, xmax, ymax, rec_comp, char_list, cls_comp, cfg)
            if r:
                if rot:
                    r = map_back_rotated(r, rot, H, W)
                results.append(r)
        if len(results) > len(best):
            best = results
        if not rotate or results or rot == 3:
            break
    best.sort(key=lambda r: (r["y"] // 20, r["x"]))
    return best


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # 错误信息走 stderr，中文需同配
    ap = argparse.ArgumentParser(description="PP-OCRv6 on OpenVINO, no PaddlePaddle")
    ap.add_argument("images", nargs="+", help="image path(s)")
    ap.add_argument("--model", choices=sorted(MODELS), default=DEFAULT_MODEL,
                    help=f"model backend (default: {DEFAULT_MODEL} = PP-OCRv6 small ONNX)")
    ap.add_argument("--cls", action="store_true",
                    help="enable per-line 180-degree correction (needs a model shipping a cls model; PP-OCRv6 does not, so this is a no-op)")
    ap.add_argument("--rotate", action="store_true", help="auto try 0/90/180/270 degree whole-image rotations")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args()
    rotate = args.rotate
    cfg = MODELS[args.model]

    missing = [p for p in (cfg["det"], cfg["rec"], cfg["dict"]) if not os.path.exists(p)]
    if missing:
        sys.exit(
            f"找不到模型文件（BASE={BASE}）：\n  " + "\n  ".join(missing) +
            "\n请设置环境变量 OCR_OV_DIR 指向含 PP-OCRv6_small_{det,rec}_onnx 与 "
            "ppocr_keys_v6.txt 的目录。")

    core = Core()
    det_model = core.read_model(cfg["det"])
    det_model.reshape([1, 3, -1, -1])
    det = core.compile_model(det_model, "CPU")
    rec_model = core.read_model(cfg["rec"])
    rec_model.reshape([1, 3, cfg["rec_height"], -1])
    rec = core.compile_model(rec_model, "CPU")
    cls = None
    if args.cls and cfg["cls"]:
        cls_model = core.read_model(cfg["cls"])
        cls_model.reshape([1, 3, CLS_SIZE, CLS_SIZE])
        cls = core.compile_model(cls_model, "CPU")
    char_list = load_char_dict(cfg["dict"])

    for p in args.images:
        img = cv2.imread(p)
        if img is None:
            print(f"FAIL: cannot read {p}")
            continue
        t0 = time.time()
        results = ocr_image(img, det, rec, cls, char_list, cfg, rotate)
        elapse = time.time() - t0
        if args.json:
            print(json.dumps({"image": p, "elapsed_s": round(elapse, 3), "lines": results},
                             ensure_ascii=False))
        else:
            print(f"{p}  [{elapse:.3f}s]")
            if not results:
                print("  (no text)")
            for r in results:
                print(f"  [{r['conf']:.2f}] {r['text']}")


if __name__ == "__main__":
    main()
