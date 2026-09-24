"""User-requested one-key mode, isolated from the legacy hold-to-test engine."""
from __future__ import annotations
from dataclasses import dataclass, replace, asdict
from pathlib import Path
import copy
import json
import math
import threading
import time
import uuid

from .simple_core import Setting, Burst
from .simple_quick import QuickRunner
from .simple_tuning import _json

HOTKEYS = {f'F{i}': 0x6F+i for i in (1, 2, 3, 4, 7, 9, 10, 11, 12)}
HOTKEYS.update({'Insert':0x2D, 'Home':0x24, 'End':0x23, '鼠标侧键4':0x05, '鼠标侧键5':0x06})
TRIGGERS = {'右键＋左键（按住开镜）':'both', '仅左键（腰射也会触发）':'left'}

@dataclass(frozen=True)
class ToggleOptions:
    key: str = 'F9'
    trigger: str = 'both'
    diagnostic: bool = False
    def __post_init__(self):
        if self.key not in HOTKEYS or self.trigger not in ('both','left') or type(self.diagnostic) is not bool:
            raise ValueError('启停键或触发方式无效')

class OptionsStore:
    """Only user-chosen key and trigger are durable, never runtime permission."""
    def __init__(self, directory):
        self.path = Path(directory)/'toggle-preferences.json'
    def read(self):
        if not self.path.exists(): return ToggleOptions()
        try:
            with self.path.open('rb') as stream: data = _json(stream.read(1025), 1024)
            if set(data) != {'key','trigger'}: raise ValueError('unexpected fields')
            return ToggleOptions(**data)
        except (ValueError, OSError, TypeError): return ToggleOptions()
    def save(self, options):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps({'key':options.key,'trigger':options.trigger},ensure_ascii=False),encoding='utf-8')
        tmp.replace(self.path)

@dataclass(frozen=True)
class Keys:
    left: bool = False
    right: bool = False
    toggle: bool = False
    foreground: bool = True
    reload: bool = False
    changed: bool = False
    emergency: bool = False
    decrease: bool = False
    increase: bool = False
    def __post_init__(self):
        if any(type(v) is not bool for v in asdict(self).values()): raise ValueError('按键反馈格式无效')

