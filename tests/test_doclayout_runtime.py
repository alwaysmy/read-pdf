"""Opt-in tests of the official layout ONNX and real OCR weights, no model mocks.

Set READPDF_LAYOUT_MODEL_DIR to the downloaded official model folder.
"""
import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'tests')]
MODEL_DIR=pathlib.Path(os.environ.get('READPDF_LAYOUT_MODEL_DIR','/nonexistent'))


@unittest.skipUnless((MODEL_DIR/'inference.onnx').is_file(),'official optional layout model not configured')
class RealLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.directory=pathlib.Path(cls.tmp.name)
        cls.env=patch.dict(os.environ,{'HOME':cls.tmp.name,'LOCALAPPDATA':cls.tmp.name})
        cls.env.start()
        from openvino_telemetry.utils.opt_in_checker import OptInChecker,ConsentCheckResult
        assert OptInChecker().update_result(ConsentCheckResult.DECLINED)
        from generate_pipeline_fixtures import generate
        generate(cls.directory)
        from doclayout_openvino import create_model
        cls.model=create_model(MODEL_DIR)
        cls.image=cls.directory/'born_page1.png'
        cls.boxes=next(cls.model.predict(cls.image))['boxes']
        import extract_pdf as ep
        with patch.object(ep,'_ov_dir',return_value=str(ROOT/'models')),patch.object(ep,'_ov_tier',return_value='small'):
            cls.ocr=ep._ov_load_openvino()
        cls.lines,_=ep._ov_lines_openvino(cls.ocr,cls.image)

    @classmethod
    def tearDownClass(cls):
        cls.env.stop();cls.tmp.cleanup()

    def test_missing_model_fails_without_download(self):
        from doclayout_openvino import create_model
        with self.assertRaisesRegex(FileNotFoundError,'layout_ov_dir'):
            create_model(self.directory/'missing-model')

    def test_explicit_gpu_is_not_silently_run_on_cpu(self):
        from doclayout_openvino import create_model
        with self.assertRaisesRegex(ValueError,'CPU only'):
            create_model(MODEL_DIR,device='gpu')

    def test_detects_table_and_image(self):
        labels=[box['label'] for box in self.boxes]
        self.assertEqual(labels.count('table'),1)
        self.assertIn('image',labels)

    def test_boxes_and_order_are_grounded(self):
        from PIL import Image
        with Image.open(self.image) as image:width,height=image.size
        order=[]
        for box in self.boxes:
            x0,y0,x1,y1=box['coordinate']
            self.assertTrue(0<=x0<x1<=width and 0<=y0<y1<=height)
            order.append(box['reading_order'])
        self.assertEqual(order,sorted(order))
        table=next(box for box in self.boxes if box['label']=='table')
        self.assertGreater(table['coordinate'][1],300)
        self.assertLess(table['coordinate'][3],800)

    def test_real_scan_cells_match_truth(self):
        import cv2,json,extract_pdf as ep
        from ruled_tables import reconstruct_table
        box=next(box for box in self.boxes if box['label']=='table')
        lines=[line for line in self.lines if ep._overlap_ratio(line['bbox'],box['coordinate'])>.5]
        table=reconstruct_table(cv2.imread(str(self.image)),box['coordinate'],lines)
        truth=json.loads((self.directory/'ground_truth.json').read_text())
        self.assertEqual(table['matrix'],truth['table_rows'])
        self.assertEqual(table['quality_flags'],[])

    def test_combined_assembly_retains_structure(self):
        import extract_pdf as ep
        boxes=[{'label':box['label'],'score':box['score'],'bbox':box['coordinate'],
                'reading_order':box['reading_order']} for box in self.boxes]
        text,stats=ep._merge_lines_with_layout(self.lines,boxes,self.image)
        self.assertIn('<table>',text)
        self.assertEqual(text.count('<td>Repeated</td>'),2)
        self.assertIn('CALIBRATION_OK_314159',text)
        self.assertTrue(stats['layout_blocks'])
        self.assertEqual(stats['layout']['status'],'ok')


if __name__=='__main__':unittest.main()
