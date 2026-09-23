"""Build, run and hash the exact portable Windows artifact; no cross-compile claim."""
from pathlib import Path
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    if platform.system()!='Windows':raise SystemExit('Windows打包必须在Windows执行')
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir',
        '--name','RecoilLab','--collect-data','recoil_lab','--collect-all','cv2',
        str(ROOT/'tools/run_app.py')],cwd=ROOT,check=True,timeout=600)
    folder=ROOT/'dist'/'RecoilLab';evidence=ROOT/'runs'/'packaged-self-test.json'
    subprocess.run([str(folder/'RecoilLab.exe'),'--self-test',str(evidence)],cwd=ROOT,check=True,timeout=90)
    report=json.loads(evidence.read_text(encoding='utf-8'))
    if not report['frozen'] or report['status']!='PASS':raise RuntimeError('打包程序未通过自检')
    (folder/'READ-ME-FIRST.txt').write_text(
        'Recoil Calibration Lab 0.6 RC1\n\n解压整个文件夹后双击 RecoilLab.exe；不要只复制EXE。\n'
        '不需要安装Python。默认打开本机浏览器；程序窗口关闭即退出。\n'
        '先点“一键跑完整演示”检查流程；演示数据不能启用真实输出。\n'
        '真实采集/验证/执行须由用户明确授权，并仅限允许的受控环境。\n'
        '第05页教识别并验证；负重只是手动标签，不内置补偿系数。\n'
        'F7+右键+左键：监督输出；F8/Esc：急停；响应采集只按F7+右键，不开枪。\n'
        '不是全自动游戏状态识别器，不保证WARDOGS允许或接受输入；不绕过任何拦截。\n'
        '此程序未签名。不要关闭安全软件或以管理员运行来绕过拦截。\n'
        '数据只保存在 %LOCALAPPDATA%\\RecoilCalibrationLab 。\n',encoding='utf-8-sig')
    manifest={'version':'0.7.0-rc1','commit':os.environ.get('GITHUB_SHA','local'),
              'platform':platform.platform(),'self_test':report,'game_tested':False,'hardware_tested':False}
    (folder/'build-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    name='RecoilLab-0.7.0-rc1-Windows-x64'
    archive=Path(shutil.make_archive(str(ROOT/'dist'/name),'zip',folder.parent,folder.name))
    sha=hashlib.sha256(archive.read_bytes()).hexdigest()
    (archive.parent/(name+'.sha256')).write_text(f'{sha}  {archive.name}\n',encoding='ascii')
    print(archive,sha,flush=True)


if __name__=='__main__':main()
