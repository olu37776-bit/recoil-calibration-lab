from dataclasses import replace
import json

import numpy as np
import pytest

from recoil_lab.contracts import (CalibrationError, Response, Trial, canonical, context_id,
                                  load_profile, load_trial, read_json, save_profile, save_trial, write_json)
from recoil_lab.demo import example_context, recoil_trial


def test_trial_roundtrip(tmp_path):
    trial = recoil_trial(1, "train")
    save_trial(tmp_path / "trial.json", trial)
    actual = load_trial(tmp_path / "trial.json")
    assert actual.content_hash == trial.content_hash
    assert actual.context_hash == trial.context_hash


def test_profile_roundtrip(tmp_path, profile):
    save_profile(tmp_path / "p.json", profile)
    restored = load_profile(tmp_path / "p.json")
    assert restored.profile_id == profile.profile_id


def test_trial_hash_tamper(tmp_path):
    save_trial(tmp_path / "t.json", recoil_trial(1, "train"))
    path = tmp_path / "t.csv"
    rows = path.read_text().splitlines()
    fields = rows[10].split(",")
    fields[2] = str(float(fields[2]) + 1.)
    rows[10] = ",".join(fields)
    path.write_text("\n".join(rows)+"\n")
    with pytest.raises(CalibrationError, match="hash"):
        load_trial(tmp_path / "t.json")


def test_profile_hash_tamper(tmp_path, profile):
    save_profile(tmp_path / "p.json", profile)
    obj = read_json(tmp_path / "p.json")
    obj["uy_counts"][3] += .1
    write_json(tmp_path / "p.json", obj)
    with pytest.raises(CalibrationError, match="hash"):
        load_profile(tmp_path / "p.json")


@pytest.mark.parametrize("field,value", [("dpi", 0), ("dpi", True), ("sensitivity", float("inf")),
    ("resolution", [0, 100]), ("resolution", [100., 100]), ("attachments", "scope"), ("weapon", "")])
def test_invalid_context(field, value):
    ctx = example_context()
    ctx[field] = value
    with pytest.raises(CalibrationError):
        context_id(ctx)


def test_missing_context():
    with pytest.raises(CalibrationError):
        context_id({})


@pytest.mark.parametrize("issue", ["nan", "duplicate_time", "negative_time", "length", "confidence", "initial_input", "valid"])
def test_invalid_trial(issue):
    t = recoil_trial(1, "train")
    kwargs = {}
    if issue == "nan":
        arr = t.dy_px.copy(); arr[4] = np.nan; kwargs["dy_px"] = arr
    elif issue == "duplicate_time":
        arr = t.t_s.copy(); arr[4] = arr[3]; kwargs["t_s"] = arr
    elif issue == "negative_time":
        kwargs["t_s"] = t.t_s - 1
    elif issue == "length":
        kwargs["dy_px"] = t.dy_px[:-1]
    elif issue == "confidence":
        kwargs["confidence"] = np.full_like(t.t_s, 1.1)
    elif issue == "initial_input":
        kwargs["uy_counts"] = t.uy_counts + 1
    else:
        kwargs["valid"] = np.full_like(t.t_s, 2)
    with pytest.raises(CalibrationError):
        replace(t, **kwargs)


@pytest.mark.parametrize("field", ["confidence", "valid"])
def test_quality_gate(field):
    t = recoil_trial(1, "train")
    arr = getattr(t, field).copy()
    arr[10] = 0
    bad = replace(t, **{field: arr})
    with pytest.raises(CalibrationError, match="confidence|invalid"):
        bad.gate()


def test_timestamp_gap():
    t = recoil_trial(1, "train")
    times = t.t_s.copy(); times[50:] += .3
    with pytest.raises(CalibrationError, match="gap"):
        replace(t, t_s=times).gate()


def test_json_reject_nonfinite_and_nonobject(tmp_path):
    with pytest.raises(CalibrationError):
        canonical({"a": float("nan")})
    p = tmp_path / "x.json"; p.write_text("[]")
    with pytest.raises(CalibrationError):
        read_json(p)


def test_path_escape_rejected(tmp_path):
    p = tmp_path / "t.json"
    save_trial(p, recoil_trial(1, "train"))
    obj = read_json(p); obj["csv"] = "../secrets.csv"; write_json(p, obj)
    with pytest.raises(CalibrationError, match="sibling"):
        load_trial(p)


def test_schema_rejected(tmp_path):
    p = tmp_path / "t.json"; write_json(p, {"schema_version": 99})
    with pytest.raises(CalibrationError, match="schema"):
        load_trial(p)


@pytest.mark.parametrize("gain", [0., float("nan"), 1000.])
def test_response_gain_gate(response, gain):
    with pytest.raises(CalibrationError):
        replace(response, gain_px_per_count=gain)


def test_speed_gate(profile):
    with pytest.raises(CalibrationError, match="speed"):
        replace(profile, max_speed_counts_s=.01)
