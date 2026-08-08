"""验证 hybrid -c 8192 配置：启动 + 就绪 + 停止."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))


def main():
    import server_manager
    from engines import load_config

    cfg = load_config()
    srv = cfg["engines"]["hybrid"]["sources"]["local"]["server"]
    print("args:", srv["args"])
    assert "-c" in srv["args"] and srv["args"][srv["args"].index("-c") + 1] == "8192", "上下文应为 8192"

    p = server_manager.start("hybrid", srv)
    print("启动成功，就绪，pid:", p.pid)
    server_manager.stop("hybrid")
    print("已停止")
    print("\nhybrid -c 8192 验证通过 ✅")


if __name__ == "__main__":
    main()
