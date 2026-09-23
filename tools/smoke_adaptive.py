"""Optional DOM/API-bridge smoke, not browser HTTP E2E or game validation."""
from __future__ import annotations
import base64
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
from recoil_lab.ui import process
from test_adaptive_hud import payload, canvas
from test_screenshots import encoded
from playwright.sync_api import sync_playwright


def main():
    out=ROOT/'runs/browser-synthetic';out.mkdir(parents=True,exist_ok=True)
    p=payload(1280,720,2)
    def write(name,data):
        path=out/name;path.write_bytes(base64.b64decode(data.split(',')[-1]));return str(path)
    refs=[write(f'ref{i}.png',r['image']) for i,r in enumerate(p['references'])]
    query=write('query.png',p['image'])
    blank=write('blank.png',encoded(canvas(1280,720,2,blank=True)[0]))
    def bridge(path,body):
        if path=='/api/bootstrap':return {'status':200,'body':{'token':'dom-only'}}
        try:return {'status':200,'body':process(path,body)}
        except Exception as exc:return {'status':400,'body':{'error':str(exc)}}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1400,'height':1050})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.expose_function('labBridge',bridge)
        html=(ROOT/'src/recoil_lab/web/adaptive.html').read_text()
        html=re.sub(r'<link[^>]+>|<script[^>]*>.*?</script>','',html,flags=re.S)
        page.set_content(html)
        page.add_style_tag(path=str(ROOT/'src/recoil_lab/web/style.css'))
        page.evaluate("""window.fetch=async(path,opts={})=>{const r=await window.labBridge(path,opts.body?JSON.parse(opts.body):{});return {ok:r.status<400,json:async()=>r.body};};""")
        page.add_script_tag(path=str(ROOT/'src/recoil_lab/web/adaptive.js'))
        page.locator('#adaptive-layout').fill('synthetic-v4')
        page.locator('#adaptive-references input').nth(0).set_input_files(refs[0])
        page.wait_for_function("document.querySelector('#reference-size').textContent.includes('640')")
        page.locator('#adaptive-references input').nth(1).set_input_files(refs[1])
        page.locator('#reference-canvas').scroll_into_view_if_needed()
        b=page.locator('#reference-canvas').bounding_box()
        def pos(x,y):return b['x']+x/640*b['width'],b['y']+y/360*b['height']
        page.mouse.move(*pos(576,296));page.mouse.down();page.mouse.move(*pos(612,332));page.mouse.up()
        assert '576, 296, 36, 36' in page.locator('#adaptive-roi').inner_text(), page.locator('#adaptive-roi').inner_text()
        page.locator('#adaptive-query').set_input_files(query)
        page.wait_for_function("document.querySelector('#adaptive-status').textContent==='候选：站立'",timeout=20000)
        r=json.loads(page.locator('#adaptive-output').inner_text())
        assert r['query_size']==[1280,720] and not r['auto_execution_eligible']
        assert not errors,errors
        with page.expect_download() as dl:page.locator('#adaptive-export').click()
        pack=out/'reference-pack.json';dl.value.save_as(str(pack))
        page.locator('#adaptive-field').select_option('ads')
        page.locator('#adaptive-import').set_input_files(str(pack))
        page.wait_for_function("document.querySelector('#adaptive-status').textContent==='候选：站立'",timeout=20000)
        page.screenshot(path=str(ROOT/'runs/adaptive-ui.png'),full_page=True)
        page.locator('#adaptive-query').set_input_files(blank)
        page.wait_for_function("document.querySelector('#adaptive-status').textContent.startsWith('未知')",timeout=20000)
        page.locator('#adaptive-auto').uncheck();page.locator('#adaptive-layout').fill('changed')
        assert page.locator('#adaptive-status').inner_text()=='输入已变化'
        page.set_viewport_size({'width':390,'height':844})
        overflow=page.evaluate('document.documentElement.scrollWidth>innerWidth')
        assert not overflow,'mobile horizontal overflow'
        browser.close()
    report={'version':'0.4.0','status':'PASS','scope':'DOM and in-process API bridge; browser network navigation blocked by environment',
            'checks':['first-reference drag maps CSS coordinates to original pixels','query dimensions read automatically',
                      'automatic cross-resolution candidate displayed','local reference pack export and reimport',
                      'missing icon produces unknown','input change invalidates previous result','mobile no horizontal overflow'],
            'page_errors':errors,'browser_network_e2e':False,'game_tested':False,'driver_tested':False}
    (ROOT/'evidence/browser-check.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
