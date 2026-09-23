"""Vertical-only robust identification, bounded updates and holdout validation."""
from __future__ import annotations

import numpy as np

from .contracts import CalibrationError, Profile, Response, Trial, context_id


def checked(trials: list[Trial], phase: str, minimum: int = 3) -> list[Trial]:
    if len(trials) < minimum:
        raise CalibrationError(f"At least {minimum} {phase} trials required")
    for trial in trials:
        trial.gate(phase)
    if len({t.context_hash for t in trials}) != 1:
        raise CalibrationError("Do not mix weapon, attachments, sensitivity or pose contexts")
    if len({t.source for t in trials}) != 1:
        raise CalibrationError("Do not mix synthetic and recorded evidence")
    if len({t.run_id for t in trials}) != len(trials) or len({t.content_hash for t in trials}) != len(trials):
        raise CalibrationError("Duplicate or relabeled trials do not count as independent runs")
    return trials


def fit_response(trials: list[Trial], latency_s: float = 0.0) -> Response:
    """Identify a through-origin pixel/count response with Huber reweighting.

    Inputs must be no-fire calibration motions, including both signs. Latency
    is supplied by the operator; this function does NOT estimate it.
    """
    checked(trials, "response", minimum=2)
    if not np.isfinite(latency_s) or not 0 <= latency_s <= .2:
        raise CalibrationError("latency_s must be in [0,0.2]")
    u = np.concatenate([np.interp(t.t_s - latency_s, t.t_s, t.uy_counts, left=0) for t in trials])
    y = np.concatenate([t.dy_px for t in trials])
    if np.max(u) < 5 or np.min(u) > -5:
        raise CalibrationError("Response trials need both positive and negative motions of >=5 counts")
    gain = float(np.dot(u, y) / np.dot(u, u))
    for _ in range(12):
        residual = y - gain * u
        scale = max(.01, float(1.4826 * np.median(np.abs(residual - np.median(residual)))))
        weights = np.minimum(1.0, 1.5 * scale / np.maximum(np.abs(residual), 1e-12))
        gain = float(np.dot(weights * u, y) / np.dot(weights * u, u))
    rmse = float(np.sqrt(np.mean((y - gain * u) ** 2)))
    if rmse > max(.5, .12 * float(np.std(y))):
        raise CalibrationError("Input response not repeatable: drift, delay or nonlinearity suspected")
    return Response(trials[0].context, trials[0].source, gain, latency_s, rmse,
                    [t.run_id for t in trials])


def _compatible(trials: list[Trial], response: Response) -> None:
    if any(t.context_hash != context_id(response.context) or t.source != response.source for t in trials):
        raise CalibrationError("Trial / response context or source mismatch")


def _intrinsic(trials: list[Trial], response: Response, grid: np.ndarray) -> np.ndarray:
    _compatible(trials, response)
    if any(t.t_s[-1] < grid[-1] - 1e-9 for t in trials):
        raise CalibrationError("Trial does not cover the complete profile duration; no extrapolation")
    return np.stack([np.interp(grid, t.t_s, t.dy_px - response.effect(t)) for t in trials])


def _limit_rate(u: np.ndarray, grid: np.ndarray, speed: float) -> np.ndarray:
    if not np.isfinite(speed) or not 0 < speed <= 10000:
        raise CalibrationError("Invalid speed limit")
    out = np.zeros_like(u)
    for i in range(1, len(u)):
        limit = speed * (grid[i] - grid[i-1])
        out[i] = out[i-1] + np.clip(u[i] - out[i-1], -limit, limit)
    return out


def _evidence(trials: list[Trial], previous: Profile | None = None) -> dict:
    result = {}
    for profile_key, attr in [("training_run_ids", "run_id"), ("training_session_ids", "session_id"),
                              ("training_content_hashes", "content_hash"), ("training_capture_ids", "capture_id")]:
        existing = getattr(previous, profile_key) if previous else []
        result[profile_key] = sorted(set(existing + [getattr(t, attr) for t in trials]))
    return result


