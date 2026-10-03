"""Real CPU OCR/CLI/HTTP/MCP smoke run; no OCR/model/transport mocks.

Install requirements-test.txt + requirements-ov.txt and configure
 defaults.ocr_backend: openvino
 engines.hybrid.recognizer.backend: openvino
in engine_config.local.yaml. This runner never writes that private configuration.
"""
import argparse
import contextlib
import json
import os
import pathlib
import subprocess
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))


def parse_result(text):
    start=text.find('\n{')
    if start < 0:
        raise ValueError('No structured result in CLI output: '+text[-500:])
    return json.loads(text[start+1:])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    parser.add_argument('--technical-pdf',help='Optional existing public technical PDF; pages 1,5 are tested')
    args=parser.parse_args()
    out=pathlib.Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
    # This dedicated test process and all CLI children share a private HOME with
    # the official consent state declined. No user preferences are overwritten.
    telemetry_home = out / 'offline-home'
    telemetry_home.mkdir(exist_ok=True)
    os.environ.update(HOME=str(telemetry_home), LOCALAPPDATA=str(telemetry_home))
    from openvino_telemetry.utils.opt_in_checker import OptInChecker, ConsentCheckResult
    checker = OptInChecker()
    if not checker.update_result(ConsentCheckResult.DECLINED):
        raise RuntimeError('Cannot disable runtime telemetry for offline smoke tests')
    assert checker.check(enable_opt_in_dialog=False) == ConsentCheckResult.DECLINED
    from generate_pipeline_fixtures import generate
    from extract_pdf import _ov_backend, _ov_openvino_ready
    if _ov_backend()!='openvino' or not _ov_openvino_ready():
        raise SystemExit('Configure/install the existing OpenVINO CPU backend before this real test')
    fixtures=generate(out/'fixtures')
    truth=json.loads((fixtures/'ground_truth.json').read_text())
    report={'mocked':False,'cases':[],'limitations':['No PP-DocLayout model or generative formula/table model is installed',
                                                   'Synthetic fixtures are correctness probes, not an accuracy benchmark']}
    def record(name,result,wall):
        markdown=pathlib.Path(result.get('file') or result.get('output')).read_text(encoding='utf-8')
        package=json.loads(pathlib.Path(result['package_path']).read_text())
        for asset in package['artifacts']:
            if asset.get('path') and 'error' not in asset:
                assert pathlib.Path(asset['path']).is_file(),asset
        entry={'name':name,'status':result['status'],'wall_time_s':round(wall,3),
               'extraction_time_s':result.get('total_time'),'package_path':result['package_path'],
               'markdown_path':result.get('file') or result.get('output'),
               'page_engines':[p['engine'] for p in result['pages']],
               'quality_flags':result['quality_flags'],
               'images':len([a for a in package['artifacts'] if a['type'] in ('source_page','embedded_image')])}
        report['cases'].append(entry)
        return markdown,package,entry
    def cli(name,pdf,extra=()):
        start=time.monotonic()
        proc=subprocess.run([sys.executable,str(ROOT/'scripts/extract_pdf.py'),str(pdf),'--no-pdfmux','--json',
                             '--output-dir',str(out/name),*extra],capture_output=True,text=True,timeout=180)
        (out/f'{name}.log').write_text(proc.stdout+'\nSTDERR:\n'+proc.stderr,encoding='utf-8')
        assert proc.returncode==0,(name,proc.returncode,proc.stderr)
        result=parse_result(proc.stdout)
        return result,record(name,result,time.monotonic()-start)
    result,(md,package,_) = cli('native_cli',fixtures/'born_digital.pdf')
    assert result['status']=='ok',result
    assert package['pages'][0]['table_data'][0]==truth['table_rows']
    assert md.count('| Repeated | 0 | 1 | 2 | mV |')==2
    assert any(a['type']=='embedded_image' for a in package['artifacts'])
    assert '![Embedded image' in md
    result,(md,package,entry)=cli('scan_cli',fixtures/'scanned.pdf',('--ov',))
    assert all(anchor in md for anchor in truth['required_anchors']),md
    assert truth['chinese_anchor'] in md,md
    entry['exact_numeric_anchors']={value:value in md for value in truth['numeric_anchors']}
    assert all(entry['exact_numeric_anchors'].values())
    # Same source/output/config: actual second CLI call must use stored OCR.
    hit,(hit_md,_,hit_entry)=cli('scan_cli',fixtures/'scanned.pdf',('--ov',))
    hit_entry['name']='scan_cli_cache_hit'
    assert hit['pages'][0].get('cache')=='hit' and md==hit_md
    result,(md,package,entry)=cli('mixed_cli',fixtures/'mixed.pdf')
    assert [p['engine'] for p in result['pages'][:3]]==['text']*3
    assert result['pages'][3]['chars']>500
    assert 'layout_unavailable' in result['quality_flags'],result
    assert result['status']=='warn'
    result,(md,package,entry)=cli('low_resolution_cli',fixtures/'scanned_96dpi.pdf',('--ov','--dpi','96'))
    entry['anchors_found']={value:value in md for value in truth['required_anchors']+truth['numeric_anchors']}
    # Low-resolution OCR accuracy is measured, not silently asserted perfect.
    os.environ['READPDF_API_KEY']='readpdf-ephemeral-smoke-only'
    from werkzeug.serving import make_server
    import server
    http=make_server('127.0.0.1',0,server.app)
    os.environ['READPDF_SERVER_URL']=f'http://127.0.0.1:{http.server_port}'
    thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    try:
        import requests
        start=time.monotonic()
        response=requests.post(os.environ['READPDF_SERVER_URL']+'/extract',
                               headers={'Authorization':'Bearer '+os.environ['READPDF_API_KEY']},
                               json={'pdf':str(fixtures/'scanned.pdf'),'engine':'ov','output_dir':str(out/'http')},timeout=180)
        assert response.status_code==200,response.text
        result=response.json();md,package,entry=record('scan_http',result,time.monotonic()-start)
        assert 'CALIBRATION_OK_314159' in md
        import mcp_server
        start=time.monotonic()
        result=mcp_server.extract_pdf(str(fixtures/'scanned.pdf'),engine='ov',output_dir=str(out/'mcp'))
        md,package,entry=record('scan_mcp_adapter',result,time.monotonic()-start)
        read=mcp_server.read_document(result['package_path'],max_chars=80)
        assert len(read['text'])==80 and read['next_cursor']
        search=mcp_server.search_document(result['package_path'],'12.5')
        assert search['returned_hits']>0 and search['hits'][0]['citation']['physical_page']==1
        # Existing stdio protocol test really launches MCP, lists six tools and calls backend.
        start=time.monotonic()
        protocol=subprocess.run([sys.executable,str(ROOT/'tests/test_mcp_protocol.py'),
                                 '--extract-scan',str(fixtures/'scanned.pdf'),
                                 '--output-dir',str(out/'mcp_stdio')],capture_output=True,text=True,timeout=180)
        (out/'mcp_stdio.log').write_text(protocol.stdout+protocol.stderr)
        assert protocol.returncode==0,protocol.stdout+protocol.stderr
        report['mcp_stdio']={'status':'passed','real_ocr':True,'wall_time_s':round(time.monotonic()-start,3)}
    finally:
        http.shutdown();thread.join()
    if args.technical_pdf:
        pdf=pathlib.Path(args.technical_pdf).resolve()
        result,(md,package,entry)=cli('technical_native',pdf,('--pages','1,5'))
        entry['table_count']=result['total_tables']
        entry['text_chars']=sum(p['chars'] for p in result['pages'])
        # Actual original technical page, rasterized with text layer removed.
        import fitz
        scanned=out/'technical_page5_scan.pdf'
        with fitz.open(pdf) as source,fitz.open() as target:
            page=source[4]
            target.new_page(width=page.rect.width,height=page.rect.height).insert_image(page.rect,
                         stream=page.get_pixmap(dpi=150).tobytes('png'))
            target.save(scanned)
        result,(md,package,entry)=cli('technical_scan',scanned,('--ov',))
        entry['text_chars']=sum(p['chars'] for p in result['pages'])
        assert entry['text_chars']>1000
    (out/'REPORT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
