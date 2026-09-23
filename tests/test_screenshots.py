import base64
from io import BytesIO
import numpy as np
import pytest
from PIL import Image
import cv2

from recoil_lab.catalog import build_preset
from recoil_lab.contracts import CalibrationError
from recoil_lab.screenshots import decode_image, pattern_summary, pair_displacement, screenshot_sequence
from test_catalog import config


def texture():
    a=np.random.default_rng(74).integers(0,256,(240,320,3),dtype=np.uint8)
    return cv2.GaussianBlur(a,(3,3),0)


def encoded(a):
    b=BytesIO();Image.fromarray(a[:,:,::-1]).save(b,format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(b.getvalue()).decode()


def context():
    return build_preset(config())['context']


def test_single_pattern_is_not_trajectory():
    a=texture();decoded,hashed=decode_image(encoded(a));assert np.array_equal(decoded,a)
    r=pattern_summary(a,[100,100],[[90,90],[110,110]],hashed,context())
    assert r['marked_impacts']==2 and r['centroid_from_aim_px']==[0.,0.]
    assert r['bbox_size_px']==[20.,20.]
    assert r['can_fit_time_curve'] is False


@pytest.mark.parametrize('aim,points', [([0,0],[]),([0,0],[[320,0]]),([0,0],[[1,float('nan')]]),([1],[[1,2]]),([1,2],[1,2]),([1,2],[['bad',1]])])
def test_bad_annotations(aim,points):
    with pytest.raises(CalibrationError):pattern_summary(texture(),aim,points,'hash',context())


@pytest.mark.parametrize('value',[None,'','bad','data:text/html;base64,abcd','abcd'*2500000],
                         ids=['null','empty','malformed','wrong-mime','oversized-10mb'])
def test_bad_image(value):
    with pytest.raises(CalibrationError):decode_image(value)


def test_dimension_mismatch():
    c=context();c['resolution']=[640,480]
    with pytest.raises(CalibrationError):pattern_summary(texture(),[0,0],[[1,1]],'hash',c)


def test_pair_static_background_not_curve():
    a=texture();b=cv2.warpAffine(a,np.float32([[1,0,3],[0,1,-4]]),(320,240),borderMode=cv2.BORDER_REFLECT)
    r=pair_displacement(a,b,[30,30,240,170],context(),['a','b'])
    assert np.allclose(r['camera_delta_px'],[-3,4],atol=.2)
    assert r['confidence']>.65 and not r['can_fit_time_curve']


@pytest.mark.parametrize('roi',[[0,0,20,20],[-1,0,80,80],[0,0,400,240],[0.,0,200,150],None])
def test_bad_roi(roi):
    with pytest.raises(CalibrationError):pair_displacement(texture(),texture(),roi,context(),['a','b'])


def test_textureless_rejected():
    a=np.zeros((240,320,3),np.uint8)
    with pytest.raises(CalibrationError):pair_displacement(a,a,[20,20,200,150],context(),['a','b'])


def sequence_data():
    a=texture()
    frames=[encoded(cv2.warpAffine(a,np.float32([[1,0,0],[0,1,-i]]),(320,240),borderMode=cv2.BORDER_REFLECT)) for i in range(12)]
    return frames,[i/30 for i in range(12)]


def test_sequence_native_trial():
    images,times=sequence_data()
    trial=screenshot_sequence(images,times,roi=[30,30,240,170],context=context(),run_id='burst',capture_session='session-1',uncompensated=True)
    assert trial.phase=='train' and trial.source=='recorded'
    assert trial.provenance['capture_sha256']=='session-1'
    assert abs(trial.dy_px[-1]-11)<.3
    assert trial.context_hash==build_preset(config())['context_id']


@pytest.mark.parametrize('case',['short','gap','reverse','nan','no-declaration','no-session','missing-time'])
def test_sequence_rejects_missing_evidence(case):
    images,times=sequence_data();kwargs=dict(roi=[30,30,240,170],context=context(),run_id='burst',capture_session='session-1',uncompensated=True)
    if case=='short':images,times=images[:3],times[:3]
    if case=='gap':times=[i*.2 for i in range(len(images))]
    if case=='reverse':times=list(reversed(times))
    if case=='nan':times[-1]=float('nan')
    if case=='no-declaration':kwargs['uncompensated']=False
    if case=='no-session':kwargs['capture_session']=''
    if case=='missing-time':times=[]
    with pytest.raises(CalibrationError):screenshot_sequence(images,times,**kwargs)
