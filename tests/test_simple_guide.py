import pytest
from recoil_lab.simple_guide import STAGES, NO_EFFECT, preparation_issue, run_notice


def ready(**changes):
    values = dict(valid=True,pending=False,target=True,consent=True,rate=20)
    values.update(changes)
    return preparation_issue(**values)


def test_stages_match_user_actions():
    assert STAGES == ('选配装','准备试射','试射调节','保存使用')
    assert ready() == ''


@pytest.mark.parametrize('changes,word', [
    ({'valid':False},'配装'), ({'pending':True},'数值'),
    ({'target':False},'刷新'), ({'consent':False},'确认'), ({'rate':0},'力度')
], ids=['config','number','window','consent','zero-rate'])
def test_preparation_missing(changes,word):
    assert word in ready(**changes)


def test_preparation_does_not_prioritize_permission_over_missing_window():
    assert '刷新' in ready(target=False,consent=False)


@pytest.mark.parametrize('second',range(1,6))
def test_countdown_from_observed_message(second):
    notice=run_notice(f'{second}秒准备：切回所选窗口；全部按键先松开',True)
    assert f'{second} 秒' in notice.title
    assert '同时按住' in notice.action


@pytest.mark.parametrize('message,active,title', [
    ('未启用',False,'当前没有输出'),
    ('待命：F7＋右键＋左键',True,'试用已开启'),
    ('下拉中；F8 / Esc 急停',True,'试用已开启'),
    ('等待松开左键；不会自动继续上一梭',True,'先松开左键'),
    ('本次调节未采用：先松手',True,'这次调节没有采用'),
    ('调节已暂停输出，等待主界面确认新力度',True,'正在同步'),
    ('已切出目标窗口，已停止；调整好后重新开始',False,'已暂停'),
    ('换弹、背包、切枪或姿态切换：已停止',False,'已停止'),
    ('F8 / Esc 已急停',False,'已停止'),
    ('本次120秒试调结束',False,'时间已结束'),
    ('窗口关闭或已最小化，请重新选择',False,'重新选择'),
    ('窗口或尺寸变化；已停止',False,'重新选择'),
    ('Windows拒绝输入；请停止测试',False,'系统没有接受'),
    ('调度中断，已停止，不补发',False,'运行被中断'),
    ('界面无响应，已停止',False,'运行被中断'),
    ('已保存手动参数；下次打开恢复',False,'已保存在本机'),
    ('快捷调节同步失败，已停止',False,'没有继续运行'),
    ('unexpected foreign error',False,'检查当前提示'),
], ids=['idle','waiting','tick-not-completion','release','busy','sync','focus','reload','emergency','timeout','closed','resize','refused','schedule','ui','saved','sync-error','unknown'])
def test_plain_language_status(message,active,title):
    notice=run_notice(message,active)
    assert title in notice.title
    assert notice.action
    assert '游戏验证通过' not in notice.title+notice.action


def test_no_effect_has_no_automatic_cure_claim():
    text='\n'.join(NO_EFFECT)
    assert '不是只按一下F7' in text
    assert '游戏未接收' in text
    assert '不要盲目' in text


def test_save_hint_is_not_game_verification():
    assert run_notice('已保存手动参数',False).kind=='success'
    assert run_notice('Windows拒绝输入',False).kind=='warning'
    assert run_notice('界面无响应',False).kind=='warning'
