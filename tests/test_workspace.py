from pathlib import Path
from io import BytesIO
import base64
import json
import zipfile

import pytest

from recoil_lab.workspace import Workspace, safe_id
from recoil_lab.contracts import CalibrationError, read_json, write_json
from recoil_lab.product import Product
from test_catalog import config


def test_complete_demo_persistent_export_and_rollback(tmp_path):
    w=Workspace(tmp_path)
    state=w.demo(); ident=state['id']
    assert len(state['trials'])==11
    assert len(state['profiles'])==2
    report=[v['report'] for v in state['profiles'] if v['id']==state['active_profile']][0]
    assert report['passed'] and report['evidence_kind']=='SIMULATED_REPLAY'
    assert state['game_verified'] is False and state['curve']['t_s'][0]==0
    assert Workspace(tmp_path).snapshot(ident)['active_profile']==state['active_profile']
    assert w.list()[0]['id']==ident
    with pytest.raises(CalibrationError,match='合成'): w.execution_profile(ident)
    initial=[v for v in state['profiles'] if v['parent_id'] is None][0]
    assert w.select(ident,initial['id'])['active_profile']==initial['id']
    data=w.export(ident)
    with zipfile.ZipFile(BytesIO(base64.b64decode(data['zip_base64']))) as z:
        assert 'project.json' in z.namelist()
        assert 'recorded-preview.json' in z.namelist()
        assert all(not n.endswith('.png') for n in z.namelist())


def test_backend_isolation(tmp_path):
    w=Workspace(tmp_path)
    p=w.create(config(),'实际项目')
    assert p['context']['input_backend']=='windows-sendinput-v1'
    assert not p['demo'] and p['response'] is None
    with pytest.raises(CalibrationError):w.profile(p['id'])
    from recoil_lab.demo import response_trial
    with pytest.raises(CalibrationError):w.add(p['id'],response_trial(1))


@pytest.mark.parametrize('value',['..','/tmp','a/b','a\\b','a.json','',None,123])
def test_no_project_path_injection(value):
    with pytest.raises(CalibrationError): safe_id(value)


@pytest.mark.parametrize('name',['', ' '*3, 'x'*81, None])
def test_names_rejected(tmp_path,name):
    with pytest.raises(CalibrationError):Workspace(tmp_path).create(config(),name)


def test_duplicate_and_train_validation_leakage(tmp_path):
    w=Workspace(tmp_path); p=w.demo(); ident=p['id']
    run=w.trials(ident,phase='train')[0]
    with pytest.raises(CalibrationError,match='重复'):w.add(ident,run)
    before=len(w.snapshot(ident)['trials'])
    run.run_id='renamed';run.session_id='another-name'
    with pytest.raises(CalibrationError,match='重复'):w.add(ident,run)
    assert len(w.snapshot(ident)['trials'])==before


def zip64(entries):
    b=BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        for k,v in entries.items():z.writestr(k,v)
    return base64.b64encode(b.getvalue()).decode()


@pytest.mark.parametrize('entry',['../evil.json','a/b.json','a\\b.json','file.exe','.json'])
def test_reject_bad_archive_paths(tmp_path,entry):
    w=Workspace(tmp_path); p=w.create(config(),'test')
    with pytest.raises(CalibrationError):w.import_trials(p['id'],zip64({entry:'{}'}))
    assert w.snapshot(p['id'])['trials']==[]


def test_invalid_archives(tmp_path):
    w=Workspace(tmp_path); p=w.create(config(),'test')
    for value in ('!!!','AAAA',zip64({'a.csv':'wrong'})):
        with pytest.raises(CalibrationError):w.import_trials(p['id'],value)


def test_product_routing_and_no_output(tmp_path):
    app=Product(tmp_path)
    env=app.handle({'action':'environment'})
    assert env['game_verified'] is False
    assert app.handle({'action':'status'})['state']=='IDLE'
    assert app.handle({'action':'stop'})['state']=='IDLE'
    with pytest.raises(CalibrationError):app.handle({'action':'not-found'})
    with pytest.raises(CalibrationError):app.handle([])
    p=app.handle({'action':'create','name':'demo name','preset':config()})
    assert app.handle({'action':'open','project_id':p['id']})['id']==p['id']


def test_corrupt_project_not_in_list(tmp_path):
    (tmp_path/'bad').mkdir();(tmp_path/'bad/project.json').write_text('bad')
    assert Workspace(tmp_path).list()==[]


def test_native_candidate_validation_sets_stay_separate(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import recoil_lab.workspace as module
    w=Workspace(tmp_path);state=w.demo();ident=state['id']
    active=state['active_profile']
    trials=[SimpleNamespace(provenance={'candidate_id':active}),
            SimpleNamespace(provenance={'candidate_id':'older-profile'}),
            SimpleNamespace(provenance={})]
    monkeypatch.setattr(w,'trials',lambda *args:trials)
    received=[]
    def validate(profile, rows):
        received.extend(rows);return {'profile_id':profile.profile_id,'passed':False}
    monkeypatch.setattr(module,'validate_profile',validate)
    w.validate(ident)
    assert received == [trials[0],trials[2]]
