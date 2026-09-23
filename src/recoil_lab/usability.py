"""Read-only progress and non-authorizing preferences for the guided UI."""
from __future__ import annotations

from math import isfinite
from .contracts import CalibrationError, read_json, write_json

SETTINGS = {'dpi', 'sensitivity', 'ads_sensitivity', 'zoom', 'resolution', 'fov', 'game_build'}
PREFERENCE_KEYS = {'last_project_id', 'last_bank_id', 'weight_label', 'teach_session', 'settings'}


def checked_report(profile: dict | None) -> bool:
    if not profile or profile.get('source') != 'recorded':
        return False
    report = profile.get('report') or {}
    return (report.get('passed') is True and report.get('evidence_kind') == 'RECORDED_REPLAY'
            and report.get('measured_replay_pass') is True)


def progress(snapshot: dict) -> dict:
    """A display hint, never an execution grant. Runtime revalidates evidence."""
    active = next((p for p in snapshot['profiles'] if p['id'] == snapshot.get('active_profile')), None)
    trials = snapshot['trials']
    source = 'synthetic' if snapshot.get('demo') else 'recorded'
    rows = [t for t in trials if t['source'] == source]
    responses = sum(t['phase'] == 'response' for t in rows)
    training = sum(t['phase'] == 'train' for t in rows)
    # Do not mistake old-candidate or untagged imported validation for this version.
    validations = sum(t['phase'] == 'validation' and active is not None
                      and t.get('candidate_id') == active['id'] for t in rows)
    used = set(active.get('training_run_ids', [])) if active else set()
    new_training = sum(t['phase'] == 'train' and t['run_id'] not in used for t in rows)
    report = active.get('report') if active else None
    step, title = 'record_response', f'先做不射击标定：{min(responses, 2)} / 2 次'
    if responses >= 2:
        if not snapshot.get('response'):
            step, title = 'response', '记录已齐，计算鼠标响应'
        elif training < 3:
            step, title = 'record_train', f'记录未补偿试射：{training} / 3 次'
        elif active is None:
            step, title = 'fit', '试射已齐，生成第一版补偿'
        elif checked_report(active) and not snapshot.get('demo'):
            step, title = 'ready', '此配置的实测回放检查已通过'
        elif snapshot.get('demo'):
            step, title = 'demo', '演示已完成；它不是你的真实校准'
        elif report and report.get('passed') is False:
            step, title = 'review', '本版效果未通过，先看原因或恢复旧版'
        elif validations < 3:
            step, title = 'record_validation', f'检查当前版本效果：{validations} / 3 次'
        else:
            step, title = 'validate', '检查记录已齐，计算本版结果'
    approved = [p['id'] for p in snapshot['profiles'] if p['id'] != snapshot.get('active_profile') and checked_report(p)]
    by_id = {p['id']: p for p in snapshot['profiles']}
    parent = active.get('parent_id') if active else None
    visited = set()
    recommended = None
    while parent in by_id and parent not in visited:
        visited.add(parent)
        if parent in approved:
            recommended = parent
            break
        parent = by_id[parent].get('parent_id')
    if recommended is None and len(approved) == 1:
        recommended = approved[0]
    return {'step': step, 'title': title, 'counts': {'response': responses, 'train': training,
            'validation_current': validations, 'new_train': new_training},
            'can_request_execution': step == 'ready', 'automatic_permission': False,
            'rollback_ids': approved, 'recommended_rollback_id': recommended,
            'game_verified': False}


def preferences(root, patch: dict | None = None) -> dict:
    """Never persist consent, active tasks, window handles, or output flags."""
    path = root / 'ui-preferences.json'
    try:
        existing = read_json(path) if path.exists() else {}
    except (ValueError, OSError):
        existing = {}
    existing = {k: v for k, v in existing.items() if k in PREFERENCE_KEYS}
    if patch is not None:
        if not isinstance(patch, dict) or not set(patch) <= PREFERENCE_KEYS:
            raise CalibrationError('只能保存界面偏好；不能保存授权或自动启用状态')
        for key, value in patch.items():
            if key == 'settings':
                if not isinstance(value, dict) or set(value) != SETTINGS:
                    raise CalibrationError('本机设置字段不完整')
                for k in SETTINGS - {'resolution', 'game_build'}:
                    v = value[k]
                    if isinstance(v, bool) or not isinstance(v, (float, int)) or not isfinite(v) or v <= 0:
                        raise CalibrationError('本机设置必须是正数')
                r = value['resolution']
                if not isinstance(r, list) or len(r) != 2 or any(type(x) is not int or x <= 0 for x in r):
                    raise CalibrationError('分辨率应为两个正整数')
                if not isinstance(value['game_build'], str) or not 1 <= len(value['game_build'].strip()) <= 128:
                    raise CalibrationError('请核对游戏版本')
            elif not isinstance(value, str) or len(value) > (32 if key == 'weight_label' else 80):
                raise CalibrationError('界面偏好长度不正确')
        existing.update(patch)
        write_json(path, existing)
    return existing
