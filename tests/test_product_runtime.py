import ctypes
import json
import time
import threading
import urllib.request
import urllib.error

import numpy as np
import pytest

from recoil_lab.contracts import CalibrationError
from recoil_lab.desktop import INPUT, MOUSEINPUT, WindowsDesktop
from recoil_lab.native_session import NativeSession
from recoil_lab.workspace import Workspace
from recoil_lab.ui import LabServer
from recoil_lab.app import self_test
from test_catalog import config


def test_input_layout_not_platform_long_width():
    assert ctypes.sizeof(INPUT)==(40 if ctypes.sizeof(ctypes.c_void_p)==8 else 28)
    event=INPUT(type=0,mi=MOUSEINPUT(0,12,0,1,0,0))
    assert event.type==0 and event.mi.dx==0 and event.mi.dy==12
    assert event.mi.dwFlags==1  # movement only, never left-click flags


def test_non_windows_reject(monkeypatch):
    monkeypatch.setattr('recoil_lab.desktop.platform.system',lambda:'Linux')
    with pytest.raises(CalibrationError,match='Windows'):WindowsDesktop()


def test_native_explicit_consent_and_synthetic_guard(tmp_path):
    w=Workspace(tmp_path); n=NativeSession(w)
    with pytest.raises(CalibrationError,match='授权'):n.start({})
    with pytest.raises(CalibrationError,match='模式'):n.start({'consent':True,'mode':'hack'})
    p=w.demo()
    with pytest.raises(CalibrationError,match='合成'):n.start({'consent':True,'mode':'preview','project_id':p['id']})
    p=w.create(config(),'native')
    common={'consent':True,'mode':'train','project_id':p['id'],'hwnd':1}
    for extra in ({'duration_s':100},{'duration_s':float('nan')},{'hwnd':0},{'roi':[1,2,3]}):
        with pytest.raises(CalibrationError):n.start({**common,**extra})
    assert n.status()['state']=='IDLE'


def test_native_stop_and_heartbeat(tmp_path):
    n=NativeSession(Workspace(tmp_path))
    n.last_client=time.monotonic()-6
    with pytest.raises(CalibrationError,match='心跳'):n._cancelled()
    n.status();n._cancelled()
    n.stop()
    with pytest.raises(CalibrationError,match='停止'):n._cancelled()


def test_native_focus_fail_never_emits(tmp_path,profile):
    class Fake:
        moves=[]
        def check(self,*a):raise CalibrationError('focus lost')
        def move(self,*a):self.moves.append(a)
    b=Fake(); n=NativeSession(Workspace(tmp_path))
    with pytest.raises(CalibrationError,match='focus'):
        n._execute(b,1,2,profile.context,profile)
    assert not b.moves


def test_native_no_fresh_release_never_outputs(tmp_path,profile):
    class Fake:
        moves=[]; calls=0
        def check(self,*a):
            self.calls+=1
            if self.calls>5:raise CalibrationError('end of test')
        def down(self,k):return True
        def triggered(self,*a):return True
        def move(self,*a):self.moves.append(a)
    b=Fake(); n=NativeSession(Workspace(tmp_path))
    with pytest.raises(CalibrationError):n._execute(b,1,2,profile.context,profile)
    assert not b.moves


def test_native_emits_then_release_stops(tmp_path,profile,monkeypatch):
    clock=[10.]
    def tick():clock[0]+=.02;return clock[0]
    monkeypatch.setattr('recoil_lab.native_session.time.perf_counter',tick)
    monkeypatch.setattr('recoil_lab.native_session.time.sleep',lambda _:None)
    class Fake:
        moves=[]; calls=0
        def check(self,*a):
            self.calls+=1
            if self.calls>12:raise CalibrationError('end')
        def down(self,k):return 2<=self.calls<=7
        def triggered(self,*a):return self.down(1)
        def move(self,*a):self.moves.append((self.calls,a[0]))
    b=Fake();n=NativeSession(Workspace(tmp_path))
    with pytest.raises(CalibrationError):n._execute(b,1,2,profile.context,profile)
    assert b.moves and all(2<=c<=7 for c,_ in b.moves)


def test_threaded_http_idle_connection_and_origin(tmp_path):
    import socket
    with LabServer(0,data_directory=tmp_path) as s:
        t=threading.Thread(target=s.serve_forever,daemon=True);t.start()
        idle=socket.create_connection(('127.0.0.1',s.server_port),timeout=2)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        root='http://127.0.0.1:'+str(s.server_port)
        try:
            with opener.open(root+'/workbench.html',timeout=3) as r:assert '工作台'.encode() in r.read()
            req=urllib.request.Request(root+'/api/product',data=json.dumps({'action':'environment'}).encode(),headers={'Content-Type':'application/json','X-Lab-Token':s.token})
            with opener.open(req,timeout=3) as r:assert json.load(r)['version']=='0.8.0-rc1'
            req.add_header('Origin','https://foreign.invalid')
            with pytest.raises(urllib.error.HTTPError) as e:opener.open(req,timeout=3)
            assert e.value.code==403
        finally:idle.close();s.shutdown();t.join(5)


def test_executable_self_test(tmp_path):
    p=tmp_path/'result.json'; self_test(p)
    r=json.loads(p.read_text())
    assert r['status']=='PASS' and r['mouse_output_tested'] is False
