import base64
import json
from io import BytesIO
import threading
import urllib.error
import urllib.request
import zipfile
import pytest
from recoil_lab.ui import LabServer, process
from recoil_lab.contracts import CalibrationError
from test_catalog import config
from test_screenshots import texture, encoded, sequence_data


def test_pattern_route():
    r=process('/api/pattern',dict(preset=config(),image=encoded(texture()),aim=[10,10],points=[[20,20]]))
    assert r['kind']=='static_pattern' and r['can_fit_time_curve'] is False


def test_sequence_export():
    images,times=sequence_data()
    r=process('/api/sequence',dict(preset=config(),images=images,timestamps=times,roi=[30,30,240,170],capture_session='test-session',uncompensated=True))
    assert r['samples']==12
    with zipfile.ZipFile(BytesIO(base64.b64decode(r['zip_base64']))) as z:
        assert sorted(z.namelist())==['trial.csv','trial.json']
        assert json.loads(z.read('trial.json'))['context']['weapon']=='galil'


@pytest.mark.parametrize('path,payload',[('/api/preset',[]),('/api/nope',{'preset':config()}),('/api/pair',{'preset':config(),'stationary':False})])
def test_route_rejection(path,payload):
    with pytest.raises(CalibrationError):process(path,payload)


def test_local_server_tokens_and_assets():
    with LabServer(0) as server:
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        root='http://127.0.0.1:'+str(server.server_port)
        try:
            with urllib.request.urlopen(root+'/') as r:
                assert '选配装'.encode() in r.read()
                assert "frame-ancestors 'none'" in r.headers['Content-Security-Policy']
            with urllib.request.urlopen(root+'/api/catalog') as r:assert len(json.load(r)['weapons'])==14
            req=urllib.request.Request(root+'/api/preset',data=json.dumps(config()).encode(),headers={'Content-Type':'application/json'})
            with pytest.raises(urllib.error.HTTPError) as e:urllib.request.urlopen(req)
            assert e.value.code==403
            req.add_header('X-Lab-Token',server.token)
            with urllib.request.urlopen(req) as r:assert json.load(r)['calibration_status']=='UNMEASURED'
            req=urllib.request.Request(root+'/api/bootstrap',headers={'Host':'evil.invalid'})
            with pytest.raises(urllib.error.HTTPError) as e:urllib.request.urlopen(req)
            assert e.value.code==403
            for path in ['/style.css','/app.js']:
                with urllib.request.urlopen(root+path) as r:assert len(r.read())>100
            with pytest.raises(urllib.error.HTTPError) as e:urllib.request.urlopen(root+'/../../etc/passwd')
            assert e.value.code==404
        finally:
            server.shutdown();thread.join(timeout=3)
