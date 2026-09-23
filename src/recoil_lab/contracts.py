"""Explicit units, provenance, validity and serialization contracts."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np


class CalibrationError(ValueError):
    """A rejected measurement, configuration or calibration artifact."""


def canonical(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise CalibrationError("JSON must contain only finite, serializable values") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def write_json(path: str | Path, value: Any) -> None:
    path = Path(path)
    # Serialize before touching the destination; do not leave half-written output.
    text = json.dumps(json.loads(canonical(value)), indent=2, ensure_ascii=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path: str | Path) -> dict:
    with Path(path).open(encoding="utf-8-sig") as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        raise CalibrationError("Expected a JSON object")
    canonical(obj)
    return obj


def identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value):
        raise CalibrationError(f"Invalid {name}")


def context_id(context: dict) -> str:
    required = {"weapon", "attachments", "dpi", "sensitivity", "ads_sensitivity",
                "zoom", "resolution", "fov", "pose", "game_build", "input_backend"}
    if not isinstance(context, dict) or not required <= context.keys():
        raise CalibrationError(f"Context requires: {sorted(required)}")
    for key in ("dpi", "sensitivity", "ads_sensitivity", "zoom", "fov"):
        val = context[key]
        if isinstance(val, bool) or not isinstance(val, (float, int)) or not np.isfinite(val) or val <= 0:
            raise CalibrationError(f"context.{key} must be finite and positive")
    res = context["resolution"]
    if not isinstance(res, list) or len(res) != 2 or any(type(v) is not int or v <= 0 for v in res):
        raise CalibrationError("resolution must be [width, height] positive integers")
    if not isinstance(context["attachments"], list) or not all(isinstance(x, str) for x in context["attachments"]):
        raise CalibrationError("attachments must be a string list")
    for key in ("weapon", "pose", "game_build", "input_backend"):
        if not isinstance(context[key], str) or not context[key]:
            raise CalibrationError(f"context.{key} must be nonempty text")
    return digest(context)


def vector(value: Any, name: str) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if arr.ndim != 1 or not np.all(np.isfinite(arr)):
        raise CalibrationError(f"{name} must be a finite one-dimensional array")
    return arr


@dataclass
class Trial:
    run_id: str
    session_id: str
    context: dict
    phase: str
    source: str
    t_s: Any
    dx_px: Any
    dy_px: Any
    uy_counts: Any
    confidence: Any
    valid: Any
    provenance: dict

    def __post_init__(self) -> None:
        identifier(self.run_id, "run_id")
        identifier(self.session_id, "session_id")
        context_id(self.context)
        if self.phase not in {"response", "train", "validation"}:
            raise CalibrationError("Invalid trial phase")
        if self.source not in {"synthetic", "recorded"}:
            raise CalibrationError("source must be synthetic or recorded")
        if not isinstance(self.provenance, dict) or not self.provenance:
            raise CalibrationError("Nonempty provenance is required")
        canonical(self.provenance)
        for field in ("t_s", "dx_px", "dy_px", "uy_counts", "confidence"):
            setattr(self, field, vector(getattr(self, field), field))
        raw_valid = np.asarray(self.valid)
        if raw_valid.ndim != 1 or not np.all(np.isin(raw_valid, [0, 1])):
            raise CalibrationError("valid must contain booleans or 0/1")
        self.valid = raw_valid.astype(bool)
        n = len(self.t_s)
        if n < 10 or any(len(getattr(self, k)) != n for k in
                         ("dx_px", "dy_px", "uy_counts", "confidence", "valid")):
            raise CalibrationError("Trial requires at least 10 equal-length samples")
        if abs(self.t_s[0]) > 1e-9 or np.any(np.diff(self.t_s) <= 0):
            raise CalibrationError("Time must start at zero and strictly increase")
        if np.any((self.confidence < 0) | (self.confidence > 1)):
            raise CalibrationError("Confidence must be in [0,1]")
        if max(abs(self.dx_px[0]), abs(self.dy_px[0]), abs(self.uy_counts[0])) > 1e-6:
            raise CalibrationError("Displacement and cumulative input must start at zero")

    @property
    def context_hash(self) -> str:
        return context_id(self.context)

    @property
    def content_hash(self) -> str:
        # Independent of filename/run_id: relabeling a capture is not a holdout.
        return digest({k: getattr(self, k).tolist() for k in
                       ("t_s", "dx_px", "dy_px", "uy_counts", "confidence", "valid")})

    @property
    def capture_id(self) -> str:
        return str(self.provenance.get("capture_sha256", self.session_id))

    def gate(self, phase: str | None = None) -> None:
        if phase is not None and phase != self.phase:
            raise CalibrationError(f"Expected {phase}, got {self.phase}: {self.run_id}")
        # V0.1 rejects whole bursts; never bridge lost tracking with invented motion.
        if not self.valid.all() or float(self.confidence.min()) < 0.65:
            raise CalibrationError(f"Low-confidence or invalid sample: {self.run_id}")
        if float(np.diff(self.t_s).max()) > 0.100001:
            raise CalibrationError(f"Timestamp gap exceeds 100 ms: {self.run_id}")
        if self.t_s[-1] < 0.2:
            raise CalibrationError("Trial duration must be at least 200 ms")


CSV_COLUMNS = ["t_s", "dx_px", "dy_px", "uy_counts", "confidence", "valid"]


def save_trial(path: str | Path, trial: Trial) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    csv_path = path.with_suffix(".csv")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLUMNS)
        for row in zip(*(getattr(trial, x) for x in CSV_COLUMNS)):
            w.writerow([*(float(v) for v in row[:-1]), int(row[-1])])
    write_json(path, {"schema_version": 1, "csv": csv_path.name,
                     "run_id": trial.run_id, "session_id": trial.session_id,
                     "context": trial.context, "phase": trial.phase,
                     "source": trial.source, "provenance": trial.provenance,
                     "content_sha256": trial.content_hash})


def load_trial(path: str | Path) -> Trial:
    path = Path(path)
    meta = read_json(path)
    if meta.get("schema_version") != 1:
        raise CalibrationError("Unsupported trial schema")
    csv_name = meta.get("csv")
    # A metadata file may refer only to its sibling CSV, not arbitrary paths.
    if not isinstance(csv_name, str) or Path(csv_name).name != csv_name or not csv_name.endswith(".csv"):
        raise CalibrationError("csv must be a sibling CSV filename")
    csv_path = path.parent / csv_name
    if csv_path.resolve().parent != path.parent.resolve():
        raise CalibrationError("CSV path must not escape the metadata directory")
    columns = {k: [] for k in CSV_COLUMNS}
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != CSV_COLUMNS:
            raise CalibrationError(f"CSV columns must be exactly {CSV_COLUMNS}")
        for row in reader:
            for k in columns:
                columns[k].append(float(row[k]))
    trial = Trial(**{k: meta[k] for k in ("run_id", "session_id", "context", "phase", "source", "provenance")},
                  **columns)
    if meta.get("content_sha256") != trial.content_hash:
        raise CalibrationError("CSV content hash mismatch")
    return trial


@dataclass
class Response:
    context: dict
    source: str
    gain_px_per_count: float
    latency_s: float
    fit_rmse_px: float
    run_ids: list[str]

    def __post_init__(self) -> None:
        context_id(self.context)
        if self.source not in {"synthetic", "recorded"}:
            raise CalibrationError("Invalid response source")
        if not np.isfinite(self.gain_px_per_count) or not 1e-4 <= abs(self.gain_px_per_count) <= 100:
            raise CalibrationError("Input response gain is zero or out of bounds")
        if not np.isfinite(self.latency_s) or not 0 <= self.latency_s <= 0.2:
            raise CalibrationError("latency_s must be in [0,0.2]")
        if not np.isfinite(self.fit_rmse_px) or self.fit_rmse_px < 0 or not self.run_ids:
            raise CalibrationError("Invalid response evidence")

    @property
    def response_id(self) -> str:
        return digest(asdict(self))

    def effect(self, trial: Trial) -> np.ndarray:
        delayed = np.interp(trial.t_s - self.latency_s, trial.t_s, trial.uy_counts, left=0)
        return self.gain_px_per_count * delayed


@dataclass
class Profile:
    context: dict
    source: str
    response: Response
    t_s: Any
    uy_counts: Any
    training_run_ids: list[str]
    training_session_ids: list[str]
    training_content_hashes: list[str]
    training_capture_ids: list[str]
    max_speed_counts_s: float
    parent_id: str | None = None

    def __post_init__(self) -> None:
        if context_id(self.context) != context_id(self.response.context) or self.source != self.response.source:
            raise CalibrationError("Profile / response context or source mismatch")
        self.t_s = vector(self.t_s, "profile.t_s")
        self.uy_counts = vector(self.uy_counts, "profile.uy_counts")
        if len(self.t_s) < 3 or len(self.uy_counts) != len(self.t_s):
            raise CalibrationError("Profile requires at least three matching knots")
        if abs(self.t_s[0]) > 1e-9 or np.any(np.diff(self.t_s) <= 0) or abs(self.uy_counts[0]) > 1e-6:
            raise CalibrationError("Profile must have increasing time and zero initial input")
        if not np.isfinite(self.max_speed_counts_s) or not 0 < self.max_speed_counts_s <= 10000:
            raise CalibrationError("Invalid profile speed limit")
        speed = np.abs(np.diff(self.uy_counts) / np.diff(self.t_s))
        if speed.max() > self.max_speed_counts_s + 1e-6:
            raise CalibrationError("Profile violates speed limit")
        if not all((self.training_run_ids, self.training_session_ids,
                    self.training_content_hashes, self.training_capture_ids)):
            raise CalibrationError("Training provenance is required")

    def to_dict(self) -> dict:
        data = asdict(self)
        data["t_s"] = self.t_s.tolist()
        data["uy_counts"] = self.uy_counts.tolist()
        return {"schema_version": 1, **data}

    @property
    def profile_id(self) -> str:
        return digest(self.to_dict())

    def input_at(self, t_s: Any) -> np.ndarray:
        return np.interp(t_s, self.t_s, self.uy_counts, left=0)

    def effect_at(self, t_s: Any) -> np.ndarray:
        return self.response.gain_px_per_count * self.input_at(np.asarray(t_s) - self.response.latency_s)


def save_profile(path: str | Path, profile: Profile) -> None:
    write_json(path, {**profile.to_dict(), "profile_id": profile.profile_id})


def load_profile(path: str | Path) -> Profile:
    data = read_json(path)
    if data.pop("schema_version", None) != 1:
        raise CalibrationError("Unsupported profile schema")
    expected = data.pop("profile_id", None)
    data["response"] = Response(**data["response"])
    profile = Profile(**data)
    if expected != profile.profile_id:
        raise CalibrationError("Profile content hash mismatch")
    return profile
