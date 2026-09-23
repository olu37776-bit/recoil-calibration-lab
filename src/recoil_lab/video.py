"""Static-background translation measurement; no target or weapon recognition."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

import numpy as np

from .contracts import CalibrationError, Trial, context_id


def _cv():
    try:
        import cv2
    except ImportError as exc:
        raise CalibrationError("Video support requires: pip install -e '.[video]'") from exc
    return cv2


def track_frames(frames: Iterable[tuple[float, np.ndarray]], roi: tuple[int, int, int, int],
                 *, context: dict, run_id: str, session_id: str, source: str,
                 provenance: dict) -> Trial:
    """Negative background motion is camera drift, in screen pixels.

    One failed interval invalidates the whole trial. This deliberately refuses
    to reinitialize cumulative position after occlusion or fabricate lost motion.
    Input is declared uncompensated and starts at the operator-selected t0.
    """
    cv = _cv()
    context_id(context)
    if len(roi) != 4 or any(type(v) is not int for v in roi):
        raise CalibrationError("ROI must be four integers: x,y,width,height")
    x, y, w, h = roi
    if min(x, y) < 0 or min(w, h) < 32:
        raise CalibrationError("ROI must be in bounds and at least 32x32")
    previous = None
    t0 = None
    last_time = None
    cumulative = np.zeros(2, dtype=float)
    anchor_cumulative = cumulative.copy()
    anchor_age = 0
    samples = []
    mask = None
    for stamp, image in frames:
        if not np.isfinite(stamp):
            raise CalibrationError("Nonfinite video timestamp")
        if last_time is not None and (stamp <= last_time or stamp - last_time > .100001):
            raise CalibrationError("Missing, nonmonotonic or >100ms video timestamp gap")
        if image is None or image.dtype != np.uint8 or image.ndim not in (2, 3):
            raise CalibrationError("Expected an 8-bit frame")
        if image.ndim == 3 and image.shape[2] not in (3, 4):
            raise CalibrationError("Expected grayscale, BGR or BGRA frame")
        gray = image if image.ndim == 2 else cv.cvtColor(image, cv.COLOR_BGR2GRAY)
        ih, iw = gray.shape
        if context["resolution"] != [iw, ih]:
            raise CalibrationError("Context resolution differs from video; implicit rescaling forbidden")
        if x+w > iw or y+h > ih:
            raise CalibrationError("ROI exceeds frame bounds")
        if previous is None:
            mask = np.zeros_like(gray)
            mask[y:y+h, x:x+w] = 255
            previous, t0, last_time = gray, stamp, stamp
            samples.append((0., 0., 0., 0., 1., 1))
            continue
        corners = cv.goodFeaturesToTrack(previous, maxCorners=240, qualityLevel=.02,
                                          minDistance=6, mask=mask, blockSize=7)
        if corners is None or len(corners) < 12:
            raise CalibrationError("Too few background features: choose a textured static ROI")
        settings = dict(winSize=(21, 21), maxLevel=3,
                        criteria=(cv.TERM_CRITERIA_EPS | cv.TERM_CRITERIA_COUNT, 30, .01))
        forward, ok_f, _ = cv.calcOpticalFlowPyrLK(previous, gray, corners, None, **settings)
        if forward is None or ok_f is None:
            raise CalibrationError("Forward optical flow failed")
        backward, ok_b, _ = cv.calcOpticalFlowPyrLK(gray, previous, forward, None, **settings)
        if backward is None or ok_b is None:
            raise CalibrationError("Backward optical flow failed")
        p = corners.reshape(-1, 2)
        q = forward.reshape(-1, 2)
        r = backward.reshape(-1, 2)
        good = ((ok_f.ravel() == 1) & (ok_b.ravel() == 1) &
                (np.linalg.norm(p-r, axis=1) <= .8) & np.isfinite(q).all(axis=1) &
                (q[:, 0] >= x) & (q[:, 0] < x+w) & (q[:, 1] >= y) & (q[:, 1] < y+h))
        if good.sum() < 12:
            raise CalibrationError("Background tracking lost; whole burst rejected")
        shifts = q[good] - p[good]
        median = np.median(shifts, axis=0)
        inliers = np.linalg.norm(shifts - median, axis=1) <= 1.25
        confidence = float(inliers.sum() / len(corners))
        if inliers.sum() < 12 or confidence < .65:
            raise CalibrationError("Inconsistent flow: movement, occlusion, zoom or scene cut suspected")
        shift = np.median(shifts[inliers], axis=0)
        # Use short keyframes instead of summing a fresh subpixel estimate
        # every frame: per-frame interpolation bias otherwise accumulates.
        current = anchor_cumulative - shift
        if np.linalg.norm(current - cumulative) > 40:
            raise CalibrationError("Frame displacement exceeds the 40px gate")
        cumulative = current
        samples.append((float(stamp-t0), *cumulative.tolist(), 0., confidence, 1))
        anchor_age += 1
        if anchor_age >= 8:
            previous, anchor_cumulative, anchor_age = gray, cumulative.copy(), 0
        last_time = stamp
    if len(samples) < 10:
        raise CalibrationError("Video interval needs at least 10 frames")
    values = np.asarray(samples, dtype=float)
    trial = Trial(run_id, session_id, context, "train", source,
                  *[values[:, i] for i in range(6)], provenance=provenance)
    trial.gate("train")
    return trial


def extract_video(path: str | Path, *, context: dict, roi: tuple[int, int, int, int],
                  run_id: str, start_s: float, duration_s: float,
                  declared_uncompensated: bool, assumed_fps: float | None = None) -> Trial:
    if not declared_uncompensated:
        raise CalibrationError("Explicit --uncompensated declaration required; input is not inferred from video")
    if not np.isfinite(start_s) or start_s < 0 or not np.isfinite(duration_s) or duration_s < .2:
        raise CalibrationError("Invalid interval: start>=0 and duration>=.2 seconds required")
    if assumed_fps is not None and (not np.isfinite(assumed_fps) or not 10 <= assumed_fps <= 1000):
        raise CalibrationError("assumed_fps must be in [10,1000]")
    path = Path(path)
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            hasher.update(chunk)
    capture_hash = hasher.hexdigest()
    cv = _cv()
    cap = cv.VideoCapture(str(path))
    if not cap.isOpened():
        cap.release()
        raise CalibrationError("Cannot open video")
    def frames():
        index = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            stamp = index / assumed_fps if assumed_fps is not None else cap.get(cv.CAP_PROP_POS_MSEC) / 1000.
            index += 1
            if stamp < start_s:
                continue
            if stamp > start_s + duration_s + 1e-9:
                break
            yield stamp, frame
    try:
        trial = track_frames(frames(), roi, context=context, run_id=run_id,
                             session_id="video-"+capture_hash[:32], source="recorded",
                             provenance={"capture_sha256": capture_hash, "roi": list(roi),
                                         "start_s": start_s, "requested_duration_s": duration_s,
                                         "timing": "assumed_fps" if assumed_fps is not None else "media_timestamps",
                                         "assumed_fps": assumed_fps,
                                         "operator_declaration": "stationary, fixed ADS, no compensation",
                                         "detector": "LK-FB-keyframe8-median-translation-v1"})
        if trial.t_s[-1] < duration_s - .100001:
            raise CalibrationError("Video ended before requested interval")
        return trial
    finally:
        cap.release()
