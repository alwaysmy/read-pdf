# -*- coding: utf-8 -*-
"""探测候选大书页数（2026-09-30，为千页级样本选型）"""
import fitz

CANDIDATES = [
    r"C:\Users\AlwaysTS\Desktop\技术资料\FPGA与数字电路\course_s1_ZYNQ那些事儿-FPGA实验篇V1.01.pdf",
    r"C:\Users\AlwaysTS\Desktop\技术资料\模拟电路\运算放大器参数解析与LTspice应用仿真.pdf",
    r"Y:\qbitDownload\书籍\Library\Z3 辞典\Z32 中国辞典\辞海\新版辞海\辞海(第六版缩印本)\辞海(第六版缩印本).pdf",
    r"Y:\qbitDownload\书籍\Library\H3 常用外国语\英语\英语词典\牛津高阶英汉双解词典第8版.pdf",
    r"D:\MyProjects\2_MyDesigns\1夹具冶具延长线转接板测试架\IT6100_USB_TTL_DB9\IT6122调研文档和通信接口\IT6122_Conn\5_docs\ITECH_Catalog_EN.pdf",
]
for p in CANDIDATES:
    try:
        d = fitz.open(p)
        # 前 5 页文本量判断文本层
        chars = sum(len(d[i].get_text().strip()) for i in range(min(5, len(d))))
        # 旋转页检测（前 50 页）
        rots = sum(1 for i in range(min(50, len(d))) if d[i].rotation % 360 != 0)
        print(f"{len(d):>5}p  text5p={chars:>6}  rot50p={rots}  {p}")
        d.close()
    except Exception as e:
        print(f"ERR {type(e).__name__}: {e}  {p}")
