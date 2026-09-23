import copy
import numpy as np
import pytest
from recoil_lab.hud import compare_hud
from recoil_lab.contracts import CalibrationError
from test_screenshots import encoded


def payload():
    rng=np.random.default_rng(50)
    a=rng.integers(0,255,(80,100,3),dtype=np.uint8)
    b=rng.integers(0,255,(80,100,3),dtype=np.uint8)
    q=np.clip(a.astype(float)+rng.normal(0,1,a.shape),0,255).astype(np.uint8)
    return {'field':'pose','layout_id':'synthetic-hud-v1','roi':[8,8,30,30],
        'image':encoded(q),'references':[
            {'label':'standing','layout_id':'synthetic-hud-v1','image':encoded(a)},
            {'label':'crouching','layout_id':'synthetic-hud-v1','image':encoded(b)}]}


def test_candidate_not_automatic_permission():
    r=compare_hud(payload())
    assert r['label']=='standing' and r['reason']=='CANDIDATE'
    assert r['score']>.9 and not r['self_match']
    assert r['auto_execution_eligible'] is False and r['game_verified'] is False
    assert not r['score_is_probability']


def test_low_texture():
    p=payload();p['image']=encoded(np.zeros((80,100,3),dtype=np.uint8))
    r=compare_hud(p);assert r['label']=='unknown' and r['reason']=='LOW_TEXTURE'


def test_unseen_state_not_forced_to_nearest():
    p=payload();p['image']=encoded(np.random.default_rng(8).integers(0,255,(80,100,3),dtype=np.uint8))
    assert compare_hud(p)['reason']=='LOW_SIMILARITY'


def test_ambiguous_states():
    p=payload();p['references'][1]['image']=p['image']
    assert compare_hud(p)['reason']=='AMBIGUOUS'


@pytest.mark.parametrize('change',[
    {'field':'weapon'}, {'field':[]}, {'layout_id':''}, {'references':[]},
    {'threshold':.1}, {'margin':0}, {'threshold':float('nan')},
    {'roi':[0,0,4,4]},{'roi':[0,0,1000,50]}, {'roi':[0,0,20.5,20]},
])
def test_bad_request(change):
    p=payload();p.update(change)
    with pytest.raises(CalibrationError):compare_hud(p)


def test_layout_mismatch():
    p=payload();p['references'][0]['layout_id']='another'
    with pytest.raises(CalibrationError):compare_hud(p)


def test_same_photo_cannot_mean_two_states():
    p=payload();p['references'][1]['image']=p['references'][0]['image']
    with pytest.raises(CalibrationError):compare_hud(p)


def test_dimension_mismatch_and_blank_reference():
    p=payload();p['references'][1]['image']=encoded(np.zeros((81,100,3),dtype=np.uint8))
    with pytest.raises(CalibrationError):compare_hud(p)
    p=payload();p['references'][1]['image']=encoded(np.zeros((80,100,3),dtype=np.uint8))
    with pytest.raises(CalibrationError):compare_hud(p)


def test_duplicate_labels_and_unknown_label():
    for label in ['standing','wrong']:
        p=payload();p['references'][1]['label']=label
        with pytest.raises(CalibrationError):compare_hud(p)


def test_self_match_is_disclosed():
    p=payload();p['image']=p['references'][0]['image']
    assert compare_hud(p)['self_match'] is True
