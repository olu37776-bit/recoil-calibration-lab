"""V0.8 deterministic user-workflow tests; virtual data, no hardware claims."""
import json
from unittest.mock import Mock

import numpy as np
import pytest

from recoil_lab.capture_support import capture_options, diagnostic, preflight, recovery
from recoil_lab.contracts import CalibrationError, Trial, read_json
from recoil_lab.native_session import NativeSession
from recoil_lab.product import Product
from recoil_lab.training_batch import NoMotionDesktop
from recoil_lab.workspace import Workspace
from test_catalog import config


@pytest.fixture
def lab(tmp_path):
    store = Workspace(tmp_path)
    project = store.create(config(), 'private-user-project')
    b = Mock()
    b.geometry.return_value = (0,0,*project['context']['resolution'])
    b.pid.return_value = 2
    return store, project, NativeSession(store, lambda: b), b


def payload(p, **kw):
    return {'project_id':p['id'], 'mode':'train_batch', 'hwnd':1, 'consent':True,
            'roi':[10,10,100,100], 'duration_s':.5, **kw}


@pytest.mark.parametrize('count', [0,4,True,1.5,'3',None])
def test_bad_batch_count(lab,count):
    w,p,n,b=lab
    with pytest.raises(CalibrationError): n.start(payload(p,count=count))
    b.move.assert_not_called()
    assert n.worker is None


@pytest.mark.parametrize('mode',['response','validation','execute','preview','train'])
def test_actual_output_modes_not_made_batch(lab,mode):
    w,p,n,b=lab
    with pytest.raises(CalibrationError): n.start(payload(p,mode=mode,count=2))
    assert n.worker is None


@pytest.mark.parametrize('roi',[[-1,0,100,100],[0,0,31,100],[1900,0,100,100],[0,1000,100,100],[0,0,True,100]])
def test_invalid_roi_rejected_before_worker(lab,roi):
    w,p,n,b=lab
    with pytest.raises(CalibrationError): n.start(payload(p,roi=roi))
    b.move.assert_not_called()
    assert n.worker is None


def test_preflight_has_no_side_effects(lab):
    w,p,n,b=lab
    r=preflight(n,payload(p))
    assert r['ready'] and r['input_sent'] is False and r['authorizes_output'] is False
    assert n.worker is None
    b.capture.assert_not_called();b.move.assert_not_called()
    assert not w.snapshot(p['id'])['trials']


def test_preflight_shows_all_missing_fields(lab):
    w,p,n,b=lab
    r=preflight(n,payload(p,hwnd=0,roi=None,consent=False))
    assert sum(not c['passed'] for c in r['checks']) == 3
    assert not r['ready']
    assert preflight(n,{})['checks'][0]['passed'] is False


def test_preflight_mismatch_does_not_rewrite_project(lab):
    w,p,n,b=lab
    b.geometry.return_value=(0,0,500,300)
    before=(w.directory(p['id'])/'project.json').read_bytes()
    assert not preflight(n,payload(p))['ready']
    assert before==(w.directory(p['id'])/'project.json').read_bytes()


def test_preflight_cannot_bypass_start_authorization(lab):
    w,p,n,b=lab
    assert preflight(n,payload(p))['ready']
    with pytest.raises(CalibrationError): n.start(payload(p,consent=False))
    assert n.worker is None


def test_facade_hard_stops_input():
    raw=Mock();b=NoMotionDesktop(raw)
    for value in (0,10,-10):
        with pytest.raises(CalibrationError): b.move(value,1,[640,480],2,'train')
    with pytest.raises(CalibrationError): b.triggered('response')
    raw.move.assert_not_called()
    b.capture(1,[640,480],2);raw.capture.assert_called_once()


def trial_for(p, i):
    t=np.linspace(0,.5,20);zero=np.zeros(20)
    return Trial('virtual-'+str(i),'virtual-session',p['context'],'train','recorded',t,
                 zero,-(20+i)*t,zero,np.ones(20),np.ones(20),{'method':'test-virtual-only'})


def test_batch_keeps_each_round_and_shared_origin(lab,monkeypatch):
    w,p,n,b=lab
    n._wait_batch_neutral=Mock()
    i=iter(range(3))
    n._capture=Mock(side_effect=lambda *a,**kw:trial_for(p,next(i)))
    n._train_batch(b,1,2,p,.5,[10,10,100,100],3)
    trials=w.trials(p['id'])
    assert len(trials)==3 and len({t.session_id for t in trials})==1
    assert len({t.run_id for t in trials})==3
    assert all(t.provenance['shared_capture_session'] for t in trials)
    assert n.info['completed']==3
    assert all(isinstance(a.args[0],NoMotionDesktop) for a in n._capture.call_args_list)
    b.move.assert_not_called()


