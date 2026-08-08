"""合并前调用测试 — 覆盖旧 skill 实际调用路径 + 新功能边界.
前置: 本体服务运行中 + 已生成 key。
用法: python tests/premerge_smoke.py
"""
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

TEXT_PDF = r"D:\MyProjects\6_Works\hd1\器件手册\连接器选型和定义\5 高速数据传输系列连接器选型手册.pdf"
SCAN_PDF = r"D:\llm\test_data\微弱信号检测_高晋占编著_清华大学出版社_2019_第3版.pdf"
OUT = ROOT / "tests" / "premerge"
OUT.mkdir(exist_ok=True)

results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"{'✅' if ok else '❌'} {name} {detail}")


def run_cli(args):
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "extract_pdf.py")] + args,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    return r


def main():
    # 1. 旧 skill 核心路径：文本 PDF（无引擎）
    r = run_cli([TEXT_PDF, "--pages", "1", "--output-dir", str(OUT)])
    check("CLI 文本 PDF", "DONE" in (r.stdout or ""), f"rc={r.returncode}")

    # 2. 图像 PDF --hybrid（默认引擎）
    r = run_cli([SCAN_PDF, "--hybrid", "--pages", "20", "--output-dir", str(OUT)])
    check("CLI hybrid", "DONE" in (r.stdout or ""), f"rc={r.returncode}")

    # 3. --glm
    r = run_cli([SCAN_PDF, "--glm", "--pages", "20", "--output-dir", str(OUT)])
    check("CLI glm", "DONE" in (r.stdout or ""), f"rc={r.returncode}")

    # 4. --dsocr
    r = run_cli([SCAN_PDF, "--dsocr", "--pages", "20", "--output-dir", str(OUT)])
    check("CLI dsocr", "DONE" in (r.stdout or ""), f"rc={r.returncode}")

    # 5. --layout（GPU）
    r = run_cli([SCAN_PDF, "--layout", "--pages", "20", "--layout-device", "gpu", "--output-dir", str(OUT)])
    check("CLI layout gpu", "DONE" in (r.stdout or ""), f"rc={r.returncode}")

    # 6. --json 输出可解析
    r = run_cli([TEXT_PDF, "--pages", "1", "--json", "--output-dir", str(OUT)])
    import json
    try:
        block_start = (r.stdout or "").find("{")
        block_end = (r.stdout or "").rfind("}")
        j = json.loads((r.stdout or "")[block_start:block_end + 1]) if block_start != -1 else {}
        check("CLI --json 解析", j.get("status") == "ok", f"status={j.get('status')}")
    except Exception as e:
        check("CLI --json 解析", False, str(e))

    # 7. 认证：无 key 401
    import requests
    try:
        r = requests.get("http://127.0.0.1:8123/health")
        check("无 key 401", r.status_code == 401, f"code={r.status_code}")
    except Exception as e:
        check("无 key 401", False, str(e))

    # 8. 认证：带 key 200（读 ~/.readpdf/key）
    key_file = pathlib.Path.home() / ".readpdf" / "key"
    key = key_file.read_text(encoding="utf-8").strip() if key_file.exists() else ""
    try:
        r = requests.get("http://127.0.0.1:8123/health", headers={"Authorization": f"Bearer {key}"})
        check("带 key 200", r.status_code == 200, f"code={r.status_code}")
    except Exception as e:
        check("带 key 200", False, str(e))

    # 9. 校验：engine 白名单
    try:
        r = requests.post("http://127.0.0.1:8123/extract", json={"pdf": TEXT_PDF, "engine": "audit"},
                          headers={"Authorization": f"Bearer {key}"})
        check("engine 白名单拦截", r.status_code == 400, f"code={r.status_code}")
    except Exception as e:
        check("engine 白名单拦截", False, str(e))

    # 10. MCP 工具（经 server）
    import mcp_server
    r = mcp_server.extract_pdf(TEXT_PDF, pages="1")
    check("MCP extract_pdf", r.get("status") == "ok", f"size={r.get('size_bytes')}")

    print(f"\n{'='*50}\n结果: {sum(1 for _, ok in results if ok)}/{len(results)} 通过")
    failed = [n for n, ok in results if not ok]
    if failed:
        print("失败项:", failed)
        sys.exit(1)
    print("合并前调用测试全部通过 ✅")


if __name__ == "__main__":
    main()
