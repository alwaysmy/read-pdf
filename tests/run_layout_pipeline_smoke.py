"""Real official CPU layout + OCR + table assembly through CLI/HTTP/MCP.

Needs configured defaults.layout_backend=openvino and layout_ov_dir. No automatic
model download, OCR mocks, cloud inference or user-config writes occur here.
"""
import argparse,json,os,pathlib,subprocess,sys,threading,time
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'tests')]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    parser.add_argument('--technical-pdf');args=parser.parse_args()
    out=pathlib.Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
    home=out/'offline-home';home.mkdir(exist_ok=True);os.environ.update(HOME=str(home),LOCALAPPDATA=str(home))
    from openvino_telemetry.utils.opt_in_checker import OptInChecker,ConsentCheckResult
    assert OptInChecker().update_result(ConsentCheckResult.DECLINED)
    import extract_pdf as ep
    if ep._ov_config().get('layout_backend')!='openvino':raise SystemExit('Configure official OpenVINO layout first')
    from generate_pipeline_fixtures import generate
    from run_real_pipeline_smoke import parse_result
    fixture=generate(out/'fixtures');truth=json.loads((fixture/'ground_truth.json').read_text())
    report={'mocked_models':False,'cases':[]}
    def cli(name,pdf,extra):
        start=time.monotonic();proc=subprocess.run([sys.executable,str(ROOT/'scripts/extract_pdf.py'),str(pdf),
          '--json','--output-dir',str(out/name),*extra],capture_output=True,text=True,timeout=180)
        (out/(name+'.log')).write_text(proc.stdout+'\n'+proc.stderr)
        assert proc.returncode==0,proc.stdout+proc.stderr
        result=parse_result(proc.stdout);report['cases'].append({'name':name,'wall_time_s':round(time.monotonic()-start,3),
            'status':result['status'],'flags':result.get('quality_flags',[]),'tables':result.get('total_tables'),
            'result':result.get('package_path') or result.get('layout_path')})
        return result
    layout=cli('layout_cli',fixture/'scanned.pdf',['--layout-only'])
    labels=[block['label'] for block in layout['pages'][0]['blocks']]
    assert 'table' in labels and 'image' in labels and layout['total_crops']>=2
    result=cli('hybrid_cli',fixture/'scanned.pdf',['--hybrid','--no-pdfmux'])
    package=json.loads(pathlib.Path(result['package_path']).read_text())
    assert package['pages'][0]['structured_tables'][0]['matrix']==truth['table_rows']
    assert any(block['type']=='table' and block.get('crop_ref') for block in package['pages'][0]['blocks'])
    cached=cli('hybrid_cli',fixture/'scanned.pdf',['--hybrid','--no-pdfmux'])
    assert cached['pages'][0].get('cache')=='hit'
    report['cases'][-1]['name']='hybrid_cli_cache_hit'
    mixed=cli('mixed_cli',fixture/'mixed.pdf',['--no-pdfmux'])
    assert [p['engine'] for p in mixed['pages'][:3]]==['text']*3 and mixed['total_tables']==1
    os.environ['READPDF_API_KEY']='readpdf-local-layout-smoke'
    from werkzeug.serving import make_server
    import server
    http=make_server('127.0.0.1',0,server.app);os.environ['READPDF_SERVER_URL']=f'http://127.0.0.1:{http.server_port}'
    thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    try:
        import requests
        headers={'Authorization':'Bearer '+os.environ['READPDF_API_KEY']}
        for endpoint,body in [('/layout',{'pdf':str(fixture/'scanned.pdf'),'device':'cpu','output_dir':str(out/'http-layout')}),
                              ('/extract',{'pdf':str(fixture/'scanned.pdf'),'engine':'hybrid','output_dir':str(out/'http-hybrid')})]:
            start=time.monotonic();response=requests.post(os.environ['READPDF_SERVER_URL']+endpoint,headers=headers,json=body,timeout=180)
            assert response.status_code==200,response.text
            data=response.json();assert data['status']=='ok',data
            if endpoint=='/extract':assert data['total_tables']==1
            report['cases'].append({'name':'http'+endpoint,'wall_time_s':round(time.monotonic()-start,3),'status':data['status']})
        start=time.monotonic();proc=subprocess.run([sys.executable,str(ROOT/'tests/test_mcp_protocol.py'),
          '--extract-scan',str(fixture/'scanned.pdf'),'--engine','hybrid','--output-dir',str(out/'mcp')],
          capture_output=True,text=True,timeout=180)
        (out/'mcp-stdio.log').write_text(proc.stdout+proc.stderr);assert proc.returncode==0,proc.stdout+proc.stderr
        report['cases'].append({'name':'mcp_stdio_hybrid','wall_time_s':round(time.monotonic()-start,3),'status':'passed'})
    finally:http.shutdown();thread.join()
    if args.technical_pdf:
        import fitz
        pdf=pathlib.Path(args.technical_pdf)
        scan=out/'technical-page5-scan.pdf'
        with fitz.open(pdf) as source,fitz.open() as target:
            page=source[4];target.new_page(width=page.rect.width,height=page.rect.height).insert_image(page.rect,stream=page.get_pixmap(dpi=150).tobytes('png'));target.save(scan)
        result=cli('technical_hybrid',scan,['--hybrid','--no-pdfmux'])
        package=json.loads(pathlib.Path(result['package_path']).read_text());table=package['pages'][0]['structured_tables'][0]
        assert table['columns']==7 and 'table_columns_inferred_from_headers' in table['quality_flags']
        offset=next(row for row in table['matrix'] if 'differential inputs' in row[2])
        assert offset[3:6]==['-3','±1','3'],offset
        inl=next(row for row in table['matrix'] if row[0]=='INL')
        assert inl[3:6]==['','','1'],inl
        report['technical_checks']={'rows':table['rows'],'columns':table['columns'],
                                     'offset_min_typ_max':offset[3:6],'inl_min_typ_max':inl[3:6],
                                     'flags':table['quality_flags']}
    (out/'REPORT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
