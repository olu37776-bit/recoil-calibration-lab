"""Manual editing helpers. No screenshots, runtime commands or input permissions."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .simple_core import Setting

MAX_PORTABLE_BYTES = 32_768


def clone(setting: Setting) -> Setting:
    return Setting.from_record(setting.record())


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('配置文件包含重复字段，未载入')
        result[key] = value
    return result


def _json(raw: bytes, limit: int) -> dict:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= limit:
        raise ValueError('配置文件为空或超过大小限制')
    try:
        data = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('配置文件不是有效的 UTF-8 JSON，未载入') from exc
    if not isinstance(data, dict):
        raise ValueError('配置文件必须是对象')
    return data


def export_setting(setting: Setting) -> bytes:
    """Export exactly one manual setting, never a target, permission or image."""
    data = {'format': 'recoil-simple-setting-v1', 'setting': clone(setting).record()}
    return (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def import_setting(raw: bytes) -> Setting:
    data = _json(raw, MAX_PORTABLE_BYTES)
    if set(data) != {'format', 'setting'} or data['format'] != 'recoil-simple-setting-v1':
        raise ValueError('请选择简易版导出的单套手动配置；不读取脚本或旧版曲线')
    return Setting.from_record(data['setting'])


def read_setting(path: str | Path) -> Setting:
    with Path(path).open('rb') as stream:
        return import_setting(stream.read(MAX_PORTABLE_BYTES + 1))


def write_setting(path: str | Path, setting: Setting) -> None:
    raw = export_setting(setting)
    target = Path(path)
    temporary = target.with_name(target.name + '.tmp')
    temporary.write_bytes(raw)
    temporary.replace(target)


class Preferences:
    """Only remembers an existing saved preset key; never persists runtime state."""
    def __init__(self, directory: str | Path):
        self.path = Path(directory) / 'simple-selection.json'
        self.warning = ''

    def read(self) -> str | None:
        if not self.path.exists():
            return None
        try:
            with self.path.open('rb') as stream:
                data = _json(stream.read(1025), 1024)
            if (set(data) != {'schema', 'last_saved_key'} or type(data['schema']) is not int
                    or data['schema'] != 1 or not isinstance(data['last_saved_key'], str)
                    or re.fullmatch('[0-9a-f]{64}', data['last_saved_key']) is None):
                raise ValueError('上次选择格式无效')
            return data['last_saved_key']
        except (OSError, ValueError):
            self.warning = '上次选择无法读取；已保留原文件，请从已保存配置手动选择。'
            return None

    def remember(self, setting: Setting) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps({'schema': 1, 'last_saved_key': setting.key}, sort_keys=True) + '\n'
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(raw, encoding='utf-8')
        temporary.replace(self.path)


class EditHistory:
    """Session-local undo and one subjective reference, not verification evidence."""
    def __init__(self, current: Setting):
        self.reset(current)

    def reset(self, current: Setting) -> None:
        self.current = clone(current)
        self.previous: list[Setting] = []
        self.reference: Setting | None = None

    def change(self, setting: Setting) -> None:
        incoming = clone(setting)
        if incoming.record() == self.current.record():
            return
        self.previous.append(clone(self.current))
        self.previous = self.previous[-30:]
        if incoming.key != self.current.key:
            self.reference = None
        self.current = incoming

    def undo(self) -> Setting:
        if not self.previous:
            raise ValueError('还没有可撤销的调节')
        previous = self.previous.pop()
        if previous.key != self.current.key:
            self.reference = None
        self.current = clone(previous)
        return clone(self.current)

    def remember_reference(self) -> None:
        self.reference = clone(self.current)

    def restore_reference(self) -> Setting:
        if self.reference is None or self.reference.key != self.current.key:
            raise ValueError('请先记住当前配装的一份满意参数')
        self.change(self.reference)
        return clone(self.current)

    def reference_text(self) -> str:
        if self.reference is None:
            return '可先记住一份手感，再继续调；它不是自动验证结果。'
        return (f'本次记住：力度 {self.reference.rate:g} / {self.reference.duration:g}秒；'
                f'当前力度差 {self.current.rate - self.reference.rate:+g}。改配装后需重新记住。')


def setting_caption(setting: Setting) -> str:
    c = setting.conditions
    return f"{c['weapon']} · {c['pose']} · {c['weight']} · {c['sight']} · 力度{setting.rate:g}"


def validate_catalog_setting(setting: Setting, catalog: dict) -> None:
    """Reject unavailable imported options before changing any visible fields."""
    c = setting.conditions
    weapon = next((w for w in catalog['weapons'].values() if w['name'] == c['weapon']), None)
    if weapon is None:
        raise ValueError('配置中的枪械不在当前目录，原配置未改动')
    for slot, ids in weapon['compatibility'].items():
        options = {'未装 / 未记录'} | {catalog['parts'][key]['name'] for key in ids}
        if c[slot] not in options:
            raise ValueError(f'配置中的 {slot} 与这把枪不兼容，原配置未改动')
    ammo = {'未装 / 未记录'} | {a['name'] for a in catalog['ammo'].values() if a['caliber'] == weapon['caliber']}
    if c['ammo'] not in ammo or c['pose'] not in {'站姿', '蹲姿', '卧姿'}:
        raise ValueError('配置中的弹药或姿态无效，原配置未改动')
