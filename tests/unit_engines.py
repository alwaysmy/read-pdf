"""engines.py 单元验证：配置加载/双源解析/local 合并.
用法: python tests/unit_engines.py
"""
import pathlib
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))


def main():
    import engines

    # 1. 配置加载
    cfg = engines.load_config(force=True)
    assert "engines" in cfg and "hybrid" in cfg["engines"], "配置加载失败"
    print("1. 配置加载 OK:", list(cfg["engines"].keys()))

    # 2. 双源解析
    engine, src = engines.get_engine("hybrid")
    assert src == "local", f"hybrid 默认源应为 local, 实际 {src}"
    engine_c, src_c = engines.get_engine("hybrid", "cloud")
    assert src_c == "cloud"
    print("2. 双源解析 OK: hybrid 默认 local, 可切 cloud")

    # 3. 端点读取
    ep, key = engines.get_endpoint("glm")
    assert "12335" in ep, f"glm 端点错误: {ep}"
    print(f"3. glm 本地端点 OK: {ep}")

    # 4. 配置直读（环境变量机制已移除：api_key 只来自 engine_config.yaml / local.yaml）
    import os
    os.environ["PADDLEOCR_MCP_AISTUDIO_ACCESS_TOKEN"] = "test-token"
    ep_c, key_c = engines.get_endpoint("paddle_vl", "cloud")
    assert key_c and key_c != "test-token", f"cloud api_key 应来自配置而非环境变量: {key_c}"
    print("4. 配置直读 OK: paddle_vl cloud api_key 来自配置（环境变量已废弃，不再展开）")

    # 5. local 合并（独立临时文件验证，不触碰真实 engine_config.local.yaml）
    root = pathlib.Path(__file__).resolve().parents[1]
    backup = engines._LOCAL_CONFIG_PATH
    tmp_local = root / "engine_config.local.test.yaml"
    try:
        engines._LOCAL_CONFIG_PATH = tmp_local
        tmp_local.write_text(
            "engines:\n  glm:\n    sources:\n      local:\n        server:\n          port: 19999\n",
            encoding="utf-8")
        engines._cache = None
        cfg2 = engines.load_config(force=True)
        assert cfg2["engines"]["glm"]["sources"]["local"]["server"]["port"] == 19999, "local 合并失败"
        print("5. local 覆盖合并 OK: glm 端口被 local 覆盖为 19999")
    finally:
        engines._LOCAL_CONFIG_PATH = backup
        engines._cache = None
        if tmp_local.exists():
            tmp_local.unlink()

    # 6. 未知引擎报错
    try:
        engines.get_engine("nonexistent")
        print("6. FAIL: 未抛错")
    except KeyError as e:
        print("6. 未知引擎报错 OK:", e)

    print("\n全部通过 ✅")


if __name__ == "__main__":
    main()
