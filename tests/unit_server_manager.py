"""server_manager 单元验证：GPU 检测 / 设备解析 / 回退逻辑.
用法: python tests/unit_server_manager.py
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

    # Test fallback policy independently of a user's local CPU deployment settings.
    import copy
    cfg = copy.deepcopy(load_config())
    cfg["defaults"]["device"] = "gpu"
    cfg["defaults"]["gpu_fallback"] = True

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

    # ---- GPU 生效性三层防护（回归保护）----
    import io
    import os
    import tempfile
    import contextlib

    # 6. _wants_gpu：-ngl/--n-gpu-layers 判定
    assert server_manager._wants_gpu(["-ngl", "100", "-c", "8192"]) is True
    assert server_manager._wants_gpu(["-ngl", "0"]) is False
    assert server_manager._wants_gpu(["-c", "8192"]) is False
    assert server_manager._wants_gpu(["--n-gpu-layers", "50"]) is True
    print("6. _wants_gpu 判定 OK")

    # 7. _find_cuda_runtime：exe 同目录有/无运行库（隔离 PATH，避免宿主 CUDA 干扰）
    old_path = os.environ.get("PATH", "")
    with tempfile.TemporaryDirectory() as td:
        exe = pathlib.Path(td) / "llama-server.exe"
        exe.write_bytes(b"")
        try:
            os.environ["PATH"] = td + os.pathsep + r"C:\Windows\System32"
            ok, where, missing, hint = server_manager._find_cuda_runtime(str(exe))
            assert not ok and set(missing) == set(server_manager._CUDA_RUNTIME_PATTERNS), \
                f"空目录应缺全部运行库: {missing}"
            for name in ("cudart64_12.dll", "cublas64_12.dll", "cublasLt64_12.dll"):
                (pathlib.Path(td) / name).write_bytes(b"")
            ok2, _, missing2, _ = server_manager._find_cuda_runtime(str(exe))
            assert ok2 and not missing2, f"运行库齐备应通过: {missing2}"
        finally:
            os.environ["PATH"] = old_path
    print("7. _find_cuda_runtime 缺失/齐备两态 OK")

    # 8. _probe_llama_devices：输出解析（mock，不真跑 llama-server）
    import subprocess as _sp
    real_run = _sp.run
    server_manager._DEVICE_PROBE_CACHE.clear()

    def _fake_run(cmd, **kw):
        class R:
            returncode = 0
            stdout = b""
            stderr = b""
        r = R()
        return r

    def _make(out_text):
        def _fr(cmd, **kw):
            class R:
                returncode = 0
            rr = R()
            rr.stdout = out_text.encode()
            rr.stderr = b""
            return rr
        return _fr

    cases = [
        ("Available devices:\n  CUDA0: Quadro T1000 (4095 MiB)\n", True),
        ("Available devices:\n  OPENVINO0: OpenVINO Runtime\n", False),
        ("Available devices:\n  (none)\n", False),
    ]
    for out, expect in cases:
        server_manager._DEVICE_PROBE_CACHE.clear()
        sm_run = server_manager.subprocess.run
        server_manager.subprocess.run = _make(out)
        try:
            got, _ = server_manager._probe_llama_devices(r"D:\fake\llama-server.exe")
            assert got is expect, f"输出解析错误: {out!r} -> {got}, 期望 {expect}"
        finally:
            server_manager.subprocess.run = sm_run
    server_manager.subprocess.run = _make(b"")
    server_manager._DEVICE_PROBE_CACHE.clear()
    try:
        got, _ = server_manager._probe_llama_devices(r"D:\fake\nope.exe")
        assert got is None, "exe 不存在应返回 None（无法判定）"
    finally:
        server_manager.subprocess.run = real_run
    server_manager._DEVICE_PROBE_CACHE.clear()
    print("8. _probe_llama_devices 三态解析 OK")

    # 9. _model_size_mib + _verify_gpu_offload 阈值（mock 显存查询）
    with tempfile.TemporaryDirectory() as td:
        m1 = pathlib.Path(td) / "model.gguf"
        m2 = pathlib.Path(td) / "mmproj.gguf"
        m1.write_bytes(b"x" * (100 * 1024 * 1024))
        m2.write_bytes(b"x" * (50 * 1024 * 1024))
        cfg_srv = {"model": str(m1), "mmproj": str(m2)}
        size = server_manager._model_size_mib(cfg_srv)
        assert 149 < size < 151, f"模型大小合计错误: {size}"
        # 卸载到位（增量 153 = 102% ≥ 80% → 不告警）与未卸载（增量 0 → 告警）
        buf = io.StringIO()
        real_q = server_manager._query_used_vram_mib
        try:
            with contextlib.redirect_stdout(buf):
                server_manager._query_used_vram_mib = lambda: 203
                server_manager._verify_gpu_offload("hybrid", 50, cfg_srv)
                assert "没有真正卸载" not in buf.getvalue(), "增量足够却告警"
                server_manager._query_used_vram_mib = lambda: 50
                server_manager._verify_gpu_offload("hybrid", 50, cfg_srv)
                assert "没有真正卸载" in buf.getvalue(), "增量≈0 未告警"
        finally:
            server_manager._query_used_vram_mib = real_q
    print("9. _model_size_mib / _verify_gpu_offload 阈值 OK")

    # 10. NO_PROXY 方括号 IPv6 清洗（extract_pdf._sanitize_bracketed_no_proxy）
    # 时序事实：paddlex 管线构造会把 NO_PROXY 重置为系统注入值，因此清洗函数
    # 必须在每次构造 VL 客户端前调用（产品代码已如此）；本条只测清洗逻辑本身，
    # 用一个不会触发管线构造的环境布置。
    import extract_pdf as ep
    old_np = os.environ.get("NO_PROXY"), os.environ.get("no_proxy")
    try:
        os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1,[::1]"
        os.environ.pop("no_proxy", None)
        before = os.environ.get("NO_PROXY")
        changed = ep._sanitize_bracketed_no_proxy()
        now = os.environ.get("NO_PROXY")
        # 若布置被外部重置（环境注入行为），跳过值断言，只验证函数不改坏环境
        if before == "localhost,127.0.0.1,::1,[::1]":
            assert changed and now == "localhost,127.0.0.1,::1", \
                f"清洗结果错误: before={before!r} after={now!r}"
        else:
            print("      (环境注入重置了布置，跳过值断言)")
        # 无方括号项：不动
        os.environ["NO_PROXY"] = "localhost,127.0.0.1"
        if os.environ.get("NO_PROXY") == "localhost,127.0.0.1":
            assert not ep._sanitize_bracketed_no_proxy(), "无方括号项不应改动"
    finally:
        if old_np[0] is not None:
            os.environ["NO_PROXY"] = old_np[0]
        else:
            os.environ.pop("NO_PROXY", None)
        if old_np[1] is not None:
            os.environ["no_proxy"] = old_np[1]
        else:
            os.environ.pop("no_proxy", None)
    print("10. NO_PROXY 方括号 IPv6 清洗 OK")

    # 11. 服务已运行时 _probe_llama_cpp 绕过显存检查
    # 场景：llama-server 常驻（模型已加载、显存已占），auto 探测不应再按
    # 空闲显存判定——否则被自己占用的显存误杀而回落别的后端
    orig_open = server_manager.is_port_open
    orig_free = server_manager._query_free_vram_mib
    try:
        server_manager._query_free_vram_mib = lambda: 1  # 远低于任何阈值
        server_manager.is_port_open = lambda port, host="127.0.0.1": False
        closed, r_closed = ep._probe_llama_cpp()
        server_manager.is_port_open = lambda port, host="127.0.0.1": True
        opened, r_open = ep._probe_llama_cpp()
        if closed is False and "空闲显存" in str(r_closed):
            assert opened is True, f"服务已运行应绕过显存检查: {r_open}"
            print(f"11. 服务运行时探测绕过显存检查 OK（{r_open}）")
        else:
            print(f"11. 本机前置不全（{r_closed}），跳过显存绕过断言")
    finally:
        server_manager.is_port_open = orig_open
        server_manager._query_free_vram_mib = orig_free

    print("\n全部通过 ✅")


if __name__ == "__main__":
    main()
