from dataclasses import replace

import numpy as np
import pytest

from recoil_lab.calibration import fit_profile, fit_response, refine_profile, validate_profile
from recoil_lab.contracts import CalibrationError
from recoil_lab.demo import recoil_trial, response_trial


def test_response_gain(response):
    assert response.gain_px_per_count == pytest.approx(1.75, abs=.005)


def test_known_latency_response():
    r = fit_response([response_trial(3, latency_s=.03), response_trial(4, latency_s=.03)], .03)
    assert r.gain_px_per_count == pytest.approx(1.75, abs=.005)


def test_response_no_excitation():
    runs = [response_trial(3), response_trial(4)]
    runs = [replace(t, uy_counts=np.zeros_like(t.t_s)) for t in runs]
    with pytest.raises(CalibrationError, match="positive and negative"):
        fit_response(runs)


def test_response_nonrepeatable():
    runs = [response_trial(3), response_trial(4)]
    rng = np.random.default_rng(14)
    for t in runs:
        t.dy_px[1:] += rng.normal(0, 40, len(t.t_s)-1)
    with pytest.raises(CalibrationError, match="not repeatable"):
        fit_response(runs)


def test_initial_fit_improves(response, training):
    p = fit_profile(training, response, learning_rate=1)
    report = validate_profile(p, [recoil_trial(i, "validation", profile=p) for i in (50, 51, 52)])
    assert report["passed"]
    assert report["evidence_kind"] == "SIMULATED_REPLAY"
    assert not report["game_verified"]
    assert min(t["improvement"] for t in report["trials"]) > .97


def test_refinement_improves_and_does_not_mutate(profile):
    old_id = profile.profile_id
    fresh = [recoil_trial(i, "train", profile=profile) for i in (31, 32, 33)]
    candidate = refine_profile(profile, fresh)
    report = validate_profile(candidate, [recoil_trial(i, "validation", profile=candidate) for i in (41, 42, 43)], previous=profile)
    assert report["passed"]
    assert candidate.parent_id == old_id == profile.profile_id
    assert len(candidate.training_run_ids) == 6
    assert all(t["residual_rms_px"] < t["previous_predicted_rms_px"] for t in report["trials"])


def test_failed_candidate_keeps_previous(profile):
    bad = replace(profile, uy_counts=-profile.uy_counts, parent_id=profile.profile_id)
    holdout = [recoil_trial(i, "validation", profile=bad) for i in (41, 42, 43)]
    report = validate_profile(bad, holdout, previous=profile)
    assert not report["passed"]
    assert report["decision"] == "KEEP_PREVIOUS"


@pytest.mark.parametrize("badness", ["same_session", "same_content", "same_run", "same_capture"])
def test_holdout_leakage(profile, training, badness):
    holdout = [recoil_trial(i, "validation") for i in (41, 42, 43)]
    if badness == "same_session":
        holdout[0].session_id = training[0].session_id
    elif badness == "same_run":
        holdout[0].run_id = training[0].run_id
    elif badness == "same_capture":
        holdout[0].provenance["capture_sha256"] = training[0].capture_id
    else:
        holdout[0] = replace(training[0], phase="validation", run_id="renamed", session_id="renamed-session")
    with pytest.raises(CalibrationError, match="leakage"):
        validate_profile(profile, holdout)


def test_offline_prediction_not_replay(response, training):
    p = fit_profile(training, response, learning_rate=1)
    report = validate_profile(p, [recoil_trial(i, "validation") for i in (41, 42, 43)])
    assert report["passed"]
    assert report["evidence_kind"] == "MODEL_PREDICTION"
    assert report["decision"] == "PREDICTION_ONLY"
    assert not report["measured_replay_pass"]


def test_recorded_label_does_not_imply_game_verification():
    # Synthetic numeric fixtures exercise the branch only; NOT recorded evidence.
    response = fit_response([response_trial(i, source="recorded") for i in (3, 4)])
    p = fit_profile([recoil_trial(i, "train", source="recorded") for i in (21, 22, 23)], response, learning_rate=1)
    report = validate_profile(p, [recoil_trial(i, "validation", profile=p, source="recorded") for i in (41, 42, 43)])
    assert report["evidence_kind"] == "RECORDED_REPLAY"
    assert not report["game_verified"]


def test_context_mismatch(response, training):
    training[0].context = dict(training[0].context, zoom=4)
    with pytest.raises(CalibrationError, match="mix"):
        fit_profile(training, response)


def test_source_mismatch(response, training):
    training[0].source = "recorded"
    with pytest.raises(CalibrationError, match="mix"):
        fit_profile(training, response)


def test_wrong_phase(response, training):
    training[0].phase = "validation"
    with pytest.raises(CalibrationError, match="Expected train"):
        fit_profile(training, response)


def test_duplicate_training(response, training):
    with pytest.raises(CalibrationError, match="Duplicate"):
        fit_profile([training[0], training[0], training[1]], response)


def test_minimum_trials(response, training):
    with pytest.raises(CalibrationError, match="At least"):
        fit_profile(training[:2], response)


def test_refine_requires_new_data(profile, training):
    with pytest.raises(CalibrationError, match="new trial"):
        refine_profile(profile, training)


def test_short_holdout(profile):
    with pytest.raises(CalibrationError, match="shorter"):
        validate_profile(profile, [recoil_trial(i, "validation", duration=1.) for i in (41, 42, 43)])


def test_refine_no_extrapolation(profile):
    with pytest.raises(CalibrationError, match="cover"):
        refine_profile(profile, [recoil_trial(i, "train", duration=1.) for i in (31, 32, 33)])


def test_nonrepeatable_recoil(response, training):
    for t, multiplier in zip(training, [.1, 1, 2]):
        t.dy_px *= multiplier
    with pytest.raises(CalibrationError, match="variability"):
        fit_profile(training, response)


def test_insufficient_signal(response, training):
    for t in training:
        t.dy_px *= .001
    with pytest.raises(CalibrationError, match="noise floor"):
        fit_profile(training, response)


def test_rate_limited(profile, response, training):
    p = fit_profile(training, response, max_speed_counts_s=10.)
    assert np.max(np.abs(np.diff(p.uy_counts) / np.diff(p.t_s))) <= 10.000001


@pytest.mark.parametrize("rate", [0, -1, 1.1, float("nan")])
def test_invalid_learning_rate(response, training, rate):
    with pytest.raises(CalibrationError, match="learning_rate"):
        fit_profile(training, response, learning_rate=rate)
