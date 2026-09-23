import numpy as np
from recoil_lab.calibration import _event_replay
from recoil_lab.demo import recoil_trial


def event_trial(profile):
    trial=recoil_trial(90,'validation',profile=profile)
    times=trial.t_s
    values=np.rint(profile.input_at(times))
    changed=np.where(np.diff(values)!=0)[0]+1
    trial.provenance.update(candidate_id=profile.profile_id,
        input_events=[{'t_s':float(times[i]),'uy_counts':int(values[i])} for i in changed])
    return trial


def test_event_log(profile):
    trial=event_trial(profile)
    assert _event_replay(profile,trial)
    trial.uy_counts[10]+=5
    assert not _event_replay(profile,trial)


def test_bad_event_values(profile):
    for change in ('candidate','time','value','missing'):
        trial=event_trial(profile)
        if change=='candidate':trial.provenance['candidate_id']='fake'
        if change=='time':trial.provenance['input_events'][0]['t_s']=-1
        if change=='value':trial.provenance['input_events'][0]['uy_counts']=99999
        if change=='missing':trial.provenance['input_events']=[{}]
        assert not _event_replay(profile,trial)
