"""Loopback-only UI with authenticated, opt-in product session routes."""
from __future__ import annotations

import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import secrets
import tempfile
from urllib.parse import urlsplit
import zipfile

from .catalog import public_catalog, build_preset
from .hud import compare_hud
from .adaptive_hud import compare_adaptive, compare_sequence
from .state_demo import run_state_demo
from .contracts import CalibrationError, canonical, save_trial
from .screenshots import decode_image, pattern_summary, pair_displacement, screenshot_sequence

MAX_BODY=32*1024*1024
STATIC=Path(__file__).parent/"web"


def process(path: str, payload: dict) -> dict:
    if not isinstance(payload,dict):
        raise CalibrationError("请求必须是 JSON 对象")
    if path=="/api/hud-adaptive":
        return compare_adaptive(payload)
    if path=="/api/hud-sequence":
        return compare_sequence(payload)
    if path=="/api/state-demo":
        return run_state_demo(payload)
    if path=="/api/hud-compare":
        return compare_hud(payload)
    if path=="/api/preset":
        return build_preset(payload)
    preset=build_preset(payload.get("preset",{}))
    context=preset["context"]
    if path=="/api/pattern":
        image,hashed=decode_image(payload.get("image"))
        return pattern_summary(image,payload.get("aim"),payload.get("points"),hashed,context)
    if path=="/api/pair":
        if payload.get("stationary") is not True:
            raise CalibrationError("请确认两张图来自同一静态场景、未移动或切换倍率")
        before,h1=decode_image(payload.get("before"))
        after,h2=decode_image(payload.get("after"))
        return pair_displacement(before,after,payload.get("roi"),context,[h1,h2])
    if path=="/api/sequence":
        trial=screenshot_sequence(payload.get("images"),payload.get("timestamps"),roi=payload.get("roi"),
            context=context,run_id=payload.get("run_id","screenshot-burst"),
            capture_session=payload.get("capture_session",""),uncompensated=payload.get("uncompensated"))
        # Temporary files contain only measured numeric trajectories, never raw images.
        with tempfile.TemporaryDirectory(prefix="recoil-lab-") as folder:
            path=Path(folder)/"trial.json"
            save_trial(path,trial)
            output=BytesIO()
            with zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED) as z:
                for item in sorted(Path(folder).iterdir()):
                    z.write(item,item.name)
        return {"kind":"timed_sequence","context_id":trial.context_hash,"samples":len(trial.t_s),
                "duration_s":float(trial.t_s[-1]),"min_confidence":float(trial.confidence.min()),
                "can_fit_time_curve":True,"requires":"independent input-response calibration and repeated training trials",
                "zip_base64":base64.b64encode(output.getvalue()).decode("ascii")}
    raise CalibrationError("未知分析入口")


class LabServer(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=True
    def __init__(self,port: int=8765, data_directory: Path | None = None):
        super().__init__(("127.0.0.1",port),Handler)
        self.token=secrets.token_urlsafe(32)
        self.data_directory=data_directory
        self.product=None
        import threading
        self.product_lock=threading.Lock()

    def product_service(self):
        with self.product_lock:
            if self.product is None:
                from .product import Product
                self.product=Product(self.data_directory)
        return self.product


class Handler(BaseHTTPRequestHandler):
    server: LabServer
    def log_message(self,format,*args):
        pass  # No filenames, image payloads or personal settings in access logs.

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def local_request(self) -> bool:
        expected={f"127.0.0.1:{self.server.server_port}",f"localhost:{self.server.server_port}"}
        origin=self.headers.get("Origin")
        return self.headers.get("Host") in expected and (origin is None or origin in {"http://"+h for h in expected})

    def respond(self,status: int,data: bytes,content_type: str):
        self.send_response(status)
        self.send_header("Content-Type",content_type)
        self.send_header("Content-Length",str(len(data)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Security-Policy","default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(data)

    def json_reply(self,status: int,value: dict):
        self.respond(status,canonical(value).encode(),"application/json; charset=utf-8")

    def do_GET(self):
        if not self.local_request():
            return self.json_reply(403,{"error":"仅允许本机访问"})
        path=urlsplit(self.path).path
        if path=="/api/bootstrap":
            return self.json_reply(200,{"token":self.server.token})
        if path=="/api/catalog":
            return self.json_reply(200,public_catalog())
        files={"/capture-help.js":("capture-help.js","text/javascript"),"/guided.js":("guided.js","text/javascript"),"/guided.css":("guided.css","text/css"),"/teaching-ui.js":("teaching-ui.js","text/javascript"),"/workbench.html":("workbench.html","text/html"),"/workbench.js":("workbench.js","text/javascript"),"/workbench.css":("workbench.css","text/css"),"/adaptive.html":("adaptive.html","text/html"),"/adaptive.js":("adaptive.js","text/javascript"),"/state.html":("state.html","text/html"),"/state.js":("state.js","text/javascript"),"/":("index.html","text/html"),"/app.js":("app.js","text/javascript"),"/style.css":("style.css","text/css")}
        if path not in files:
            return self.json_reply(404,{"error":"不存在"})
        name,mime=files[path]
        self.respond(200,(STATIC/name).read_bytes(),mime+"; charset=utf-8")

    def do_POST(self):
        if not self.local_request() or self.headers.get("X-Lab-Token")!=self.server.token:
            return self.json_reply(403,{"error":"本地请求验证失败，请刷新页面"})
        if self.headers.get("Content-Type","").split(";")[0]!="application/json":
            return self.json_reply(415,{"error":"仅接受 JSON"})
        if self.headers.get("Transfer-Encoding"):
            return self.json_reply(400,{"error":"不支持流式请求体"})
        try:
            size=int(self.headers.get("Content-Length","0"))
            if not 0<size<=MAX_BODY:
                return self.json_reply(413,{"error":"请求体须介于 1 字节与 32 MiB"})
            self.connection.settimeout(15)
            payload=json.loads(self.rfile.read(size))
            path=urlsplit(self.path).path
            result=self.server.product_service().handle(payload) if path=="/api/product" else process(path,payload)
            return self.json_reply(200,result)
        except (CalibrationError,ValueError,TypeError,KeyError,OSError) as exc:
            return self.json_reply(400,{"error":str(exc)})
        except Exception:
            return self.json_reply(500,{"error":"分析失败；请检查图片、可选依赖和运行环境"})


def main():
    p=argparse.ArgumentParser(description="本地中文选枪与截图分析界面")
    p.add_argument("--port",type=int,default=8765)
    args=p.parse_args()
    with LabServer(args.port) as server:
        print(f"Recoil Calibration Lab: http://127.0.0.1:{server.server_port}",flush=True)
        print("仅本机；图片不写入仓库；Ctrl+C 退出；鼠标输出默认关闭。",flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__=="__main__":
    main()
