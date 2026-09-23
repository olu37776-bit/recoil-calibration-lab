"""Explicit between-burst edits; never edit while firing or infer game state."""
from __future__ import annotations

from dataclasses import replace
import copy
import math
import time
import uuid

from .simple_core import Burst, Runner, Setting


def _keys(values, length):
    if not isinstance(values, tuple) or len(values) != length or any(type(v) is not bool for v in values):
        raise ValueError('按键反馈无效，已停止')
    return values


class QuickSession:
    """Pure handshake: neutral -> key edge -> UI ack -> neutral -> new burst."""
    def __init__(self, setting: Setting, step: int):
        if type(step) is not int or step not in (1, 5, 10):
            raise ValueError('快捷调节步长只能是1、5或10')
        self.setting = Setting.from_record(setting.record())
        self.step = step
        self.burst = Burst(self.setting)
        self.pending = None
        self.sequence = 0
        self.neutral_required = True
        self.previous_keys = None
        self.message = '先松开 F7、左右键和 F5/F6，再主动开始'
        self.notice_until = 0.0
        self.last = None

    def block(self):
        self.burst = Burst(self.setting)
        self.neutral_required = True

    def acknowledge(self, sequence: int, setting: Setting):
        if type(sequence) is not int or self.pending is None or sequence != self.sequence:
            raise ValueError('调节应答已过期，未采用')
        if self.pending.record() != setting.record():
            raise ValueError('界面参数与待采用参数不一致，已停止')
        self.setting = Setting.from_record(setting.record())
        self.pending = None
        self.block()

    def tick(self, now: float, keys: tuple, tuning: tuple):
        if (isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now)
                or (self.last is not None and (now < self.last or now-self.last > .100001))):
            self.block()
            raise ValueError('调节时钟或调度无效，已停止')
        self.last = now
        left, right, enable = _keys(keys, 3)
        decrease, increase = _keys(tuning, 2)
        previous = self.previous_keys
        self.previous_keys = tuning
        neutral = not any(keys) and not any(tuning)
        if self.pending is not None:
            self.message = '调节已暂停输出，等待主界面确认新力度'
            return 0, None
        if self.neutral_required:
            if neutral:
                self.neutral_required = False
                self.burst = Burst(self.setting)
                self.burst.tick(now, left=False, right=False, enable=False)
            return 0, None
        if any(tuning):
            self.block()
            if previous != (False, False):
                return 0, None
            if any(keys) or (decrease and increase):
                self.message = '本次调节未采用：请松开 F7 和左右键，再单按 F5 或 F6'
                self.notice_until = now + 2.0
                return 0, None
            rate = round(max(0.0, min(400.0, self.setting.rate + (-self.step if decrease else self.step))), 4)
            if rate == self.setting.rate:
                self.message = f'力度已到边界 {rate:g}，没有继续更改'
                self.notice_until = now + 2.0
                return 0, None
            self.pending = replace(self.setting, rate=rate)
            self.sequence += 1
            return 0, {'sequence': self.sequence, 'before': self.setting.record(), 'after': self.pending.record()}
        delta = self.burst.tick(now, left=left, right=right, enable=enable)
        if now >= self.notice_until:
            if left and right and enable and self.burst.started is not None:
                self.message = f'试射中 · 力度 {self.setting.rate:g} · F8 / Esc 急停'
            elif left:
                self.message = '等待松开左键；不会自动继续上一梭'
            else:
                self.message = f'待命 · 力度 {self.setting.rate:g} · 松手后 F5− / F6＋'
        return delta, None


class QuickRunner(Runner):
    """Uses the original send/stop lock and safety checks; extra mode is opt-in."""
    def __init__(self, desktop_factory):
        super().__init__(desktop_factory)
        self.shortcuts = False
        self.step = 5
        self.controller = None
        self.events = []
        self.session_id = None

    def configure(self, enabled: bool, step: int):
        if type(enabled) is not bool or type(step) is not int or step not in (1, 5, 10):
            raise ValueError('快捷调节设置无效')
        with self.lock:
            if self.active or (self.thread and self.thread.is_alive()):
                raise ValueError('请先停止当前试调，再更改快捷调节选项')
            if self.events:
                raise ValueError('上次调节尚未同步，请稍等再开始')
            self.shortcuts = enabled
            self.step = step
            self.controller = None
            self.session_id = uuid.uuid4().hex

    def take_events(self):
        with self.lock:
            events, self.events = self.events, []
            return copy.deepcopy(events)

    def acknowledge(self, event: dict, setting: Setting):
        with self.lock:
            if not self.active or self.cancel.is_set() or event['session_id'] != self.session_id:
                return False
            try:
                self.controller.acknowledge(event['sequence'], setting)
                self.message = f'已调为 {setting.rate:g}，尚未保存；松开全部三键后再试射'
                self.controller.message = self.message
                self.controller.notice_until = time.perf_counter() + 2.0
            except Exception:
                self.stop('调节同步失败，已停止；请回主界面确认')
                raise
            return True

    def _step(self, backend, target, now):
        with self.lock:
            self._check_alive()
            if not self.active:
                raise InterruptedError()
            backend.check(target)
            keys = backend.keys()
            tuning = (backend.down(0x74), backend.down(0x75))
            delta, event = self.controller.tick(now, keys, tuning)
            if event is not None:
                event['session_id'] = self.session_id
                self.events.append(event)
            self.message = self.controller.message
            if delta:
                # Never send a precomputed step after a newly pressed adjustment key.
                if backend.down(0x74) or backend.down(0x75):
                    self.controller.block()
                    self.message = '调节键已按下，本梭停止；松手后重新调节'
                    return
                self._send(backend, target, delta)

    def _run(self, backend, setting, target):
        if not self.shortcuts:
            return super()._run(backend, setting, target)
        try:
            for i in range(50):
                self._check_alive()
                backend.check(target, foreground=False)
                with self.lock:
                    if self.cancel.is_set():
                        raise InterruptedError()
                    self.message = f'{5-i//10}秒准备：切回所选窗口；全部按键先松开'
                if self.cancel.wait(.1):
                    raise InterruptedError()
            target = backend.acquire(target)
            with self.lock:
                self._check_alive()
                self.controller = QuickSession(setting, self.step)
            deadline = time.monotonic() + 120
            last = time.perf_counter()
            while time.monotonic() < deadline:
                now = time.perf_counter()
                if now < last or now-last > .100001:
                    raise ValueError('调度中断，已停止，不补发')
                last = now
                self._step(backend, target, now)
                if self.cancel.wait(.005):
                    raise InterruptedError()
            self.stop('本次120秒试调结束；当前调节已同步，回主界面保存')
        except InterruptedError:
            pass
        except Exception as exc:
            self.stop(str(exc))
        finally:
            with self.lock:
                self.active = False
                self.cancel.set()
