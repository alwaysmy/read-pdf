"""核实 PaddleOCR-VL-1.6 GGUF 的训练上下文（n_ctx_train）.
直接读 GGUF 元数据，不加载模型。
"""
import struct
import pathlib

MODEL = pathlib.Path(r"D:\llm\PaddlePaddle\PaddleOCR-VL-1.6-GGUF\PaddleOCR-VL-1.6-GGUF.gguf")


def read_gguf_metadata(path):
    with open(path, "rb") as f:
        magic = f.read(4)
        if magic != b"GGUF":
            return None
        version = struct.unpack("<I", f.read(4))[0]
        n_tensors = struct.unpack("<Q", f.read(8))[0]
        n_kv = struct.unpack("<Q", f.read(8))[0]
        kv = {}
        for _ in range(n_kv):
            klen = struct.unpack("<Q", f.read(8))[0]
            key = f.read(klen).decode()
            vtype = struct.unpack("<I", f.read(4))[0]
            if vtype == 0:
                val = struct.unpack("<B", f.read(1))[0]
            elif vtype == 1:
                val = struct.unpack("<b", f.read(1))[0]
            elif vtype == 2:
                val = struct.unpack("<H", f.read(2))[0]
            elif vtype == 3:
                val = struct.unpack("<h", f.read(2))[0]
            elif vtype == 4:
                val = struct.unpack("<I", f.read(4))[0]
            elif vtype == 5:
                val = struct.unpack("<i", f.read(4))[0]
            elif vtype == 6:
                val = struct.unpack("<f", f.read(4))[0]
            elif vtype == 7:
                val = struct.unpack("?", f.read(1))[0]
            elif vtype == 8:
                slen = struct.unpack("<Q", f.read(8))[0]
                val = f.read(slen).decode()
            elif vtype == 10:
                val = struct.unpack("<Q", f.read(8))[0]
            else:
                break
            kv[key] = val
        return kv


def main():
    print(f"模型: {MODEL}  ({MODEL.stat().st_size / 1e9:.2f} GB)")
    kv = read_gguf_metadata(MODEL)
    if not kv:
        print("读取失败")
        return
    for k in sorted(kv.keys()):
        if any(s in k.lower() for s in ("context", "block_count", "name", "arch")):
            print(f"  {k} = {kv[k]}")


if __name__ == "__main__":
    main()
