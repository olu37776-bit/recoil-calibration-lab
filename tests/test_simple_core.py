import ctypes
import threading
import time
import pytest
from recoil_lab.simple_core import Setting, Store, Burst, Runner, LABELS, impact_summary
from recoil_lab.simple_desktop import Input

def setting(rate=20,duration=2):
    c=dict.fromkeys(LABELS,'');c.update(weapon='Galil',pose='站姿',weight='轻装')
    return Setting(c,rate,duration)

@pytest.mark.parametrize('rate',[0,20,400,0.25])
def test_numbers_accepted(rate):assert setting(rate).rate==rate
@pytest.mark.parametrize('rate',[-1,401,float('nan'),float('inf'),'20',True,None])
def test_bad_rate(rate):
    with pytest.raises(ValueError):setting(rate)
@pytest.mark.parametrize('duration',[0,.49,6.1,float('inf'),True,'3',None])
def test_bad_duration(duration):
    with pytest.raises(ValueError):setting(duration=duration)
@pytest.mark.parametrize('duration',[.5,1,2,6])
def test_duration(duration):assert setting(duration=duration).duration==duration

def test_copy_identity():
    c=setting().conditions;s=Setting(c);c['weight']='changed'
    assert s.conditions['weight']=='轻装' and s.key!=Setting(c).key
    assert setting(40).key==setting(20).key

def test_save_persistence_previous(tmp_path):
    store=Store(tmp_path);a=setting();store.save(a);store.save(a)
    with pytest.raises(ValueError):store.previous(a.key)
    store.save(setting(25));assert store.previous(a.key).rate==20
    store.save(Setting({**a.conditions,'pose':'蹲姿'},30))
    recovered=Store(tmp_path);assert len(recovered.items())==2 and recovered.data==store.data
    text=(tmp_path/'manual-presets.json').read_text(encoding='utf-8')
    assert 'consent' not in text and 'handle' not in text

def test_provenance_not_faked():
    for key,value in [('source','recorded'),('game_verified',True),('consent',True)]:
        d=setting().record();d[key]=value
        with pytest.raises(ValueError):Setting.from_record(d)

def test_corruption_preserves_file(tmp_path):
    f=tmp_path/'manual-presets.json';f.write_text('{BAD')
    with pytest.raises(ValueError):Store(tmp_path)
    assert f.read_text()=='{BAD'

def test_fresh_release():
    b=Burst(setting())
    for i in range(10):assert b.tick(i*.01,left=True,right=True,enable=True)==0
    assert b.tick(.1,left=False,right=True,enable=True)==0
    assert b.tick(.11,left=True,right=True,enable=True)==0
    assert b.tick(.16,left=True,right=True,enable=True)==1

@pytest.mark.parametrize('released',['left','right','enable'])
def test_release_stops(released):
    b=Burst(setting(100));b.tick(0,left=False,right=False,enable=False)
    assert b.tick(.01,left=True,right=True,enable=True)==0
    assert b.tick(.02,left=True,right=True,enable=True)==1
    keys={'left':True,'right':True,'enable':True};keys[released]=False
    assert b.tick(.03,**keys)==0
    assert b.tick(.04,left=True,right=True,enable=True)==0

@pytest.mark.parametrize('bad_time',[.2,-1,float('nan')])
def test_clock_fails(bad_time):
    b=Burst(setting());b.tick(0,left=False,right=False,enable=False)
    with pytest.raises(ValueError):b.tick(bad_time,left=True,right=True,enable=True)

def test_endpoint_no_loop():
    b=Burst(setting(20,.5));b.tick(0,left=False,right=False,enable=False)
    assert sum(b.tick(i*.01,left=True,right=True,enable=True) for i in range(1,81))==10
    b.tick(.81,left=False,right=True,enable=True)
    assert b.tick(.82,left=True,right=True,enable=True)==0
    assert b.tick(.87,left=True,right=True,enable=True)==1

def test_fractional_quantization():
    b=Burst(setting(5,1));b.tick(0,left=False,right=False,enable=False)
    assert sum(b.tick(i*.005,left=True,right=True,enable=True) for i in range(1,230))==5

def test_delta_cap():
    b=Burst(setting(400));b.tick(0,left=False,right=False,enable=False);b.tick(.01,left=True,right=True,enable=True)
    with pytest.raises(ValueError):b.tick(.1,left=True,right=True,enable=True)

class Fake:
    def __init__(self):self.sent=[];self.pressed=(True,True,True);self.valid=True
    def check(self,target,foreground=True):
        if not self.valid:raise ValueError('focus lost')
    def acquire(self,target):return target
    def keys(self):return self.pressed
    def move(self,x):self.sent.append(x)
TARGET={'handle':1,'pid':2,'size':[1920,1080]}
def runner():
    f=Fake();r=Runner(lambda:f);r.cancel.clear();r.active=True;r.pulse();return r,f

def test_send_rechecks_keys_and_stop():
    r,f=runner();r._send(f,TARGET,1);assert f.sent==[1]
    f.pressed=(False,True,True)
    with pytest.raises(ValueError):r._send(f,TARGET,1)
    assert f.sent==[1]
    r.stop()
    with pytest.raises(InterruptedError):r._send(f,TARGET,1)

def test_no_send_after_stop_returns():
    r,f=runner();done=threading.Event()
    def sending():
        for _ in range(100):
            try:r._send(f,TARGET,1)
            except InterruptedError:break
            time.sleep(.001)
        done.set()
    t=threading.Thread(target=sending);t.start();time.sleep(.005);r.stop();n=len(f.sent);t.join(2)
    assert done.is_set() and len(f.sent)==n

def test_heartbeat_stall():
    r,f=runner();r.heartbeat-=1
    with pytest.raises(ValueError):r._send(f,TARGET,1)
    assert not f.sent

def test_focus_stops():
    r,f=runner();f.valid=False
    with pytest.raises(ValueError):r._send(f,TARGET,1)
    assert not f.sent

@pytest.mark.parametrize('consent',[False,None,1,'true'])
def test_consent_strict(consent):
    r,f=runner()
    with pytest.raises(ValueError):r.start(setting(),TARGET,consent)
    assert not f.sent

def test_countdown_stop_no_capture():
    f=Fake();r=Runner(lambda:f);r.start(setting(),TARGET,True);r.stop();r.thread.join(2)
    assert not r.thread.is_alive() and not f.sent

@pytest.mark.parametrize('target',[None,{},{'handle':1},{'handle':1,'pid':1,'size':[0,0]}])
def test_bad_target(target):
    r,f=runner()
    with pytest.raises(ValueError):r.start(setting(),target,True)

def test_abi():assert ctypes.sizeof(Input)==(40 if ctypes.sizeof(ctypes.c_void_p)==8 else 28)

def test_impact_result():
    s=impact_summary((10,10),[(10,0),(12,4)])
    assert '纵向 -8.0' in s and '不是逐发' in s
    with pytest.raises(ValueError):impact_summary(None,[(1,2)])
    with pytest.raises(ValueError):impact_summary((1,float('nan')),[(1,2)])

def test_no_live_capture_import():
    import inspect,recoil_lab.simple_core as c,recoil_lab.simple_desktop as d
    for m in (c,d):
        source=inspect.getsource(m)
        assert 'ImageGrab' not in source and 'capture(' not in source and 'track_frames' not in source
