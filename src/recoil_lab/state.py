"""Full-snapshot, fail-closed observation gate for RECORDING-ONLY playback.

No keyboard hooks, screen capture, mouse injection or game process access.
An externally supplied observation is not proof that the game is in that state.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from .contracts import CalibrationError, Profile, context_id
from .playback import Playback, RecordingSink

ACTIONS = {"ready", "reload", "inventory", "grenade", "melee", "heal", "sprint", "dead", "vehicle", "unknown"}
KINDS = {"firearm", "grenade", "melee", "tool", "unknown"}
SOURCES = {"synthetic", "manual_annotation", "recorded_hud", "input_inference"}
MODES = {"auto", "semi", "burst", "unknown"}


def number(value: Any, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise CalibrationError(f"{name} must be a finite number")
    return float(value)


@dataclass(frozen=True)
class Observation:
    observed_s: float
    context_id: str
    pressed: bool | None
    ads: bool | None
    focused: bool | None
    item_kind: str
    action: str
    fire_mode: str
    ammo: int | None
    confidence: float
    source: str

    @classmethod
    def parse(cls, value: dict) -> "Observation":
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise CalibrationError("Observation requires exactly the documented full snapshot fields")
        obj = cls(**value)
        if number(obj.observed_s, "observed_s") < 0:
            raise CalibrationError("observed_s must be nonnegative")
        if not isinstance(obj.context_id, str) or len(obj.context_id) > 128:
            raise CalibrationError("Invalid context_id")
        if any(v is not None and type(v) is not bool for v in (obj.pressed, obj.ads, obj.focused)):
            raise CalibrationError("pressed/ads/focused must be boolean or null")
        for value, allowed in [(obj.action, ACTIONS), (obj.item_kind, KINDS),
                               (obj.source, SOURCES), (obj.fire_mode, MODES)]:
            if not isinstance(value, str) or value not in allowed:
                raise CalibrationError("Unknown observation enum")
        if obj.ammo is not None and (type(obj.ammo) is not int or not 0 <= obj.ammo <= 10000):
            raise CalibrationError("ammo must be an integer in [0,10000] or null")
        if not 0 <= number(obj.confidence, "confidence") <= 1:
            raise CalibrationError("confidence must be in [0,1]")
        return obj


class StatePlayback:
    """Routes exact-context profiles; requires release after any interruption.

    Only RecordingSink is used. This layer does not mark profiles game-verified.
    The original Playback contract remains unchanged for existing CLI users.
    """
    def __init__(self, profiles: list[Profile], *, max_age_s: float = .1,
                 min_confidence: float = .85):
        if not 0 < number(max_age_s, "max_age_s") <= .1:
            raise CalibrationError("max_age_s must be in (0,.1]")
        if not .65 <= number(min_confidence, "min_confidence") <= 1:
            raise CalibrationError("min_confidence must be in [.65,1]")
        self.profiles = {context_id(p.context): p for p in profiles}
        if len(self.profiles) != len(profiles):
            raise CalibrationError("Duplicate context: choose one candidate profile per context")
        self.max_age_s, self.min_confidence = max_age_s, min_confidence
        self.sink = RecordingSink()
        self.player: Playback | None = None
        self.active_id: str | None = None
        self.released = False
        self.last_s: float | None = None
        self.last_observed_s: float | None = None

    def _stop(self, reason: str, now: float | None) -> dict:
        self.released = False
        self.player = None
        return self._result(reason, now, False)

    def _result(self, reason: str, now: float | None, eligible: bool) -> dict:
        return {"t_s": now, "reason": reason, "eligible": eligible,
                "playback_state": self.player.state if self.player else "WAIT_RELEASE",
                "active_context_id": self.active_id, "events_recorded": len(self.sink.events),
                "game_verified": False, "output": "recording_only"}

    def tick(self, now_s: float, observation: dict) -> dict:
        try:
            now = number(now_s, "now_s")
            if now < 0:
                raise CalibrationError("Clock must be nonnegative")
            obs = Observation.parse(observation)
        except (CalibrationError, TypeError, ValueError):
            return self._stop("INVALID_OBSERVATION", None)
        if self.last_s is not None and now <= self.last_s:
            return self._stop("NON_MONOTONIC_CLOCK", now)
        gap = self.last_s is not None and now - self.last_s > .1 + 1e-9
        self.last_s = now
        age = now - obs.observed_s
        if age < -1e-9 or age > self.max_age_s + 1e-9:
            return self._stop("STALE_OR_FUTURE_OBSERVATION", now)
        if self.last_observed_s is not None and obs.observed_s < self.last_observed_s:
            return self._stop("OUT_OF_ORDER_OBSERVATION", now)
        self.last_observed_s = obs.observed_s
        if obs.confidence < self.min_confidence:
            return self._stop("LOW_CONFIDENCE", now)
        if obs.source == "input_inference":
            return self._stop("INFERRED_STATE_NOT_CONFIRMED", now)
        if obs.pressed is None:
            return self._stop("FIRE_INPUT_UNKNOWN", now)
        # Release is a stop, never an action. Other checks must pass on next press.
        if obs.pressed is False:
            self.released, self.player = True, None
            return self._result("RELEASED", now, False)
        if gap:
            return self._stop("SCHEDULER_GAP", now)
        if obs.focused is not True:
            return self._stop("NOT_FOCUSED", now)
        if obs.ads is not True:
            return self._stop("NOT_ADS", now)
        if obs.item_kind != "firearm":
            return self._stop("NOT_FIREARM", now)
        if obs.action != "ready":
            return self._stop("ACTION_" + obs.action.upper(), now)
        if obs.ammo is None:
            return self._stop("AMMO_UNKNOWN", now)
        if obs.ammo == 0:
            return self._stop("EMPTY", now)
        if obs.fire_mode != "auto":
            return self._stop("FIRE_MODE_NOT_SUPPORTED", now)
        if obs.context_id not in self.profiles:
            return self._stop("PROFILE_MISSING", now)
        if self.player is not None and obs.context_id != self.active_id:
            return self._stop("CONTEXT_CHANGED", now)
        if not self.released:
            return self._result("WAIT_RELEASE", now, False)
        if self.player is None:
            self.active_id = obs.context_id
            self.player = Playback(self.profiles[self.active_id], self.sink)
            self.player.tick(now, pressed=False, ads=True, focused=True, active_context_id=self.active_id)
        self.player.tick(now, pressed=True, ads=True, focused=True, active_context_id=self.active_id)
        if self.player.state == "WAIT_RELEASE":
            return self._stop("CURVE_FINISHED", now)
        return self._result("RUNNING", now, True)
