"""Run every test file with a hard process deadline and preserve the last output."""
from pathlib import Path
import json
import os
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


def main():
    out=ROOT/'runs'/'bounded';out.mkdir(parents=True,exist_ok=True)
    report=[];env=dict(os.environ,PYTHONUNBUFFERED='1',NO_PROXY='127.0.0.1,localhost',no_proxy='127.0.0.1,localhost')
    for file in sorted((ROOT/'tests').glob('test_*.py')):
        name=file.stem;log=out/(name+'.log');start=time.monotonic()
        command=[sys.executable,'-m','pytest','-vv','-s',str(file),'-o','faulthandler_timeout=45',f'--junitxml={out/name}.xml']
        print('START',name,flush=True)
        # A log file survives process termination; nothing waits for buffered PIPE output.
        with log.open('w',encoding='utf-8') as handle:
            proc=subprocess.Popen(command,cwd=ROOT,env=env,stdout=handle,stderr=subprocess.STDOUT)
            try:code=proc.wait(timeout=90)
            except subprocess.TimeoutExpired:
                proc.kill();proc.wait(timeout=10);code=124
        text=log.read_text(encoding='utf-8',errors='replace');print(text,flush=True)
        report.append({'test_file':name,'exit_code':code,'seconds':round(time.monotonic()-start,2),'log':log.name})
        (out/'summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        if code: return code
    return 0


if __name__=='__main__':raise SystemExit(main())
