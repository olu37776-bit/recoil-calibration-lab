"""Exercise the real loopback HTTP UI; no browser bridge or mouse output."""
from pathlib import Path
import json
import os
import shutil
import tempfile
import threading
from playwright.sync_api import sync_playwright
from recoil_lab.ui import LabServer

ROOT=Path(__file__).resolve().parents[1]


def main():
    out=ROOT/'runs';out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as td, LabServer(0,data_directory=Path(td)) as server:
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True,executable_path=os.environ.get('CHROME_PATH') or shutil.which('chromium'),args=['--no-sandbox'])
                page=browser.new_page(viewport={'width':1440,'height':1000},device_scale_factor=1)
                errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.server_port}/workbench.html',wait_until='networkidle',timeout=20000)
                page.wait_for_function("document.querySelector('#weapon').options.length===14")
                page.click('#demo')
                page.wait_for_function("document.querySelector('#profiles').options.length===2",timeout=20000)
                assert 'SIMULATED_REPLAY' in page.locator('#report').inner_text()
                assert page.locator('#trials tr').count()==12
                page.click('[data-tab=execute]')
                with page.expect_download() as download:page.click('#export')
                assert download.value.suggested_filename.endswith('.zip')
                page.reload(wait_until='networkidle')
                page.wait_for_function("document.querySelector('#projects').options.length===1")
                page.select_option('#projects',index=0);page.dispatch_event('#projects','change')
                page.wait_for_function("document.querySelector('#profiles').options.length===2")
                page.click('[data-tab=calibrate]')
                page.screenshot(path=str(out/'product-interface.png'),full_page=True)
                browser.close()
                if errors:raise AssertionError(errors)
            result={'status':'PASS','mode':'actual_browser_loopback_HTTP', 'checks':['catalog','full_demo','report','export','reload_project_persistence'], 'game_tested':False,'input_tested':False}
        except Exception as exc:
            result={'status':'FAIL','mode':'actual_browser_loopback_HTTP','error':str(exc),'game_tested':False,'input_tested':False}
            raise
        finally:
            (out/'product-browser.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
            server.shutdown();thread.join(5)


if __name__=='__main__':main()
