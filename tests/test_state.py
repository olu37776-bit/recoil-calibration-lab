import copy
import math
import pytest

from recoil_lab.contracts import CalibrationError, context_id
from recoil_lab.state import StatePlayback, Observation
from recoil_lab.state_demo import profiles, run_state_demo, SCENARIOS


def obs(t=0., **updates):
    return dict(observed_s=t, context_id=context_id(profiles()[0].context),
                pressed=True, ads=True, focused=True, item_kind='firearm', action='ready',
                fire_mode='auto', ammo=30, confidence=1., source='synthetic', **updates)


def update(t, **change):
    return {**obs(t), **change}


def running():
    p = StatePlayback(profiles())
    p.tick(0., update(0., pressed=False))
    p.tick(.02, obs(.02))
    p.tick(.04, obs(.04))
    return p


@pytest.mark.parametrize('change,reason', [
    ({'ads':False},'NOT_ADS'), ({'ads':None},'NOT_ADS'),
    ({'focused':False},'NOT_FOCUSED'), ({'ammo':0},'EMPTY'),
    ({'ammo':None},'AMMO_UNKNOWN'), ({'action':'reload'},'ACTION_RELOAD'),
    ({'action':'inventory'},'ACTION_INVENTORY'), ({'action':'grenade'},'ACTION_GRENADE'),
    ({'action':'melee'},'ACTION_MELEE'), ({'action':'heal'},'ACTION_HEAL'),
    ({'action':'dead'},'ACTION_DEAD'), ({'action':'sprint'},'ACTION_SPRINT'),
    ({'action':'vehicle'},'ACTION_VEHICLE'), ({'item_kind':'tool'},'NOT_FIREARM'),
    ({'fire_mode':'semi'},'FIRE_MODE_NOT_SUPPORTED'),
    ({'fire_mode':'burst'},'FIRE_MODE_NOT_SUPPORTED'),
    ({'source':'input_inference'},'INFERRED_STATE_NOT_CONFIRMED'),
    ({'confidence':.5},'LOW_CONFIDENCE'), ({'context_id':'missing'},'PROFILE_MISSING'),
    ({'pressed':None},'FIRE_INPUT_UNKNOWN'),
])
def test_block_and_no_resume_while_held(change, reason):
    p = running(); count = len(p.sink.events)
    assert count > 0
    assert p.tick(.06, update(.06, **change))['reason'] == reason
    for t in [.08, .1, .12]:
        assert p.tick(t, obs(t))['eligible'] is False
    assert len(p.sink.events) == count
    p.tick(.14, update(.14, pressed=False)); p.tick(.16, obs(.16)); p.tick(.2, obs(.2))
    assert len(p.sink.events) > count


@pytest.mark.parametrize('change', [{'pressed':1}, {'ammo':True}, {'ammo':-1},
    {'confidence':float('nan')}, {'observed_s':float('inf')}, {'action':[]},
    {'source':'magic'}, {'context_id':None}])
def test_malformed_snapshots_stop(change):
    p=running(); before=len(p.sink.events)
    assert p.tick(.06, update(.06, **change))['reason']=='INVALID_OBSERVATION'
    p.tick(.08, obs(.08)); assert len(p.sink.events)==before


def test_partial_snapshot_not_silently_merged():
    p=running(); assert p.tick(.06, {'ammo':0})['reason']=='INVALID_OBSERVATION'


@pytest.mark.parametrize('now,seen,reason', [(.06,-.1,'INVALID_OBSERVATION'),
    (.3,.1,'STALE_OR_FUTURE_OBSERVATION'),(.06,.2,'STALE_OR_FUTURE_OBSERVATION'),
    (.06,.01,'OUT_OF_ORDER_OBSERVATION')])
def test_feedback_age_and_order(now,seen,reason):
    p=running(); assert p.tick(now, update(seen))['reason']==reason


def test_clock_and_gap():
    p=running(); assert p.tick(.04, obs(.04))['reason']=='NON_MONOTONIC_CLOCK'
    assert p.tick(.5, obs(.5))['reason']=='SCHEDULER_GAP'
    assert p.tick(.52, obs(.52))['eligible'] is False


def test_profile_selection_by_exact_context():
    p=running(); ids=[context_id(x.context) for x in profiles()]
    assert p.tick(.06, update(.06, context_id=ids[1]))['reason']=='CONTEXT_CHANGED'
    assert p.tick(.08, update(.08, context_id=ids[1]))['reason']=='WAIT_RELEASE'
    p.tick(.1, update(.1, pressed=False, context_id=ids[1]))
    result=p.tick(.12, update(.12, context_id=ids[1]))
    assert result['active_context_id']==ids[1] and result['eligible'] is True


def test_hold_does_not_repeat_and_no_horizontal_output():
    p=StatePlayback(profiles()); p.tick(0., update(0., pressed=False))
    for n in range(1,100):
        t=n*.02; p.tick(t, obs(t))
    assert sum(e['dy_counts'] for e in p.sink.events)==40
    assert all(e['dx_counts']==0 for e in p.sink.events)


def test_no_initial_press_without_release():
    p=StatePlayback(profiles()); assert p.tick(0., obs(0.))['reason']=='WAIT_RELEASE'
    p.tick(.04, obs(.04)); assert not p.sink.events


@pytest.mark.parametrize('kwargs',[{'max_age_s':0},{'max_age_s':float('nan')},{'min_confidence':.1}])
def test_invalid_gate_configuration(kwargs):
    with pytest.raises(CalibrationError):StatePlayback(profiles(),**kwargs)


def test_duplicate_context_rejected():
    with pytest.raises(CalibrationError):StatePlayback([profiles()[0],profiles()[0]])


@pytest.mark.parametrize('scenario',SCENARIOS)
def test_demo_labels_scope(scenario):
    r=run_state_demo({'scenario':scenario})
    assert not r['game_verified'] and r['source']=='synthetic'
    assert len(r['trace'])==81 and r['events']
    assert all(row['output']=='recording_only' for row in r['trace'])


def test_unknown_demo_rejected():
    with pytest.raises(CalibrationError):run_state_demo({'scenario':'anything'})