def fit_profile(trials: list[Trial], response: Response, *, knot_s: float = .05,
                learning_rate: float = .7, max_speed_counts_s: float = 1500.) -> Profile:
    checked(trials, "train")
    if not np.isfinite(knot_s) or not .01 <= knot_s <= .1:
        raise CalibrationError("knot_s must be between 10 and 100 ms")
    if not np.isfinite(learning_rate) or not 0 < learning_rate <= 1:
        raise CalibrationError("learning_rate must be in (0,1]")
    duration = min(float(t.t_s[-1]) for t in trials)
    grid = np.linspace(0, duration, max(3, int(np.ceil(duration / knot_s)) + 1))
    samples = _intrinsic(trials, response, grid)
    median = np.median(samples, axis=0)
    # Abort if run-to-run variation is large; do not fit random spread as a curve.
    variability = float(np.median(np.sqrt(np.mean((samples - median) ** 2, axis=1))))
    signal = float(np.sqrt(np.mean(median ** 2)))
    if signal < 1.0:
        raise CalibrationError("Insufficient repeatable drift above the 1 px noise floor")
    if variability > max(2., .25 * signal):
        raise CalibrationError("Run-to-run recoil variability too large for a fixed curve")
    target = -learning_rate * median / response.gain_px_per_count
    target = _limit_rate(target, grid, max_speed_counts_s)
    return Profile(trials[0].context, trials[0].source, response, grid, target,
                   **_evidence(trials), max_speed_counts_s=max_speed_counts_s)


def refine_profile(previous: Profile, trials: list[Trial], *, learning_rate: float = .6,
                   max_update_counts: float = 30.) -> Profile:
    checked(trials, "train")
    if not np.isfinite(learning_rate) or not 0 < learning_rate <= 1:
        raise CalibrationError("learning_rate must be in (0,1]")
    if not np.isfinite(max_update_counts) or max_update_counts <= 0:
        raise CalibrationError("max_update_counts must be positive")
    if any(t.content_hash in previous.training_content_hashes or t.run_id in previous.training_run_ids for t in trials):
        raise CalibrationError("Refinement requires new trial evidence")
    samples = _intrinsic(trials, previous.response, previous.t_s)
    median = np.median(samples, axis=0)
    variability = float(np.median(np.sqrt(np.mean((samples - median) ** 2, axis=1))))
    if variability > max(2., .25 * float(np.sqrt(np.mean(median ** 2)))):
        raise CalibrationError("Refinement evidence is not repeatable")
    target = -median / previous.response.gain_px_per_count
    update = np.clip(learning_rate * (target - previous.uy_counts), -max_update_counts, max_update_counts)
    u = _limit_rate(previous.uy_counts + update, previous.t_s, previous.max_speed_counts_s)
    return Profile(previous.context, previous.source, previous.response, previous.t_s, u,
                   **_evidence(trials, previous), max_speed_counts_s=previous.max_speed_counts_s,
                   parent_id=previous.profile_id)


def _event_replay(profile: Profile, trial: Trial) -> bool:
    """Check actual, integer accepted-event records without inventing missing input.

    This verifies consistency, not authenticity or that an external game accepted
    the events. The independently measured residual still decides pass/fail.
    """
    events = trial.provenance.get("input_events")
    if trial.provenance.get("candidate_id") != profile.profile_id or not isinstance(events, list) or not events:
        return False
    try:
        stamps = np.asarray([e["t_s"] for e in events], dtype=float)
        values = np.asarray([e["uy_counts"] for e in events], dtype=float)
        if (not np.isfinite(stamps).all() or not np.isfinite(values).all() or
            stamps[0] < 0 or np.any(np.diff(stamps) <= 0) or stamps[-1] > trial.t_s[-1] or
            np.any(values != np.rint(values)) or
            np.max(np.abs(values - profile.input_at(stamps))) > .51 or
            abs(values[-1] - profile.uy_counts[-1]) > .51):
            return False
        # Recorded image samples must agree with the accepted input log exactly.
        idx = np.searchsorted(stamps, trial.t_s, side="right") - 1
        observed = np.where(idx >= 0, values[np.maximum(0, idx)], 0.)
        if np.max(np.abs(observed - trial.uy_counts)) > 1e-6:
            return False
        # No undocumented late/missing changes hidden between measurement frames.
        grid = np.linspace(0, profile.t_s[-1], max(21, int(profile.t_s[-1]*200)+1))
        j = np.searchsorted(stamps, grid, side="right") - 1
        step = np.where(j >= 0, values[np.maximum(0, j)], 0.)
        tolerance = .51 + profile.max_speed_counts_s * .1
        return bool(np.max(np.abs(step-profile.input_at(grid))) <= tolerance)
    except (KeyError, TypeError, ValueError, IndexError):
        return False


