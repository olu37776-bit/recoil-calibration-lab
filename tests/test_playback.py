import numpy as np
import pytest

from recoil_lab.contracts import CalibrationError, context_id
from recoil_lab.playback import Playback, RecordingSink, dry_run


def flags(profile):
    return dict(ads=True, focused=True, active_context_id=context_id(profile.context))


def test_cumulative_rounding(profile):
    for tick in (.003, .01, .017, .05):
        events = dry_run(profile, tick)
        assert sum(e["dy_counts"] for e in events) == int(np.rint(profile.uy_counts[-1]))
        assert all(e["dx_counts"] == 0 for e in events)


def test_release_required_at_start(profile):
    sink = RecordingSink(); p = Playback(profile, sink)
    for t in np.arange(0, .5, .01):
        p.tick(t, pressed=True, **flags(profile))
    assert not sink.events


def test_focus_loss_latches_until_release(profile):
    sink = RecordingSink(); p = Playback(profile, sink); f = flags(profile)
    p.tick(0, pressed=False, **f)
    p.tick(.01, pressed=True, **f)
    p.tick(.03, pressed=True, **f)
    before = len(sink.events)
    p.tick(.04, pressed=True, **dict(f, focused=False))
    p.tick(.06, pressed=True, **f)
    assert len(sink.events) == before
    p.tick(.07, pressed=False, **f)
    p.tick(.08, pressed=True, **f)
    p.tick(.1, pressed=True, **f)
    assert len(sink.events) > before


@pytest.mark.parametrize("change", [{"ads": False}, {"active_context_id": "wrong"}])
def test_state_gate(profile, change):
    sink = RecordingSink(); p = Playback(profile, sink); f = flags(profile)
    p.tick(0, pressed=False, **f)
    p.tick(.01, pressed=True, **dict(f, **change))
    p.tick(.03, pressed=True, **f)
    assert not sink.events


def test_stall_does_not_catch_up(profile):
    sink = RecordingSink(); p = Playback(profile, sink); f = flags(profile)
    p.tick(0, pressed=False, **f)
    p.tick(.01, pressed=True, **f)
    p.tick(.02, pressed=True, **f)
    before = len(sink.events)
    p.tick(.5, pressed=True, **f)
    p.tick(.51, pressed=True, **f)
    assert len(sink.events) == before


def test_release_stops_immediately(profile):
    sink = RecordingSink(); p = Playback(profile, sink); f = flags(profile)
    p.tick(0, pressed=False, **f)
    p.tick(.01, pressed=True, **f)
    p.tick(.03, pressed=False, **f)
    assert not sink.events


def test_long_hold_does_not_restart(profile):
    sink = RecordingSink(); p = Playback(profile, sink); f = flags(profile)
    p.tick(-.01, pressed=False, **f)
    for t in np.arange(0, 4.01, .01):
        p.tick(float(t), pressed=True, **f)
    assert sum(e["dy_counts"] for e in sink.events) == int(np.rint(profile.uy_counts[-1]))


def test_bad_clock(profile):
    p = Playback(profile, RecordingSink()); f = flags(profile)
    p.tick(1, pressed=False, **f)
    with pytest.raises(CalibrationError, match="backwards"):
        p.tick(.1, pressed=True, **f)
    with pytest.raises(CalibrationError, match="finite"):
        p.tick(float("nan"), pressed=True, **f)


def test_sink_failure_disarms(profile):
    class Broken:
        def move(self, *args):
            raise RuntimeError("sink failed")
    p = Playback(profile, Broken()); f = flags(profile)
    p.tick(0, pressed=False, **f)
    p.tick(.01, pressed=True, **f)
    with pytest.raises(RuntimeError):
        p.tick(.03, pressed=True, **f)
    assert p.state == "WAIT_RELEASE"


@pytest.mark.parametrize("tick", [0, .2, float("nan")])
def test_invalid_tick(profile, tick):
    with pytest.raises(CalibrationError):
        dry_run(profile, tick)
