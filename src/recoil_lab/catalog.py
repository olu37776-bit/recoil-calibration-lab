"""Small, manually reviewed public-fact catalog; no scraping or game integration."""
from __future__ import annotations

from copy import deepcopy
from .contracts import CalibrationError, context_id, digest

REVISION = "wardogs-community-2026-09-23.1"
BASE = "https://wardogs.tools/database/"
SLOTS = ("sight", "muzzle", "underbarrel", "magazine")
ROLES = {"initial": "初始", "assault": "突击", "medic": "医疗", "support": "支援", "total": "总等级", "recon": "侦察"}
# Only a curated subset of named facts, not the source site's text, images or full database.
# id | Chinese label | slot | role | level | unlock | purchase | capacity/zoom
PART_ROWS = """
t2|紧凑型 T-2 红点|sight|total|4|5000|340|1.2
tricon15|Tricon 1.5× 紧凑棱镜|sight|assault|12|10000|650|1.5
cq2|CQ-2× 棱镜战斗瞄准镜|sight|assault|17|15000|640|2
combat25|2.5× 战斗瞄准镜|sight|total|26|10000|690|2.5
tactical3|3× 战术棱镜|sight|total|31|15000|740|3
holo|全息瞄准镜|sight|assault|22|20000|620|1.2
kobra|Kobra 反射式瞄准镜|sight|total|21|7500|520|1.2
spitfire3|Spitfire 3× 瞄准镜|sight|assault|26|25000|790|3
rubber|橡胶人体工学前握把|underbarrel|assault|11|7500|540|
rk6|RK6 战术前握把|underbarrel|total|15|7500|380|
afg|AFG 倾斜前握把|underbarrel|assault|14|10000|820|
angled|倾斜战术前握把|underbarrel|initial|0|0|650|
cqr|CQR 战术前导轨握把|underbarrel|assault|38|25000|1100|
m249bipod|M249 脚架|underbarrel|support|18|15000|1050|
pkmbipod|PKM 脚架|underbarrel|support|33|35000|1350|
topcomp|TopComp 制退器|muzzle|assault|5|7500|770|
hex|六角制退器|muzzle|assault|2|5000|350|
ballista|Ballista 制退器|muzzle|medic|13|15000|380|
armulti|AR 多口径抑制器|muzzle|assault|21|20000|1350|
rc556|RC-556 抑制器|muzzle|assault|29|30000|1550|
cqb74|CQB 74 制退器|muzzle|assault|8|12500|680|
pbs4|PBS-4 抑制器|muzzle|assault|27|25000|1300|
dualport|双口制退器|muzzle|medic|1|7500|720|
sgmulti|SG 多口径抑制器|muzzle|medic|48|50000|1220|
tread|Tread 制退器|muzzle|support|17|10000|620|
srvv|SRVV 制退器|muzzle|recon|20|17500|1470|
constrictor|Constrictor 制退器|muzzle|recon|23|20000|760|
galil35|Galil 35 发弹匣|magazine|assault|10|0|60|35
galil50|Galil 50 发弹匣|magazine|assault|15|25000|110|50
ak30|AK74 30 发弹匣|magazine|assault|3|0|35|30
ak60|AK74 60 发弹匣|magazine|assault|25|30000|150|60
stanag20|STANAG 20 发弹匣|magazine|initial|0|0|10|20
stanag30|STANAG 30 发弹匣|magazine|assault|6|10000|55|30
stanag60|STANAG 60 发弹匣|magazine|assault|30|25000|180|60
pp30|PP-19 30 发弹匣|magazine|medic|4|0|100|30
pp50|PP-19 50 发弹鼓|magazine|medic|29|50000|200|50
amp20|AMP-9 20 发弹匣|magazine|initial|0|0|70|20
amp30|AMP-9 30 发弹匣|magazine|medic|10|10000|100|30
amp50|AMP-9 50 发弹鼓|magazine|medic|20|15000|180|50
mp520|MP5 20 发弹匣|magazine|medic|15|0|70|20
mp530|MP5 30 发弹匣|magazine|medic|25|25000|100|30
mp550|MP5 50 发弹鼓|magazine|medic|45|75000|230|50
vector13|Super-45 13 发弹匣|magazine|medic|35|0|30|13
vector30|Super-45 30 发弹匣|magazine|medic|38|25000|80|30
fal20|FAL 20 发弹匣|magazine|assault|35|0|150|20
fal30|FAL 30 发弹匣|magazine|assault|50|50000|250|30
m249100|M249 100 发弹袋|magazine|support|15|0|200|100
m249200|M249 200 发弹箱|magazine|support|23|35000|250|200
pkm100|PKM 100 发弹箱|magazine|support|30|0|100|100
"""
# The four selected displayed modifiers are not a complete stat model.
MODIFIERS = {
    "t2": {"aim_time": -10}, "tricon15": {"aim_time": -3}, "cq2": {"aim_time": 5},
    "combat25": {"aim_time": 5}, "tactical3": {"aim_time": 10}, "spitfire3": {"aim_time": 10},
    "holo": {"aim_time": -10}, "kobra": {"aim_time": -15},
    "rubber": dict(vertical=-18, horizontal=-7, spread=-16, aim_time=2),
    "rk6": dict(vertical=-15, horizontal=-8, spread=-15, aim_time=10),
    "afg": dict(vertical=-6, horizontal=-25, spread=-22, aim_time=-15),
    "angled": dict(vertical=2, horizontal=-16, spread=-16, aim_time=-12),
    "cqr": dict(vertical=-30, horizontal=-3, spread=-9, aim_time=15),
    "topcomp": dict(vertical=-18, horizontal=-2, spread=-4, aim_time=5),
    "hex": dict(vertical=-1, horizontal=-22, spread=-4, aim_time=5),
    "ballista": dict(vertical=2, horizontal=-20, spread=-5, aim_time=4),
    "armulti": dict(vertical=-12, horizontal=-7, spread=-10, aim_time=10),
    "rc556": dict(vertical=-12, horizontal=-8, spread=-12, aim_time=12),
    "cqb74": dict(vertical=-20, horizontal=-3, spread=-4, aim_time=4),
    "pbs4": dict(vertical=-14, horizontal=-8, spread=-12, aim_time=12),
    "dualport": dict(vertical=-18, horizontal=-4, spread=-5, aim_time=5),
    "sgmulti": dict(vertical=-10, horizontal=-6, spread=-9, aim_time=8),
    "tread": dict(vertical=-14, horizontal=-2, spread=-3, aim_time=3),
    "srvv": dict(vertical=-12, horizontal=-18, spread=-5, aim_time=5),
    "constrictor": dict(vertical=1, horizontal=-17, spread=-3, aim_time=3),
    "galil50": dict(vertical=19, horizontal=21, aim_time=19),
    "ak60": dict(vertical=19, horizontal=21, aim_time=19),
    "stanag20": dict(vertical=-16, horizontal=-15, aim_time=-15),
    "stanag60": dict(vertical=19, horizontal=21, aim_time=19),
    "pp50": dict(vertical=20, horizontal=18, aim_time=20),
    "amp30": dict(vertical=12, horizontal=14, aim_time=11),
    "amp50": dict(vertical=20, horizontal=18, aim_time=20),
    "mp520": dict(vertical=-13, horizontal=-12, aim_time=-13),
    "mp550": dict(vertical=20, horizontal=18, aim_time=20),
    "vector13": dict(vertical=-17, horizontal=-17, aim_time=-17),
    "fal30": dict(vertical=22, horizontal=24, aim_time=26),
    "m249200": dict(vertical=17, horizontal=17, aim_time=20), "pkm100": dict(aim_time=10),
}
# id | name | category | role | level | unlock | price | caliber | rpm | source slug
WEAPON_ROWS = """
galil|Galil|AR|assault|10|35000|2200|556|650|galil
ak74|AK74|AR|assault|3|10000|1600|545|650|ak74m
m4|M4|AR|assault|20|100000|2800|556|800|m4
fal|FAL|AR|assault|35|200000|6500|308|650|fal
t21|T-21|AR|initial|0|0|600|556|750|t-21
a91|A-91|AR|initial|0|0||556|700|a91
m17s|Bushmaster M17S|AR|initial|0|0||556|700|bushmaster-m17s
kh2002|KH-2002|AR|initial|0|0||556|700|kh2002
pp19|PP-19 勇士|SMG|medic|4|25000|1200|9mm|800|pp-19-vityaz
amp9|AMP-9|SMG|initial|0|0|900|9mm|900|mp9
mp5|MP5|SMG|medic|15|75000|1500|9mm|800|mp5
super45|Super-45|SMG|medic|35|150000|2600|45|1200|vector
m249|M249 轻机枪|LMG|support|15|100000|3200|556|850|m249
pkm|PKM 通用机枪|LMG|support|30|150000|4500|762||pkm
"""
ALL_SIGHTS = "t2 tricon15 cq2 combat25 tactical3 holo kobra spitfire3".split()
SMG_SIGHTS = "t2 tricon15 cq2 combat25 holo kobra".split()
GRIPS = "rubber rk6 afg angled".split()
STANAG = "stanag20 stanag30 stanag60".split()
FIT = {
    "galil": [ALL_SIGHTS, "topcomp hex ballista armulti rc556".split(), GRIPS+["cqr"], ["galil35", "galil50"]],
    "ak74": [ALL_SIGHTS, ["cqb74", "pbs4"], GRIPS+["cqr"], ["ak30", "ak60"]],
    "m4": [ALL_SIGHTS, "topcomp hex armulti rc556".split(), GRIPS+["cqr"], STANAG],
    "fal": [ALL_SIGHTS, ["armulti", "constrictor"], GRIPS+["cqr"], ["fal20", "fal30"]],
    "t21": [ALL_SIGHTS, "topcomp hex ballista armulti rc556".split(), GRIPS, STANAG],
    "a91": [[], [], [], STANAG], "m17s": [[], [], [], STANAG],
    "kh2002": [ALL_SIGHTS, [], [], STANAG],
    "pp19": [SMG_SIGHTS, ["dualport", "sgmulti"], GRIPS, ["pp30", "pp50"]],
    "amp9": [SMG_SIGHTS, ["dualport", "sgmulti"], GRIPS, ["amp20", "amp30", "amp50"]],
    "mp5": [SMG_SIGHTS, ["dualport", "sgmulti"], GRIPS, ["mp520", "mp530", "mp550"]],
    "super45": [SMG_SIGHTS, ["sgmulti"], GRIPS, ["vector13", "vector30"]],
    "m249": [ALL_SIGHTS, ["topcomp", "armulti", "rc556", "tread"], GRIPS+["cqr", "m249bipod"], ["m249100", "m249200"]+STANAG],
    "pkm": [ALL_SIGHTS, ["srvv"], ["pkmbipod"], ["pkm100"]],
}
CALIBERS = {"556": "5.56×45mm", "545": "5.45×39mm", "9mm": "9×19mm", "45": ".45 ACP", "308": ".308 Win", "762": "7.62×54mm"}
AMMO_PRICES = {"556": [15,40,25], "545": [15,40,25], "9mm": [10,20,15], "45": [10,20,15], "308": [40,180,70], "762": [30,90,55]}
AMMO_UNLOCKS = {("556","AP"):(83,75000), ("556","HP"):(10,5000), ("9mm","AP"):(75,75000), ("9mm","HP"):(6,5000), ("762","AP"):(82,75000), ("762","HP"):(28,5000), ("545","HP"):(16,5000), ("45","HP"):(48,5000), ("308","HP"):(65,5000)}


