"""Run deterministic regressions and existing suites. --offline skips live backend tests."""
import argparse
import json
import pathlib
import subprocess
import sys
import time

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

ROOT = pathlib.Path(__file__).resolve().parent
SUITES = [
    ('unit_engines.py', 'engine configuration', False),
    ('unit_server_manager.py', 'server manager', False),
    ('test_friendly_hint.py', 'setup diagnostics', False),
    ('test_extraction_quality.py', 'generated-PDF quality regressions', False),
    ('test_image_outputs.py', 'real image export / CLI failure modes', False),
    ('test_completion_metadata.py', 'completion metadata', False),
    ('test_ppocr_runtime.py', 'optional real bundled CPU OCR runtime', False),
    ('test_layout_tables.py', 'visible table geometry / honest assembly', False),
    ('test_doclayout_runtime.py', 'optional real official layout model', False),
    ('test_document_reader.py', 'document readers / Flask / MCP adapters', False),
    ('test_mcp_tools.py', 'live HTTP/MCP tools', True),
    ('test_mcp_protocol.py', 'live MCP stdio protocol', True),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true', help='skip suites requiring a running HTTP backend')
    args = parser.parse_args()
    results = []
    for script, description, needs_server in SUITES:
        if args.offline and needs_server:
            print(f'SKIP {script}: live backend required', flush=True)
            results.append({'script': script, 'description': description, 'status': 'skipped', 'ok': None})
            continue
        print(f'\n=== {description} [{script}] ===', flush=True)
        start = time.monotonic()
        try:
            result = subprocess.run([sys.executable, str(ROOT / script)], capture_output=True,
                                    text=True, encoding='utf-8', errors='replace', timeout=1200)
            print(result.stdout, end='')
            print(result.stderr, end='', file=sys.stderr)
            ok = result.returncode == 0
        except subprocess.TimeoutExpired:
            print(f'FAIL {script}: timeout after 1200s', flush=True)
            ok = False
        results.append({'script': script, 'description': description, 'ok': ok,
                        'status': 'passed' if ok else 'failed', 'time_s': round(time.monotonic() - start, 3)})
    all_ok = all(result['ok'] is not False for result in results)
    for result in results:
        print(f"{result['status'].upper():7s} {result['script']}")
    print('All executed suites passed' if all_ok else 'Some suites failed')
    out = ROOT / 'all_tests'
    out.mkdir(exist_ok=True)
    tag = time.strftime('%Y%m%d_%H%M%S')
    path = out / f'run_all_tests_{tag}.json'
    path.write_text(json.dumps({'tag': tag, 'offline': args.offline, 'all_ok': all_ok,
                                'results': results}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Report: {path}')
    return 0 if all_ok else 1


if __name__ == '__main__':
    sys.exit(main())
