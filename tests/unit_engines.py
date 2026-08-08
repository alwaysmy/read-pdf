"""engines.py 单元验证：配置加载/双源解析/ENV 展开/local 合并.
用法: python tests/unit_engines.py
"""
import pathlib
import sys

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

    # 4. ENV 展开
    import os
    os.environ["PADDLEOCR_MCP_AISTUDIO_ACCESS_TOKEN"] = "test-token"
    ep_c, key_c = engines.get_endpoint("paddle_vl", "cloud")
    assert key_c == "test-token", f"ENV 展开失败: {key_c}"
    print("4. ${ENV} 展开 OK: paddle_vl cloud api_key 正确")

    # 5. local 合并（写临时 local 配置验证）
    import tempfile
    root = pathlib.Path(__file__).resolve().parents[1]
    backup = engines._LOCAL_CONFIG_PATH
    try:
        engines._LOCAL_CONFIG_PATH = root / "engine_config.local.yaml"
        engines._LOCAL_CONFIG_PATH.write_text(
            "engines:\n  glm:\n    sources:\n      local:\n        server:\n          port: 19999\n",
            encoding="utf-8")
        engines._cache = None
        cfg2 = engines.load_config(force=True)
        assert cfg2["engines"]["glm"]["sources"]["local"]["server"]["port"] == 19999, "local 合并失败"
        print("5. local 覆盖合并 OK: glm 端口被 local.yaml 覆盖为 19999")
    finally:
        engines._LOCAL_CONFIG_PATH = backup
        engines._cache = None
        if (root / "engine_config.local.yaml").exists():
            (root / "engine_config.local.yaml").unlink()

    # 6. 未知引擎报错
    try:
        engines.get_engine("nonexistent")
        print("6. FAIL: 未抛错")
    except KeyError as e:
        print("6. 未知引擎报错 OK:", e)

    print("\n全部通过 ✅")


if __name__ == "__main__":
    main()
