"""Run the same UI assertions with an explicit local API bridge.

For restricted development containers only. This does not replace the real
browser/HTTP workflow or exercise the HTTP security boundary. No mouse output.
"""
from contextlib import ExitStack
import json
from pathlib import Path
import re
from unittest.mock import patch

from playwright.sync_api import Page

from recoil_lab.catalog import public_catalog
from recoil_lab.ui import LabServer
import smoke_product

ROOT = Path(__file__).resolve().parents[1]


def main():
    servers = []
    prepared_pages = set()
    original_goto = Page.goto

    class BridgedServer(LabServer):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            servers.append(self)

    def load(page, url='', **kwargs):
        original_goto(page, 'about:blank')
        if id(page) not in prepared_pages:
            def bridge(path, body):
                try:
                    if path == '/api/bootstrap':
                        return {'ok': True, 'data': {'token': 'dom-test'}}
                    if path == '/api/catalog':
                        return {'ok': True, 'data': public_catalog()}
                    if path != '/api/product':
                        return {'ok': False, 'data': {'error': 'Unsupported bridge request'}}
                    data = servers[-1].product_service().handle(json.loads(body))
                    return {'ok': True, 'data': data}
                except Exception as exc:
                    return {'ok': False, 'data': {'error': str(exc)}}
            page.expose_function('labBridge', bridge)
            prepared_pages.add(id(page))
        html = (ROOT/'src/recoil_lab/web/workbench.html').read_text(encoding='utf-8')
        html = re.sub(r'<script\b[^>]*>.*?</script>', '', html, flags=re.S)
        html = re.sub(r'<link\b[^>]*>', '', html)
        page.set_content(html)
        for name in ('workbench.css', 'guided.css'):
            page.add_style_tag(content=(ROOT/'src/recoil_lab/web'/name).read_text(encoding='utf-8'))
        page.evaluate("""window.fetch=async(path, options={})=>{
            const r=await window.labBridge(path,options.body||'{}');
            return {ok:r.ok,json:async()=>r.data};
        }""")
        for name in ('workbench.js', 'teaching-ui.js', 'guided.js'):
            page.add_script_tag(content=(ROOT/'src/recoil_lab/web'/name).read_text(encoding='utf-8'))
        page.wait_for_function('window.labInitialized===true')

    report_path = ROOT/'runs/product-browser.json'
    previous_report = report_path.read_bytes() if report_path.exists() else None
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(smoke_product, 'LabServer', BridgedServer))
            stack.enter_context(patch.object(Page, 'goto', load))
            stack.enter_context(patch.object(Page, 'reload', lambda page, **kw: load(page)))
            smoke_product.main()
    finally:
        # Preserve the real-network result, including a local policy rejection.
        if report_path.exists():
            report = json.loads(report_path.read_text(encoding='utf-8'))
            report['mode'] = 'DOM with in-process API bridge; NOT browser-network E2E'
            (ROOT/'runs/product-dom.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        if previous_report is not None:
            report_path.write_bytes(previous_report)
        else:
            report_path.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
