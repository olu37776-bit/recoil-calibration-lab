from dataclasses import replace
import threading
import time

import pytest

from recoil_lab.simple_core import LABELS, Setting
from recoil_lab.simple_quick import QuickSession, QuickRunner

NEUTRAL = (False, False, False)
FIRE = (True, True, True)
NONE = (False, False)
PLUS = (False, True)
MINUS = (True, False)
TARGET = {'handle':1, 'pid':2, 'size':[1920,1080]}


def setting(rate=20, duration=2):
    c = dict.fromkeys(LABELS, '')
    c.update(weapon='Galil', pose='站姿', weight='未记录')
    return Setting(c, rate, duration)


def ready(rate=20, step=5):
    q = QuickSession(setting(rate), step)
    assert q.tick(0., NEUTRAL, NONE) == (0, None)
    return q


@pytest.mark.parametrize('step', [1, 5, 10])
def test_adjust_requires_ack_and_neutral(step):
    q = ready(step=step)
    delta, event = q.tick(.01, NEUTRAL, PLUS)
    assert delta == 0 and event['after']['rate'] == 20+step
    assert q.setting.rate == 20 and q.pending.rate == 20+step
    assert q.tick(.02, FIRE, NONE) == (0, None)
    q.acknowledge(event['sequence'], Setting.from_record(event['after']))
    for t in (.03, .04, .05): assert q.tick(t, FIRE, NONE) == (0, None)
    q.tick(.06, NEUTRAL, NONE)
    q.tick(.07, FIRE, NONE)
    assert q.tick(.14, FIRE, NONE)[0] == {1: 1, 5: 2, 10: 2}[step]


def test_initial_held_hotkey_not_applied():
    q = QuickSession(setting(), 5)
    for i in range(20): assert q.tick(i*.01, NEUTRAL, PLUS) == (0, None)
    q.tick(.21, NEUTRAL, NONE)
    assert q.tick(.22, NEUTRAL, PLUS)[1]['after']['rate'] == 25


@pytest.mark.parametrize('keys', [FIRE, (True,False,False), (False,True,False), (False,False,True)])
def test_busy_key_rejects_not_queued(keys):
    q = ready()
    assert q.tick(.01, keys, PLUS) == (0, None)
    assert q.setting.rate == 20 and q.pending is None
    assert q.tick(.02, NEUTRAL, PLUS) == (0, None)
    q.tick(.03, NEUTRAL, NONE)
    assert q.pending is None
    assert q.tick(.04, NEUTRAL, PLUS)[1]['after']['rate'] == 25


def test_simultaneous_tuning_rejected():
    q = ready()
    assert q.tick(.01, NEUTRAL, (True,True)) == (0, None)
    assert q.pending is None and q.setting.rate == 20


def test_hold_only_one_edit():
    q = ready()
    _, event = q.tick(.01, NEUTRAL, PLUS)
    q.acknowledge(event['sequence'], q.pending)
    for i in range(2, 20): assert q.tick(i*.01, NEUTRAL, PLUS) == (0, None)
    assert q.sequence == 1 and q.setting.rate == 25


@pytest.mark.parametrize('rate,tune,expected', [(2,MINUS,0), (398,PLUS,400), (20,MINUS,15)])
def test_limits(rate, tune, expected):
    q=ready(rate)
    _,event=q.tick(.01,NEUTRAL,tune)
    assert event['after']['rate']==expected


@pytest.mark.parametrize('rate,tune', [(0,MINUS),(400,PLUS)])
def test_no_event_at_limit(rate,tune):
    q=ready(rate)
    assert q.tick(.01,NEUTRAL,tune)==(0,None)
    assert q.pending is None and '边界' in q.message


@pytest.mark.parametrize('step',[True,0,2,20,'5',None])
def test_invalid_step(step):
    with pytest.raises(ValueError): QuickSession(setting(),step)


def test_forged_ack_stops_change():
    q=ready();_,e=q.tick(.01,NEUTRAL,PLUS)
    for s in (setting(99), replace(setting(25),duration=3), Setting({**setting().conditions,'pose':'蹲姿'},25)):
        with pytest.raises(ValueError):q.acknowledge(e['sequence'],s)
        assert q.setting.rate==20
    with pytest.raises(ValueError):q.acknowledge(2,setting(25))


def test_finished_burst_never_loops():
    q=QuickSession(setting(20,.5),5);q.tick(0,NEUTRAL,NONE)
    total=sum(q.tick(i*.01,FIRE,NONE)[0] for i in range(1,90))
    assert total==10
    q.tick(.9,NEUTRAL,NONE);q.tick(.91,FIRE,NONE)
    assert q.tick(.96,FIRE,NONE)[0]==1


class Fake:
    def __init__(self):
        self.valid=True;self.pressed=NEUTRAL;self.tuning=NONE;self.sent=[];self.checks=0
    def check(self,target,foreground=True):
        self.checks+=1
        if not self.valid:raise ValueError('focus lost')
    def acquire(self,target):return dict(target)
    def keys(self):return self.pressed
    def down(self,key):return self.tuning[0] if key==0x74 else self.tuning[1]
    def move(self,n):self.sent.append(n)


def runner():
    f=Fake();r=QuickRunner(lambda:f);r.configure(True,5)
    r.cancel.clear();r.active=True;r.pulse();r.controller=QuickSession(setting(),5)
    return r,f


