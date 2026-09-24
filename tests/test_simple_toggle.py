from dataclasses import replace
import ctypes
import json
import threading
import time
import pytest
from recoil_lab.simple_core import Setting,LABELS
from recoil_lab.simple_toggle import (ToggleOptions,OptionsStore,Keys,ToggleSession,ToggleRunner,HOTKEYS)

def setting():return Setting({k:('Galil' if k=='weapon' else '') for k in LABELS},100, .5)
def session(**kwargs):return ToggleSession(setting(),ToggleOptions(**kwargs))
class Clock:
    def __init__(self,s):self.t=-.01;self.s=s
    def tick(self,**kw):self.t+=.01;return self.s.tick(self.t,Keys(**kw))
    def on(self):self.tick();self.tick(toggle=True);self.tick()

@pytest.mark.parametrize('key',list(HOTKEYS))
def test_all_selectable_keys(key):assert ToggleOptions(key=key).key==key
@pytest.mark.parametrize('key',['F8','Esc','F5','F6','left','UNKNOWN',''])
def test_reserved_keys(key):
    with pytest.raises(ValueError):ToggleOptions(key=key)

def test_one_press_toggles_no_hold_or_delay():
    s=session();c=Clock(s);c.on();assert s.enabled
    c.tick(left=True,right=True);delta,_=c.tick(left=True,right=True)
    assert delta>0
    assert c.tick(toggle=True,left=True,right=True)[0]==0 and not s.enabled
    for _ in range(8):c.tick(toggle=True)
    assert not s.enabled
    c.tick();c.tick(toggle=True);assert s.enabled

def test_initial_held_key_ignored():
    s=session();c=Clock(s)
    for _ in range(5):c.tick(toggle=True)
    assert not s.enabled
    c.tick();c.tick(toggle=True);assert s.enabled

def test_left_held_never_enables():
    s=session();c=Clock(s);c.tick();c.tick(toggle=True,left=True)
    assert not s.enabled and s.reason=='RELEASE'

def test_background_never_enables_and_focus_loss_disables():
    s=session();c=Clock(s);c.tick(foreground=False);c.tick(toggle=True,foreground=False)
    assert not s.enabled
    c.tick(toggle=True);assert not s.enabled
    c.tick();c.tick(toggle=True);c.tick();assert s.enabled
    c.tick(foreground=False);assert not s.enabled
    c.tick();assert not s.enabled

@pytest.mark.parametrize('field',['emergency','changed'])
def test_close_events_require_new_toggle(field):
    s=session();c=Clock(s);c.on();c.tick(**{field:True})
    assert not s.enabled;c.tick(left=True,right=True);assert not s.enabled

def test_reload_only_pauses_then_fresh_fire():
    s=session();c=Clock(s);c.on();c.tick(left=True,right=True)
    assert c.tick(left=True,right=True)[0]>0
    assert c.tick(reload=True)[0]==0 and s.enabled
    assert c.tick(left=True,right=True)[0]==0
    c.tick();c.tick(left=True,right=True)
    assert c.tick(left=True,right=True)[0]>0

@pytest.mark.parametrize('trigger,right,expected',[('both',False,False),('both',True,True),('left',False,True)])
def test_mouse_trigger_modes(trigger,right,expected):
    s=session(trigger=trigger);c=Clock(s);c.on();c.tick(left=True,right=right)
    assert (c.tick(left=True,right=right)[0]>0)==expected

def test_duration_cap_stops_until_release():
    s=session();c=Clock(s);c.on();total=0
    for _ in range(100):total+=c.tick(left=True,right=True)[0]
    assert total==50 and s.reason=='LIMIT'
    c.tick();c.tick(left=True,right=True);assert c.tick(left=True,right=True)[0]>0

def test_idle_has_no_session_timeout():
    s=session();c=Clock(s);c.on()
    for _ in range(13000):assert c.tick()[0]==0
    assert s.enabled

def test_schedule_gap_not_caught_up():
    s=session();c=Clock(s);c.on();c.tick(left=True,right=True)
    with pytest.raises(ValueError):s.tick(c.t+.11,Keys(left=True,right=True))
    assert not s.enabled

@pytest.mark.parametrize('stamp',[float('inf'),float('nan'),True,-1])
def test_invalid_clock(stamp):
    s=session();s.tick(0,Keys())
    with pytest.raises(ValueError):s.tick(stamp,Keys())

def test_quick_edit_handshake():
    s=ToggleSession(setting(),ToggleOptions(),1,True);c=Clock(s);c.on()
    delta,event=c.tick(increase=True)
    assert delta==0 and event and s.pending.rate==101
    assert c.tick(left=True,right=True)[0]==0
    s.acknowledge(event['sequence'],Setting.from_record(event['after']))
    assert s.enabled and s.neutral_required
    c.tick();c.tick(left=True,right=True);assert c.tick(left=True,right=True)[0]>0

