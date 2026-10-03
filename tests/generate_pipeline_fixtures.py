"""Original deterministic technical PDF corpus for real end-to-end smoke tests."""
import argparse
import io
import json
import pathlib

import fitz
from PIL import Image, ImageDraw
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader


def generate(directory):
    directory = pathlib.Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    born = directory / 'born_digital.pdf'
    plot = Image.new('RGB', (900, 240), 'white')
    draw = ImageDraw.Draw(plot)
    draw.line((60, 180, 860, 180), fill='black', width=3)
    draw.line((60, 30, 60, 210), fill='black', width=3)
    draw.line([(60,160),(180,160),(180,75),(350,75),(350,130),(550,130),(550,45),(850,45)], fill='#12628d', width=5)
    plot.save(directory / 'waveform.png')
    c = canvas.Canvas(str(born), pagesize=(595,842), invariant=1)
    c.setTitle('read-pdf original end-to-end fixture')
    c.setFont('Helvetica-Bold',18); c.drawString(42,797,'ADC FRONT-END TEST NOTE')
    c.setFont('Helvetica',11)
    for y, line in zip((771,753,735), (
        'Fixture ID: RPDF-CPU-2026. Revision 1. Original synthetic test.',
        'Input range: -2.5 V to +2.5 V. Sample rate: 1000 samples/s.',
        'Equation: Vout = Gain * Vin + Offset. Gain = 2.0.')):
        c.drawString(42,y,line)
    c.setFont('STSong-Light',12);c.drawString(42,711,'中文检查：输入电压与噪声测试，保留单位和重复数据。')
    c.setFont('Helvetica-Bold',12); c.drawString(42,678,'Electrical characteristics (25 C)')
    rows=[['Parameter','Min','Typ','Max','Unit'],['Input offset','-0.5','0','0.5','mV'],['Noise RMS','','12.5','15','uV'],['Gain','1.99','2.00','2.01','V/V'],['Repeated','0','1','2','mV'],['Repeated','0','1','2','mV']]
    xs=[42,222,294,366,438,550]; top=659; height=28
    for x in xs:c.line(x,top,x,top-height*len(rows))
    for i in range(len(rows)+1):c.line(xs[0],top-i*height,xs[-1],top-i*height)
    for i,row in enumerate(rows):
        c.setFont('Helvetica-Bold' if i==0 else 'Helvetica',10)
        for j,value in enumerate(row):c.drawString(xs[j]+7,top-i*height-18,value)
    c.setFont('Helvetica-Bold',12);c.drawString(42,464,'Figure 1. Settling waveform (embedded raster figure)')
    c.drawImage(ImageReader(plot),42,300,width=508,height=136)
    c.setFont('Helvetica',10);c.drawString(42,279,'x: time (ms). y: amplitude (mV). Values are test fixtures.')
    c.drawString(42,251,'REFERENCE TOKEN: CALIBRATION_OK_314159')
    c.drawString(42,232,'Formula note: 0.5 * 20 = 10.0; sign and decimal must remain.')
    c.setFont('Helvetica',9);c.drawString(42,28,'Physical page 1 | synthetic, no proprietary data')
    c.showPage()
    c.setFont('Helvetica-Bold',18);c.drawString(42,797,'PAGE TWO: CHECKLIST')
    c.setFont('Helvetica',12)
    for i,line in enumerate(['Native text should not need OCR.', 'Required value: 3.300 V; tolerance: +/- 0.010 V.',
                              'Footnote: repeated rows are intentional observations.', 'SECOND_PAGE_TOKEN_271828']):
        c.drawString(42,756-i*26,line)
    c.setFont('Helvetica',9);c.drawString(42,28,'Physical page 2 | synthetic, no proprietary data')
    c.save()
    with fitz.open(born) as source:
        preview=source[0].get_pixmap(dpi=150)
        preview.save(directory/'born_page1.png')
        scan=fitz.open(); scan.new_page(width=595,height=842).insert_image(fitz.Rect(0,0,595,842),stream=preview.tobytes('png'))
        scan.save(directory/'scanned.pdf');scan.close()
        low=source[0].get_pixmap(dpi=96)
        low.save(directory/'scan_96dpi.png')
        scan=fitz.open();scan.new_page(width=595,height=842).insert_image(fitz.Rect(0,0,595,842),stream=low.tobytes('png'))
        scan.save(directory/'scanned_96dpi.pdf');scan.close()
        mixed=fitz.open()
        for _ in range(3):mixed.insert_pdf(source,from_page=1,to_page=1)
        mixed.new_page(width=595,height=842).insert_image(fitz.Rect(0,0,595,842),stream=preview.tobytes('png'))
        mixed.save(directory/'mixed.pdf');mixed.close()
    expected={'required_anchors':['ADC FRONT-END TEST NOTE','Input range','2.5','1000','Vout','12.5','Repeated','CALIBRATION_OK_314159'],
              'chinese_anchor':'输入电压与噪声测试','table_rows':rows,'numeric_anchors':['-2.5','+2.5','-0.5','12.5','1.99','2.00','2.01'],
              'files':{}}
    for pdf in sorted(directory.glob('*.pdf')):
        with fitz.open(pdf) as doc:
            expected['files'][pdf.name]=[{'page':i+1,'native_chars':len(p.get_text().strip()),'image_count':len(p.get_images())} for i,p in enumerate(doc)]
    (directory/'ground_truth.json').write_text(json.dumps(expected,ensure_ascii=False,indent=2),encoding='utf-8')
    return directory


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('directory');args=ap.parse_args();print(generate(args.directory))
