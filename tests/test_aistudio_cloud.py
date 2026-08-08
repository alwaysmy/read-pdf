"""PaddleOCR AI Studio 云 API 连通性测试（job 模式）.
token 从环境变量读，不落盘。用法: python tests/test_aistudio_cloud.py <image_or_pdf>
"""
import argparse
import json
import os
import pathlib
import sys
import time

JOB_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
TOKEN_ENV = "PADDLEOCR_MCP_AISTUDIO_ACCESS_TOKEN"
TAG = time.strftime("%Y%m%d_%H%M%S")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", help="本地文件路径或 URL")
    ap.add_argument("--model", default="PaddleOCR-VL-1.6", choices=["PaddleOCR-VL-1.6", "PP-OCRv6"])
    ap.add_argument("--out-dir", default="tests/bench_cloud")
    args = ap.parse_args()

    token = os.environ.get(TOKEN_ENV)
    if not token:
        print(f"错误: 环境变量 {TOKEN_ENV} 未设置（测试用 token 请临时设置）")
        sys.exit(1)

    import requests
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    headers = {"Authorization": f"bearer {token}"}
    optional_payload = {
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": False,
    }

    # 提交 job
    t0 = time.time()
    if args.file.startswith("http"):
        headers["Content-Type"] = "application/json"
        payload = {"fileUrl": args.file, "model": args.model, "optionalPayload": optional_payload}
        resp = requests.post(JOB_URL, json=payload, headers=headers, timeout=30)
    else:
        data = {"model": args.model, "optionalPayload": json.dumps(optional_payload)}
        with open(args.file, "rb") as f:
            resp = requests.post(JOB_URL, headers=headers, data=data, files={"file": f}, timeout=60)
    print(f"提交状态: {resp.status_code}")
    if resp.status_code != 200:
        print(f"响应: {resp.text[:500]}")
        sys.exit(1)
    job_id = resp.json()["data"]["jobId"]
    print(f"jobId: {job_id}（提交耗时 {time.time()-t0:.1f}s）")

    # 轮询
    t_poll = time.time()
    while True:
        r = requests.get(f"{JOB_URL}/{job_id}", headers=headers, timeout=30)
        state = r.json()["data"]["state"]
        if state == "pending":
            print("  pending...", flush=True)
        elif state == "running":
            try:
                p = r.json()["data"]["extractProgress"]
                print(f"  running: {p.get('extractedPages')}/{p.get('totalPages')} 页", flush=True)
            except KeyError:
                print("  running...", flush=True)
        elif state == "done":
            p = r.json()["data"]["extractProgress"]
            print(f"完成: {p.get('extractedPages')} 页, {p.get('startTime')} → {p.get('endTime')}")
            jsonl_url = r.json()["data"]["resultUrl"]["jsonUrl"]
            break
        elif state == "failed":
            print(f"失败: {r.json()['data'].get('errorMsg')}")
            sys.exit(1)
        time.sleep(5)
    print(f"轮询耗时: {time.time()-t_poll:.1f}s")

    # 拉结果
    jr = requests.get(jsonl_url, timeout=30)
    lines = jr.text.strip().split("\n")
    print(f"结果行数: {len(lines)}")
    for ln, line in enumerate(lines, 1):
        result = json.loads(line)["result"]
        if "layoutParsingResults" in result:
            for i, res in enumerate(result["layoutParsingResults"]):
                md = res["markdown"]["text"]
                print(f"  doc[{ln-1}][{i}]: markdown {len(md)} chars")
                print(f"    images: {list(res['markdown'].get('images', {}).keys())}")
                print(f"    outputImages: {list(res.get('outputImages', {}).keys())}")
                (out_dir / f"cloud_doc{ln-1}_{i}_{TAG}.md").write_text(md, encoding="utf-8")
        elif "ocrResults" in result:
            print(f"  ocrResults: {len(result['ocrResults'])} 页")
    print(f"输出目录: {out_dir}", flush=True)


if __name__ == "__main__":
    main()
