"""Build and launch the actual Windows one-file native UI before publishing."""
from pathlib import Path
import hashlib
import json
import os
import platform
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]

def main():
    if platform.system()!='Windows':raise SystemExit('Windows runner required')
    os.chdir(ROOT);sys.path.insert(0,str(ROOT/'src'))
    from recoil_lab.catalog import public_catalog
    from recoil_lab.simple_core import VERSION
    (ROOT/'src/recoil_lab/simple_catalog.json').write_text(json.dumps(public_catalog(),ensure_ascii=False),encoding='utf-8')
    cmd=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile','--windowed',
         '--name','RecoilLab-Simple','--paths','src',
         '--add-data','src/recoil_lab/simple_catalog.json;recoil_lab',
         '--exclude-module','numpy','--exclude-module','cv2','--exclude-module','recoil_lab.catalog','tools/run_simple.py']
    subprocess.run(cmd,check=True,timeout=300)
    report=ROOT/'runs/simple-frozen.json';report.parent.mkdir(exist_ok=True)
    env=os.environ.copy();env['SIMPLE_SCREENSHOT']=str(ROOT/'runs/simple-windows.png')
    app=ROOT/'dist/RecoilLab-Simple.exe'
    subprocess.run([str(app),'--self-test',str(report)],env=env,check=True,timeout=45)
    result=json.loads(report.read_text(encoding='utf-8'))
    if result['status']!='PASS' or result['version']!=VERSION:raise RuntimeError('Frozen UI self-test/version failed')
    digest=hashlib.sha256(app.read_bytes()).hexdigest()
    (ROOT/'dist/RecoilLab-Simple.exe.sha256').write_text(digest+'  '+app.name+'\n',encoding='ascii')
    print(json.dumps({'sha256':digest,'version':VERSION,'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'frozen_selftest':'PASS','physical_input_tested':False,'game_tested':False}))
if __name__=='__main__':main()
