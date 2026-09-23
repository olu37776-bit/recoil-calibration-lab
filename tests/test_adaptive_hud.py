import copy
import cv2
import numpy as np
import pytest

from recoil_lab.adaptive_hud import AdaptiveHUD, compare_adaptive, compare_sequence, _axis
from recoil_lab.contracts import CalibrationError
from test_screenshots import encoded


def icon(seed):
    rng = np.random.default_rng(seed)
    patch = cv2.resize(rng.integers(30, 230, (12, 12), dtype=np.uint8), (36, 36), interpolation=cv2.INTER_NEAREST)
    return np.repeat(patch[:, :, None], 3, axis=2)


def canvas(width=640, height=360, scale=1., seed=1, shift=(0, 0), blank=False):
    image = np.full((height, width, 3), 45, dtype=np.uint8)
    size = round(36*scale)
    x, y = width-round(64*scale)+shift[0], height-round(64*scale)+shift[1]
    if not blank:
        image[y:y+size, x:x+size] = cv2.resize(icon(seed), (size, size), interpolation=cv2.INTER_LINEAR)
    return image, [x, y, size, size]


def payload(width=640, height=360, scale=1., seed=1, shift=(0, 0)):
    refs = []
    for i, label in [(1, 'standing'), (2, 'crouching')]:
        a, roi = canvas(seed=i)
        refs.append({'label': label, 'image': encoded(a), 'layout_id': 'synthetic-v4', 'roi': roi})
    a, _ = canvas(width, height, scale, seed, shift)
    a[0, 0] = 255  # Independent synthetic image; not an identical reference.
    return {'field': 'pose', 'layout_id': 'synthetic-v4', 'references': refs, 'image': encoded(a)}


@pytest.mark.parametrize('width,height,scale', [(640,360,1), (1280,720,2), (1920,1080,3), (860,360,1), (800,450,1.25)])
def test_adaptive_locates_scaled_or_wide_hud(width,height,scale):
    p = payload(width,height,scale,shift=(4,-3))
    r = compare_adaptive(p)
    assert r['label'] == 'standing', r
    assert r['anchor'] == ['end','end']
    assert r['query_size'] == [width,height]
    _, target = canvas(width,height,scale,shift=(4,-3))
    assert np.max(np.abs(np.array(r['roi']) - target)) <= 2
    assert not r['game_verified'] and not r['auto_execution_eligible']
    assert not r['score_is_probability'] and not r['self_match']


@pytest.mark.parametrize('width,height,scale', [(1280,720,2/3), (1920,1080,1), (2560,1440,4/3), (3840,2160,2), (3440,1440,4/3)])
def test_native_1080_references_across_resolutions(width,height,scale):
    p = payload()
    for i, ref in enumerate(p['references'], 1):
        a, roi = canvas(1920,1080,1,seed=i)
        ref.update(image=encoded(a), roi=roi)
    a, target = canvas(width,height,scale,shift=(3,1))
    a[0,0] = 255
    p['image'] = encoded(a)
    r = compare_adaptive(p)
    assert r['label'] == 'standing', r
    assert np.max(np.abs(np.array(r['roi']) - target)) <= 2


def test_missing_icon_and_unseen_icon_are_unknown():
    for a in [canvas(blank=True)[0], canvas(seed=42)[0]]:
        p = payload(); p['image'] = encoded(a)
        assert compare_adaptive(p)['label'] == 'unknown'


def test_same_icon_twice_is_spatially_ambiguous():
    p = payload(); a, roi = canvas()
    x,y,w,h = roi
    a[y:y+h,x-40:x-40+w] = icon(1)
    p['image'] = encoded(a)
    r = compare_adaptive(p)
    assert r['reason'] == 'AMBIGUOUS_LOCATION'


def test_distinct_labels_visible_is_ambiguous():
    p = payload(); a, roi = canvas()
    x,y,w,h = roi
    a[y:y+h,x-40:x-40+w] = icon(2)
    p['image'] = encoded(a)
    assert compare_adaptive(p)['reason'] == 'AMBIGUOUS_LABEL'


def test_identical_reference_crops_different_background_rejected():
    p=payload(); a,_=canvas();a[0,0]=200
    p['references'][1]['image']=encoded(a)
    with pytest.raises(CalibrationError):compare_adaptive(p)


@pytest.mark.parametrize('change', [
    {'field':[]}, {'field':'weapon'}, {'layout_id':''}, {'references':[]},
    {'threshold':float('nan')}, {'threshold':.5}, {'margin':0}, {'margin':True}])
def test_bad_request(change):
    p=payload();p.update(change)
    with pytest.raises(CalibrationError):compare_adaptive(p)


@pytest.mark.parametrize('change', [{'roi':[0,0,4,4]}, {'roi':[999,0,20,20]},
    {'roi':[0,0,30.5,30]}, {'label':'unknown'}, {'label':'crouching'}, {'layout_id':'other'}])
def test_bad_reference(change):
    p=payload();p['references'][0].update(change)
    with pytest.raises(CalibrationError):compare_adaptive(p)


def test_duplicate_and_blank_references():
    p=payload();p['references'][1]['image']=p['references'][0]['image']
    with pytest.raises(CalibrationError):compare_adaptive(p)
    p=payload();p['references'][0]['image']=encoded(canvas(blank=True)[0])
    with pytest.raises(CalibrationError):compare_adaptive(p)


def test_self_matching_is_disclosed_and_not_stabilized():
    p=payload();p['image']=p['references'][0]['image']
    assert compare_adaptive(p)['self_match']
    p.update(images=[p['image']]*3,timestamps=[0,.04,.08])
    r=compare_sequence(p)
    assert all(not t['temporal']['stable'] for t in r['trace'])


def test_sequence_acquire_and_withdraw():
    p=payload();frames=[]
    for i, state in enumerate([1,1,1,2,2,2]):
        a,_=canvas(seed=state);a[0,0]=100+i;frames.append(encoded(a))
    p.update(images=frames,timestamps=[i*.04 for i in range(6)])
    r=compare_sequence(p)
    assert r['trace'][2]['temporal']['label']=='standing'
    assert r['trace'][3]['temporal']['label']=='unknown'
    assert r['trace'][5]['temporal']['label']=='crouching'
    assert not r['auto_execution_eligible']


@pytest.mark.parametrize('times', [[0,0],[-1,0],[.1,0],[0,float('nan')],[0], [0,True]])
def test_sequence_bad_clock(times):
    p=payload();p.update(images=[p['image']]*2,timestamps=times)
    with pytest.raises(CalibrationError):compare_sequence(p)


def test_pixel_budget(monkeypatch):
    import recoil_lab.adaptive_hud as mod
    monkeypatch.setattr(mod,'MAX_PIXELS',100)
    with pytest.raises(CalibrationError):compare_adaptive(payload())


def test_center_and_left_anchor():
    assert _axis(10,100,200,2)==(20,'start')
    assert _axis(50,100,250,2)==(125,'center')
    assert _axis(90,100,250,2)==(230,'end')