def public_catalog() -> dict:
    parts = {}
    for line in PART_ROWS.strip().splitlines():
        ident,name,slot,role,level,unlock,price,value = line.split("|")
        parts[ident] = {"id":ident, "name":name, "slot":slot, "unlock": {"role":role,"level":int(level),"fee":int(unlock)},
            "price":int(price), "modifiers":deepcopy(MODIFIERS.get(ident, {})),
            "capacity":int(value) if slot=="magazine" else None,
            "zoom":float(value) if slot=="sight" else None,
            "sources":[BASE+"attachments"], "status":"community-listed"}
    weapons = {}
    for line in WEAPON_ROWS.strip().splitlines():
        ident,name,category,role,level,unlock,price,caliber,rpm,slug = line.split("|")
        weapons[ident] = {"id":ident,"name":name,"category":category,"caliber":caliber,"rpm":int(rpm) if rpm else None,
            "unlock":{"role":role,"level":int(level),"fee":int(unlock)}, "price":int(price) if price else None,
            "compatibility":dict(zip(SLOTS, deepcopy(FIT[ident]))), "sources":[BASE+"weapons/"+slug],
            "fitment_status": "partial-pending" if ident in {"a91","m17s","kh2002"} else "community-listed"}
    ammo = {}
    for caliber,prices in AMMO_PRICES.items():
        for kind,price in zip(("FMJ","AP","HP"),prices):
            level,fee=(0,0) if kind=="FMJ" else AMMO_UNLOCKS.get((caliber,kind),(None,None))
            ident=caliber+"-"+kind
            sources=list(dict.fromkeys(w["sources"][0] for w in weapons.values() if w["caliber"]==caliber))
            ammo[ident]={"id":ident,"name":CALIBERS[caliber]+" "+{"FMJ":"标准弹","AP":"穿甲弹","HP":"空尖弹"}[kind],
                "kind":kind,"caliber":caliber,"price":price,"pack_size":None,
                "unlock":{"role":"initial" if kind=="FMJ" else "total","level":level,"fee":fee},
                "sources":sources+[BASE.replace("database/", "progression")],"status":"community-listed"}
    return {"schema_version":1,"revision":REVISION,"reviewed_on":"2026-09-23","site_version_label":"v1.1.0 / 2026-09-22 (not verified game build)",
        "scope":"14 automatic-capable rifles/SMGs/LMGs and a curated compatible attachment subset, not the full arsenal",
        "notice":"社区资料，不代表官方保证；中文名称可能与游戏译名不同。待核验不等于不能安装。面板属性不等于实测补偿量。",
        "roles":ROLES,"slots":list(SLOTS),"calibers":CALIBERS,"weapons":weapons,"parts":parts,"ammo":ammo}


