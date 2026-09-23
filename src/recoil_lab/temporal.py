"""Consecutive-frame confirmation for offline candidates, never input permission."""
from __future__ import annotations

from .contracts import CalibrationError, digest
from .hud import LABELS
from .state import number


class CandidateStabilizer:
    """Any unknown/change withdraws the old label immediately; no grace holding."""
    def __init__(self):
        self.last_s = None
        self.key = None
        self.label = None
        self.started_s = None
        self.count = 0
        self.last_hash = None
        self.streak_hashes = set()

    def _clear(self):
        self.label, self.started_s, self.count = None, None, 0
        self.streak_hashes.clear()

    def update(self, t_s: float, candidate: dict) -> dict:
        try:
            t_s = number(t_s, "timestamp")
            if t_s < 0 or (self.last_s is not None and t_s <= self.last_s):
                raise CalibrationError("Timestamp must move forward")
        except CalibrationError:
            self._clear()
            raise
        gap = self.last_s is not None and t_s-self.last_s > .1 + 1e-9
        self.last_s = t_s
        if not isinstance(candidate, dict):
            self._clear()
            raise CalibrationError("Candidate must be an object")
        field, label = candidate.get("field"), candidate.get("label")
        if not isinstance(field, str) or field not in LABELS:
            self._clear()
            raise CalibrationError("Candidate field is invalid")
        for name in ("reference_set_id", "pixel_sha256", "layout_id"):
            if not isinstance(candidate.get(name), str) or not candidate[name]:
                self._clear()
                raise CalibrationError("Candidate identity is missing")
        size = candidate.get("query_size")
        if not isinstance(size, list) or len(size) != 2 or any(type(v) is not int or v <= 0 for v in size):
            self._clear()
            raise CalibrationError("Candidate dimensions are invalid")
        key = digest([field, candidate["reference_set_id"], candidate["layout_id"], size])
        changed = self.key is not None and self.key != key
        self.key = key
        hashed = candidate["pixel_sha256"]
        duplicate = hashed == self.last_hash or hashed in self.streak_hashes
        self.last_hash = hashed
        reason = ("SELF_MATCH" if candidate.get("self_match") is not False else
                  "DUPLICATE_FRAME" if duplicate else
                  "UNKNOWN" if candidate.get("reason") != "CANDIDATE" or not isinstance(label, str) or label not in LABELS[field] else None)
        if reason:
            self._clear()
            return self._result(reason, False)
        if gap or changed or self.label != label:
            self._clear()
        if self.count == 0:
            self.started_s = t_s
            self.label = label
        self.count += 1
        self.streak_hashes.add(hashed)
        stable = self.count >= 3 and t_s-self.started_s >= .08-1e-9
        return self._result("STABLE_CANDIDATE" if stable else
                            "GEOMETRY_CHANGED" if changed else "FRAME_GAP" if gap else "CONFIRMING", stable)

    def _result(self, reason, stable):
        return {"label": self.label if stable else "unknown", "reason": reason,
                "consecutive_frames": self.count, "stable": stable,
                "auto_execution_eligible": False, "game_verified": False}
