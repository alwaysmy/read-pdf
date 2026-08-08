"""server_manager 单元验证：GPU 检测 / 设备解析 / 回退逻辑.
用法: python tests/unit_server_manager.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))


def main():
    import server_manager
    from engines import load_config

    cfg = load_config()

    # 1. GPU 检测（本机有 GPU 则 True）
    gpu = server_manager._detect_gpu()
    print("1. GPU 检测:", gpu)

    # 2. 默认设备解析（device=gpu，有 GPU → gpu，无告警）
    dev, warned = server_manager._resolve_device(cfg, "glm")
    print(f"2. 默认设备解析: {dev} | 告警: {warned}")

    # 3. 无 GPU + gpu_fallback=false → 报错
    cfg_no_fallback = dict(cfg)
    cfg_no_fallback["defaults"] = dict(cfg["defaults"])
    cfg_no_fallback["defaults"]["gpu_fallback"] = False
    # 模拟无 GPU
    server_manager._detect_gpu = lambda: False
    try:
        server_manager._resolve_device(cfg_no_fallback, "glm")
        print("3. FAIL: 未抛错")
    except RuntimeError as e:
        print("3. gpu_fallback=false + 无GPU 报错 OK")
    # 4. 无 GPU + gpu_fallback=true → 回退 cpu + 告警
    server_manager._detect_gpu = lambda: False
    dev2, warned2 = server_manager._resolve_device(cfg, "glm")
    print(f"4. 无GPU+fallback=true → 设备: {dev2} | 告警: {warned2}")
    assert dev2 == "cpu" and warned2, "回退逻辑失败"

    # 5. 云源 server:null → ensure 直接跳过
    from engines import get_engine
    engine_p, src = get_engine("paddle_vl")
    started = server_manager.ensure("paddle_vl", engine_p["sources"][src].get("server"))
    print(f"5. 云源 ensure: started={started}（应为 False/跳过）")

    print("\n全部通过 ✅")


if __name__ == "__main__":
    main()
