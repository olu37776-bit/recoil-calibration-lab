"""Driver-independent state machine. The bundled sink ONLY records events."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from .contracts import CalibrationError, Profile, context_id


class MotionSink(Protocol):
    def move(self, t_s: float, dx_counts: int, dy_counts: int) -> None: ...


@dataclass
class RecordingSink:
    events: list[dict] = field(default_factory=list)

    def move(self, t_s: float, dx_counts: int, dy_counts: int) -> None:
        self.events.append({"t_s": t_s, "dx_counts": dx_counts, "dy_counts": dy_counts})


class Playback:
    """One burst per press; interruption requires release before rearming.

    tick() consumes externally supplied monotonic time. It does not read global
    keys, sleep, inject input, inspect processes, or interact with a game.
    """
    def __init__(self, profile: Profile, sink: MotionSink, max_gap_s: float = .1):
        if not np.isfinite(max_gap_s) or not 0 < max_gap_s <= .1:
            raise CalibrationError("max_gap_s must be in (0,.1]")
        self.profile, self.sink, self.max_gap_s = profile, sink, max_gap_s
        self.state = "WAIT_RELEASE"
        self.started_s: float | None = None
        self.last_s: float | None = None
        self.emitted = 0

    def tick(self, now_s: float, *, pressed: bool, ads: bool, focused: bool,
             active_context_id: str) -> None:
        if not np.isfinite(now_s):
            self.state = "WAIT_RELEASE"
            raise CalibrationError("Clock must be finite")
        old = self.last_s
        self.last_s = now_s
        if old is not None and now_s < old:
            self.state = "WAIT_RELEASE"
            raise CalibrationError("Clock moved backwards")
        if not pressed:
            self.state, self.started_s, self.emitted = "ARMED", None, 0
            return
        if not ads or not focused or active_context_id != context_id(self.profile.context):
            self.state = "WAIT_RELEASE"
            return
        if self.state == "WAIT_RELEASE":
            return
        if self.state == "ARMED":
            self.state, self.started_s, self.emitted = "RUNNING", now_s, 0
            return
        if old is not None and now_s - old > self.max_gap_s + 1e-9:
            self.state = "WAIT_RELEASE"  # Never catch up after a stall.
            return
        assert self.started_s is not None
        elapsed = now_s - self.started_s
        end = float(self.profile.t_s[-1])
        target = int(np.rint(self.profile.input_at(min(elapsed, end))))
        delta = target - self.emitted
        if delta:
            try:
                self.sink.move(elapsed, 0, delta)
            except Exception:
                self.state = "WAIT_RELEASE"
                raise
            self.emitted = target
        if elapsed >= end:
            self.state = "WAIT_RELEASE"


def dry_run(profile: Profile, tick_s: float = .01) -> list[dict]:
    if not np.isfinite(tick_s) or not .001 <= tick_s <= .05:
        raise CalibrationError("tick_s must be in [.001,.05]")
    sink = RecordingSink()
    player = Playback(profile, sink)
    flags = {"ads": True, "focused": True, "active_context_id": context_id(profile.context)}
    player.tick(-tick_s, pressed=False, **flags)
    player.tick(0., pressed=True, **flags)
    end = float(profile.t_s[-1])
    times = np.arange(tick_s, end, tick_s).tolist() + [end]
    for t in times:
        player.tick(float(t), pressed=True, **flags)
    player.tick(end + tick_s, pressed=False, **flags)
    return sink.events
