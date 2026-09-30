# -*- coding: utf-8 -*-
"""pdf-inspector 文本页 suspected_garbled_text 判定核验（2026-09-29）
对照 fitz 原文的乱码特征（PUA 私用区字符 / U+FFFD / cmap_gaps），判断该路由是真判还是误报。
"""
import re
import pdf_inspector
import fitz

TEXT_PDF = r"D:\MyProjects\6_Works\hd1\器件手册\连接器选型和定义\5 高速数据传输系列连接器选型手册.pdf"

t = pdf_inspector.process_pdf(TEXT_PDF, pages=list(range(6)))
print("cmap_gaps:", t.cmap_gaps, "| has_encoding_issues:", t.has_encoding_issues)
print("routes:", [(p.page, p.reasons) for p in t.ocr_reasons_by_page])

d = fitz.open(TEXT_PDF)
pua_re = re.compile("[\ue000-\uf8ff]")
for i in range(6):
    txt = d[i].get_text()
    pua = len(pua_re.findall(txt))
    repl = txt.count("\ufffd")
    head = txt[:70].replace("\n", " ")
    print(f"p{i+1}: chars={len(txt)} pua={pua} repl={repl} head={head!r}")
d.close()
