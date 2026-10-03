"""Deterministic extraction regressions: generated PDFs, mocked OCR, no GPU/network."""
import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

import fitz
from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import extract_pdf as ep


def generate_pdf(path, *, mixed=False, text='Native evidence and exact units 0 mV. ', blank=False):
    doc = fitz.open()
    count = 4 if mixed else 1
    for i in range(count):
        page = doc.new_page(width=400, height=500)
        if blank:
            continue
        if mixed and i == 3:
            img = Image.new('RGB', (800, 1000), 'white')
            ImageDraw.Draw(img).text((60, 60), 'SCANNED PAGE FOUR 2.5 mV', fill='black')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            page.insert_image(page.rect, stream=buf.getvalue())
        else:
            page.insert_textbox(fitz.Rect(20, 20, 380, 480), text * 12, fontsize=10)
    doc.save(path)
    doc.close()


def run_cli(pdf, output, *extra, ocr=None):
    args = [str(ROOT / 'scripts/extract_pdf.py'), str(pdf), '--output-dir', str(output),
            '--no-pdfmux', '--no-table', '--json', *extra]
    stream = io.StringIO()
    with patch.object(sys, 'argv', args), contextlib.redirect_stdout(stream), \
         patch.object(ep, '_ensure_hybrid_server'), \
         patch.object(ep, '_pipeline_signature', return_value='test-pipeline'), \
         patch.object(ep, 'extract_hybrid', side_effect=ocr or (lambda *a, **k: ('Scanned evidence 2.5 mV. ' * 3, {}))), \
         patch.object(ep.time, 'sleep'):
        ep.main()
    out = stream.getvalue()
    return json.loads(out[out.index('{'):])


class TableTests(unittest.TestCase):
    def test_duplicate_rows_remain(self):
        result = ep.format_table_md([['Parameter', 'Value'], ['gain', '1'], ['gain', '1']])
        self.assertEqual(result.count('| gain | 1 |'), 2)

    def test_none_zero_ragged_and_escaped_cells(self):
        result = ep.format_table_md([[None, 'value'], ['x|y\nz', 0, 'extra'], ['last']])
        self.assertIn('x\\|y<br>z', result)
        self.assertIn('| 0 | extra |', result)
        self.assertIn('| last |  |  |', result)
        self.assertNotIn('None', result)


class GeneratedPDFTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)

    def test_selected_scan_after_first_three_text_pages(self):
        pdf = self.root / 'mixed.pdf'
        generate_pdf(pdf, mixed=True)
        result = run_cli(pdf, self.root, '--pages', '4')
        self.assertEqual(result['pages'][0]['engine'], 'hybrid')
        self.assertGreater(result['pages'][0]['chars'], 0)
        self.assertEqual(result['coverage']['requested_pages'], [4])
        self.assertEqual(result['coverage']['unprocessed_pages'], [1, 2, 3])

    def test_mixed_auto_only_ocrs_scan(self):
        pdf = self.root / 'mixed.pdf'
        generate_pdf(pdf, mixed=True)
        calls = []
        def ocr(*args, **kwargs):
            calls.append(args)
            return 'Scanned evidence 2.5 mV. ' * 3, {}
        result = run_cli(pdf, self.root, ocr=ocr)
        self.assertEqual([p['engine'] for p in result['pages']], ['text', 'text', 'text', 'hybrid'])
        self.assertEqual(len(calls), 1)

    def test_same_name_different_bytes_never_reuses_cache(self):
        a, b = self.root / 'a', self.root / 'b'
        a.mkdir(); b.mkdir()
        p1, p2 = a / 'same.pdf', b / 'same.pdf'
        generate_pdf(p1, text='FIRST source. ')
        generate_pdf(p2, text='SECOND source. ')
        one = run_cli(p1, self.root, '--force-ocr', ocr=lambda *a, **k: ('FIRST OCR ' * 10, {}))
        two = run_cli(p2, self.root, '--force-ocr', ocr=lambda *a, **k: ('SECOND OCR ' * 10, {}))
        self.assertIn('SECOND OCR', pathlib.Path(two['file']).read_text())
        self.assertNotEqual(one['revision_id'], two['revision_id'])
        first_package = json.loads(pathlib.Path(one['package_path']).read_text())
        self.assertIn('FIRST OCR', pathlib.Path(first_package['artifacts'][0]['path']).read_text())

    def test_truncation_survives_cache_hit_and_warns(self):
        pdf = self.root / 'scan.pdf'
        generate_pdf(pdf)
        stats = {'finish_reason': 'length', 'truncated': True,
                 'quality_flags': ['completion_truncated'], 'model': 'test-model',
                 'usage': {'completion_tokens': 8}, 'recognizer': {'backend': 'test'}}
        first = run_cli(pdf, self.root, '--force-ocr', ocr=lambda *a, **k: ('partial evidence ' * 10, stats))
        second = run_cli(pdf, self.root, '--force-ocr', ocr=lambda *a, **k: self.fail('OCR called on cache hit'))
        for result in (first, second):
            self.assertEqual(result['status'], 'warn')
            self.assertEqual(result['pages'][0]['finish_reason'], 'length')
            self.assertIn('completion_truncated', result['pages'][0]['quality_flags'])
        self.assertEqual(second['pages'][0]['cache'], 'hit')
        self.assertEqual(second['pages'][0]['recognizer'], {'backend': 'test'})

    def test_empty_ocr_is_failed_not_ok(self):
        pdf = self.root / 'scan.pdf'
        generate_pdf(pdf)
        result = run_cli(pdf, self.root, '--force-ocr', ocr=lambda *a, **k: ('', {}))
        self.assertNotEqual(result['status'], 'ok')
        self.assertEqual(result['coverage']['failed_pages'], [1])

    def test_blank_page_does_not_start_ocr(self):
        pdf = self.root / 'blank.pdf'
        generate_pdf(pdf, blank=True)
        result = run_cli(pdf, self.root, ocr=lambda *a, **k: self.fail('blank page OCR'))
        self.assertEqual(result['pages'][0]['engine'], 'text')
        self.assertEqual(result['pages'][0]['status'], 'blank')


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.pdf = self.root / 'native.pdf'
        generate_pdf(self.pdf)

    def test_sparse_native_text_does_not_require_ocr(self):
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((50, 50), 'Title')
            signals = ep.classify_page(page)
        self.assertFalse(signals['needs_ocr'])
        self.assertFalse(signals['blank'])

    def test_corrupt_and_legacy_cache_are_misses(self):
        self.assertIsNone(ep.cache_get(self.root, 'missing'))
        (self.root / 'broken.json').write_text('{')
        self.assertIsNone(ep.cache_get(self.root, 'broken'))
        (self.root / 'legacy.txt').write_text('old unverified output')
        self.assertIsNone(ep.cache_get(self.root, 'legacy'))
        (self.root / 'bad-schema.json').write_text('[]')
        self.assertIsNone(ep.cache_get(self.root, 'bad-schema'))
        ep.cache_put(self.root, 'valid', 'output', {'finish_reason': 'length'})
        self.assertEqual(ep.cache_get(self.root, 'valid'), ('output', {'finish_reason': 'length'}))

    def test_refresh_cache_replaces_result(self):
        run_cli(self.pdf, self.root, '--force-ocr', ocr=lambda *a, **k: ('first ' * 10, {}))
        fresh = run_cli(self.pdf, self.root, '--force-ocr', '--refresh-cache',
                        ocr=lambda *a, **k: ('fresh ' * 10, {}))
        hit = run_cli(self.pdf, self.root, '--force-ocr',
                      ocr=lambda *a, **k: self.fail('refresh should be persisted'))
        self.assertEqual(hit['pages'][0]['cache'], 'hit')
        self.assertIn('fresh', pathlib.Path(hit['file']).read_text())

    def test_no_cache_bypasses_reads_and_writes(self):
        run_cli(self.pdf, self.root, '--force-ocr', '--no-cache',
                ocr=lambda *a, **k: ('uncached ' * 10, {}))
        self.assertFalse((self.root / 'native_output' / '.cache').exists())

    def test_table_failure_is_visible(self):
        # Exercise native extraction with real PDF text and a failing table backend.
        stream = io.StringIO()
        args = ['extract_pdf.py', str(self.pdf), '--output-dir', str(self.root), '--no-pdfmux', '--json']
        with patch.object(sys, 'argv', args), contextlib.redirect_stdout(stream), \
             patch('pdfplumber.open', side_effect=RuntimeError('table decoder failed')):
            ep.main()
        result = json.loads(stream.getvalue()[stream.getvalue().index('{'):])
        self.assertEqual(result['status'], 'warn')
        self.assertIn('table_extraction_failed', result['quality_flags'])
        self.assertEqual(result['pages'][0]['table_error'], 'table decoder failed')

    def test_document_package_preserves_exact_cells_and_provenance(self):
        import document_reader
        result = run_cli(self.pdf, self.root)
        package = json.loads(pathlib.Path(result['package_path']).read_text())
        self.assertEqual(package['source']['sha256'], ep.source_revision(self.pdf))
        self.assertEqual(package['pages'][0]['physical_page'], 1)
        self.assertIsNone(package['pages'][0]['blocks'][0]['bbox'])
        self.assertEqual(package['pages'][0]['blocks'][0]['validation_state'], 'unverified')
        self.assertEqual(document_reader.open_document(result['package_path'])['revision_id'], result['revision_id'])
        self.assertIn('exact units', document_reader.read_document(result['package_path'])['text'])

    def test_config_changes_invalidate_pipeline_cache(self):
        import copy
        import engines
        config = copy.deepcopy(engines.load_config())
        with patch.object(engines, 'load_config', return_value=config):
            first = ep._pipeline_signature('glm', 150, 'local')
            config['engines']['glm']['max_tokens'] = 123
            second = ep._pipeline_signature('glm', 150, 'local')
            config['engines']['glm']['prompt'] = 'new exact prompt'
            third = ep._pipeline_signature('glm', 150, 'local')
            config['engines']['glm']['sources']['local']['api_key'] = 'different-secret'
            fourth = ep._pipeline_signature('glm', 150, 'local')
        self.assertNotEqual(first, second)
        self.assertNotEqual(second, third)
        self.assertEqual(third, fourth)

    def test_ov_and_audit_config_change_pipeline(self):
        import copy
        import engines
        config = copy.deepcopy(engines.load_config())
        with patch.object(engines, 'load_config', return_value=config), \
             patch.object(ep, '_ov_backend', return_value='openvino'):
            config['defaults']['ocr_ov_dir'] = '/models/a'
            first = ep._pipeline_signature('ov', 150, 'local')
            config['defaults']['ocr_ov_dir'] = '/models/b'
            self.assertNotEqual(first, ep._pipeline_signature('ov', 150, 'local'))
            first = ep._pipeline_signature('audit', 150, 'local')
            config['engines']['qwen']['prompt'] = 'different audit prompt'
            self.assertNotEqual(first, ep._pipeline_signature('audit', 150, 'local'))

    def test_tables_available_in_reader(self):
        import document_reader
        import pdfplumber
        table = [['TABLE_ONLY_NEEDLE', '0'], ['repeat', '1'], ['repeat', '1']]
        args = ['extract_pdf.py', str(self.pdf), '--output-dir', str(self.root), '--no-pdfmux', '--json']
        stream = io.StringIO()
        from unittest.mock import MagicMock
        fake_plumber = MagicMock()
        fake_plumber.__enter__.return_value.pages[0].extract_tables.return_value = [table]
        with patch.object(sys, 'argv', args), contextlib.redirect_stdout(stream), \
             patch.object(pdfplumber, 'open', return_value=fake_plumber):
            ep.main()
        result = json.loads(stream.getvalue()[stream.getvalue().index('{'):])
        package = json.loads(pathlib.Path(result['package_path']).read_text())
        self.assertEqual(package['pages'][0]['blocks'][1]['cells'], table)
        self.assertEqual(document_reader.search_document(result['package_path'], 'TABLE_ONLY_NEEDLE')['total_matches'], 1)
        self.assertIn('| repeat | 1 |', document_reader.read_document(result['package_path'])['text'])

    def test_audit_batch_never_fabricates_single_page_citations(self):
        import document_reader
        generate_pdf(self.root / 'mixed.pdf', mixed=True)
        args = ['extract_pdf.py', str(self.root / 'mixed.pdf'), '--pages', '1-2', '--audit', '--batch',
                '--output-dir', str(self.root), '--json']
        stream = io.StringIO()
        with patch.object(sys, 'argv', args), contextlib.redirect_stdout(stream), \
             patch.object(ep, 'ensure_server'), \
             patch.object(ep, 'extract_qwen_multi', return_value=('FIRST PAGE SECOND_PAGE_TOKEN', {})):
            ep.main()
        result = json.loads(stream.getvalue()[stream.getvalue().index('{'):])
        package = json.loads(pathlib.Path(result['package_path']).read_text())
        self.assertEqual(package['unaligned_candidates'][0]['source_pages'], [1, 2])
        self.assertEqual(package['coverage']['processed_pages'], [])
        self.assertEqual(document_reader.read_document(result['package_path'], pages='2')['text'], '')
        search = document_reader.search_document(result['package_path'], 'SECOND_PAGE_TOKEN')
        self.assertFalse(search['complete_document_search'])
        self.assertEqual(search['hits'], [])

    def test_qwen_raw_retains_truncation(self):
        from unittest.mock import MagicMock
        image = self.root / 'page.png'
        Image.new('RGB', (10, 10), 'white').save(image)
        response = MagicMock(status_code=200)
        response.json.return_value = {'choices': [{'message': {'content': '<p>partial</p>'},
                                                   'finish_reason': 'length'}],
                                      'model': 'test-qwen', 'usage': {'completion_tokens': 3}}
        with patch('requests.post', return_value=response):
            text, stats = ep._qwen_raw([str(image)])
        self.assertEqual(text, '<p>partial</p>')
        self.assertTrue(stats['truncated'])
        self.assertIn('completion_truncated', stats['quality_flags'])
        self.assertEqual(stats['model'], 'test-qwen')

    def test_cloud_extraction_never_initializes_local_server(self):
        args = ['extract_pdf.py', str(self.pdf), '--hybrid', '--source', 'cloud', '--json',
                '--output-dir', str(self.root), '--no-cache']
        stream = io.StringIO()
        with patch.object(sys, 'argv', args), contextlib.redirect_stdout(stream), \
             patch.object(ep, '_ensure_hybrid_server', side_effect=AssertionError('local OCR started')), \
             patch.object(ep, '_engines_call', return_value=('cloud evidence ' * 10, {'source': 'cloud'})) as call:
            ep.main()
        result = json.loads(stream.getvalue()[stream.getvalue().index('{'):])
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(call.call_args.kwargs['source'], 'cloud')
        self.assertEqual(result['pages'][0]['source'], 'cloud')

    def test_cache_hit_skips_page_render_and_server_start(self):
        run_cli(self.pdf, self.root, '--force-ocr')
        args = ['extract_pdf.py', str(self.pdf), '--force-ocr', '--json',
                '--output-dir', str(self.root), '--no-table', '--no-pdfmux']
        stream = io.StringIO()
        with patch.object(sys, 'argv', args), contextlib.redirect_stdout(stream), \
             patch.object(ep, '_pipeline_signature', return_value='test-pipeline'), \
             patch.object(ep, '_ensure_hybrid_server', side_effect=AssertionError('server started')), \
             patch.object(fitz.Page, 'get_pixmap', side_effect=AssertionError('rendered cache hit')):
            ep.main()
        result = json.loads(stream.getvalue()[stream.getvalue().index('{'):])
        self.assertEqual(result['pages'][0]['cache'], 'hit')

    def test_layout_does_not_initialize_ocr(self):
        args = ['extract_pdf.py', str(self.pdf), '--layout-only', '--json', '--output-dir', str(self.root)]
        with patch.object(sys, 'argv', args), contextlib.redirect_stdout(io.StringIO()), \
             patch.object(ep, '_ensure_hybrid_server', side_effect=AssertionError('OCR initialized')), \
             patch.object(ep, 'extract_layout', return_value=([], {})), \
             self.assertRaises(SystemExit) as context:
            ep.main()
        self.assertEqual(context.exception.code, 0)


if __name__ == '__main__':
    unittest.main()
