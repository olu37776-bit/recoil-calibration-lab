import base64
from io import BytesIO

import numpy as np
from PIL import Image
import pytest

from recoil_lab.catalog import build_preset
from recoil_lab.contracts import CalibrationError, context_id, read_json, write_json
from recoil_lab.teaching import Teaching, Matcher, fingerprint, features, weight_label
from recoil_lab.workspace import Workspace
from recoil_lab.taught_runtime import RouteGate
from test_catalog import config


def picture(label=1, shot=0, blank=False):
    # New background per shot; the observable indicator is stable per label.
    image=np.random.default_rng(shot+1000).integers(0,60,(180,320),dtype=np.uint8)
    pattern=np.random.default_rng(label).integers(20,235,(32,64),dtype=np.uint8)
    image[100:132,230:294]=0 if blank else pattern
    out=BytesIO();Image.fromarray(image).save(out,format='PNG')
    return base64.b64encode(out.getvalue()).decode(),image


def preset(weight='重装'):
    p=config();p['settings']['resolution']=[320,180];p['settings']['weight_label']=weight
    return p


@pytest.fixture
def taught(tmp_path):
    w=Workspace(tmp_path);t=Teaching(w)
    a=w.create(preset(),'测试配置A');b=w.create(preset(),'测试配置B')
    bank=t.create({'project_id':a['id'],'rois':[[230,100,64,32]],'consent':True,
                   'session_id':'train','image':picture(1,0)[0]})
    t.add(bank['id'],{'project_id':b['id'],'consent':True,'session_id':'train','image':picture(2,1)[0]})
    return w,t,a,b,bank['id']


def fill_validation(t,a,b,bank):
    for label,p in [(1,a),(2,b)]:
        for n in [1,2]:
            t.add(bank,{'project_id':p['id'],'consent':True,'phase':'validation',
                        'session_id':'validation','image':picture(label,10*label+n)[0]})
    t.add(bank,{'project_id':None,'weight':'重装','consent':True,'phase':'validation',
               'session_id':'validation','image':picture(8,91)[0]})


def test_weight_is_label_not_multiplier():
    old=config(); original=build_preset(old)
    p=build_preset(preset('自定义-背包一'))
    assert p['settings']['weight_label']=='自定义-背包一'
    assert p['context']['weight_label']=='自定义-背包一'
    assert 'weight_label' not in original['context']
    assert context_id(original['context'])==original['context_id']
    a=preset('轻装');b=preset('重装')
    assert build_preset(a)['context_id']!=build_preset(b)['context_id']
    assert build_preset(a)['known_purchase_total']==build_preset(b)['known_purchase_total']


@pytest.mark.parametrize('v',[None,True,1,'',' '*2,'a'*33,'a\nb'])
def test_invalid_weight(v):
    with pytest.raises(CalibrationError):weight_label(v)
    p=preset();p['settings']['weight_label']=v
    with pytest.raises(CalibrationError):build_preset(p)


def test_teach_persist_crops_not_full_images(taught):
    w,t,a,b,bank=taught
    data=t.load(bank)
    assert len(data['samples'])==2
    assert 'image' not in data['samples'][0]
    assert len(base64.b64decode(data['samples'][0]['features'][0]))==4096
    assert 'features' not in t.list()[0]['samples'][0]
    reloaded=Teaching(Workspace(w.root))
    result=reloaded.query(bank,picture(2,7)[0],'重装')
    assert result['project_id']==b['id'] and result['mouse_output'] is False
    assert result['recognition_checked'] is False


def test_weight_never_inferred(taught):
    _,t,a,b,bank=taught
    assert t.query(bank,picture(1,10)[0],'轻装')['project_id'] is None
    assert t.query(bank,picture(1,10)[0],'重装')['project_id']==a['id']


def test_unknown_blank_ambiguity(taught):
    w,t,a,b,bank=taught
    assert t.query(bank,picture(8,7)[0],'重装')['project_id'] is None
    assert t.query(bank,picture(1,9,True)[0],'重装')['project_id'] is None
    t.add(bank,{'project_id':b['id'],'consent':True,'session_id':'train','image':picture(1,72)[0]})
    r=t.query(bank,picture(1,9)[0],'重装')
    assert r['reason']=='AMBIGUOUS' and r['project_id'] is None


