"""read-pdf 全量测试聚合 — 一次跑完所有测试套件并汇总.
用法: python tests/run_all_tests.py
"""
import pathlib
import subprocess
import sys
import time

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent
TAG = time.strftime("%Y%m%d_%H%M%S")

# (脚本名, 描述, 是否需要本体服务)
SUITES = [
    ("unit_engines.py", "engines 单元（配置/双源/local合并）", False),
    ("unit_server_manager.py", "server_manager 单元（GPU/回退/云跳过）", False),
    ("test_friendly_hint.py", "首次运行友好提示", False),
    ("test_mcp_tools.py", "MCP 工具函数（需本体服务）", True),
]

results = []
for script, desc, needs_server in SUITES:
    print(f"\n{'='*60}\n▶ {desc}  [{script}]\n{'='*60}", flush=True)
    t0 = time.time()
    r = subprocess.run([sys.executable, str(ROOT / script)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=1200)
    dt = time.time() - t0
    ok = r.returncode == 0
    print(f"  退出码: {r.returncode}  耗时: {dt:.1f}s")
    # 打印最后几行输出
    tail = (r.stdout or "")[-600:]
    if tail.strip():
        print("  --- 输出尾部 ---")
        print("\n".join("  " + l for l in tail.splitlines()[-6:]))
    if not ok and r.stderr:
        print("  --- stderr ---")
        print("\n".join("  " + l for l in r.stderr.splitlines()[-6:]))
    results.append({"script": script, "desc": desc, "ok": ok, "time_s": round(dt, 1)})

print(f"\n{'='*60}\n📊 汇总\n{'='*60}")
all_ok = True
for r in results:
    mark = "✅" if r["ok"] else "❌"
    print(f"{mark} {r['desc']}  [{r['script']}]  {r['time_s']}s")
    all_ok = all_ok and r["ok"]
print(f"\n总结果: {'全部通过 ✅' if all_ok else '有失败 ❌'}")

# 存档
import json
report = {"tag": TAG, "results": results, "all_ok": all_ok}
out = ROOT / "all_tests" 
out.mkdir(exist_ok=True)
(rp := out / f"run_all_tests_{TAG}.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"报告存档: {rp}")
sys.exit(0 if all_ok else 1)
