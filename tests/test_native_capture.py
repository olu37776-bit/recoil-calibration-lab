"""Virtual desktop feedback only. These tests do not call Windows or a game."""
import time
import cv2
import numpy as np
import pytest
from recoil_lab.workspace import Workspace
from recoil_lab.native_session import NativeSession
from recoil_lab.calibration import fit_response
from test_catalog import config


class VirtualDesktop:
    def __init__(self,phase):
        self.phase=phase;self.u=0;self.start=None
        self.image=np.random.default_rng(19).integers(0,256,(480,640),dtype=np.uint8)
        self.image=cv2.GaussianBlur(self.image,(3,3),0)
    def check(self,*args):pass
    def down(self,key):return self.start is not None
    def triggered(self,phase):
        if self.start is None:self.start=time.perf_counter()
        return True
    def move(self,dy,*args):self.u+=dy
    def capture(self,*args):
        recoil=0 if self.phase=='response' or self.start is None else -25*(time.perf_counter()-self.start)
        dy=recoil+1.5*self.u
        return cv2.warpAffine(self.image,np.float32([[1,0,0],[0,1,-dy]]),(640,480),borderMode=cv2.BORDER_REFLECT)


def test_virtual_closed_loop_response(tmp_path):
    payload=config();payload['settings']['resolution']=[640,480]
    w=Workspace(tmp_path);p=w.create(payload,'virtual capture test');n=NativeSession(w)
    trials=[]
    for i in range(2):
        n.status()
        t=n._capture(VirtualDesktop('response'),1,2,p['context'],'response',.8,[70,70,490,320],None)
        assert len(t.t_s)==len(t.uy_counts)
        assert t.phase=='response' and min(t.uy_counts)<=-5 and max(t.uy_counts)>=5
        trials.append(t)
    response=fit_response(trials)
    assert response.gain_px_per_count==pytest.approx(1.5,abs=.15)


def test_virtual_training_no_output(tmp_path):
    payload=config();payload['settings']['resolution']=[640,480]
    w=Workspace(tmp_path);p=w.create(payload,'virtual training');n=NativeSession(w)
    b=VirtualDesktop('train')
    t=n._capture(b,1,2,p['context'],'train',.5,[70,70,490,320],None)
    assert b.u==0 and np.max(abs(t.uy_counts))==0
    assert t.dy_px[-1]<-8
    assert t.provenance['raw_images_saved'] is False
