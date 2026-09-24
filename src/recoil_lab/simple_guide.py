"""Read-only, plain-language guidance. Never grants input permission."""
from __future__ import annotations
from dataclasses import dataclass
import re

STAGES = ('选配装', '准备试射', '试射调节', '保存使用')

@dataclass(frozen=True)
class Notice:
    title: str
    action: str
    kind: str = 'info'


def preparation_issue(*, valid: bool, pending: bool, target: bool,
                      consent: bool, rate: float) -> str:
    """UI hints only; the runner revalidates every start and input."""
    if not valid:
        return '先回第1步，把枪械和配装选完整。'
    if pending:
        return '力度输入框有尚未采用的数值：先采用或改回当前值。'
    if not target:
        return '先打开游戏，点“刷新窗口列表”，再选游戏窗口。'
    if not consent:
        return '请先确认本次是在明确允许的受控场景中试用。'
    if rate <= 0:
        return '当前力度为0，不会下拉。请在第3步设置大于0的力度。'
    return ''


def run_notice(message: str, active: bool) -> Notice:
    """Translate observed software status, without inferring game state."""
    if active:
        match = re.match(r'([1-5])秒准备', message)
        if match:
            return Notice(f'还有 {match[1]} 秒：现在切回游戏',
                          '松开F7和鼠标左右键。倒计时结束后，再同时按住这三个键。')
        if '调节未采用' in message or '调节键已按下' in message:
            return Notice('这次调节没有采用', '先松开F7和鼠标左右键，再单按F5减小或F6增大。', 'warning')
        if '等待主界面确认' in message:
            return Notice('正在同步新力度，暂不输出', '先保持松手；同步完成后再主动试射。')
        if '等待松开左键' in message:
            return Notice('先松开左键', '上一轮不会自动续接。重新瞄准后，再同时按住F7和鼠标左右键。')
        # Do not label individual zero-delta polling ticks as shot completion.
        return Notice('试用已开启：按住 F7 ＋ 右键 ＋ 左键',
                      '三个键要同时保持按住；松手或到时即停。试完松手，切回本程序看效果。')
    if '已切出目标窗口' in message:
        return Notice('已暂停：你切回了本程序',
                      '这是正常停止。已经试射就点“我已试射，看效果”；还没试射就重新开始。')
    if any(s in message for s in ('换弹', '切枪', '姿态切换')):
        return Notice('已停止：检测到换弹或切换按键',
                      '先在游戏里换好弹、核对姿态和配装，再回第2步重新开始。')
    if 'F8' in message or 'Esc' in message:
        return Notice('已停止：你按了停止键', '不会自行恢复。准备好后，再回第2步点开始。')
    if '120秒' in message:
        return Notice('本次试用时间已结束', '调好的数值还在；满意就保存，需要继续就重新开始。')
    if '窗口关闭' in message or '最小化' in message or '窗口或尺寸变化' in message or '进程变化' in message:
        return Notice('目标窗口需要重新选择', '先打开并恢复游戏窗口，再回第2步刷新列表、重新选择。', 'warning')
    if 'Windows拒绝' in message:
        return Notice('系统没有接受输入', '停止测试并保留详细提示。不要提权或关闭安全防护；加大力度无效。', 'warning')
    if '调度' in message or '界面无响应' in message:
        return Notice('运行被中断，已停止', '先等系统恢复。仍重复出现时保留详细提示，不要靠加大力度处理。', 'warning')
    if any(s in message for s in ('失败', '冲突', '无效', '过期')):
        return Notice('本次没有继续运行', '展开详细状态核对原因；原参数不会因这条提示自动变好。', 'warning')
    if '已保存' in message:
        return Notice('参数已保存在本机', '下次可直接载入；仍需选择窗口并主动开始。', 'success')
    if '未启用' in message or not message or '已停止' in message or '关闭' in message or '修改' in message:
        return Notice('当前没有输出', '先准备好窗口，再点开始。程序不会自己开火或自己开始。')
    return Notice('请先检查当前提示', '展开“详细状态”查看原始提示；问题解决前不要继续增加力度。', 'warning')


NO_EFFECT = (
    '先看是否完成5秒倒计时，并且回到了你选择的游戏窗口。',
    '先松开，再同时按住F7、鼠标右键和左键；不是只按一下F7。',
    '力度不能为0；每轮到设定秒数就停止，需松开后再开始下一轮。',
    '换弹、切枪、切出窗口会停止整个会话：回第2步重新开始。',
    '仍无作用就停止，并保留详细状态。程序可能发出了事件，但游戏未接收；不要盲目加到最大。',
)
