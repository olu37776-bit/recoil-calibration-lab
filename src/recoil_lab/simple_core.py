"""Manual settings and bounded playback, separate from calibrated profiles."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import copy
import hashlib
import json
import math
import os
import threading
import time

VERSION = '1.5.1-rc1'
SOURCE = 'manual-user-v1'
LABELS = ('weapon','sight','muzzle','underbarrel','magazine','ammo','pose','weight','notes')

def number(value, minimum, maximum, label):
    if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f'{label}须为 {minimum}～{maximum} 的有限数值')
    return float(value)

@dataclass(frozen=True)
class Setting:
    conditions: dict
    rate: float = 20.0
    duration: float = 2.0
    def __post_init__(self):
        if not isinstance(self.conditions,dict) or set(self.conditions) != set(LABELS):
            raise ValueError('配装字段不完整')
        if any(not isinstance(v,str) or len(v)>256 for v in self.conditions.values()):
            raise ValueError('配装标签须为不超过256字的文本')
        if not self.conditions['weapon'].strip(): raise ValueError('请选择枪械')
        object.__setattr__(self,'conditions',copy.deepcopy(self.conditions))
        number(self.rate,0,400,'下拉力度')
        number(self.duration,.5,6,'单轮时长')
    @property
    def key(self):
        raw=json.dumps(self.conditions,ensure_ascii=False,sort_keys=True).encode('utf-8')
        return hashlib.sha256(raw).hexdigest()
    def record(self):
        return {'source':SOURCE,'game_verified':False,**asdict(self)}
    @classmethod
    def from_record(cls, record):
        if not isinstance(record,dict) or set(record) != {'source','game_verified','conditions','rate','duration'}:
            raise ValueError('不是本简易版的手动配置')
        if record['source'] != SOURCE or record['game_verified'] is not False:
            raise ValueError('不能把其他曲线或验证状态当成手动配置')
        return cls(record['conditions'],record['rate'],record['duration'])

class Store:
    """Dedicated storage; never persist a window handle or input authorization."""
    def __init__(self, directory=None):
        self.directory=Path(directory or Path(os.environ.get('LOCALAPPDATA',Path.home()))/'RecoilLabSimple')
        self.path=self.directory/'manual-presets.json'
        self.data={'schema':1,'records':{}}
        if self.path.exists():
            if self.path.stat().st_size>4_000_000: raise ValueError('配置文件异常大，已保留原文件')
            data=json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(data,dict) or set(data)!={'schema','records'} or data['schema']!=1 or not isinstance(data['records'],dict):
                raise ValueError('配置文件格式不正确，未覆盖原文件')
            for key, versions in data['records'].items():
                if not isinstance(versions,list) or not 1<=len(versions)<=50: raise ValueError('历史版本无效')
                for record in versions:
                    if Setting.from_record(record).key!=key: raise ValueError('配装指纹不匹配')
            self.data=data
    def save(self, setting):
        new=copy.deepcopy(self.data)
        versions=new['records'].setdefault(setting.key,[])
        if not versions or versions[-1]!=setting.record():
            versions.append(setting.record()); del versions[:-50]
        text=json.dumps(new,ensure_ascii=False,indent=2,allow_nan=False)
        if len(text.encode('utf-8'))>4_000_000: raise ValueError('配置库已满，未覆盖原文件')
        self.directory.mkdir(parents=True,exist_ok=True)
        tmp=self.path.with_suffix('.tmp')
        tmp.write_text(text,encoding='utf-8')
        tmp.replace(self.path); self.data=new
    def items(self):
        return [(key,Setting.from_record(records[-1])) for key,records in self.data['records'].items()]
    def previous(self, key):
        records=self.data['records'].get(key,[])
        if len(records)<2: raise ValueError('这一配装还没有上一个保存版本')
        return Setting.from_record(records[-2])

class Burst:
    """Pure state machine: fresh presses, cumulative quantization, no catch-up."""
    def __init__(self, setting):
        self.setting=setting; self.last=None; self.started=None; self.emitted=0; self.ready=False
    def tick(self, now, *, left, right, enable):
        if not isinstance(now,(float,int)) or not math.isfinite(now): raise ValueError('时钟无效')
        if self.last is not None and (now<self.last or now-self.last>.100001):
            self.ready=False;self.started=None;raise ValueError('调度中断，已停止，不补发')
        self.last=now
        if not left:
            self.ready=True;self.started=None;self.emitted=0;return 0
        if not right or not enable:
            self.ready=False;self.started=None;self.emitted=0;return 0
        if not self.ready: return 0
        if self.started is None: self.started=now
        elapsed=now-self.started
        target=round(self.setting.rate*min(elapsed,self.setting.duration))
        delta=target-self.emitted
        if not 0<=delta<=32:
            self.ready=False;self.started=None;raise ValueError('单次移动过大，已停止，不补发')
        self.emitted=target
        if elapsed>=self.setting.duration:
            self.ready=False;self.started=None
        return delta

class Runner:
    """Explicit short test session; stop shares the lock with every send."""
    def __init__(self, desktop_factory):
        self.factory=desktop_factory;self.lock=threading.RLock();self.cancel=threading.Event()
        self.thread=None;self.message='未启用';self.heartbeat=time.monotonic();self.active=False
    def pulse(self):
        with self.lock: self.heartbeat=time.monotonic();return self.message
    def stop(self, message='已停止；再次使用需点开始'):
        with self.lock:
            self.cancel.set();self.active=False;self.message=message
    def start(self, setting, target, consent):
        if consent is not True: raise ValueError('请先确认仅在允许的受控环境中试用')
        if setting.rate<=0: raise ValueError('力度为0，不会移动；请先调高一点')
        if not isinstance(target,dict) or set(target)!={'handle','pid','size'}: raise ValueError('请刷新并选择目标窗口')
        if type(target['handle']) is not int or target['handle']<=0 or type(target['pid']) is not int or target['pid']<=0:
            raise ValueError('目标窗口无效')
        if not isinstance(target['size'],list) or len(target['size'])!=2 or any(type(x) is not int or x<64 for x in target['size']):
            raise ValueError('目标尺寸无效')
        with self.lock:
            if self.thread and self.thread.is_alive(): raise ValueError('上一任务正在停止，请稍等再点开始')
            backend=self.factory();backend.check(target,foreground=False)
            self.cancel.clear();self.active=True;self.heartbeat=time.monotonic()
            self.message='5秒准备：切到所选窗口，先松开左键'
            self.thread=threading.Thread(target=self._run,args=(backend,Setting.from_record(setting.record()),copy.deepcopy(target)),daemon=True)
            self.thread.start()
    def _check_alive(self):
        if self.cancel.is_set(): raise InterruptedError()
        if time.monotonic()-self.heartbeat>.5: raise ValueError('界面无响应，已停止')
    def _send(self, backend, target, delta):
        with self.lock:
            self._check_alive();backend.check(target)
            left,right,enable=backend.keys()
            if not left or not right or not enable: raise ValueError('使能已松开，已停止')
            if not self.active: raise InterruptedError()
            backend.move(delta)
    def _run(self, backend, setting, target):
        try:
            for i in range(50):
                self._check_alive();backend.check(target,foreground=False)
                with self.lock:
                    if self.cancel.is_set():raise InterruptedError()
                    self.message=f'{5-i//10}秒准备：切到所选窗口，先松开左键'
                if self.cancel.wait(.1): raise InterruptedError()
            target=backend.acquire(target)
            deadline=time.monotonic()+120;burst=Burst(setting)
            self.message='等待试射：按住 F7＋右键＋左键；单轮结束后先松开左键'
            while time.monotonic()<deadline:
                self._check_alive();backend.check(target)
                left,right,enable=backend.keys()
                delta=burst.tick(time.perf_counter(),left=left,right=right,enable=enable)
                if delta: self._send(backend,target,delta)
                with self.lock:
                    if not self.cancel.is_set():
                        self.message=('下拉中；F8 / Esc 急停' if delta else '待命：F7＋右键＋左键；释放左键后可开始下一轮')
                if self.cancel.wait(.005): raise InterruptedError()
            self.stop('本次120秒试用结束；需要时重新开始')
        except InterruptedError:
            pass
        except Exception as exc:
            self.stop(str(exc))
        finally:
            with self.lock: self.active=False; self.cancel.set()

def impact_summary(aim, points):
    if not points: return '先点原始瞄准位置，再点弹孔；只做静态效果反馈'
    if aim is None: raise ValueError('先标原始瞄准点')
    coords=[aim]+list(points)
    if any(len(p)!=2 or any(not isinstance(v,(float,int)) or not math.isfinite(v) for v in p) for p in coords):
        raise ValueError('坐标无效')
    dx=sum(p[0]-aim[0] for p in points)/len(points)
    dy=sum(p[1]-aim[1] for p in points)/len(points)
    return f'已标 {len(points)} 个弹孔：中心相对原始瞄准点，横向 {dx:+.1f}px，纵向 {dy:+.1f}px（负=偏上）。不是逐发后坐轨迹。'
