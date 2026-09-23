"""Supervised capture/validation sessions, bounded and explicitly stoppable."""
from __future__ import annotations

import hashlib
import threading
import time
import uuid

import numpy as np

from .contracts import CalibrationError, read_json
from .desktop import WindowsDesktop
from .video import track_frames


class NativeSession:
    def __init__(self, workspace, backend_factory=WindowsDesktop):
        self.workspace = workspace
        self.backend_factory = backend_factory
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.worker = None
        self.info = {'state':'IDLE', 'message':'默认关闭，不发送输入', 'progress':0}
        self.preview_result = None
        self.last_client = time.monotonic()

    def status(self):
        with self.lock:
            self.last_client = time.monotonic()
            return dict(self.info)

    def update(self, **values):
        with self.lock: self.info.update(values)

    def stop(self):
        self.stop_event.set()
        return self.status()

    def start(self, payload: dict):
        if payload.get('consent') is not True:
            raise CalibrationError('请明确确认受控测试环境、窗口采集及标准鼠标输出授权')
        mode = payload.get('mode')
        if mode not in {'preview','response','train','validation','execute'}:
            raise CalibrationError('未知桌面会话模式')
        project_id = payload.get('project_id')
        p = self.workspace.directory(project_id)
        meta = read_json(p/'project.json')
        if meta['demo']:
            raise CalibrationError('合成项目禁止桌面输入和实测采集')
        hwnd = payload.get('hwnd')
        if type(hwnd) is not int or hwnd<=0: raise CalibrationError('请先选择目标窗口')
        duration = float(payload.get('duration_s',2))
        if not np.isfinite(duration) or not .5<=duration<=6:
            raise CalibrationError('单轮采样时长需在0.5至6秒')
        profile = None
        if mode in {'validation','execute'}:
            profile = (self.workspace.execution_profile(project_id) if mode=='execute'
                       else self.workspace.profile(project_id))
            if profile.source!='recorded': raise CalibrationError('仅支持当前配置的真实采样曲线')
            duration = float(profile.t_s[-1])
            if duration>6: raise CalibrationError('桌面输出曲线最长6秒；不自动裁剪')
        roi = payload.get('roi')
        if mode not in {'execute','preview'} and (not isinstance(roi,list) or len(roi)!=4 or any(type(v)is not int for v in roi)):
            raise CalibrationError('请在窗口预览中框选静态纹理区域')
        backend = self.backend_factory()
        pid = backend.pid(hwnd)
        if list(backend.geometry(hwnd)[2:]) != meta['context']['resolution']:
            raise CalibrationError('项目分辨率与目标窗口不同，请按实际窗口尺寸新建项目')
        with self.lock:
            if self.worker and self.worker.is_alive(): raise CalibrationError('已有任务，请先停止或等待结束')
            self.stop_event.clear()
            self.last_client = time.monotonic()
            self.preview_result = None
            self.info = {'state':'RUNNING','mode':mode,'project_id':project_id,'progress':0,
                         'message':'5秒准备时间：切到所选窗口。F8/Esc急停。'}
            self.worker = threading.Thread(target=self._run, args=(backend,hwnd,pid,meta,mode,duration,roi,profile),daemon=True)
            self.worker.start()
        return self.status()

    def _cancelled(self):
        if self.stop_event.is_set(): raise CalibrationError('用户已停止')
        if time.monotonic()-self.last_client>5:
            raise CalibrationError('工作台心跳中断，已停止')

    def _run(self, backend, hwnd, pid, meta, mode, duration, roi, profile):
        try:
            for _ in range(50):
                self._cancelled(); time.sleep(.1)
            context = meta['context']; res = context['resolution']
            backend.check(hwnd,res,pid)
            if mode=='preview':
                from PIL import Image
                from io import BytesIO
                import base64
                image = backend.capture(hwnd,res,pid)
                b=BytesIO(); Image.fromarray(image).save(b,format='PNG')
                self.preview_result={'image':base64.b64encode(b.getvalue()).decode(),'resolution':res}
                self.update(state='DONE', message='窗口预览已就绪，只存于当前进程内存', preview=self.preview_result)
                return
            if mode=='execute':
                self._execute(backend,hwnd,pid,context,profile)
            else:
                self.update(message=('响应采集：按住F7+右键，不开枪。' if mode=='response' else
                                     '纹理墙面前：先松开左键，再按住F7+右键+左键至本轮完成。'))
                trial=self._capture(backend,hwnd,pid,context,mode,duration,roi,profile)
                record=self.workspace.add(meta['id'],trial)
                self.update(trial_id=record)
            self.update(state='DONE',progress=1,message='本轮完成；已停止输出。可返回工作台查看结果。')
        except Exception as exc:
            self.update(state='STOPPED' if self.stop_event.is_set() else 'ERROR',message=str(exc))
        finally:
            self.stop_event.set()

    def _capture(self, b, hwnd, pid, context, phase, duration, roi, profile):
        res=context['resolution']; deadline=time.perf_counter()+30
        # A fresh release is required; capture the last no-fire reference frame.
        released=False; reference=None; reference_time=None
        while time.perf_counter()<deadline:
            self._cancelled();b.check(hwnd,res,pid)
            if not b.down(1):
                released=True
                reference=b.capture(hwnd,res,pid);reference_time=time.perf_counter()
            if released and b.triggered(phase): break
            time.sleep(.015)
        else: raise CalibrationError('30秒内未收到使能/开火，已停止')
        if reference is None: raise CalibrationError('缺少射击前参考画面')
        if time.perf_counter()-reference_time>.09: raise CalibrationError('射击前参考帧过旧，请重新采样')
        start=reference_time; applied=[0.]; emitted=0; capture_hash=hashlib.sha256()
        input_events=[]; last_clock=start
        def frames():
            nonlocal emitted,last_clock
            capture_hash.update(reference.tobytes())
            yield 0., reference
            while True:
                self._cancelled(); b.check(hwnd,res,pid)
                if not b.triggered(phase): raise CalibrationError('采样未结束便松开使能/开火，整轮未保存')
                now=time.perf_counter(); elapsed=now-start
                if now-last_clock>.1: raise CalibrationError('采集或处理间隔超过100ms，整轮拒绝')
                if phase=='response':
                    target=round(12*np.sin(2*np.pi*min(elapsed,duration)/duration))
                elif profile is not None:
                    target=int(np.rint(profile.input_at(min(elapsed,duration))))
                else: target=0
                delta=target-emitted
                if delta:
                    b.move(int(delta),hwnd,res,pid,phase)
                    emitted=target
                    input_events.append({'t_s':time.perf_counter()-start,'uy_counts':emitted})
                capture_start=time.perf_counter()
                image=b.capture(hwnd,res,pid)
                end=time.perf_counter()
                if end-capture_start>.05: raise CalibrationError('单帧捕获超过50ms，无法可靠对齐输入；降低采集分辨率并重建项目')
                stamp=(capture_start+end)/2-start
                capture_hash.update(image.tobytes())
                capture_hash.update(repr(stamp).encode())
                applied.append(float(emitted))
                last_clock=end
                self.update(progress=min(1,stamp/duration))
                yield stamp,image
                if elapsed>=duration and stamp>=duration: break
                time.sleep(.01)
        ident=uuid.uuid4().hex
        trial=track_frames(frames(),tuple(roi),context=context,run_id='capture-'+ident,
            session_id='session-'+ident,source='recorded',provenance={'method':'supervised-desktop-v1'})
        trial.phase=phase;trial.uy_counts=np.asarray(applied,dtype=float)
        trial.provenance.update(capture_sha256=capture_hash.hexdigest(),input_events=input_events,
            input_backend='windows-sendinput-v1',observer='static-background-optical-flow',
            supervised=True,actual_game_state_inferred=False,raw_images_saved=False,
            candidate_id=profile.profile_id if profile else None)
        trial.gate(phase)
        return trial

    def _execute(self,b,hwnd,pid,context,profile):
        res=context['resolution'];deadline=time.perf_counter()+120
        started=None; emitted=0; released=False; last=None
        self.update(message='手动监督运行，最长120秒；每轮先释放左键。F7+右键+左键输出；F8/Esc停止。')
        while time.perf_counter()<deadline:
            self._cancelled();b.check(hwnd,res,pid)
            now=time.perf_counter()
            if last is not None and now-last>.1: raise CalibrationError('调度中断，已停止，不补发')
            last=now
            if not b.down(1):
                released=True;started=None;emitted=0
            elif not b.triggered('execute'):
                released=False;started=None;emitted=0
            elif released:
                if started is None: started=now
                elapsed=now-started
                target=int(np.rint(profile.input_at(min(elapsed,profile.t_s[-1]))))
                if target!=emitted:
                    b.move(target-emitted,hwnd,res,pid,'execute');emitted=target
                if elapsed>=profile.t_s[-1]:
                    released=False;started=None;emitted=0
            time.sleep(.005)
