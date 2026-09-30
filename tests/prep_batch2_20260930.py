# -*- coding: utf-8 -*-
"""第二批穷尽测试：探测千页大书 + 造特殊样本（旋转/加密/双语，2026-09-30）"""
import sys
from pathlib import Path

import fitz

OUT = Path(r"D:\MyProjects\AI\ChatSpace\TEST_RESULTS\read-pdf-bench_20260930")
OUT.mkdir(parents=True, exist_ok=True)

# ---- 1) 千页级候选探测 ----
BIG = [
    r"E:\手册与技术支持\设备资料与文档\A320操作手册\A320 FCOM 中文版__2012.09.13.pdf",
    r"E:\手册与技术支持\002.Datasheet\ADS2011射频电路设计与仿真实例 [徐兴福著][电子工业出版社][2014.05][523页].pdf",
    r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Documents\DaVinci Resolve.pdf",
]
for p in BIG:
    try:
        d = fitz.open(p)
        chars = sum(len(d[i].get_text().strip()) for i in range(min(3, len(d))))
        print(f"BIG: {len(d):>5}p text3p={chars:>6}  {Path(p).name}")
        d.close()
    except Exception as e:
        print(f"BIG ERR: {type(e).__name__}: {e}  {Path(p).name}")

# ---- 2) 造旋转页样本（源：SCPI 手册前 6 页，交替旋转） ----
SRC_SCPI = r"D:\MyProjects\EmoeR_D\研发中项目\EmoeCalibrator\Calibrator_Agent_Dev\客户操作手册\EmoeCalibrator_SCPI操作手册.pdf"
src = fitz.open(SRC_SCPI)
new = fitz.open()
new.insert_pdf(src, from_page=0, to_page=5)
src.close()
for i, deg in enumerate([90, 180, 270, 0, 90, 180]):
    new[i].set_rotation(deg)
rot_out = OUT / "synth_rotate_20260930.pdf"
new.save(rot_out)
new.close()
print(f"ROTATE: {rot_out.name} (6p: rot 90/180/270/0/90/180)")

# ---- 3) 造加密样本 ----
# 3a) owner-only（打开免密）
plain = fitz.open(SRC_SCPI)
enc_o = OUT / "synth_enc_owner_20260930.pdf"
plain.save(enc_o, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner-secret")
plain.close()
# 3b) user 密码（打开需密）
plain = fitz.open(SRC_SCPI)
enc_u = OUT / "synth_enc_user_20260930.pdf"
plain.save(enc_u, encryption=fitz.PDF_ENCRYPT_AES_256,
           owner_pw="owner-secret", user_pw="user-secret")
plain.close()
print(f"ENC: {enc_o.name} (owner-only), {enc_u.name} (user-pw)")

# ---- 4) 造双语混排（SCPI 中文 3 页 + arXiv 英文 3 页交替） ----
arxiv = OUT / "arxiv_1706.03762.pdf"
if arxiv.exists():
    bi = OUT / "synth_bilingual_20260930.pdf"
    out = fitz.open()
    c = fitz.open(SRC_SCPI)
    e = fitz.open(arxiv)
    out.insert_pdf(c, from_page=0, to_page=2)   # 中文 p1-3
    out.insert_pdf(e, from_page=0, to_page=2)   # 英文 p4-6
    out.insert_pdf(c, from_page=3, to_page=5)   # 中文 p7-9
    out.insert_pdf(e, from_page=3, to_page=5)   # 英文 p10-12
    out.save(bi)
    out.close()
    c.close()
    e.close()
    print(f"BILINGUAL: {bi.name} (12p: 中英交替)")
else:
    print("BILINGUAL: arxiv missing")
