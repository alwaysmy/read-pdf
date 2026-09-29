"""Build a labeled contact sheet of the 6 compare screenshots.

Each source image gets a filename label burned into its top strip, so any
subsequent view of the sheet self-identifies which file each panel came from
(photo-identification defeats any read() replay/mismatch ambiguity).

Output: tests/contact_sheet_<timestamp>.jpg (timestamped to avoid overwrite)
"""
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SHOTS = Path(r"D:\MyProjects\AGENT方法库\skills\read-pdf\.openchamber\screenshots")
FILES = [
    "compare-page12-2026-09-29T09-37-18-070.jpg",
    "cmp-p13-2026-09-29T09-51-26-231.jpg",
    "cmp-p17-2026-09-29T09-54-27-229.jpg",
    "cmp-p20-2026-09-29T09-54-52-080.jpg",
    "cmp-p29-2026-09-29T09-57-53-452.jpg",
    "cmp-p34-2026-09-29T09-58-26-009.jpg",
]

PANEL_W = 900
LABEL_H = 56


def main():
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = Path(__file__).with_name(f"contact_sheet_{ts}.jpg")
    font = ImageFont.truetype("arialbd.ttf", 40)
    panels = []
    for name in FILES:
        img = Image.open(SHOTS / name).convert("RGB")
        ratio = PANEL_W / img.width
        img = img.resize((PANEL_W, int(img.height * ratio)))
        panel = Image.new("RGB", (PANEL_W, img.height + LABEL_H), "black")
        panel.paste(img, (0, LABEL_H))
        draw = ImageDraw.Draw(panel)
        short = name.split("-2026")[0]
        draw.text((10, 6), f"FILE: {short}", fill="yellow", font=font)
        panels.append(panel)

    total_h = sum(p.height for p in panels)
    sheet = Image.new("RGB", (PANEL_W, total_h), "black")
    y = 0
    for p in panels:
        sheet.paste(p, (0, y))
        y += p.height
    sheet.save(out_path, quality=88)
    print(f"written: {out_path}  size={sheet.size}")


if __name__ == "__main__":
    main()
