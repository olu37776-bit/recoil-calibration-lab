from dataclasses import replace
import json
import pytest
from recoil_lab.simple_core import Store, Setting, LABELS
from recoil_lab.simple_panel_model import TargetRule, PanelDraft, AutoReady
from recoil_lab.simple_toggle import ToggleOptions
from recoil_lab.simple_panel_selftest import TestRunner as StubRunner, TARGET
from recoil_lab.catalog import public_catalog
from recoil_lab.simple_tuning import import_setting, export_setting


def preset():
    cat=public_catalog();w=next(iter(cat['weapons'].values()))
    c={k:'未装 / 未记录' for k in LABELS}
    c.update(weapon=w['name'],pose='站姿',weight='未记录',notes='测试')
    return Setting(c,100,.5)


def test_auto_ready_then_exactly_one_key_on(tmp_path):
    r=StubRunner();a=AutoReady(r);s=preset();opt=ToggleOptions(trigger='left')
    a.update(s,TARGET,opt)
    assert r.active and not r.controller.enabled and not r.backend.events
    r.activate();r.tick(left=True);r.tick(left=True)
    assert r.backend.events and r.controller.enabled
    r.tick(toggle=True)
    assert not r.controller.enabled


def test_same_config_does_not_restart_listener():
    r=StubRunner();a=AutoReady(r);s=preset();o=ToggleOptions()
    for _ in range(30):a.update(s,TARGET,o)
    assert r.starts==1
    r.activate();a.update(s,TARGET,o);assert r.controller.enabled


def test_different_config_disables_without_prepare():
    r=StubRunner();a=AutoReady(r);s=preset();o=ToggleOptions()
    a.update(s,TARGET,o);r.activate()
    a.update(replace(s,rate=101),TARGET,o)
    assert r.starts==2 and not r.controller.enabled and r.controller.setting.rate==101


def test_no_target_no_setting_no_movement():
    r=StubRunner();a=AutoReady(r);s=preset();o=ToggleOptions()
    a.update(s,None,o);assert not r.active
    a.update(None,TARGET,o);assert not r.active
    a.update(replace(s,rate=0),TARGET,o);assert not r.active


def test_stop_synchronizes_with_next_send():
    r=StubRunner();a=AutoReady(r);a.update(preset(),TARGET,ToggleOptions(trigger='left'))
    r.activate();r.tick(left=True);r.tick(left=True);count=len(r.backend.events)
    a.disable();r.tick(left=True)
    assert len(r.backend.events)==count and not r.controller.enabled
    assert r.active  # F9 can be used again, no prepare button.


def test_start_error_is_not_retried_forever():
    r=StubRunner();a=AutoReady(r);calls=[]
    def fail(*args):calls.append(1);raise ValueError('backend error')
    r.start=fail
    for _ in range(10):a.update(preset(),TARGET,ToggleOptions())
    assert len(calls)==1 and a.error
    a.retry();a.update(preset(),TARGET,ToggleOptions());assert len(calls)==2


def test_runtime_error_not_silently_restarted():
    r=StubRunner();a=AutoReady(r);s=preset();o=ToggleOptions()
    a.update(s,TARGET,o);r.stop('Windows拒绝')
    for _ in range(5):a.update(s,TARGET,o)
    assert r.starts==1 and not r.active


def test_old_session_edits_discarded_on_configuration_change():
    r=StubRunner();a=AutoReady(r);s=preset();o=ToggleOptions()
    a.update(s,TARGET,o,shortcuts=True);r.activate();r.tick(increase=True)
    assert r.events
    a.update(replace(s,rate=50),TARGET,o)
    assert not r.events and r.controller.setting.rate==50 and not r.controller.enabled


def test_acknowledged_draft_edit_does_not_restart():
    r=StubRunner();a=AutoReady(r);s=preset();o=ToggleOptions()
    a.update(s,TARGET,o,shortcuts=True);r.activate();r.tick(increase=True)
    event=r.take_events()[0];new=Setting.from_record(event['after'])
    assert r.acknowledge(event,new)
    a.accept_edit(new,TARGET,o,shortcuts=True)
    a.update(new,TARGET,o,shortcuts=True)
    assert r.starts==1 and r.controller.setting.rate==105


def test_closed_never_restarts():
    r=StubRunner();a=AutoReady(r);a.close()
    a.update(preset(),TARGET,ToggleOptions());assert not r.active


@pytest.mark.parametrize('title',['WARDOGS - Steam','Wardogs Launcher','RecoilLab WARDOGS','WARDOGS screenshot','WARDOGS game'])
def test_default_target_match_is_not_a_substring(tmp_path,title):
    rule=TargetRule(tmp_path);assert rule.resolve([(title,TARGET)])[0] is None


def test_exact_rule_remembers_only_title_and_detects_ambiguity(tmp_path):
    rule=TargetRule(tmp_path);rule.save('Custom game')
    assert json.loads(rule.path.read_text())=={'title':'Custom game'}
    reloaded=TargetRule(tmp_path)
    assert reloaded.resolve([('Custom game',TARGET)])[0]==TARGET
    assert reloaded.resolve([('Custom game',TARGET),('Custom game',dict(TARGET,handle=50))])[0] is None
    reloaded.reset();assert reloaded.title=='' and not reloaded.path.exists()


