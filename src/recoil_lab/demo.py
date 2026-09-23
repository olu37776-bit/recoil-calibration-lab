"""Reproducible artificial test rig; contains no measured game weapon data."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import numpy as np

from .calibration import fit_profile, fit_response, refine_profile, validate_profile
from .contracts import Profile, Trial, save_profile, save_trial, write_json
from .playback import dry_run
from .report import write_html


def example_context() -> dict:
    return {"weapon": "SYNTHETIC_TEST_RIG_NOT_A_GAME_WEAPON", "attachments": [],
            "dpi": 800, "sensitivity": 1., "ads_sensitivity": 1., "zoom": 1.5,
            "resolution": [640, 480], "fov": 90., "pose": "stationary",
            "game_build": "synthetic-v1", "input_backend": "synthetic-recording-v1"}


def response_trial(seed: int, *, source: str = "synthetic", gain: float = 1.75,
                   latency_s: float = 0.) -> Trial:
    rng = np.random.default_rng(seed)
    t = np.linspace(0, 2, 201)
    u = 30 * np.sin(2*np.pi*t + .07*seed)
    u -= u[0]
    y = gain * np.interp(t-latency_s, t, u, left=0) + rng.normal(0, .04, len(t))
    y -= y[0]
    return Trial(f"response-{seed}", f"response-session-{seed}", example_context(), "response", source,
                 t, np.zeros_like(t), y, u, np.ones_like(t), np.ones_like(t),
                 {"generator": "response-v1", "seed": seed})


def recoil_trial(seed: int, phase: str, *, profile: Profile | None = None,
                 source: str = "synthetic", gain: float = 1.75,
                 duration: float = 2., latency_s: float = 0.) -> Trial:
    rng = np.random.default_rng(seed)
    t = np.linspace(0, duration, int(duration*100)+1)
    intrinsic = -(45*t + 28*(1-np.exp(-7*t)))
    intrinsic *= 1 + rng.normal(0, .004)
    intrinsic += rng.normal(0, .1, len(t))
    intrinsic -= intrinsic[0]
    u = np.rint(profile.input_at(t)) if profile else np.zeros_like(t)
    y = intrinsic + gain * np.interp(t-latency_s, t, u, left=0)
    return Trial(f"{phase}-{seed}", f"capture-{seed}", example_context(), phase, source,
                 t, np.zeros_like(t), y, u, np.ones_like(t), np.ones_like(t),
                 {"generator": "recoil-v1", "seed": seed})


def run_demo(out: str | Path) -> dict:
    out = Path(out)
    response_runs = [response_trial(n) for n in (10, 11, 12)]
    response = fit_response(response_runs)
    training = [recoil_trial(n, "train") for n in (21, 22, 23)]
    initial = fit_profile(training, response)
    refinement = [recoil_trial(n, "train", profile=initial) for n in (31, 32, 33)]
    candidate = refine_profile(initial, refinement)
    holdout = [recoil_trial(n, "validation", profile=candidate) for n in (41, 42, 43)]
    report = validate_profile(candidate, holdout, previous=initial)
    for trial in response_runs + training + refinement + holdout:
        save_trial(out / "trials" / (trial.run_id + ".json"), trial)
    write_json(out / "response.json", asdict(response))
    write_json(out / "context.json", example_context())
    save_profile(out / "initial-profile.json", initial)
    save_profile(out / "candidate-profile.json", candidate)
    write_json(out / "validation.json", report)
    write_html(out / "report.html", report)
    write_json(out / "dry-run-events.json", {"mode": "recording_only", "profile_id": candidate.profile_id,
                                            "events": dry_run(candidate)})
    return report
