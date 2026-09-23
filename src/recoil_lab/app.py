"""Desktop entry point and packaged-program self-test."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import sys
import threading
import urllib.request
import webbrowser

from .desktop import dpi_awareness, INPUT
from .ui import LabServer
from .workspace import data_home


def self_test(output: Path) -> None:
    import ctypes
    from tempfile import TemporaryDirectory
    from .product import Product
    with TemporaryDirectory() as td, LabServer(0, data_directory=Path(td)) as server:
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        root=f'http://127.0.0.1:{server.server_port}'
        try:
            for page in ('/workbench.html','/workbench.js','/teaching-ui.js','/guided.js','/guided.css','/capture-help.js','/api/catalog'):
                with opener.open(root+page,timeout=5) as response:
                    if response.status!=200 or not response.read(): raise RuntimeError('本机HTTP自检失败')
            result=Product(Path(td)/'demo').handle({'action':'demo'})
            report=[p['report'] for p in result['profiles'] if p['id']==result['active_profile']][0]
            if not report['passed']: raise RuntimeError('核心算法自检失败')
        finally:
            server.shutdown();thread.join(5)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({'status':'PASS','version':'0.8.0-rc1','platform':platform.platform(),
        'frozen':bool(getattr(sys,'frozen',False)), 'input_abi_bytes':ctypes.sizeof(INPUT),
        'http_and_synthetic_pipeline':True,'mouse_output_tested':False,'game_tested':False},indent=2),encoding='utf-8')


def main() -> int:
    parser=argparse.ArgumentParser(description='Recoil Calibration Lab 本机工作台')
    parser.add_argument('--port',type=int,default=0)
    parser.add_argument('--data-dir',type=Path)
    parser.add_argument('--headless',action='store_true')
    parser.add_argument('--self-test',type=Path)
    args=parser.parse_args()
    dpi_awareness()
    if args.self_test:
        self_test(args.self_test);return 0
    try:
        with LabServer(args.port,data_directory=args.data_dir) as server:
            url=f'http://127.0.0.1:{server.server_port}/workbench.html'
            print(f'本机工作台：{url}\n默认不输出。F7使能；F8/Esc急停。关闭本窗口退出。',flush=True)
            if not args.headless:
                threading.Timer(.5,lambda:webbrowser.open(url)).start()
            try: server.serve_forever()
            except KeyboardInterrupt: pass
            finally:
                if server.product is not None: server.product.native.stop()
        return 0
    except Exception as exc:
        log=data_home()/'startup-error.txt';log.parent.mkdir(parents=True,exist_ok=True)
        log.write_text(str(exc),encoding='utf-8')
        print(f'启动失败：{exc}\n诊断：{log}',file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