@pytest.mark.parametrize('title',['','x'*257,'   ','x\nY',23,None])
def test_bad_target_title(tmp_path,title):
    rule=TargetRule(tmp_path)
    with pytest.raises(ValueError):rule.save(title)


def test_corrupt_target_never_restores_runtime_permission(tmp_path):
    path=tmp_path/'panel-target.json';path.write_text('{"title":"WARDOGS","enabled":true}')
    rule=TargetRule(tmp_path);assert rule.warning and rule.title=='' and 'enabled' in path.read_text()


def test_changed_pid_does_not_reuse_old_handle(tmp_path):
    rule=TargetRule(tmp_path)
    one=rule.resolve([('WARDOGS',TARGET)])[0]
    two=rule.resolve([('WARDOGS',dict(TARGET,pid=123))])[0]
    assert one['pid']!=two['pid']


def test_draft_change_and_save_are_separate(tmp_path):
    store=Store(tmp_path);s=preset();store.save(s)
    d=PanelDraft(store,public_catalog());d.load(s);d.adjust(5)
    assert d.dirty and dict(store.items())[s.key].rate==100
    d.save();assert not d.dirty and dict(Store(tmp_path).items())[s.key].rate==105


def test_copy_and_weight_preserve_old_setting(tmp_path):
    store=Store(tmp_path);s=preset();store.save(s)
    d=PanelDraft(store,public_catalog());d.load(s);d.copy_as('副本')
    d.change(replace(d.current,conditions=dict(d.current.conditions,weight='背包方案B')))
    d.save();assert len(store.items())==2 and dict(store.items())[s.key].record()==s.record()


def test_copy_collision_rejected(tmp_path):
    store=Store(tmp_path);s=preset();store.save(s)
    d=PanelDraft(store,public_catalog());d.load(s)
    with pytest.raises(ValueError):d.copy_as(s.conditions['notes'])
    assert d.current.record()==s.record()


def test_portable_backward_compatibility(tmp_path):
    d=PanelDraft(Store(tmp_path),public_catalog());s=preset()
    d.load(import_setting(export_setting(s)));d.save()
    assert d.current.record()==s.record() and not d.current.record()['game_verified']


def test_draft_invalid_import_keeps_current(tmp_path):
    d=PanelDraft(Store(tmp_path),public_catalog());s=preset();d.load(s)
    with pytest.raises(ValueError):d.load(replace(s,conditions=dict(s.conditions,weapon='Unknown')))
    assert d.current.record()==s.record()


@pytest.mark.parametrize('title', [
    'WARDOGS', 'Wardogs', 'wardogs', 'WaRdOgS',
    'Wardogs ', ' Wardogs', '\tWardogs\r\n', '\u00a0Wardogs\u3000', ' 战狗 ',
])
def test_real_caption_case_and_padding_find_and_persist(tmp_path, title):
    rule = TargetRule(tmp_path)
    assert rule.resolve([(title, TARGET)])[0] == TARGET
    rule.save(title)
    assert json.loads(rule.path.read_text(encoding='utf-8')) == {'title': title}
    loaded = TargetRule(tmp_path)
    assert not loaded.warning
    assert loaded.resolve([(title, TARGET)])[0] == TARGET
    assert loaded.resolve([(title.strip().swapcase(), TARGET)])[0] == TARGET


@pytest.mark.parametrize('title', ['', ' ', '\t\n', '\x00Wardogs', 'War\ndogs', 'War\tdogs', 7, None])
def test_invalid_enumerated_caption_never_matches(tmp_path, title):
    rule = TargetRule(tmp_path)
    assert rule.resolve([(title, TARGET)])[0] is None
    with pytest.raises(ValueError):
        rule.save(title)


def test_normalized_caption_collisions_never_pick_first(tmp_path):
    rule = TargetRule(tmp_path)
    windows = [('Wardogs', TARGET), (' WARDOGS\t', dict(TARGET, handle=43))]
    for save in (False, True):
        if save:
            rule.save(' Wardogs ')
        target, reason = rule.resolve(windows)
        assert target is None and '多个同名窗口' in reason


def test_selected_raw_caption_does_not_match_launcher_or_substring(tmp_path):
    rule = TargetRule(tmp_path)
    rule.save(' Wardogs ')
    for title in ('Wardogs Launcher', 'RecoilLab Wardogs', 'Wardogs - Steam', 'War dogs'):
        assert rule.resolve([(title, TARGET)])[0] is None


def test_padded_caption_cannot_bypass_target_validation(tmp_path):
    rule = TargetRule(tmp_path)
    for invalid in (dict(TARGET, pid=0), dict(TARGET, handle=True),
                    dict(TARGET, size=[0, 0]), dict(TARGET, enabled=True)):
        assert rule.resolve([(' Wardogs ', invalid)])[0] is None


def test_caption_resolution_never_restores_activation(tmp_path):
    rule = TargetRule(tmp_path)
    rule.save(' Wardogs ')
    target, _ = TargetRule(tmp_path).resolve([('wardogs', TARGET)])
    runner = StubRunner()
    ready = AutoReady(runner)
    ready.update(preset(), target, ToggleOptions())
    assert runner.active and not runner.snapshot()['enabled']
    assert not runner.backend.events
