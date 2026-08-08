"""P1 云源异常保护验证：无 token / 坏配置时应返回友好 error 而非崩溃.
用法: python tests/verify_p1_cloud_errors.py
"""
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# 确保云 token 未设置（验证缺失时友好报错）
os.environ.pop("PADDLEOCR_MCP_AISTUDIO_ACCESS_TOKEN", None)


def main():
    import engines

    # 1. 云源无 token → call 应返回 error 而非崩溃
    os.environ.pop("PADDLEOCR_MCP_AISTUDIO_ACCESS_TOKEN", None)
    text, stats = engines.call("paddle_vl", "dummy.png", source="cloud")
    print("1. 云源无 token:", stats)
    assert "error" in stats and "环境变量" in stats["error"], f"应有环境变量错误, 实际 {stats}"

    # 2. 未知引擎 → 友好 KeyError 消息
    text, stats = engines.call("nonexistent", "dummy.png")
    print("2. 未知引擎:", stats)
    assert "error" in stats, f"应有错误, 实际 {stats}"

    # 3. 云源 URL 不可达（设假 token，请求失败应返回网络错误而非崩溃）
    os.environ["PADDLEOCR_MCP_AISTUDIO_ACCESS_TOKEN"] = "fake-token-for-test"
    text, stats = engines.call("paddle_vl", "dummy.png", source="cloud")
    print("3. 云源网络错误:", stats)
    assert "error" in stats, f"网络错误应被捕获, 实际 {stats}"

    print("\nP1 云源异常保护验证通过 ✅")


if __name__ == "__main__":
    main()
