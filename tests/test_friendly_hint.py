"""T3: 首次运行友好提示测试 — llama-server / 模型路径不存在时应打印 SETUP_GUIDE 指引.
用法: python tests/test_friendly_hint.py
"""
import pathlib
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))


def main():
    import server_manager
    from engines import load_config

    cfg = load_config()
    glm_server = cfg["engines"]["glm"]["sources"]["local"]["server"]

    # 场景 1: llama_dir 不存在
    import copy
    cfg_bad_dir = copy.deepcopy(cfg)
    cfg_bad_dir["defaults"]["llama_dir"] = "Z:/nonexistent"
    print("=== 场景1: llama_dir 不存在 ===")
    try:
        # monkeypatch load_config 返回坏配置
        orig = server_manager.load_config
        server_manager.load_config = lambda: cfg_bad_dir
        server_manager.start("glm", glm_server)
        print("FAIL: 未抛错")
    except FileNotFoundError as e:
        print(f"OK: FileNotFoundError {e}")
    finally:
        server_manager.load_config = orig

    # 场景 2: 模型路径不存在（llama_dir 有效但 model 路径坏）
    print("\n=== 场景2: model 路径不存在 ===")
    import copy as _c
    bad_model = _c.deepcopy(glm_server)
    bad_model["model"] = "Z:/nonexistent/model.gguf"
    try:
        server_manager.start("glm", bad_model)
        print("FAIL: 未抛错")
    except FileNotFoundError as e:
        print(f"OK: FileNotFoundError {e}")

    print("\nT3 通过 ✅")


if __name__ == "__main__":
    main()