def validate_profile(profile: Profile, trials: list[Trial], *, previous: Profile | None = None,
                     min_improvement: float = .5, max_peak_px: float = 20.) -> dict:
    """Validate on held-out captures; distinguish prediction from recorded replay.

    A real-world claim is never inferred from a synthetic sample or an offline
    counterfactual. Returning passed=True means only the stated evidence passed.
    """
    checked(trials, "validation")
    _compatible(trials, profile.response)
    if not np.isfinite(min_improvement) or not 0 <= min_improvement < 1:
        raise CalibrationError("min_improvement must be in [0,1)")
    if not np.isfinite(max_peak_px) or max_peak_px <= 0:
        raise CalibrationError("max_peak_px must be positive")
    if previous:
        if previous.response.response_id != profile.response.response_id or previous.t_s[-1] != profile.t_s[-1]:
            raise CalibrationError("Comparison profiles require same response and duration")
    for t in trials:
        for p in [profile] + ([previous] if previous else []):
            if (t.run_id in p.training_run_ids or t.session_id in p.training_session_ids or
                t.content_hash in p.training_content_hashes or t.capture_id in p.training_capture_ids):
                raise CalibrationError("Training / validation data leakage detected")
        if t.t_s[-1] + 1e-9 < profile.t_s[-1]:
            raise CalibrationError("Holdout shorter than profile; refusing extrapolation")
    details = []
    all_replayed = True
    for trial in trials:
        # A common evaluation grid makes scores independent of irregular FPS.
        grid = np.linspace(0, profile.t_s[-1], max(21, int(profile.t_s[-1] * 100) + 1))
        intrinsic = np.interp(grid, trial.t_s, trial.dy_px - profile.response.effect(trial))
        predicted = intrinsic + profile.effect_at(grid)
        applied = np.interp(grid, trial.t_s, trial.uy_counts)
        replayed = bool(np.max(np.abs(applied - profile.input_at(grid))) <= .51) or _event_replay(profile, trial)
        all_replayed &= replayed
        # Recorded replay uses measured residual, not a corrected prediction.
        residual = np.interp(grid, trial.t_s, trial.dy_px) if replayed else predicted
        base_rms = float(np.sqrt(np.mean(intrinsic ** 2)))
        rms = float(np.sqrt(np.mean(residual ** 2)))
        peak = float(np.max(np.abs(residual)))
        improvement = 1. - rms / max(base_rms, 1e-9)
        phase_rms = [float(np.sqrt(np.mean(part ** 2))) for part in np.array_split(residual, 3)]
        previous_rms = None
        no_regression = True
        if previous:
            prev_residual = intrinsic + previous.effect_at(grid)
            previous_rms = float(np.sqrt(np.mean(prev_residual ** 2)))
            no_regression = rms <= previous_rms + .1
        details.append({"run_id": trial.run_id, "session_id": trial.session_id,
                        "content_sha256": trial.content_hash, "baseline_rms_px": base_rms,
                        "residual_rms_px": rms, "peak_abs_px": peak,
                        "improvement": improvement, "stage_rms_px": phase_rms,
                        "replayed": replayed, "previous_predicted_rms_px": previous_rms,
                        "passed": bool(base_rms >= 1. and improvement >= min_improvement and
                                       peak <= max_peak_px and no_regression)})
    passed = all(x["passed"] for x in details)
    kind = "SIMULATED_REPLAY" if profile.source == "synthetic" and all_replayed else (
        "RECORDED_REPLAY" if all_replayed else "MODEL_PREDICTION")
    return {"schema_version": 1, "profile_id": profile.profile_id,
            "previous_profile_id": previous.profile_id if previous else None,
            "evidence_kind": kind, "source": profile.source, "passed": passed,
            "measured_replay_pass": bool(passed and all_replayed),
            "game_verified": False,
            "decision": ("KEEP_CANDIDATE_IN_LAB" if passed and all_replayed else
                         "PREDICTION_ONLY" if passed else "KEEP_PREVIOUS"),
            "thresholds": {"min_improvement": min_improvement, "max_peak_px": max_peak_px},
            "limitations": ["Vertical displacement only; not bullet-impact accuracy",
                            "No live game, mouse driver or anti-cheat integration tested",
                            "Latency is a model parameter; UI grid-search estimates are not hardware certification",
                            "A previous-profile comparison is a model prediction, not a paired live replay"],
            "trials": details}