class ToggleSession:
    def __init__(self, setting, options, step=5, shortcuts=False):
        if type(step) is not int or step not in (1,5,10) or type(shortcuts) is not bool: raise ValueError('步长无效')
        self.setting = Setting.from_record(setting.record())
        self.options = options
        self.step, self.shortcuts = step, shortcuts
        self.enabled = False
        self.previous = None
        self.last = None
        self.pending = None
        self.sequence = 0
        self.neutral_required = True
        self.burst = Burst(self.setting)
        self.reason = 'OFF'
        self.message = f'已准备，尚未开启：切回目标窗口，按一下 {options.key}'
        self.notice_until = 0.0
    def block(self):
        self.burst = Burst(self.setting)
        self.neutral_required = True
    def disable(self, reason, message):
        self.enabled = False
        self.pending = None
        self.block()
        self.reason, self.message = reason, message
    def acknowledge(self, sequence, setting):
        if (type(sequence) is not int or self.pending is None or sequence != self.sequence or
                self.pending.record() != setting.record()):
            raise ValueError('调节应答过期或不一致')
        self.setting = Setting.from_record(setting.record())
        self.pending = None
        self.block()
    def tick(self, now, keys):
        if not isinstance(keys, Keys): raise ValueError('按键快照无效')
        if isinstance(now,bool) or not isinstance(now,(int,float)) or not math.isfinite(now): raise ValueError('时钟无效')
        previous = self.previous
        if self.last is not None and (now < self.last or now-self.last > .100001):
            self.disable('SCHEDULER','调度中断：已关闭，没有补发。请停止其他任务后重新准备。')
            raise ValueError(self.message)
        self.last, self.previous = now, keys
        edge = previous is not None and keys.toggle and not previous.toggle
        if keys.emergency:
            self.disable('EMERGENCY',f'已急停；需要时回目标窗口重新按 {self.options.key}')
            return 0, None
        if not keys.foreground:
            self.disable('BACKGROUND',f'不在目标窗口，开关已关闭；回去后按 {self.options.key}')
            return 0, None
        if keys.changed:
            self.disable('CONDITIONS',f'背包/切枪/姿态键已按下，开关已关闭；核对配装后按 {self.options.key}')
            return 0, None
        if edge:
            if self.enabled:
                self.disable('OFF',f'已关闭；再按 {self.options.key} 开启')
            elif not previous.foreground or keys.left or keys.reload or keys.decrease or keys.increase:
                self.disable('RELEASE',f'先松开开火键及操作键，再按 {self.options.key} 开启')
            else:
                self.enabled = True
                self.block()
                self.reason, self.message = 'ON',f'已开启：松开启停键，然后正常开镜、开火；再按 {self.options.key} 关闭'
            return 0, None
        if keys.toggle:
            self.block()
            return 0, None
        if not self.enabled:
            return 0, None
        if keys.reload:
            self.block()
            self.reason, self.message = 'RELOAD','换弹键按下：本次暂停，开关保持开启；换好松手，再重新按开火'
            return 0, None
        if self.pending is not None:
            self.reason,self.message = 'SYNC','正在同步新力度；本次暂停输出'
            return 0, None
        if self.shortcuts and (keys.decrease or keys.increase):
            self.block()
            neutral_previous = previous is not None and not (previous.decrease or previous.increase)
            if keys.left or keys.right or not neutral_previous or (keys.decrease and keys.increase):
                self.reason,self.message = 'TUNE_BLOCKED','调节未采用：松开鼠标左右键，再单按 F5 或 F6'
                return 0,None
            rate = round(max(0.,min(400.,self.setting.rate+(-self.step if keys.decrease else self.step))),4)
            if rate != self.setting.rate:
                self.pending = replace(self.setting,rate=rate);self.sequence += 1
                return 0,{'sequence':self.sequence,'before':self.setting.record(),'after':self.pending.record()}
            return 0,None
        if self.neutral_required:
            if not keys.left:
                self.neutral_required = False
                self.burst.tick(now,left=False,right=False,enable=False)
            self.reason,self.message = 'READY','已开启：等待新一次开火；不用按住启停键'
            return 0,None
        right = keys.right or self.options.trigger == 'left'
        delta = self.burst.tick(now,left=keys.left,right=right,enable=True)
        if not keys.left:
            self.reason,self.message = 'READY','已开启，等待开火'
        elif not right:
            self.reason,self.message = 'RIGHT','检测到左键，但没有右键；默认需要按住右键。切换式开镜请改“仅左键”'
        elif self.burst.started is None or not self.burst.ready:
            self.reason,self.message = 'LIMIT',f'已到单次 {self.setting.duration:g} 秒上限；松开左键，再按可重新开始'
        else:
            self.reason,self.message = 'OUTPUT','仅诊断：不发送移动' if self.options.diagnostic else '已开启，正在按设定下拉；不证明游戏已接收'
        return delta,None

