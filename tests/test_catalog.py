import pytest
from recoil_lab.catalog import public_catalog, build_preset
from recoil_lab.contracts import CalibrationError


def config():
    return dict(weapon="galil",slots=dict(sight="tricon15",muzzle="topcomp",underbarrel="rubber",magazine="galil35"),ammo="556-AP",
        settings=dict(dpi=800,sensitivity=1.,ads_sensitivity=1.,zoom=1.5,resolution=[320,240],fov=90,pose="standing",game_build="synthetic-test",bipod_deployed=False))


def test_catalog_referential_integrity():
    c=public_catalog()
    assert len(c['weapons'])==14 and len(c['parts'])==49
    for w in c['weapons'].values():
        assert w['sources']
        for slot,ids in w['compatibility'].items():
            assert len(ids)==len(set(ids))
            for ident in ids:
                assert c['parts'][ident]['slot']==slot
    assert not c['weapons']['a91']['compatibility']['underbarrel']
    assert c['weapons']['pkm']['compatibility']['underbarrel']==['pkmbipod']
    c['parts']['rubber']['modifiers']['vertical']=999
    assert public_catalog()['parts']['rubber']['modifiers']['vertical']==-18


def test_preset_cost_and_identity():
    a=config();p=build_preset(a)
    assert p['known_purchase_total']==4220
    assert p['calibration_status']=='UNMEASURED'
    assert p['context']['input_backend']=='recording-only'
    a['slots']=dict(reversed(list(a['slots'].items())))
    assert build_preset(a)['context_id']==p['context_id']
    a['slots']['muzzle']='hex'
    assert build_preset(a)['context_id']!=p['context_id']


@pytest.mark.parametrize('change',[
 lambda a:a.update(weapon='hacked'),lambda a:a['slots'].update(magazine='ak30'),
 lambda a:a['slots'].update(barrel='unknown'),lambda a:a.update(ammo='9mm-AP'),
 lambda a:a['slots'].update(magazine=None),lambda a:a['settings'].update(bipod_deployed=True),
 lambda a:a['settings'].update(game_build=''),lambda a:a['settings'].update(zoom=float('nan')),
 lambda a:a['settings'].update(pose='flying'),lambda a:a['settings'].update(resolution=[0,240]),
 lambda a:a['settings'].update(bipod_deployed=1),lambda a:a.update(settings={})])
def test_invalid_preset(change):
    a=config();change(a)
    with pytest.raises(CalibrationError):build_preset(a)


@pytest.mark.parametrize('key,value',[('zoom',2),('dpi',1600),('ads_sensitivity',2),('pose','crouching'),('game_build','another-build')])
def test_config_change_invalidates(key,value):
    a=config();first=build_preset(a);a['settings'][key]=value
    assert build_preset(a)['context_id']!=first['context_id']


def test_unknown_not_zero():
    a=config();a.update(weapon='a91',slots={'magazine':'stanag30'})
    p=build_preset(a);assert p['unknown_prices']==['A-91']
    assert p['known_purchase_total']==55
    assert public_catalog()['ammo']['545-AP']['unlock']['level'] is None
