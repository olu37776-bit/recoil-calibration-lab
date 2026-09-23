import copy
import pytest
from recoil_lab.temporal import CandidateStabilizer
from recoil_lab.contracts import CalibrationError


def candidate(i=0, label='standing'):
    return dict(field='pose',label=label,reason='CANDIDATE',self_match=False,
                reference_set_id='refs',layout_id='v1',query_size=[1920,1080],pixel_sha256=str(i))


def stable(s):
    for i in range(3):r=s.update(i*.04,candidate(i))
    assert r['stable'] and not r['auto_execution_eligible']


def test_requires_frames_and_elapsed_time():
    s=CandidateStabilizer()
    for i in range(8):assert not s.update(i*.01,candidate(i))['stable']
    assert s.update(.08,candidate(8))['stable']


@pytest.mark.parametrize('patch,reason', [({'label':'unknown','reason':'LOW_SIMILARITY'},'UNKNOWN'),
    ({'self_match':True},'SELF_MATCH'), ({'pixel_sha256':'2'},'DUPLICATE_FRAME')])
def test_stop_without_holding_old_label(patch,reason):
    s=CandidateStabilizer();stable(s)
    c=candidate(3);c.update(patch)
    r=s.update(.12,c)
    assert r['reason']==reason and r['label']=='unknown' and not r['stable']
    assert not s.update(.16,candidate(4))['stable']


@pytest.mark.parametrize('patch', [{'query_size':[2560,1440]},{'layout_id':'v2'},{'reference_set_id':'new'}])
def test_geometry_change_reacquires(patch):
    s=CandidateStabilizer();stable(s);c=candidate(3);c.update(patch)
    r=s.update(.12,c)
    assert r['reason']=='GEOMETRY_CHANGED' and r['consecutive_frames']==1 and not r['stable']


def test_new_label_and_gap_require_new_dwell():
    s=CandidateStabilizer();stable(s)
    assert not s.update(.12,candidate(3,'crouching'))['stable']
    r=s.update(.3,candidate(4,'crouching'))
    assert r['reason']=='FRAME_GAP' and not r['stable']


@pytest.mark.parametrize('t',[-1,float('nan'),float('inf'),.08,True])
def test_bad_time_clears(t):
    s=CandidateStabilizer();stable(s)
    with pytest.raises(CalibrationError):s.update(t,candidate(3))
    assert s.count==0


@pytest.mark.parametrize('patch',[{'field':[]},{'pixel_sha256':None},{'layout_id':''},{'query_size':[0,0]}])
def test_bad_identity_clears(patch):
    s=CandidateStabilizer();stable(s);c=candidate(3);c.update(patch)
    with pytest.raises(CalibrationError):s.update(.12,c)
    assert s.count==0


def test_repeated_old_frame_cannot_increase_stability():
    s=CandidateStabilizer()
    assert not s.update(0,candidate(0))['stable']
    assert not s.update(.04,candidate(1))['stable']
    assert s.update(.08,candidate(0))['reason']=='DUPLICATE_FRAME'


def test_invalid_label_is_unknown():
    s=CandidateStabilizer();stable(s);c=candidate(3);c['label']=[]
    assert s.update(.12,c)['reason']=='UNKNOWN'
