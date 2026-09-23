"""Exercise the real loopback HTTP UI; no browser bridge or mouse output."""
from pathlib import Path
import json
import os
import shutil
import tempfile
import threading
from playwright.sync_api import sync_playwright, expect
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
                expect(page.locator("#weapon option")).to_have_count(14, timeout=20000)
                expect(page.locator('#daily')).to_be_visible()
                expect(page.locator('#dailyRun')).to_be_disabled()
                page.check('#expertMode')
                page.locator('details').filter(has=page.locator('#demo')).locator('summary').click()
                page.click('#demo')
                expect(page.locator("#profiles option")).to_have_count(2, timeout=20000)
                assert 'SIMULATED_REPLAY' in page.locator('#report').inner_text()
                assert page.locator('#trials tr').count()==12
                page.click('[data-tab=execute]')
                with page.expect_download() as download:page.click('#export')
                assert download.value.suggested_filename.endswith('.zip')
                page.reload(wait_until='networkidle')
                page.check('#expertMode')
                expect(page.locator("#projects option")).to_have_count(1, timeout=20000)
                page.select_option('#projects',index=0);page.dispatch_event('#projects','change')
                expect(page.locator("#profiles option")).to_have_count(2, timeout=20000)
                page.click('[data-tab=setup]')
                page.fill('#name','浏览器教学测试')
                page.locator('#settingsPanel summary').click()
                page.fill('#build','synthetic-browser-only')
                page.fill('#width','320');page.fill('#height','180')
                page.fill('#weightLabel','重装')
                page.check('#settingsConfirmed')
                page.click('#create')
                expect(page.locator('#summary')).to_contain_text('浏览器教学测试')
                page.click('[data-tab=teach]')
                import numpy as np
                from PIL import Image
                from io import BytesIO
                pixels=np.random.default_rng(6).integers(20,240,(180,320),dtype=np.uint8)
                image=BytesIO();Image.fromarray(pixels).save(image,format='PNG')
                page.locator('#teachImage').set_input_files({'name':'synthetic.png','mimeType':'image/png','buffer':image.getvalue()})
                expect(page.locator('#teachCanvas')).to_have_attribute('width','320')
                page.locator('#teachCanvas').scroll_into_view_if_needed()
                c=page.locator('#teachCanvas').bounding_box()
                page.mouse.move(c['x']+230,c['y']+100);page.mouse.down()
                page.mouse.move(c['x']+294,c['y']+132);page.mouse.up()
                page.check('#teachConsent')
                page.locator('details').filter(has=page.locator('#teachSession')).locator('summary').click()
                page.fill('#teachSession','browser-reference')
                page.click('#teachReference')
                expect(page.locator('#teachBanks option')).to_have_count(2,timeout=10000)
                page.select_option('#teachWeight','重装');page.click('#teachQuery')
                expect(page.locator('#teachReport')).to_contain_text('MATCH')
                expect(page.locator('#teachReport')).to_contain_text('不会输出鼠标')
                page.reload(wait_until='networkidle')
                page.check('#expertMode')
                page.click('[data-tab=teach]')
                expect(page.locator('#teachBanks option')).to_have_count(2,timeout=10000)
                page.select_option('#teachBanks',index=1)
                expect(page.locator('#teachSamples tr')).to_have_count(1)
                # Check the new daily path and confirmed settings survive browser/app origin changes.
                page.click('#homeButton')
                expect(page.locator('#dailyTitle')).to_have_text('浏览器教学测试')
                expect(page.locator('#dailyConsent')).not_to_be_checked()
                expect(page.locator('#dailyRun')).to_be_disabled()
                page.click('#duplicateConfig')
                expect(page.locator('#setup')).to_be_visible()
                expect(page.locator('#weightLabel')).to_have_value('重装')
                expect(page.locator('#settingsConfirmed')).to_be_checked()
                expect(page.locator('#guideTitle')).to_have_text('保存这份新配装')
                page.screenshot(path=str(out/'guided-interface.png'),full_page=True)
                page.click('#homeButton')
                page.uncheck('#expertMode')
                page.screenshot(path=str(out/'product-interface.png'),full_page=True)
                browser.close()
                if errors:raise AssertionError(errors)
            result={'status':'PASS','mode':'actual_browser_loopback_HTTP', 'checks':['catalog','full_demo','report','export','reload_project_persistence','manual_weight','teach_region_save','known_image_select','recognition_bank_persistence','daily_default_off','restore_last_project','copy_only_changed_condition','confirmed_settings_reuse'], 'game_tested':False,'input_tested':False}
        except Exception as exc:
            result={'status':'FAIL','mode':'actual_browser_loopback_HTTP','error':str(exc),'game_tested':False,'input_tested':False}
            raise
        finally:
            (out/'product-browser.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
            server.shutdown();thread.join(5)


if __name__=='__main__':main()