@pytest.mark.parametrize('extra',[{'left':True},{'right':True},{'decrease':True}])
def test_quick_edit_unsafe_rejected(extra):
    s=ToggleSession(setting(),ToggleOptions(),5,True);c=Clock(s);c.on()
    _,event=c.tick(increase=True,**extra)
    assert event is None and s.setting.rate==100

def test_quick_edit_off_ignored():
    s=ToggleSession(setting(),ToggleOptions(),5,True);c=Clock(s);c.tick();c.tick(increase=True)
    assert s.pending is None

def test_options_never_store_permission(tmp_path):
    store=OptionsStore(tmp_path);store.save(ToggleOptions('鼠标侧键4','left',True))
    raw=json.loads(store.path.read_text());assert set(raw)=={'key','trigger'}
    assert store.read()==ToggleOptions('鼠标侧键4','left',False)
    store.path.write_text('{"key":"F9","trigger":"both","enabled":true}')
    assert store.read()==ToggleOptions()

class Fake:
    def __init__(self):self.keys=Keys();self.sent=[];self.error=False;self.fresh_override=None
    def inspect(self,t,check_size=True):return t.copy()
    def in_foreground(self,t):return self.keys.foreground
    def sample(self,t,o):
        if self.fresh_override is not None:
            value=self.fresh_override;self.fresh_override=None;return value
        return self.keys
    def send(self,t,d,o):
        if self.error:raise ValueError('Windows未接受输入（返回0）')
        self.sent.append(d)
TARGET={'handle':123,'pid':42,'size':[1920,1080]}

def runner(diagnostic=False):
    r=ToggleRunner(Fake,Fake);r.options=ToggleOptions(diagnostic=diagnostic)
    r.controller=ToggleSession(setting(),r.options);r.active=True;r.cancel.clear();r.pulse()
    return r

def advance(r,f):
    for i,k in enumerate([Keys(),Keys(toggle=True),Keys(),Keys(left=True,right=True),Keys(left=True,right=True)]):
        f.keys=k;r._step_toggle(f,TARGET,i*.01)

def test_runner_counts_only_accepted_events():
    r=runner();f=Fake();advance(r,f)
    report=r.snapshot();assert report['accepted_events']==len(f.sent)>0
    assert report['accepted_counts']==sum(f.sent) and report['game_acceptance']=='unknown'

def test_diagnostic_never_sends():
    r=runner(True);f=Fake();advance(r,f);report=r.snapshot()
    assert not f.sent and report['attempted_events']==0 and report['accepted_events']==0
    assert report['diagnostic_steps']>0

def test_error_has_attempt_but_no_acceptance():
    r=runner();f=Fake();f.error=True
    with pytest.raises(ValueError):advance(r,f)
    assert r.snapshot()['attempted_events']==1 and r.snapshot()['accepted_events']==0
    assert r.snapshot()['system_error']

def test_stop_prevents_further_send():
    r=runner();f=Fake();advance(r,f);r.stop();before=list(f.sent)
    with pytest.raises(InterruptedError):r._step_toggle(f,TARGET,.06)
    assert f.sent==before

def test_changed_between_compute_send_discards_burst():
    r=runner();f=Fake()
    for i,k in enumerate([Keys(),Keys(toggle=True),Keys(),Keys(left=True,right=True)]):
        f.keys=k;r._step_toggle(f,TARGET,i*.01)
    class Race(Fake):
        def __init__(self):super().__init__();self.n=0
        def sample(self,t,o):
            self.n+=1;return Keys(left=True,right=True,foreground=self.n==1)
    race=Race();r._step_toggle(race,TARGET,.04)
    assert not race.sent and r.snapshot()['reason']=='CHANGED_BEFORE_SEND'

def test_start_immediate_listen_off_then_stop():
    r=ToggleRunner(Fake,Fake);r.set_options(ToggleOptions())
    start=time.monotonic();r.start(setting(),TARGET,True)
    assert r.active and time.monotonic()-start<1 and not r.snapshot()['enabled']
    assert '5秒' not in r.message
    r.stop();r.thread.join(timeout=1);assert not r.thread.is_alive()

@pytest.mark.parametrize('consent',[False,None,1,'yes'])
def test_explicit_permission_required(consent):
    r=runner();r.active=False
    with pytest.raises(ValueError):r.start(setting(),TARGET,consent)

def test_report_copy_cannot_mutate_runtime():
    r=runner();s=r.snapshot();s['accepted_counts']=999
    assert r.snapshot()['accepted_counts']==0

def test_ui_hang_stops_before_send():
    r=runner();r.heartbeat=time.monotonic()-1;f=Fake()
    with pytest.raises(ValueError):r._step_toggle(f,TARGET,0)
    assert not f.sent

def test_no_toggle_runtime_calls_legacy_hold_check():
    import inspect
    source=inspect.getsource(ToggleRunner._run_toggle)+inspect.getsource(ToggleRunner._step_toggle)
    assert 'super()._run' not in source and 'backend.check(' not in source and 'sleep(5' not in source
