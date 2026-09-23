"""Read-only preparation checks and privacy-minimal recovery summaries."""
from __future__ import annotations

import math
import platform

from .contracts import CalibrationError


def capture_options(payload: dict, resolution: list[int]) -> tuple[str, float, int]:
    mode = payload.get('mode')
    if mode not in {'preview', 'response', 'train', 'train_batch', 'validation', 'execute'}:
        raise CalibrationError('未知桌面会话模式')
    count = payload.get('count', 3 if mode == 'train_batch' else 1)
    if type(count) is not int or not 1 <= count <= 3 or (mode != 'train_batch' and count != 1):
        raise CalibrationError('只有未补偿训练支持一组1至3轮；其他阶段仍逐轮启动')
    duration = payload.get('duration_s', 2)
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or not .5 <= duration <= 6:
        raise CalibrationError('单轮采样时长需在0.5至6秒')
    if mode not in {'execute', 'preview'}:
        roi = payload.get('roi')
        if not isinstance(roi, list) or len(roi) != 4 or any(type(v) is not int for v in roi):
            raise CalibrationError('请在窗口预览中框选静态纹理区域')
        x, y, w, h = roi
        if x < 0 or y < 0 or w < 32 or h < 32 or x + w > resolution[0] or y + h > resolution[1]:
            raise CalibrationError('选区须位于原图范围内且至少32×32像素，请重新框选墙面')
    return mode, float(duration), count


# Exports use only these authored messages, never raw exception strings.
RECOVERY = {
    'STOPPED': ('已停止', '已成功的记录保留。准备好后，重新点击开始；不会自行继续。'),
    'FOCUS': ('目标窗口已变化', '重新核对窗口，切回目标画面后再采集。不要使用旧窗口预览。'),
    'GEOMETRY': ('窗口尺寸或选区不匹配', '重新取得预览并框选墙面；尺寸改变时复制配装，只修改实际尺寸。'),
    'HOLD': ('本轮提前松开', '本轮未保存；保持使能和开火到结束。之前成功的轮次不必重做。'),
    'TIMING': ('采集未能及时完成', '先停止其他录制或后台重负载，再重试本轮。仍失败时导出诊断，不会放宽时间检查。'),
    'TRACKING': ('画面不适合跟踪', '换一块有纹理、无枪口火光和动态物体的墙面，再取预览和框选。'),
    'ACTION': ('收到换弹或姿态等指令', '完成动作、恢复本项目姿态后重新开始。组内换弹应在“等待下一轮”时进行。'),
    'HEARTBEAT': ('工作台连接中断', '保持工作台页面打开，确认本机程序仍在运行后再开始。'),
    'WAIT': ('等待操作超时', '不需要重建项目。准备好后重新开始，按提示先松开再按下。'),
    'INPUT': ('系统拒绝输入', '保留系统提示并停止测试；不要关闭保护、提权或绕过拦截。'),
    'OTHER': ('本轮未完成', '已保存记录不变。核对页面原始错误后重试，或导出无图片诊断。'),
}


def recovery(error: str, stopped: bool = False) -> dict:
    code = 'STOPPED' if stopped else 'OTHER'
    if not stopped:
        for key, terms in (
            ('HEARTBEAT', ('心跳',)), ('INPUT', ('拒绝了输入',)),
            ('GEOMETRY', ('尺寸', '分辨率', '选区', '框选')),
            ('FOCUS', ('焦点', '窗口不存在', '最小化', 'focus')),
            ('HOLD', ('松开',)), ('TIMING', ('100ms', '50ms', '参考帧过旧', '调度')),
            ('ACTION', ('急停', '指令')), ('WAIT', ('30秒', '等待', '超时')),
            ('TRACKING', ('texture', 'feature', 'track', 'confidence', '纹理', '跟踪', '质量')),
        ):
            if any(term in str(error) for term in terms):
                code = key
                break
    title, hint = RECOVERY[code]
    return {'code': code, 'title': title, 'hint': hint, 'retry_automatic': False}


def preflight(session, payload: dict) -> dict:
    """Only checks metadata and existing evidence. Never creates a desktop task."""
    checks = []
    def add(name, ok, hint):
        checks.append({'name': name, 'passed': bool(ok), 'hint': hint})
    ident = payload.get('project_id')
    try:
        snap = session.workspace.snapshot(ident)
    except (CalibrationError, OSError, ValueError):
        add('已选择配置', False, '先保存或选择一套配置。')
        return {'ready': False, 'checks': checks, 'input_sent': False, 'authorizes_output': False}
    add('真实配置', not snap['demo'], '合成演示只能检查软件流程，不能采集真实数据。')
    try:
        mode, _, _ = capture_options(payload, snap['context']['resolution'])
        add('时长与墙面选区', True, '已在当前原图范围内；仍需实际确认墙面静止、有纹理。')
    except CalibrationError as exc:
        mode = payload.get('mode')
        add('时长与墙面选区', False, str(exc))
    add('本次采集授权', payload.get('consent') is True, '勾选本次授权；不会保存或代为勾选。')
    add('没有其他任务', not (session.worker and session.worker.is_alive()), '已有任务时先停止，等待结束。')
    hwnd = payload.get('hwnd')
    if type(hwnd) is not int or hwnd <= 0:
        add('目标窗口', False, '先读取窗口列表，明确选中本次目标。')
    else:
        try:
            backend = session.backend_factory()
            same = list(backend.geometry(hwnd)[2:]) == snap['context']['resolution']
            add('目标窗口尺寸', same, '窗口尺寸必须与当前配置一致；检查不代表游戏已接受输入。')
        except Exception:
            add('目标窗口', False, '未能读取所选窗口；检查Windows环境并重新选择窗口。')
    if mode in {'validation', 'execute'}:
        try:
            p = session.workspace.execution_profile(ident) if mode == 'execute' else session.workspace.profile(ident)
            add('对应真实曲线', p.source == 'recorded' and float(p.t_s[-1]) <= 6,
                '候选检查需真实曲线；常规执行还需本版实测回放检查通过。')
        except (CalibrationError, OSError, ValueError):
            add('对应真实曲线', False, '先完成本项目训练和对应曲线检查。')
    return {'ready': all(c['passed'] for c in checks), 'checks': checks,
            'input_sent': False, 'authorizes_output': False}


def diagnostic(session, project_id=None) -> dict:
    """An explicit export, not telemetry; bounded fields omit personal identifiers."""
    with session.lock:
        info = dict(session.info)
    r = recovery(info.get('message', ''), info.get('state') == 'STOPPED')
    state = info.get('state')
    mode = info.get('mode')
    result = {'format': 'recoil-diagnostic-v1', 'platform': platform.system(),
              'state': state if state in {'IDLE', 'RUNNING', 'DONE', 'STOPPED', 'ERROR'} else 'UNKNOWN',
              'mode': mode if mode in {'preview', 'response', 'train', 'train_batch', 'validation', 'execute', 'recognize', 'auto_execute'} else None,
              'recovery': r if state in {'ERROR', 'STOPPED'} else None,
              'batch_saved': int(info.get('completed', 0)),
              'project': None, 'game_tested': False, 'input_compatibility_verified': False,
              'contains': '版本、系统、阶段、记录数量和固定错误分类；不含图片、路径、窗口标题、账号、原始错误或曲线'}
    if project_id:
        snap = session.workspace.snapshot(project_id)
        result['project'] = {'demo': snap['demo'], 'trial_count': len(snap['trials']),
                             'profile_count': len(snap['profiles']), 'step': snap['workflow']['step'],
                             'counts': snap['workflow']['counts']}
    return result
