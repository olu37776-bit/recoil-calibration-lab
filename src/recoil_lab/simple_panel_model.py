"""Two-screen product model. Readiness never enables output; the hotkey does."""
from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
import copy
import json

from .simple_core import Setting
from .simple_toggle import ToggleOptions
from .simple_tuning import EditHistory, _json, validate_catalog_setting

DEFAULT_TITLES = ('WARDOGS', '战狗')


def title_valid(title):
    return (isinstance(title, str) and 0 < len(title) <= 256
            and not any(ord(c) < 32 for c in title)
            and title == title.strip())


class TargetRule:
    """Remember only an exact title. Never reuse a handle or persisted PID."""
    def __init__(self, directory):
        self.path = Path(directory) / 'panel-target.json'
        self.title = ''
        self.warning = ''
        if self.path.exists():
            try:
                with self.path.open('rb') as f:
                    data = _json(f.read(2049), 2048)
                if set(data) != {'title'} or not title_valid(data['title']):
                    raise ValueError('窗口规则无效')
                self.title = data['title']
            except (ValueError, OSError, TypeError):
                self.warning = '窗口设置未读取；请重新选择，不会使用损坏的记录。'

    def save(self, title):
        if not title_valid(title):
            raise ValueError('窗口名称无效')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps({'title': title}, ensure_ascii=False), encoding='utf-8')
        tmp.replace(self.path)
        self.title = title

    def reset(self):
        if self.path.exists():
            self.path.unlink()
        self.title = ''

    def resolve(self, windows):
        allowed = (self.title,) if self.title else DEFAULT_TITLES
        candidates = [(title, info) for title, info in windows if title in allowed]
        if not candidates:
            return None, '未找到游戏窗口；先打开游戏，或在“键位与窗口”中选择一次。'
        if len(candidates) != 1:
            return None, '找到多个同名窗口，暂不启用；请关闭重复窗口后再试。'
        title, info = candidates[0]
        if (not isinstance(info, dict) or set(info) != {'handle', 'pid', 'size'}
                or any(type(info.get(k)) is not int or info[k] <= 0 for k in ('handle', 'pid'))
                or not isinstance(info['size'], list) or len(info['size']) != 2
                or any(type(n) is not int or n < 64 for n in info['size'])):
            return None, '游戏窗口不可用；请打开正常大小的游戏窗口。'
        return copy.deepcopy(info), title


class PanelDraft:
    """An editable copy with explicit save. The running draft is never auto-saved."""
    def __init__(self, store, catalog):
        self.store, self.catalog = store, catalog
        self.edit = None
        self.origin = None

    @property
    def current(self):
        return self.edit.current if self.edit else None

    @property
    def dirty(self):
        if self.current is None:
            return False
        saved = dict(self.store.items()).get(self.current.key)
        return saved is None or saved.record() != self.current.record()

    def load(self, setting):
        validate_catalog_setting(setting, self.catalog)
        self.edit = EditHistory(setting)
        self.origin = Setting.from_record(setting.record())

    def change(self, setting):
        validate_catalog_setting(setting, self.catalog)
        if self.edit is None:
            self.load(setting)
        else:
            self.edit.change(setting)

    def adjust(self, delta):
        if self.current is None:
            raise ValueError('请先选择配置')
        self.change(replace(self.current, rate=round(max(0, min(400, self.current.rate + delta)), 4)))
        return self.current

    def save(self):
        if self.current is None:
            raise ValueError('请先选择配置')
        self.store.save(self.current)
        self.origin = Setting.from_record(self.current.record())
        return self.current

    def copy_as(self, name):
        if self.current is None or not isinstance(name, str) or not 0 < len(name.strip()) <= 256:
            raise ValueError('请输入配置名称')
        conditions = dict(self.current.conditions)
        conditions['notes'] = name.strip()
        setting = replace(self.current, conditions=conditions)
        if setting.key in dict(self.store.items()):
            raise ValueError('已有同名同条件配置，请换一个名称，原配置不会覆盖。')
        self.load(setting)
        return setting


class AutoReady:
    """Keep one OFF listener in sync with the selected setting; never auto-arm.

    A new desired binding replaces the old listener after its thread stops.
    Runtime errors are latched for this binding, not retried continuously.
    """
    def __init__(self, runner):
        self.runner = runner
        self.desired = None
        self.pending = None
        self.bound = None
        self.error = ''
        self.closed = False

    @staticmethod
    def signature(setting, target, options, shortcuts, step):
        if setting is None or target is None or setting.rate <= 0:
            return None
        return json.dumps({'setting': setting.record(), 'target': {k:target[k] for k in ('handle','pid')},
                           'options': asdict(options), 'shortcuts': shortcuts, 'step': step},
                          sort_keys=True, ensure_ascii=False)

    def update(self, setting, target, options, *, shortcuts=False, step=5):
        if self.closed:
            return
        signature = self.signature(setting, target, options, shortcuts, step)
        if signature != self.desired:
            self.runner.stop('已关闭；新配置就绪后按启停键开启')
            self.desired = signature
            self.bound = None
            self.pending = (Setting.from_record(setting.record()), copy.deepcopy(target), options, shortcuts, step) if signature else None
            self.error = ''
        if self.error or self.pending is None:
            return
        if self.runner.thread and self.runner.thread.is_alive():
            return
        args, self.pending = self.pending, None
        try:
            setting, target, options, shortcuts, step = args
            self.runner.take_events()  # Old-session events never apply to the new draft.
            self.runner.configure(shortcuts, step)
            self.runner.set_options(options)
            # This creates an OFF listener only. A fresh hotkey press in the
            # chosen foreground is the user's actual activation/authorization.
            self.runner.start(setting, target, True)
            self.bound = signature
        except Exception as exc:
            self.runner.stop(str(exc))
            self.error = str(exc)

    def accept_edit(self, setting, target, options, *, shortcuts=False, step=5):
        """After an exact acknowledged F5/F6 edit, don't restart the listener."""
        self.desired = self.bound = self.signature(setting, target, options, shortcuts, step)

    def disable(self, message='已关闭；按启停键开启'):
        with self.runner.lock:
            controller = self.runner.controller
            if controller is not None and self.runner.active:
                controller.disable('OFF', message)
                self.runner.message = message
                self.runner.report.update(enabled=False, reason='OFF')

    def retry(self):
        self.runner.stop('重试监听，输出仍关闭')
        self.desired = None
        self.bound = None
        self.pending = None
        self.error = ''

    def close(self):
        self.closed = True
        self.pending = None
        self.runner.stop('已退出')
