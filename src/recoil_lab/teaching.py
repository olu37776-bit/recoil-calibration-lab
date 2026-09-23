"""User-labelled local screenshot library, separate from recoil calibration."""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import uuid
from pathlib import Path

import cv2
import numpy as np

from .contracts import CalibrationError, context_id, digest, read_json, write_json
from .conditions import weight_label
from .screenshots import decode_image
from .workspace import safe_id

ENV_KEYS = ('dpi', 'sensitivity', 'ads_sensitivity', 'resolution', 'fov', 'game_build', 'input_backend')
ENGINE = 'taught-multiregion-v1'


def environment(context: dict) -> str:
    return digest({k: context[k] for k in ENV_KEYS})


def gray(image: np.ndarray) -> np.ndarray:
    return image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)


def regions(rois, resolution):
    if not isinstance(rois, list) or not 1 <= len(rois) <= 3:
        raise CalibrationError('首次框选1至3个能区分配置的界面区域')
    for roi in rois:
        if (not isinstance(roi, list) or len(roi) != 4 or any(type(x) is not int for x in roi)):
            raise CalibrationError('识别区域须为四个整数')
        x, y, w, h = roi
        if min(x,y)<0 or min(w,h)<8 or max(w,h)>512 or x+w>resolution[0] or y+h>resolution[1]:
            raise CalibrationError('区域须在原图内，宽高8至512像素')
    return deepcopy(rois)


def features(image: np.ndarray, rois: list) -> list[str]:
    g = gray(image)
    result=[]
    for x,y,w,h in rois:
        patch=cv2.resize(g[y:y+h,x:x+w], (64,64), interpolation=cv2.INTER_AREA)
        result.append(base64.b64encode(patch.astype(np.uint8).tobytes()).decode('ascii'))
    return result


def vector(encoded: str) -> np.ndarray:
    raw=base64.b64decode(encoded, validate=True)
    if len(raw)!=4096: raise CalibrationError('识别裁剪数据长度错误')
    a=np.frombuffer(raw,dtype=np.uint8).astype(np.float32)
    a-=a.mean()
    norm=float(np.linalg.norm(a))
    return a/norm if norm >= 192 else np.zeros(4096, dtype=np.float32)


def fingerprint(bank):
    return digest({k:bank[k] for k in ('engine','resolution','environment','rois','samples')})


class Matcher:
    def __init__(self, bank: dict, weight: str):
        self.bank=bank
        self.weight=weight_label(weight)
        self.refs=[(s,[vector(x) for x in s['features']]) for s in bank['samples']
                   if s['phase']=='reference' and s['weight']==self.weight]

    def compare_features(self, fs: list[str]) -> dict:
        query=[vector(x) for x in fs]
        scores={}
        for sample,vs in self.refs:
            score=min(float(np.dot(a,b)) for a,b in zip(query,vs))
            ident=sample['project_id']
            scores[ident]=max(scores.get(ident,-1.),score)
        ranked=sorted(scores.items(),key=lambda x:x[1],reverse=True)
        best,score=ranked[0] if ranked else (None,-1.)
        margin=score-ranked[1][1] if len(ranked)>1 else score+1
        reason=('NO_REFERENCE_FOR_WEIGHT' if not ranked else 'LOW_SIMILARITY' if score<.90
                else 'AMBIGUOUS' if margin<.08 else 'MATCH')
        return {'project_id':best if reason=='MATCH' else None,'reason':reason,
                'score':float(np.clip(score,-1,1)),'margin':margin,'weight':self.weight,
                'scores':[{'project_id':k,'score':float(np.clip(v,-1,1))} for k,v in ranked],
                'score_is_probability':False,'game_verified':False}

    def compare(self, image: np.ndarray) -> dict:
        if [image.shape[1],image.shape[0]]!=self.bank['resolution']:
            raise CalibrationError('识别库分辨率与原图不同；不能自动迁移已校准曲线')
        return self.compare_features(features(image,self.bank['rois']))


