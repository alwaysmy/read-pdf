"""Real PDF/PNG export and command-line failure-mode regression tests."""
import contextlib
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

import fitz
from PIL import Image

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import extract_pdf as ep


class ImageOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=pathlib.Path(self.temp.name)
        self.pdf=self.root/'diagram.pdf'
        self.document=fitz.open()
        page=self.document.new_page(width=300,height=400)
        page.insert_text((30,30),'Native technical diagram 3.300 V')
        image=Image.new('RGB',(80,40),'#1685b8');stream=io.BytesIO();image.save(stream,format='PNG')
        page.insert_image(fitz.Rect(30,70,110,110),stream=stream.getvalue())
        # A vector-only drawing must survive in the full source-page render.
        page.draw_rect(fitz.Rect(30,150,160,230),color=(1,0,0))
        self.document.save(self.pdf)
        self.addCleanup(self.document.close)

    def run_cli(self,*args):
        return subprocess.run([sys.executable,str(ROOT/'scripts/extract_pdf.py'),str(self.pdf),
                               '--json','--no-pdfmux','--no-table','--output-dir',str(self.root),*args],
                              capture_output=True,text=True,timeout=30)

    def test_native_markdown_links_resolve_to_real_pngs(self):
        result=self.run_cli();self.assertEqual(result.returncode,0,result.stderr)
        data=json.loads(result.stdout[result.stdout.find('\n{')+1:])
        self.assertEqual(data['status'],'ok')
        self.assertEqual([item['type'] for item in data['images']],['source_page','embedded_image'])
        markdown=pathlib.Path(data['file']).read_text()
        for asset in data['images']:
            self.assertIn(asset['relative_path'],markdown)
            with Image.open(asset['path']) as image:
                image.verify()
        self.assertEqual(data['images'][1]['coordinate_space'],'rotated_pdf_points')

    def test_rotated_embedded_image_crop(self):
        page=self.document[0];page.set_rotation(90)
        assets=ep.export_page_images(page,self.root,'a'*64,dpi=72)
        crop=next(asset for asset in assets if asset['type']=='embedded_image')
        with Image.open(crop['path']) as image:
            self.assertEqual(image.size,(40,80))
            self.assertEqual(image.getpixel((20,40)),(22,133,184))

    def test_no_images_opt_out(self):
        result=self.run_cli('--no-images');self.assertEqual(result.returncode,0,result.stderr)
        data=json.loads(result.stdout[result.stdout.find('\n{')+1:])
        self.assertEqual(data['images'],[])
        self.assertNotIn('Source page',pathlib.Path(data['file']).read_text())

    def test_invalid_dpi_is_bounded(self):
        result=self.run_cli('--dpi','2000')
        self.assertEqual(result.returncode,1)
        self.assertIn('between 50 and 600',result.stdout)
        self.assertNotIn('Traceback',result.stderr)

    def test_corrupt_pdf_reports_actionable_error(self):
        self.pdf.write_bytes(b'not a PDF')
        result=self.run_cli()
        self.assertEqual(result.returncode,1)
        self.assertIn('cannot open PDF',result.stdout)
        self.assertNotIn('Traceback',result.stderr)

    def test_encrypted_pdf_reports_actionable_error(self):
        secured=self.root/'secured.pdf'
        self.document.save(secured,encryption=fitz.PDF_ENCRYPT_AES_256,
                           owner_pw='synthetic-owner',user_pw='synthetic-user')
        self.pdf=secured
        result=self.run_cli()
        self.assertEqual(result.returncode,1)
        self.assertIn('password-protected',result.stdout)
        self.assertNotIn('Traceback',result.stderr)

    def test_image_options_change_package_identity(self):
        first=self.run_cli()
        first=json.loads(first.stdout[first.stdout.find('\n{')+1:])
        second=self.run_cli('--no-images')
        second=json.loads(second.stdout[second.stdout.find('\n{')+1:])
        third=self.run_cli('--dpi','96')
        third=json.loads(third.stdout[third.stdout.find('\n{')+1:])
        self.assertEqual(len({first['package_path'],second['package_path'],third['package_path']}),3)

    def test_audit_batch_retains_image_failure_flag(self):
        from unittest.mock import patch
        self.document.new_page(width=300,height=400)
        pdf=self.root/'two.pdf';self.document.save(pdf)
        argv=['extract_pdf.py',str(pdf),'--audit','--batch','--json','--output-dir',str(self.root)]
        stream=io.StringIO()
        with patch.object(sys,'argv',argv),contextlib.redirect_stdout(stream), \
             patch.object(ep,'export_page_images',side_effect=OSError('synthetic image write failure')), \
             patch.object(ep,'ensure_server'),patch.object(ep,'extract_qwen_multi',return_value=('Batch text',{})):
            ep.main()
        raw=stream.getvalue();result=json.loads(raw[raw.find('\n{')+1:])
        self.assertIn('image_export_failed',result['quality_flags'])
        self.assertIn('audit_batch_unaligned',result['quality_flags'])

    def test_missing_layout_is_quality_warning(self):
        flags,status=ep._page_quality('available text',{'layout':{'status':'unavailable','error':'missing model'}},
                                      {'blank':False},'hybrid')
        self.assertIn('layout_unavailable',flags)
        self.assertEqual(status,'needs_review')


if __name__=='__main__':unittest.main()
