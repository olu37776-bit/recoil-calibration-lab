from pathlib import Path

import numpy as np
import pytest

cv = pytest.importorskip("cv2")

from recoil_lab.contracts import CalibrationError
from recoil_lab.demo import example_context
from recoil_lab.video import extract_video, track_frames


def context():
    ctx = example_context(); ctx["resolution"] = [320, 240]
    return ctx


def frames(n=30):
    rng = np.random.default_rng(450)
    image = rng.integers(0, 256, size=(240, 320), dtype=np.uint8)
    image = cv.GaussianBlur(image, (3, 3), 0)
    for i in range(n):
        transform = np.float32([[1, 0, i*.3], [0, 1, i*.5]])
        yield i/30., cv.warpAffine(image, transform, (320, 240), borderMode=cv.BORDER_REFLECT)


def kwargs():
    return dict(context=context(), run_id="video-test", session_id="video-test-session",
                source="synthetic", provenance={"generator": "translation-test-v1"})


def test_known_translation():
    trial = track_frames(frames(), (40, 30, 240, 180), **kwargs())
    assert trial.dx_px[-1] == pytest.approx(-8.7, abs=.4)
    assert trial.dy_px[-1] == pytest.approx(-14.5, abs=.4)
    assert trial.confidence.min() >= .65


def test_blank_roi_rejected():
    data = [(i/30., np.zeros((240, 320), dtype=np.uint8)) for i in range(15)]
    with pytest.raises(CalibrationError, match="features"):
        track_frames(data, (40, 30, 240, 180), **kwargs())


def test_occlusion_rejected():
    data = list(frames())
    data[10] = (data[10][0], np.full((240, 320), 255, dtype=np.uint8))
    with pytest.raises(CalibrationError):
        track_frames(data, (40, 30, 240, 180), **kwargs())


@pytest.mark.parametrize("roi", [(0, 0, 10, 10), (-1, 0, 100, 100), (0, 0, 500, 500)])
def test_roi_gate(roi):
    with pytest.raises(CalibrationError, match="ROI"):
        track_frames(frames(), roi, **kwargs())


def test_resolution_gate():
    kw = kwargs(); kw["context"] = example_context()
    with pytest.raises(CalibrationError, match="resolution"):
        track_frames(frames(), (40, 30, 240, 180), **kw)


def test_video_timestamp_gate():
    data = list(frames())
    data[2] = (0., data[2][1])
    with pytest.raises(CalibrationError, match="timestamp"):
        track_frames(data, (40, 30, 240, 180), **kwargs())


def test_insufficient_frames():
    with pytest.raises(CalibrationError, match="10 frames"):
        track_frames(frames(5), (40, 30, 240, 180), **kwargs())


def make_video(tmp_path):
    path = tmp_path / "synthetic.avi"
    writer = cv.VideoWriter(str(path), cv.VideoWriter_fourcc(*"MJPG"), 30., (320, 240))
    assert writer.isOpened(), "Test environment needs MJPG encoding"
    for _, img in frames():
        writer.write(cv.cvtColor(img, cv.COLOR_GRAY2BGR))
    writer.release()
    return path


def test_encoded_video_end_to_end(tmp_path):
    path = make_video(tmp_path)
    trial = extract_video(path, context=context(), roi=(40, 30, 240, 180), run_id="actual-file",
                          start_s=0., duration_s=.9, declared_uncompensated=True)
    assert trial.source == "recorded"
    assert trial.dy_px[-1] == pytest.approx(-13.5, abs=.65)
    assert trial.provenance["timing"] == "media_timestamps"
    assert trial.session_id.startswith("video-")


def test_explicit_assumed_fps(tmp_path):
    path = make_video(tmp_path)
    trial = extract_video(path, context=context(), roi=(40, 30, 240, 180), run_id="actual-file",
                          start_s=0., duration_s=.9, declared_uncompensated=True, assumed_fps=30.)
    assert trial.provenance["timing"] == "assumed_fps"


def test_operator_declaration_required(tmp_path):
    with pytest.raises(CalibrationError, match="declaration"):
        extract_video(tmp_path / "absent.avi", context=context(), roi=(40, 30, 240, 180), run_id="x",
                      start_s=0., duration_s=1., declared_uncompensated=False)


def test_video_shorter_than_interval(tmp_path):
    path = make_video(tmp_path)
    with pytest.raises(CalibrationError, match="ended"):
        extract_video(path, context=context(), roi=(40, 30, 240, 180), run_id="actual-file",
                      start_s=0., duration_s=2., declared_uncompensated=True)


def test_keyframes_limit_accumulated_subpixel_bias():
    trial = track_frames(frames(120), (40, 30, 240, 180), **kwargs())
    assert trial.dx_px[-1] == pytest.approx(-35.7, abs=.5)
    assert trial.dy_px[-1] == pytest.approx(-59.5, abs=.5)