class Teaching:
    def __init__(self, workspace):
        self.workspace=workspace
        self.root=workspace.root/'recognition'
        self.root.mkdir(exist_ok=True)

    def load(self, ident):
        path=self.root/(safe_id(ident)+'.json')
        if not path.is_file():raise CalibrationError('识别库不存在')
        return read_json(path)

    def save(self, bank):
        write_json(self.root/(safe_id(bank['id'])+'.json'), bank)

    def summary(self, bank):
        records=[]
        for s in bank['samples']:
            records.append({k:v for k,v in s.items() if k!='features'})
        return {k:deepcopy(v) for k,v in bank.items() if k!='samples'} | {
            'samples':records,'revision':fingerprint(bank),
            'weights':sorted(set(s['weight'] for s in records)),
            'privacy':'只保存已同意的区域裁剪，不保存完整原图；不上传',
            'game_verified':False}

    def list(self):
        return [self.summary(read_json(p)) for p in sorted(self.root.glob('*.json'))]

    def _project(self, ident, bank=None):
        meta=read_json(self.workspace.directory(ident)/'project.json')
        if bank and environment(meta['context'])!=bank['environment']:
            raise CalibrationError('识别库与项目的游戏版本、输入设置或分辨率不一致')
        return meta

    def create(self, payload):
        if payload.get('phase','reference')!='reference':
            raise CalibrationError('先用参考图建立识别库')
        meta=self._project(payload.get('project_id'))
        name=payload.get('name','我的识别库')
        if not isinstance(name,str) or not 1<=len(name.strip())<=80:
            raise CalibrationError('识别库名称需为1至80字')
        bank={'id':uuid.uuid4().hex,'engine':ENGINE,'schema_version':1,'name':name.strip(),
              'resolution':meta['context']['resolution'],'environment':environment(meta['context']),
              'rois':regions(payload.get('rois'),meta['context']['resolution']),
              'samples':[],'validation':None}
        self._append(bank,payload)
        self.save(bank)
        return self.summary(bank)

    def _append(self, bank, payload):
        if payload.get('consent') is not True:
            raise CalibrationError('请同意仅在本机保存识别区域裁剪图')
        if len(bank['samples'])>=128:raise CalibrationError('每个识别库最多128张样本')
        phase=payload.get('phase','reference')
        if phase not in {'reference','validation'}:raise CalibrationError('样本阶段无效')
        session=payload.get('session_id')
        if not isinstance(session,str) or not 1<=len(session.strip())<=80:
            raise CalibrationError('填写本次原始采集会话；同一录像的截图必须使用相同会话')
        ident=payload.get('project_id')
        if ident is None:
            if phase!='validation':raise CalibrationError('未知状态只用作验证负例')
            meta=None; weight=weight_label(payload.get('weight','未记录')); cid=None
        else:
            meta=self._project(ident,bank)
            weight=weight_label(meta['context'].get('weight_label','未记录'))
            cid=context_id(meta['context'])
        image,_=decode_image(payload.get('image'))
        if [image.shape[1],image.shape[0]]!=bank['resolution']:
            raise CalibrationError('样本原图尺寸与识别库不一致')
        pixel_hash=hashlib.sha256(gray(image).tobytes()).hexdigest()
        if any(s['pixel_hash']==pixel_hash for s in bank['samples']):
            raise CalibrationError('同一张图已存在，改文件名不能当独立样本')
        if any(s['session_id']==session and s['phase']!=phase for s in bank['samples']):
            raise CalibrationError('参考与验证必须来自不同原始采集会话')
        fs=features(image,bank['rois'])
        if phase=='reference' and any(not np.any(vector(x)) for x in fs):
            raise CalibrationError('参考区域缺少纹理；请框清晰且能区分条件的图标或文字')
        bank['samples'].append({'id':uuid.uuid4().hex,'project_id':ident,
            'name':meta['name'] if meta else '未知/应停止', 'context_id':cid,
            'weight':weight,'phase':phase,'session_id':session,'pixel_hash':pixel_hash,
            'features':fs,'source':'user_labelled','demo':meta['demo'] if meta else False})
        bank['validation']=None

    def add(self, ident, payload):
        bank=self.load(ident);self._append(bank,payload);self.save(bank)
        return self.summary(bank)

    def remove(self, ident, sample_id):
        bank=self.load(ident)
        if sample_id not in {s['id'] for s in bank['samples']}:raise CalibrationError('样本不存在')
        bank['samples']=[s for s in bank['samples'] if s['id']!=sample_id]
        bank['validation']=None;self.save(bank);return self.summary(bank)

    def _check_projects(self, bank):
        for s in bank['samples']:
            if s['project_id']:
                meta=self._project(s['project_id'],bank)
                if context_id(meta['context'])!=s['context_id']:
                    raise CalibrationError('项目条件改变，识别参考不能继续关联旧校准')

    def evaluate(self, bank):
        self._check_projects(bank)
        refs=[s for s in bank['samples'] if s['phase']=='reference']
        vals=[s for s in bank['samples'] if s['phase']=='validation']
        labels={s['project_id'] for s in refs}
        missing=[]
        for ident in sorted(labels):
            if len([s for s in vals if s['project_id']==ident])<2:
                missing.append(ident+': 需要2张独立验证截图')
        for weight in sorted({s['weight'] for s in refs}):
            if not any(s['project_id'] is None and s['weight']==weight for s in vals):
                missing.append(weight+': 需要1张未知/菜单/换弹等负例')
        trace=[]
        for s in vals:
            actual=Matcher(bank,s['weight']).compare_features(s['features'])
            passed=actual['project_id']==s['project_id'] and (s['project_id'] is None or s['project_id'] in labels)
            trace.append({'sample_id':s['id'],'expected':s['project_id'],'actual':actual['project_id'],
                          'passed':passed,'reason':actual['reason'],'score':actual['score']})
        report={'passed':bool(labels) and not missing and bool(trace) and all(x['passed'] for x in trace),
                'revision':fingerprint(bank),'missing':missing,'trace':trace,
                'scope':'仅用户提供的独立截图，非全游戏准确率','game_verified':False}
        return report

    def verify(self, ident):
        bank=self.load(ident);report=self.evaluate(bank)
        bank['validation']=report;self.save(bank);return self.summary(bank)

    def query(self, ident, image, weight):
        bank=self.load(ident);self._check_projects(bank)
        decoded,_=decode_image(image)
        result=Matcher(bank,weight).compare(decoded)
        result['recognition_checked']=bool(bank['validation'] and bank['validation']['passed']
            and bank['validation']['revision']==fingerprint(bank))
        result['mouse_output']=False
        if result['project_id']:
            p=self.workspace.snapshot(result['project_id'])
            result.update(project_name=p['name'],profile_id=p['active_profile'],context=p['context'])
        return result

    def prepare(self, ident, weight, execute=False):
        bank=self.load(ident);self._check_projects(bank)
        if execute and not self.evaluate(bank)['passed']:
            raise CalibrationError('识别库尚未通过独立截图检查，先教识别并验证')
        labels={s['project_id'] for s in bank['samples'] if s['phase']=='reference' and s['weight']==weight}
        if not labels:raise CalibrationError('所选负重下还没有参考配置')
        profiles={};blocked={}
        for label in labels:
            try:
                if execute: profiles[label]=self.workspace.execution_profile(label)
                else: profiles[label]=self.workspace.profile(label)
                if execute and float(profiles[label].t_s[-1])>6:raise CalibrationError('曲线超过6秒')
            except (CalibrationError,OSError) as exc:
                blocked[label]=str(exc);profiles.pop(label,None)
        if execute and not profiles:raise CalibrationError('没有通过实测回放检查的可执行曲线')
        return bank,Matcher(bank,weight),profiles,blocked
