"""Server lifecycle — GLM-OCR Q8_0 + PaddleOCR-VL GGUF.

Usage:
    python manage_servers.py start glm     # start GLM-OCR
    python manage_servers.py start llama   # start PaddleOCR-VL
    python manage_servers.py start all     # start both
    python manage_servers.py stop          # stop all
    python manage_servers.py status        # check ports
"""
import sys, os, subprocess, atexit, time, socket, requests
sys.path.insert(0, os.path.dirname(__file__))
# NOTE: importing SERVERS from extract_pdf also registers atexit handler,
# but _started_servers will be empty so stop_all_servers() is a no-op.
from extract_pdf import SERVERS


def is_port_open(port, host="127.0.0.1"):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False


_procs = {}

def start_server(name):
    cfg = SERVERS[name]
    if is_port_open(cfg["port"]):
        print(f"{name} already running on :{cfg['port']}")
        return
    # VRAM check
    try:
        out = subprocess.check_output(
            "nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits",
            shell=True, text=True
        )
        free_mb = int(out.strip())
        if free_mb < 3072:
            print(f"WARNING: only {free_mb} MiB VRAM free (need >3GB)")
    except Exception:
        pass
    print(f"starting {name} on :{cfg['port']}...")
    proc_env = os.environ.copy()
    if cfg.get("env"):
        proc_env.update(cfg["env"])
    _procs[name] = subprocess.Popen(
        cfg["args"],
        env=proc_env,
        creationflags=subprocess.CREATE_NEW_CONSOLE
    )
    for _ in range(60):
        if is_port_open(cfg["port"]):
            import requests
            try:
                r = requests.get(f"http://127.0.0.1:{cfg['port']}/health", timeout=2)
                if r.status_code == 200:
                    print(f"{name} ready (PID {_procs[name].pid})")
                    return
            except Exception:
                pass
        time.sleep(2)
    print(f"WARNING: {name} health check timeout")

def stop_all():
    for name, proc in list(_procs.items()):
        pid = proc.pid
        subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
        print(f"{name} (PID {pid}) stopped")
        del _procs[name]

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    target = sys.argv[2] if len(sys.argv) > 2 else None

    if cmd == "start":
        if target == "all":
            for name in SERVERS:
                start_server(name)
        elif target in SERVERS:
            start_server(target)
        else:
            print(f"Unknown: {target}. Choose: glm, llama, qwen, all")
    elif cmd == "stop":
        stop_all()
    elif cmd == "status":
        for name, cfg in SERVERS.items():
            status = "RUNNING" if is_port_open(cfg["port"]) else "STOPPED"
            print(f"  {name:10s} :{cfg['port']:<5d}  {status}")
