"""Bounded supervised routing of a user-validated local recognition library."""
from __future__ import annotations

import threading
import time

import numpy as np

from .contracts import CalibrationError
from .conditions import weight_label
from .native_session import NativeSession


class RouteGate:
    """A fresh release after stable recognition is required for each burst."""
    def __init__(self, profiles):
        self.profiles=profiles
        self.label=None
        self.first=None
        self.count=0
        self.last=None
        self.started=None
        self.released=False
        self.emitted=0

    def clear(self):
        self.label=None;self.first=None;self.count=0
        self.started=None;self.released=False;self.emitted=0

    def tick(self, now, candidate, *, pressed, enabled):
        if not np.isfinite(now) or now<0 or (self.last is not None and now<=self.last):
            self.clear();raise CalibrationError('自动选档时钟无效')
        gap=self.last is not None and now-self.last>.10
        self.last=now
        if gap:self.clear()
        if not candidate or candidate not in self.profiles:
            self.clear();return {'project_id':None,'dy':0,'reason':'UNKNOWN_OR_UNVALIDATED'}
        if candidate!=self.label:
            self.clear();self.label=candidate;self.first=now;self.count=1
        else:self.count+=1
        if self.count<3 or now-self.first<.08:
            return {'project_id':None,'dy':0,'reason':'CONFIRMING'}
        result={'project_id':candidate,'dy':0,'reason':'WAIT_RELEASE'}
        if not pressed:
            self.released=True;self.started=None;self.emitted=0
            return result | {'reason':'SELECTED'}
        if not enabled:
            self.released=False;self.started=None;self.emitted=0
            return result | {'reason':'NOT_ENABLED'}
        if not self.released:return result
        if self.started is None:self.started=now
        profile=self.profiles[candidate]
        elapsed=now-self.started
        total=int(np.rint(profile.input_at(min(elapsed,profile.t_s[-1]))))
        delta=total-self.emitted
        if abs(delta)>32:
            self.clear();raise CalibrationError('本次输出超过32单位，停止而不是补发')
        self.emitted=total
        if elapsed>=profile.t_s[-1]:
            self.released=False;self.started=None;self.emitted=0
        return result | {'dy':delta,'reason':'SUPERVISED_OUTPUT'}


def start_taught(session, payload):
    if payload.get('consent') is not True:
        raise CalibrationError('请明确授权前台窗口识别；自动应用仅限允许的受控环境')
    execute=payload.get('mode')=='auto_execute'
    weight=weight_label(payload.get('weight','未记录'))
    bank,matcher,profiles,blocked=session.teaching.prepare(payload.get('bank_id'),weight,execute)
    hwnd=payload.get('hwnd')
    if type(hwnd) is not int or hwnd<=0:raise CalibrationError('请选择目标窗口')
    backend=session.backend_factory();pid=backend.pid(hwnd)
    if list(backend.geometry(hwnd)[2:])!=bank['resolution']:
        raise CalibrationError('窗口尺寸与识别库不同，需建立对应条件的配置')
    with session.lock:
        if session.worker and session.worker.is_alive():raise CalibrationError('已有桌面任务，请先停止')
        session.stop_event.clear();session.last_client=time.monotonic()
        session.info={'state':'RUNNING','mode':payload['mode'],'progress':0,
                      'message':'5秒内切到所选窗口；负重手动固定为：'+weight,
                      'weight':weight,'selected_project':None,'blocked_profiles':blocked}
        session.worker=threading.Thread(target=run_taught,args=(session,backend,hwnd,pid,bank,matcher,profiles,execute),daemon=True)
        session.worker.start()
    return session.status()


def run_taught(session,b,hwnd,pid,bank,matcher,profiles,execute):
    try:
        for _ in range(50):session._cancelled();time.sleep(.1)
        end=time.perf_counter()+120
        # Monitor mode can select a project without a curve. Never output from it.
        routing_profiles=profiles if execute else {s['project_id']:None for s in bank['samples']
            if s['phase']=='reference' and s['weight']==matcher.weight}
        gate=RouteGate(routing_profiles)
        while time.perf_counter()<end:
            session._cancelled();b.check_window(hwnd,bank['resolution'],pid)
            if b.interrupted():
                gate.clear()
                session.update(selected_project=None,message='动作指令：暂停并重新确认；恢复后先释放左键')
                time.sleep(.02);continue
            before=time.perf_counter()
            image=b.capture_recognition(hwnd,bank['resolution'],pid)
            match=matcher.compare(image)
            now=time.perf_counter()
            session._cancelled();b.check_window(hwnd,bank['resolution'],pid)
            if now-before>.1:
                gate.clear()
                session.update(selected_project=None,message='本帧识别超过100ms：本帧不输出')
                continue
            if b.interrupted():gate.clear();continue
            decision=gate.tick(now,match['project_id'],pressed=b.down(1) if execute else False,
                               enabled=execute and b.triggered('execute'))
            if execute and decision['dy']:
                try:
                    b.move(decision['dy'],hwnd,bank['resolution'],pid,'execute')
                except CalibrationError:
                    b.check_window(hwnd,bank['resolution'],pid)
                    if b.interrupted() or not b.triggered('execute'):
                        gate.clear();continue
                    raise
            session.update(selected_project=decision['project_id'],recognition=match,
                           message=decision['reason']+' / '+match['reason'],
                           actual_output_enabled=execute,progress=max(0,1-(end-now)/120))
            time.sleep(.02)
        session.update(state='DONE',message='120秒会话结束，已停止',selected_project=None)
    except Exception as exc:
        session.update(state='STOPPED' if session.stop_event.is_set() else 'ERROR',
                       message=str(exc),selected_project=None)
    finally:session.stop_event.set()


class PersonalNativeSession(NativeSession):
    """Extend, rather than alter, the verified single-project capture workflow."""
    teaching = None

    def start(self, payload: dict):
        if payload.get('mode') in {'recognize','auto_execute'}:
            if self.teaching is None:raise CalibrationError('个人识别库尚未初始化')
            return start_taught(self,payload)
        return super().start(payload)
