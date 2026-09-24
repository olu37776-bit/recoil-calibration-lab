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
    if (result['status']!='PASS' or result['version']!=VERSION or result.get('default_entrypoint')!='PanelApplication' or
        not {'quick_restart_keeps_settings_not_permission','guide_restart_keeps_parameter_not_authorization', 'guide_failed_start_visible_in_prepare', 'guide_footer_visible_all_steps_820x580', 'daily_restart_recovers_preferences_not_permission', 'prepare_listens_without_five_seconds_or_output', 'panel_auto_ready_no_prepare_no_checkbox', 'panel_home_and_config_identical_single_key', 'panel_restart_restores_selection_auto_ready_but_off', 'panel_case_padded_caption_auto_ready_off', 'panel_padded_caption_combobox_selection_succeeds_without_output', 'panel_restart_padded_caption_rule_remains_off', 'panel_real_win32_padded_caption_enumeration'}.issubset(result.get('checks',[]))):raise RuntimeError('Frozen UI self-test/version failed')
    digest=hashlib.sha256(app.read_bytes()).hexdigest()
    (ROOT/'dist/RecoilLab-Simple.exe.sha256').write_text(digest+'  '+app.name+'\n',encoding='ascii')
    print(json.dumps({'sha256':digest,'version':VERSION,'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'frozen_selftest':'PASS','physical_input_tested':False,'game_tested':False}))
if __name__=='__main__':main()