def test_pending_handshake_blocks_output():
    r,f=runner();r._step(f,TARGET,0)
    f.tuning=PLUS;r._step(f,TARGET,.01)
    e=r.take_events()[0]
    assert e['session_id']==r.session_id and e['after']['rate']==25 and not f.sent
    f.tuning=NONE;f.pressed=FIRE;r._step(f,TARGET,.02)
    assert not f.sent
    assert r.acknowledge(e,Setting.from_record(e['after']))
    r._step(f,TARGET,.03);assert not f.sent
    f.pressed=NEUTRAL;r._step(f,TARGET,.04)
    f.pressed=FIRE;r._step(f,TARGET,.05);r._step(f,TARGET,.10)
    assert f.sent==[1]


def test_stop_cannot_be_revived_by_ack():
    r,f=runner();r._step(f,TARGET,0);f.tuning=PLUS;r._step(f,TARGET,.01)
    event=r.take_events()[0];r.stop()
    assert r.acknowledge(event,Setting.from_record(event['after'])) is False
    assert not r.active and not f.sent
    with pytest.raises(InterruptedError):r._step(f,TARGET,.02)


def test_stale_session_ack_never_reactivates():
    r,f=runner();r._step(f,TARGET,0);f.tuning=PLUS;r._step(f,TARGET,.01)
    event=r.take_events()[0];event['session_id']='old-session'
    assert not r.acknowledge(event,Setting.from_record(event['after']))
    assert r.controller.pending is not None and not f.sent


def test_heartbeat_loss_during_edit():
    r,f=runner();r.heartbeat-=1
    with pytest.raises(ValueError):r._step(f,TARGET,0)
    assert not f.sent


def test_focus_loss_prevents_edit_or_send():
    r,f=runner();f.valid=False;f.tuning=PLUS
    with pytest.raises(ValueError):r._step(f,TARGET,0)
    assert not r.events and not f.sent


def test_recheck_tuning_before_send():
    r,f=runner();r._step(f,TARGET,0);f.pressed=FIRE;r._step(f,TARGET,.01)
    calls=[]
    def newly_pressed(key):
        calls.append(key)
        return len(calls)>2
    f.down=newly_pressed
    r._step(f,TARGET,.06)
    assert not f.sent and r.controller.neutral_required


def test_no_send_after_stop():
    r,f=runner();f.pressed=FIRE
    def send():
        for _ in range(30):
            try:r._send(f,TARGET,1)
            except InterruptedError:return
            time.sleep(.001)
    t=threading.Thread(target=send);t.start();time.sleep(.005);r.stop();n=len(f.sent);t.join(2)
    assert len(f.sent)==n and not t.is_alive()


def test_options_cannot_be_hot_changed():
    r,f=runner()
    with pytest.raises(ValueError):r.configure(False,1)
    assert r.shortcuts and r.step==5


def test_pending_event_prevents_new_session():
    r,f=runner();r._step(f,TARGET,0);f.tuning=PLUS;r._step(f,TARGET,.01);r.stop()
    with pytest.raises(ValueError):r.configure(True,5)
    assert len(r.events)==1


def test_normal_mode_uses_original_runner(monkeypatch):
    from recoil_lab.simple_core import Runner
    r=QuickRunner(Fake);called=[]
    monkeypatch.setattr(Runner,'_run',lambda *args:called.append(args))
    r._run(Fake(),setting(),TARGET)
    assert len(called)==1


def test_new_module_never_captures_or_clicks():
    import inspect
    import recoil_lab.simple_quick as module
    text=inspect.getsource(module)
    for forbidden in ('ImageGrab','track_frames','RegisterHotKey','SetWindowsHookEx','MOUSEEVENTF_LEFTDOWN'):
        assert forbidden not in text

@pytest.mark.parametrize('stamp', [float('nan'),float('inf'),-.01,.2,True])
def test_pending_state_still_rejects_invalid_clock(stamp):
    q=ready();q.tick(.01,NEUTRAL,PLUS)
    with pytest.raises(ValueError):q.tick(stamp,FIRE,NONE)


def test_ack_boolean_not_sequence():
    q=ready();q.tick(.01,NEUTRAL,PLUS)
    with pytest.raises(ValueError):q.acknowledge(True,q.pending)


def test_whole_worker_timeout_never_extends_on_edit(monkeypatch):
    import types
    import recoil_lab.simple_quick as module
    class ClockEvent:
        def __init__(self):self.t=0.;self.flag=False
        def clear(self):self.flag=False
        def set(self):self.flag=True
        def is_set(self):return self.flag
        def wait(self,seconds):self.t+=seconds;return self.flag
    clock=ClockEvent();f=Fake();r=QuickRunner(lambda:f);r.configure(True,1)
    r.cancel=clock;r.active=True
    monkeypatch.setattr(module,'time',types.SimpleNamespace(monotonic=lambda:clock.t,perf_counter=lambda:clock.t))
    # Real heartbeat behavior is separately tested; avoid depending on CI CPU speed.
    def alive():
        if clock.is_set():raise InterruptedError()
    r._check_alive=alive
    r._run(f,setting(),TARGET)
    assert not r.active and clock.is_set() and not f.sent
    assert 125<=clock.t<125.1 and '120秒' in r.message


def test_whole_worker_stops_on_focus_loss(monkeypatch):
    import types
    import recoil_lab.simple_quick as module
    class Clock:
        t=0.;flag=False
        def wait(self,seconds):self.t+=seconds;return self.flag
        def is_set(self):return self.flag
        def set(self):self.flag=True
    clock=Clock();f=Fake();r=QuickRunner(lambda:f);r.configure(True,5);r.active=True;r.cancel=clock
    monkeypatch.setattr(module,'time',types.SimpleNamespace(monotonic=lambda:clock.t,perf_counter=lambda:clock.t))
    def check(target,foreground=True):
        if foreground:raise ValueError('focus lost')
    f.check=check
    r._run(f,setting(),TARGET)
    assert not f.sent and not r.active and r.message=='focus lost'
