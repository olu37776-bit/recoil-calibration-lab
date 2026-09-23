"""Restricted-container DOM check. Explicitly NOT a network E2E test."""
from pathlib import Path
import json
import shutil
import tempfile
from playwright.sync_api import sync_playwright
from recoil_lab.catalog import public_catalog
from recoil_lab.product import Product

ROOT=Path(__file__).resolve().parents[1]


def main():
    out=ROOT/'runs';out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        app=Product(Path(td))
        def bridge(path,body):
            try:
                if path=='/api/bootstrap':return {'ok':True,'data':{'token':'dom-test'}}
                if path=='/api/catalog':return {'ok':True,'data':public_catalog()}
                return {'ok':True,'data':app.handle(json.loads(body))}
            except Exception as e:return {'ok':False,'data':{'error':str(e)}}
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.expose_function('labBridge',bridge)
            html=(ROOT/'src/recoil_lab/web/workbench.html').read_text()
            html=html.replace('<link rel="stylesheet" href="/workbench.css">','').replace('<script src="/workbench.js"></script>','')
            page.set_content(html)
            page.add_style_tag(content=(ROOT/'src/recoil_lab/web/workbench.css').read_text())
            page.evaluate("window.fetch=async (path,options={})=>{const r=await window.labBridge(path,options.body||'{}');return {ok:r.ok,json:async()=>r.data}}")
            page.add_script_tag(content=(ROOT/'src/recoil_lab/web/workbench.js').read_text())
            page.wait_for_function("document.querySelector('#weapon').options.length===14")
            page.click('#demo')
            page.wait_for_function("document.querySelector('#profiles').options.length===2",timeout=20000)
            assert 'SIMULATED_REPLAY' in page.locator('#report').inner_text()
            assert page.locator('#trials tr').count()==12
            page.screenshot(path=str(out/'product-interface.png'),full_page=True)
            if errors:raise AssertionError(errors)
            browser.close()
    (out/'product-dom.json').write_text(json.dumps({'status':'PASS','scope':'DOM with in-process API bridge; NOT network E2E','checks':['catalog choices','full demo','displayed report','data table'],'game_tested':False,'mouse_output_tested':False},indent=2),encoding='utf-8')


if __name__=='__main__':main()
