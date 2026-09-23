import pytest

from recoil_lab.calibration import fit_profile, fit_response
from recoil_lab.demo import recoil_trial, response_trial


@pytest.fixture
def response():
    return fit_response([response_trial(10), response_trial(11), response_trial(12)])


@pytest.fixture
def training():
    return [recoil_trial(i, "train") for i in (21, 22, 23)]


@pytest.fixture
def profile(response, training):
    return fit_profile(training, response)