def test_independent_images_gate_and_revoke(taught):
    w,t,a,b,bank=taught
    assert not t.verify(bank)['validation']['passed']
    with pytest.raises(CalibrationError,match='识别库'):t.prepare(bank,'重装',True)
    fill_validation(t,a,b,bank)
    result=t.verify(bank)
    assert result['validation']['passed'] and len(result['validation']['trace'])==5
    assert t.query(bank,picture(1,67)[0],'重装')['recognition_checked']
    # Correct recognition is insufficient for input: no real calibrated profile exists.
    with pytest.raises(CalibrationError,match='曲线'):t.prepare(bank,'重装',True)
    t.add(bank,{'project_id':a['id'],'consent':True,'session_id':'train','image':picture(1,73)[0]})
    assert t.load(bank)['validation'] is None


def test_wrong_validation_never_passes(taught):
    w,t,a,b,bank=taught;fill_validation(t,a,b,bank)
    t.add(bank,{'project_id':a['id'],'consent':True,'phase':'validation',
                'session_id':'holdout2','image':picture(2,71)[0]})
    r=t.verify(bank)['validation']
    assert not r['passed'] and len([s for s in r['trace'] if not s['passed']])==1


def test_duplicate_and_same_session_rejected(taught):
    _,t,a,b,bank=taught
    req={'project_id':a['id'],'consent':True,'phase':'validation','session_id':'test','image':picture(1,0)[0]}
    with pytest.raises(CalibrationError,match='同一张'):t.add(bank,req)
    with pytest.raises(CalibrationError,match='不同原始'):t.add(bank,{**req,'image':picture(1,18)[0],'session_id':'train'})
    with pytest.raises(CalibrationError,match='同意'):t.add(bank,{**req,'consent':False})
    assert len(t.load(bank)['samples'])==2


def test_environment_and_context_change_rejected(taught):
    w,t,a,b,bank=taught
    bad=preset();bad['settings']['dpi']=1600;c=w.create(bad,'其他输入')
    with pytest.raises(CalibrationError,match='不一致'):
        t.add(bank,{'project_id':c['id'],'consent':True,'session_id':'train','image':picture(3,90)[0]})
    file=w.directory(a['id'])/'project.json';meta=read_json(file)
    meta['context']['pose']='prone';write_json(file,meta)
    with pytest.raises(CalibrationError,match='条件改变'):t.query(bank,picture(1,19)[0],'重装')


def test_size_and_regions_rejected(taught):
    _,t,a,b,bank=taught
    raw=np.zeros((100,100),dtype=np.uint8);bio=BytesIO();Image.fromarray(raw).save(bio,format='PNG')
    with pytest.raises(CalibrationError,match='分辨率'):t.query(bank,base64.b64encode(bio.getvalue()).decode(),'重装')
    for rois in [[],[[0,0,2,8]],[[0,0,600,20]],[[0,0,8,8]]*4]:
        with pytest.raises(CalibrationError):
            t.create({'project_id':a['id'],'rois':rois,'consent':True,'image':picture()[0],'session_id':'a'})


def test_remove_revokes_report(taught):
    _,t,a,b,bank=taught;fill_validation(t,a,b,bank);r=t.verify(bank)
    assert r['validation']['passed']
    r=t.remove(bank,r['samples'][0]['id']);assert r['validation'] is None
    with pytest.raises(CalibrationError):t.remove(bank,'not-present')


def test_router_switch_unknown_and_release(profile):
    gate=RouteGate({'a':profile,'b':profile})
    for n in range(4):r=gate.tick(n*.04,'a',pressed=False,enabled=False)
    assert r['project_id']=='a' and r['dy']==0
    values=[gate.tick(.16+n*.04,'a',pressed=True,enabled=True) for n in range(6)]
    assert any(v['dy'] for v in values)
    assert gate.tick(.40,'b',pressed=True,enabled=True)['dy']==0
    for n in range(4):r=gate.tick(.44+n*.04,'b',pressed=True,enabled=True)
    assert r['dy']==0 and r['reason']=='WAIT_RELEASE'
    gate.tick(.60,'b',pressed=False,enabled=True)
    gate.tick(.64,'b',pressed=True,enabled=True)
    assert gate.tick(.68,'b',pressed=True,enabled=True)['dy']!=0
    assert gate.tick(.72,None,pressed=True,enabled=True)['project_id'] is None
    for n in range(5):r=gate.tick(.76+n*.04,'a',pressed=True,enabled=True)
    assert r['dy']==0