def build_preset(payload: dict) -> dict:
    """Validate all choices on the server and freeze a reproducible configuration."""
    if not isinstance(payload,dict) or not isinstance(payload.get("settings"),dict):
        raise CalibrationError("需要配装对象和 settings")
    cat=public_catalog()
    wid=payload.get("weapon")
    if not isinstance(wid,str) or wid not in cat["weapons"]:
        raise CalibrationError("未知枪械")
    weapon=cat["weapons"][wid]
    slots=payload.get("slots",{})
    if not isinstance(slots,dict) or set(slots)-set(SLOTS):
        raise CalibrationError("未知配件槽位")
    selected={}
    for slot in SLOTS:
        value=slots.get(slot) or None
        if value is not None and (not isinstance(value,str) or value not in weapon["compatibility"][slot]):
            raise CalibrationError(f"{slot} 配件未被当前目录确认兼容")
        selected[slot]=value
    if selected["magazine"] is None:
        raise CalibrationError("必须选择弹匣")
    aid=payload.get("ammo")
    if not isinstance(aid,str) or aid not in cat["ammo"] or cat["ammo"][aid]["caliber"]!=weapon["caliber"]:
        raise CalibrationError("弹药口径与枪械不匹配")
    settings=payload["settings"]
    keys=("dpi","sensitivity","ads_sensitivity","zoom","resolution","fov","pose","game_build")
    if not set(keys)<=settings.keys():
        raise CalibrationError("请完整填写实际画面与灵敏度设置")
    if type(settings.get("bipod_deployed",False)) is not bool:
        raise CalibrationError("脚架状态必须是布尔值")
    deployed=settings.get("bipod_deployed",False)
    if deployed and selected["underbarrel"] not in {"m249bipod","pkmbipod"}:
        raise CalibrationError("未安装脚架，不能声明已展开")
    context={k:deepcopy(settings[k]) for k in keys}
    context.update(weapon=wid,attachments=[f"{s}:{selected[s]}" for s in SLOTS if selected[s]],
                   input_backend="recording-only",ammo=aid,bipod_deployed=deployed,catalog_revision=REVISION)
    if settings.get("pose") not in {"standing","crouching","prone"}:
        raise CalibrationError("姿态无效")
    if not isinstance(settings["game_build"], str) or not settings["game_build"].strip() or settings["game_build"].strip().lower() in {"unknown","待填写"}:
        raise CalibrationError("请填写实际游戏版本/构建号；资料站版本不能代替游戏版本")
    fingerprint=context_id(context)
    items=[weapon]+[cat["parts"][v] for v in selected.values() if v]
    unknown=[i["name"] for i in items if i["price"] is None]
    return {"schema_version":1,"catalog_revision":REVISION,"weapon":wid,"slots":selected,"ammo":aid,
        "settings":{**{k:context[k] for k in keys},"bipod_deployed":deployed},"context":context,"context_id":fingerprint,
        "known_purchase_total":sum(i["price"] for i in items if i["price"] is not None),"unknown_prices":unknown,
        "cost_scope":"gun + one magazine + selected attachments; ammunition/other kit excluded",
        "calibration_status":"UNMEASURED","sources":list(dict.fromkeys(s for i in items for s in i["sources"]))}
