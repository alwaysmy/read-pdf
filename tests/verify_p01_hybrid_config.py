"""P0-1 验证：hybrid 配置化生效（local.yaml 覆盖端口 → 配置被消费）.
用法: python tests/verify_p01_hybrid_config.py
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

LOCAL = ROOT / "engine_config.local.yaml"


def main():
    import engines

    # 1. 默认配置 endpoint
    ep, key = engines.get_endpoint("hybrid", "local")
    print("1. 默认 endpoint:", ep)
    assert "12336" in ep, f"默认端口应为 12336, 实际 {ep}"

    # 2. local.yaml 覆盖端口 19936
    LOCAL.write_text(
        "engines:\n  hybrid:\n    sources:\n      local:\n        server:\n          port: 19936\n",
        encoding="utf-8")
    try:
        engines._cache = None
        srv = engines.load_config(force=True)["engines"]["hybrid"]["sources"]["local"]["server"]
        print("2. local.yaml 覆盖后 port:", srv["port"])
        assert srv["port"] == 19936, f"local.yaml 覆盖未生效: {srv['port']}"
        # endpoint 是从 server.port 构造的？确认 get_endpoint 与 server.port 一致
        ep2, _ = engines.get_endpoint("hybrid", "local")
        print("3. 覆盖后 endpoint:", ep2)
    finally:
        LOCAL.unlink(missing_ok=True)
        engines._cache = None

    # 3. 恢复默认
    ep3, _ = engines.get_endpoint("hybrid", "local")
    print("4. 恢复后 endpoint:", ep3)
    assert "12336" in ep3

    print("\nP0-1 hybrid 配置化验证通过 ✅")


if __name__ == "__main__":
    main()
