import json
from dataclasses import replace

import pytest

from recoil_lab.simple_core import LABELS, SOURCE, Setting, Store
from recoil_lab.simple_tuning import (EditHistory, Preferences, export_setting, import_setting,
                                      read_setting, write_setting, validate_catalog_setting)


def setting(rate=20, **conditions):
    c = dict.fromkeys(LABELS, '')
    c.update(weapon='Galil', pose='站姿', weight='未记录', **conditions)
    return Setting(c, rate)


def test_undo_is_not_save_or_verification():
    h = EditHistory(setting())
    h.change(setting(21)); h.change(setting(26))
    assert h.undo().rate == 21
    assert h.undo().rate == 20
    with pytest.raises(ValueError): h.undo()
    assert h.current.record()['source'] == SOURCE
    assert h.current.record()['game_verified'] is False


def test_identical_edit_no_extra_undo():
    h = EditHistory(setting()); h.change(setting())
    assert not h.previous


def test_history_limit():
    h = EditHistory(setting())
    for value in range(21, 70): h.change(setting(value))
    assert len(h.previous) == 30


def test_remember_compare_restore():
    h = EditHistory(setting()); h.remember_reference(); h.change(setting(25))
    assert '+5' in h.reference_text()
    assert h.restore_reference().rate == 20
    assert h.undo().rate == 25
    assert h.reference.rate == 20


@pytest.mark.parametrize('field,value', [('pose', '蹲姿'), ('weight', '30公斤'), ('weapon', 'M249'),
                                         ('muzzle', '替换枪口'), ('notes', '新的灵敏度')])
def test_condition_change_clears_comparison(field, value):
    h = EditHistory(setting()); h.remember_reference()
    h.change(Setting({**h.current.conditions, field: value}, 25))
    assert h.reference is None
    with pytest.raises(ValueError): h.restore_reference()


def test_duration_change_keeps_same_condition_reference():
    h = EditHistory(setting()); h.remember_reference(); h.change(replace(setting(), duration=1))
    assert h.reference.duration == 2
    assert h.restore_reference().duration == 2


def test_clone_isolation():
    s = setting(); h = EditHistory(s); s.conditions['weight'] = 'mutated'
    assert h.current.conditions['weight'] == '未记录'
    h.remember_reference(); h.change(setting(21)); h.current.conditions['notes'] = 'mutable current'
    assert h.reference.conditions['notes'] == ''


def test_new_preset_resets_reference_and_undo():
    h = EditHistory(setting()); h.remember_reference(); h.change(setting(22))
    h.reset(setting(30))
    assert h.current.rate == 30 and not h.previous and h.reference is None


@pytest.mark.parametrize('rate', [0, 0.25, 20, 21, 399, 400])
def test_portable_roundtrip(rate, tmp_path):
    s = setting(rate, notes='灵敏度由用户填写')
    p = tmp_path/'配装.json'; write_setting(p, s)
    assert read_setting(p).record() == s.record()
    assert not p.with_name(p.name+'.tmp').exists()
    assert import_setting(export_setting(s)).record() == s.record()
    assert import_setting(b'\xef\xbb\xbf' + export_setting(s)).record() == s.record()


@pytest.mark.parametrize('raw', [b'', b'{', b'[]', b'{}', b'\xff', b'X' * 32769,
                                 b'{"format":"a","format":"b"}', b'[' * 1000 + b']' * 1000])
def test_bad_portable(raw):
    with pytest.raises(ValueError): import_setting(raw)


@pytest.mark.parametrize('key,value', [('consent', True), ('handle', 123), ('script', 'anything'),
                                      ('game_verified', True), ('source', 'recorded'), ('rate', float('nan'))])
def test_untrusted_record_rejected(key, value):
    data = json.loads(export_setting(setting())); data['setting'][key] = value
    with pytest.raises(ValueError): import_setting(json.dumps(data).encode())


def test_nested_duplicate_rejected():
    raw = export_setting(setting()).replace(b'"rate": 20,', b'"rate": 20, "rate": 100,')
    assert raw != export_setting(setting())
    with pytest.raises(ValueError): import_setting(raw)


def test_import_does_not_save_or_mutate_store(tmp_path):
    store = Store(tmp_path); store.save(setting())
    before = store.path.read_bytes()
    candidate = import_setting(export_setting(setting(30)))
    assert candidate.rate == 30 and store.path.read_bytes() == before


def test_preference_only_saved_key(tmp_path):
    p = Preferences(tmp_path); s = setting()
    assert p.read() is None
    p.remember(s)
    assert Preferences(tmp_path).read() == s.key
    assert set(json.loads(p.path.read_text())) == {'schema', 'last_saved_key'}


@pytest.mark.parametrize('data', [{'schema': 1, 'last_saved_key': 'bad'}, {'schema': True, 'last_saved_key': 'a'*64},
                                 {'schema': 1, 'last_saved_key': 'a'*64, 'consent': True}, [], 'not json'])
def test_bad_preference_preserved(tmp_path, data):
    p = Preferences(tmp_path); raw = json.dumps(data); p.path.write_text(raw)
    assert p.read() is None and p.warning
    assert p.path.read_text() == raw


def test_oversized_preference_preserved(tmp_path):
    p = Preferences(tmp_path); p.path.write_bytes(b'a'*2000)
    assert p.read() is None and len(p.path.read_bytes()) == 2000


def test_legacy_presets_readable(tmp_path):
    original = Store(tmp_path); original.save(setting())
    before = original.path.read_bytes()
    Preferences(tmp_path).remember(setting())
    assert Store(tmp_path).items()[0][1].record() == setting().record()
    assert original.path.read_bytes() == before


def catalog_setting():
    from recoil_lab.catalog import public_catalog
    c = dict.fromkeys(LABELS, '未装 / 未记录'); c.update(weapon='Galil', pose='站姿', weight='轻装', notes='')
    return Setting(c), public_catalog()


def test_catalog_valid_before_apply():
    s, catalog = catalog_setting(); validate_catalog_setting(s, catalog)


@pytest.mark.parametrize('key,value', [('weapon', 'unknown'), ('sight', 'unknown'), ('ammo', 'unknown'),
                                      ('pose', 'unknown'), ('underbarrel', 'unknown')])
def test_bad_catalog(key, value):
    s, catalog = catalog_setting()
    with pytest.raises(ValueError): validate_catalog_setting(Setting({**s.conditions, key: value}), catalog)