class ToggleRunner(QuickRunner):
    """Legacy mode remains testable; default GUI selects the new toggle mode."""
    def __init__(self, desktop_factory, toggle_factory=None):
        super().__init__(desktop_factory)
        self.toggle_factory = toggle_factory
        self.options = None
        self.report = self._empty_report()
    @staticmethod
    def _empty_report():
        return {'listening':False,'enabled':False,'reason':'OFF','keys':{},
                'attempted_events':0,'accepted_events':0,'accepted_counts':0,
                'diagnostic_steps':0,'system_error':None,'game_acceptance':'unknown'}
    def snapshot(self):
        with self.lock: return copy.deepcopy(self.report)
    def set_options(self, options):
        if options is not None and not isinstance(options,ToggleOptions): raise ValueError('选项无效')
        with self.lock:
            if self.active or (self.thread and self.thread.is_alive()): raise ValueError('先停止监听，再改启停设置')
            self.options = options
    def stop(self,message='监听已停止；点准备后，到目标窗口按启停键'):
        with self.lock:
            super().stop(message)
            if self.options is not None:
                if isinstance(self.controller,ToggleSession): self.controller.disable('STOPPED',message)
                self.report.update(listening=False,enabled=False,reason='STOPPED')
    def start(self,setting,target,consent):
        if self.options is None: return super().start(setting,target,consent)
        if consent is not True: raise ValueError('请先确认本次使用场景')
        if setting.rate <= 0: raise ValueError('力度为0，不会移动')
        if (not isinstance(target,dict) or set(target)!={'handle','pid','size'} or
            any(type(target.get(k)) is not int or target[k]<=0 for k in ('handle','pid')) or
            not isinstance(target['size'],list) or len(target['size'])!=2 or
            any(type(v) is not int or v<64 for v in target['size'])): raise ValueError('请先选择目标窗口')
        with self.lock:
            if self.thread and self.thread.is_alive(): raise ValueError('上一监听正在停止，请稍等再点准备')
            if self.toggle_factory is None:
                from .simple_toggle_desktop import ToggleDesktop
                self.toggle_factory = ToggleDesktop
            backend = self.toggle_factory()
            backend.inspect(target,check_size=False)
            self.cancel.clear();self.active=True;self.heartbeat=time.monotonic()
            self.session_id=uuid.uuid4().hex;self.events=[]
            self.controller=ToggleSession(setting,self.options,self.step,self.shortcuts)
            self.report=self._empty_report();self.report['listening']=True
            self.message=self.controller.message
            self.thread=threading.Thread(target=self._run_toggle,args=(backend,copy.deepcopy(target)),daemon=True)
            self.thread.start()
    def acknowledge(self,event,setting):
        if self.options is None: return super().acknowledge(event,setting)
        with self.lock:
            if (not self.active or self.cancel.is_set() or event['session_id'] != self.session_id): return False
            self.controller.acknowledge(event['sequence'],setting)
            self.message=f'已调为 {setting.rate:g}，尚未保存；松开左键，再重新试射'
            self.controller.message=self.message
            return True
    def _step_toggle(self,backend,target,now):
        with self.lock:
            self._check_alive()
            if not self.active: raise InterruptedError()
            keys = backend.sample(target,self.options)
            delta,event=self.controller.tick(now,keys)
            self.message=self.controller.message
            self.report.update(listening=True,enabled=self.controller.enabled,reason=self.controller.reason,keys=asdict(keys))
            if event:
                event['session_id']=self.session_id;self.events.append(event)
            if delta:
                fresh=backend.sample(target,self.options)
                if fresh != keys:
                    # Discard the remainder of this burst, never compensate a missed send.
                    self.controller.block()
                    self.report['reason']='CHANGED_BEFORE_SEND'
                    self.message='按键/焦点发生变化，本次不发送；请松开后重新开火'
                    return
                if self.options.diagnostic:
                    self.report['diagnostic_steps']+=1
                    return
                self.report['attempted_events']+=1
                try:
                    backend.send(target,delta,self.options)
                except Exception as exc:
                    self.report['system_error']=str(exc)
                    raise
                self.report['accepted_events']+=1
                self.report['accepted_counts']+=delta
    def _run_toggle(self,backend,target):
        try:
            # Binding uses first explicit in-target activation, not an arbitrary delay.
            bound=False
            while not self.cancel.is_set():
                self._check_alive()
                if not bound:
                    fresh=backend.inspect(target,check_size=False)
                    if backend.in_foreground(target):
                        target=fresh;bound=True
                self._step_toggle(backend,target,time.perf_counter())
                self.cancel.wait(.005)
        except InterruptedError: pass
        except Exception as exc:
            self.stop(str(exc))
            with self.lock: self.report.update(reason='ERROR',system_error=str(exc))
        finally:
            with self.lock:
                self.active=False;self.cancel.set();self.report.update(listening=False,enabled=False)
