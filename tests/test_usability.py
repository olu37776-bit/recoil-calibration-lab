from copy import deepcopy
import pytest
from recoil_lab.usability import progress, preferences
from recoil_lab.contracts import CalibrationError
from recoil_lab.workspace import Workspace
from test_catalog import config


def sample():
    return {'demo': False, 'trials': [], 'profiles': [], 'response': None, 'active_profile': None}


def rows(phase, n, candidate=None):
    return [{'source': 'recorded', 'phase': phase, 'run_id': phase+str(i), 'candidate_id': candidate} for i in range(n)]


def test_guided_steps():
    p=sample();assert progress(p)['step']=='record_response'
    p['trials']+=rows('response',2);assert progress(p)['step']=='response'
    p['response']={'gain':1};assert progress(p)['step']=='record_train'
    p['trials']+=rows('train',3);assert progress(p)['step']=='fit'
    p['profiles']=[{'id':'new','source':'recorded','report':None}];p['active_profile']='new'
    assert progress(p)['step']=='record_validation'
    p['trials']+=rows('validation',3,'old')
    assert progress(p)['counts']['validation_current']==0
    p['trials']+=rows('validation',3,'new');assert progress(p)['step']=='validate'
    p['profiles'][0]['report']={'passed':True,'evidence_kind':'RECORDED_REPLAY','measured_replay_pass':True}
    assert progress(p)['step']=='ready'
    assert progress(p)['automatic_permission'] is False


@pytest.mark.parametrize('report',[{}, {'passed':True}, {'passed':True,'evidence_kind':'MODEL_PREDICTION'}, {'passed':True,'evidence_kind':'RECORDED_REPLAY','measured_replay_pass':False}])
def test_no_display_ready_from_incomplete_proof(report):
    p=sample();p.update(response={},active_profile='x',profiles=[{'id':'x','source':'recorded','report':report}]);p['trials']=rows('response',2)+rows('train',3)
    assert not progress(p)['can_request_execution']


def test_actual_demo_is_not_ready(tmp_path):
    p=Workspace(tmp_path).demo()
    assert p['workflow']['step']=='demo'
    assert not p['workflow']['can_request_execution']
    assert p['workflow']['rollback_ids']==[]


def test_snapshot_is_read_only(tmp_path):
    w=Workspace(tmp_path);p=w.create(config(),'my config')
    assert w.snapshot(p['id'])['workflow']['counts']['response']==0
    assert len(list((w.directory(p['id'])/'profiles').glob('*')))==0


def test_preferences_survive_new_instance_and_do_not_authorize(tmp_path):
    preferences(tmp_path,{'last_project_id':'abc','weight_label':'重装'})
    assert preferences(tmp_path)['last_project_id']=='abc'
    with pytest.raises(CalibrationError):preferences(tmp_path,{'consent':True})
    with pytest.raises(CalibrationError):preferences(tmp_path,{'hwnd':23})
    with pytest.raises(CalibrationError):preferences(tmp_path,{'output_enabled':True})


@pytest.mark.parametrize('value',[True,0,-1,float('inf'),'2'])
def test_preferences_reject_invalid_settings(tmp_path,value):
    settings={'dpi':800,'sensitivity':1,'ads_sensitivity':1,'zoom':1.5,'resolution':[1920,1080],'fov':90,'game_build':'test'}
    settings['dpi']=value
    with pytest.raises(CalibrationError):preferences(tmp_path,{'settings':settings})


def test_settings_store_and_corruption_recovery(tmp_path):
    s={'dpi':800,'sensitivity':1,'ads_sensitivity':1,'zoom':1.5,'resolution':[1920,1080],'fov':90,'game_build':'test'}
    preferences(tmp_path,{'settings':s});assert preferences(tmp_path)['settings']==s
    (tmp_path/'ui-preferences.json').write_text('{')
    assert preferences(tmp_path)=={}


def test_failed_candidate_exposes_approved_rollback():
    p=sample();p['trials']=rows('response',2)+rows('train',3);p['response']={'x':1}
    p['active_profile']='bad'
    p['profiles']=[{'id':'good','source':'recorded','report':{'passed':True,'evidence_kind':'RECORDED_REPLAY','measured_replay_pass':True}}, {'id':'bad','source':'recorded','report':{'passed':False}}]
    before=deepcopy(p)
    assert progress(p)['step']=='review' and progress(p)['rollback_ids']==['good']
    assert p==before