def test_batch_failure_preserves_success_and_retries_only_when_requested(lab,monkeypatch):
    w,p,n,b=lab
    monkeypatch.setattr('recoil_lab.native_session.time.sleep', lambda _:None)
    n._wait_batch_neutral=Mock()
    n._capture=Mock(side_effect=[trial_for(p,0),CalibrationError('本轮提前松开')])
    n._run(b,1,2,p,'train_batch',.5,[10,10,100,100],None,3)
    assert n.info['state']=='ERROR' and n.info['completed']==1
    assert n.info['recovery']['code']=='HOLD'
    assert n._capture.call_count==2 and len(w.trials(p['id']))==1
    assert n.batch_deadline is None and n.stop_event.is_set()
    n.stop_event.clear()
    n._capture=Mock(side_effect=[trial_for(p,1),trial_for(p,2)])
    n._run(b,1,2,p,'train_batch',.5,[10,10,100,100],None,2)
    assert n.info['state']=='DONE' and len(w.trials(p['id']))==3
    # A retry is a new actual capture batch, not retroactively relabelled old data.
    assert len({t.session_id for t in w.trials(p['id'])})==2
    b.move.assert_not_called()


def test_stop_after_capture_does_not_save_incomplete_round(lab,monkeypatch):
    w,p,n,b=lab
    n._wait_batch_neutral=Mock()
    def cancelled(*a,**kw):
        n.stop_event.set()
        return trial_for(p,0)
    n._capture=cancelled
    with pytest.raises(CalibrationError):n._train_batch(b,1,2,p,.5,[10,10,100,100],3)
    assert not w.trials(p['id'])


def test_waits_for_release_all_keys_and_action_completion(lab,monkeypatch):
    w,p,n,b=lab
    ticks=iter([0,1,2,3,4,5])
    monkeypatch.setattr('recoil_lab.native_session.time.perf_counter',lambda:next(ticks))
    monkeypatch.setattr('recoil_lab.native_session.time.sleep',lambda _:None)
    b.interrupted.side_effect=[True,False,False]
    b.down.side_effect=[True,False,False,False]
    n._wait_batch_neutral(b,1,2,[1920,1080])
    assert b.check_window.call_count==3
    b.capture.assert_not_called();b.move.assert_not_called()


def test_batch_timeout_does_not_rearm(lab,monkeypatch):
    w,p,n,b=lab
    n.batch_deadline=5
    monkeypatch.setattr('recoil_lab.native_session.time.perf_counter',lambda:6)
    with pytest.raises(CalibrationError,match='120秒'):n._cancelled()


def test_held_input_never_starts_next_round(lab,monkeypatch):
    w,p,n,b=lab
    ticks=iter([0,1,2,31])
    monkeypatch.setattr('recoil_lab.native_session.time.perf_counter',lambda:next(ticks))
    monkeypatch.setattr('recoil_lab.native_session.time.sleep',lambda _:None)
    b.interrupted.return_value=False;b.down.return_value=True
    with pytest.raises(CalibrationError,match='等待'):n._wait_batch_neutral(b,1,2,[1920,1080])
    b.move.assert_not_called()


@pytest.mark.parametrize('sound',[False,True])
def test_optional_audio_does_not_control_capture(lab,sound):
    w,p,n,b=lab;n._wait_batch_neutral=Mock()
    n._capture=Mock(return_value=trial_for(p,1));b.cue.side_effect=RuntimeError('no sound')
    n._train_batch(b,1,2,p,.5,[10,10,100,100],1,sound)
    assert n.info['completed']==1 and b.cue.call_count==int(sound)
    b.move.assert_not_called()


@pytest.mark.parametrize('message,code',[
    ('焦点离开目标窗口','FOCUS'),('显示尺寸变化','GEOMETRY'),('松开使能','HOLD'),
    ('处理超过100ms','TIMING'),('30秒内未收到使能','WAIT'),('工作台心跳中断','HEARTBEAT'),
    ('急停或换弹指令','ACTION'),('Windows拒绝了输入','INPUT'),('Low-confidence','TRACKING'),
    ('C:/Users/private/secret.txt: some unknown exception','OTHER')])
def test_readable_recovery(message,code):
    r=recovery(message)
    assert r['code']==code and r['retry_automatic'] is False
    assert 'private' not in json.dumps(r)


def test_diagnostic_whitelists_fields(lab):
    w,p,n,b=lab
    n.info={'state':'ERROR','mode':'train_batch','completed':1,'message':'C:/Users/private/password.txt unknown',
            'hwnd':123,'preview':{'image':'secret pixels'},'selected_project':'sensitive'}
    r=diagnostic(n,p['id']);text=json.dumps(r)
    for sensitive in ['password','private','secret pixels','hwnd','sensitive',p['id']]:assert sensitive not in text
    assert r['recovery']['code']=='OTHER' and r['project']['trial_count']==0


def test_support_routes_return_no_execution_grant(tmp_path):
    product=Product(tmp_path)
    p=product.handle({'action':'create','name':'case','preset':config()})
    r=product.handle({'action':'preflight',**payload(p,hwnd=0)})
    assert not r['ready'] and not r['authorizes_output']
    r=product.handle({'action':'diagnostic','project_id':p['id']})
    assert r['version']=='0.8.0-rc1'
    assert product.native.worker is None