def test_router_lost_enable_clock_gap_and_unvalidated(profile):
    gate=RouteGate({'a':profile})
    for n in range(4):gate.tick(n*.04,'a',pressed=False,enabled=True)
    gate.tick(.16,'a',pressed=True,enabled=True)
    gate.tick(.20,'a',pressed=True,enabled=False)
    assert gate.tick(.24,'a',pressed=True,enabled=True)['dy']==0
    assert gate.tick(.4,'a',pressed=True,enabled=True)['dy']==0
    assert gate.tick(.44,'missing',pressed=False,enabled=True)['project_id'] is None
    with pytest.raises(CalibrationError):gate.tick(.44,'a',pressed=False,enabled=False)
    assert gate.label is None


def test_product_api_teaching(tmp_path):
    from recoil_lab.product import Product
    p=Product(tmp_path);a=p.handle({'action':'create','preset':preset(),'name':'A'})
    b=p.handle({'action':'teach_create','project_id':a['id'],'consent':True,'session_id':'train',
                'image':picture()[0],'rois':[[230,100,64,32]]})
    assert len(p.handle({'action':'teach_list'})['banks'])==1
    q=p.handle({'action':'teach_query','bank_id':b['id'],'image':picture(1,2)[0],'weight':'重装'})
    assert q['project_id']==a['id']
    with pytest.raises(CalibrationError,match='授权'):
        p.handle({'action':'native','mode':'auto_execute','bank_id':b['id']})


def test_no_synthetic_curve_execution(tmp_path):
    w=Workspace(tmp_path);t=Teaching(w);a=w.demo()
    # Sample resolution agrees with the demo; no synthetic curve can authorize output.
    ctx=a['context'];res=ctx['resolution']
    image=np.random.default_rng(1).integers(0,255,(res[1],res[0]),dtype=np.uint8)
    def encode(im):
        o=BytesIO();Image.fromarray(im).save(o,format='PNG');return base64.b64encode(o.getvalue()).decode()
    if image.nbytes>6*1024*1024:pytest.skip('demo resolution exceeds sample limit')
    bank=t.create({'project_id':a['id'],'rois':[[0,0,32,32]],'consent':True,'session_id':'ref','image':encode(image)})
    for n in [1,2]:
        other=image.copy();other[-1,-n]=0
        t.add(bank['id'],{'project_id':a['id'],'phase':'validation','consent':True,
                         'session_id':'holdout','image':encode(other)})
    unknown=np.zeros_like(image)
    t.add(bank['id'],{'project_id':None,'phase':'validation','consent':True,'session_id':'holdout',
                     'weight':'未记录','image':encode(unknown)})
    assert t.verify(bank['id'])['validation']['passed']
    with pytest.raises(CalibrationError,match='曲线'):t.prepare(bank['id'],'未记录',True)


def test_monitor_never_outputs(taught,monkeypatch):
    from recoil_lab.native_session import NativeSession
    from recoil_lab.taught_runtime import run_taught
    w,t,a,b,ident=taught
    bank,matcher,profiles,_=t.prepare(ident,'重装',False)
    n=NativeSession(w); clock=[1.]
    def now():clock[0]+=.005;return clock[0]
    monkeypatch.setattr('recoil_lab.taught_runtime.time.perf_counter',now)
    monkeypatch.setattr('recoil_lab.taught_runtime.time.sleep',lambda _:None)
    class Fake:
        def __init__(self):self.calls=0;self.moves=[];self.selected=[]
        def check_window(self,*args):
            self.calls+=1
            if self.calls>100:n.stop_event.set()
        def interrupted(self):return False
        def capture_recognition(self,*args):
            self.selected.append(n.info.get('selected_project'))
            return picture(1,1)[1]
        def down(self,k):return True
        def triggered(self,*args):return True
        def move(self,*args):self.moves.append(args)
    f=Fake();run_taught(n,f,1,2,bank,matcher,profiles,False)
    assert a['id'] in f.selected and not f.moves
    assert n.info['state']=='STOPPED'


def test_curves_end_do_not_repeat(profile):
    g=RouteGate({'a':profile})
    for n in range(4):g.tick(n*.04,'a',pressed=False,enabled=True)
    moves=[]
    for n in range(300):moves.append(g.tick(.16+n*.04,'a',pressed=True,enabled=True)['dy'])
    assert any(moves) and not any(moves[-50:])
