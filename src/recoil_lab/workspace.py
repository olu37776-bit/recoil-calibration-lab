"""Local, versioned projects. No hidden game state, network, or driver access."""
from __future__ import annotations

from dataclasses import asdict
import base64
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import uuid
import zipfile

import numpy as np

from .calibration import fit_profile, fit_response, refine_profile, validate_profile
from .catalog import build_preset
from .contracts import (CalibrationError, Response, Trial, context_id, load_profile,
                        load_trial, read_json, save_profile, save_trial, write_json)
from .demo import response_trial, recoil_trial
from .playback import dry_run


def data_home() -> Path:
    base = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local' / 'share')))
    return base / 'RecoilCalibrationLab'


def safe_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', value):
        raise CalibrationError('无效的本机记录ID')
    return value


class Workspace:
    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root is not None else data_home()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def directory(self, project_id: str) -> Path:
        p = self.root / safe_id(project_id)
        if not (p / 'project.json').is_file():
            raise CalibrationError('项目不存在，请先创建或选择项目')
        return p

    def list(self) -> list[dict]:
        items = []
        for p in sorted(self.root.glob('*/project.json')):
            try:
                m = read_json(p)
                items.append({k: m[k] for k in ('id', 'name', 'context', 'demo')})
            except (ValueError, KeyError, OSError):
                continue
        return items

    def create(self, preset: dict, name: str, *, demo: bool = False) -> dict:
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise CalibrationError('项目名称需为1至80字')
        frozen = build_preset(preset) if not demo else None
        if demo:
            from .demo import example_context
            context = example_context()
        else:
            context = dict(frozen['context'])
            # This is a distinct backend: V0.4 recording-only profiles do not transfer.
            context['input_backend'] = 'windows-sendinput-v1'
        ident = uuid.uuid4().hex
        p = self.root / ident
        p.mkdir()
        for child in ('trials', 'profiles', 'reports'):
            (p / child).mkdir()
        meta = {'id': ident, 'name': name.strip(), 'context': context, 'preset': frozen,
                'demo': demo, 'active_profile': None, 'schema_version': 1}
        write_json(p / 'project.json', meta)
        return self.snapshot(ident)

    def trials(self, project_id: str, ids: list[str] | None = None, phase: str | None = None) -> list[Trial]:
        p = self.directory(project_id)
        paths = sorted((p / 'trials').glob('*.json')) if ids is None else [p / 'trials' / (safe_id(i)+'.json') for i in ids]
        result = [load_trial(f) for f in paths]
        return [t for t in result if phase is None or t.phase == phase]

    def add(self, project_id: str, trial: Trial) -> str:
        with self.lock:
            p = self.directory(project_id)
            m = read_json(p / 'project.json')
            trial.gate()
            if trial.context_hash != context_id(m['context']):
                raise CalibrationError('数据配装/倍率/后端与当前项目不一致，不自动改写')
            if (trial.source == 'synthetic') != m['demo']:
                raise CalibrationError('演示和真实记录必须分开项目')
            existing = self.trials(project_id)
            if any(t.run_id == trial.run_id or t.content_hash == trial.content_hash for t in existing):
                raise CalibrationError('重复采样或改名数据不能算新一轮')
            ident = uuid.uuid4().hex
            save_trial(p / 'trials' / (ident+'.json'), trial)
            return ident

    def snapshot(self, project_id: str) -> dict:
        p = self.directory(project_id)
        result = read_json(p / 'project.json')
        result['trials'] = []
        for f in sorted((p/'trials').glob('*.json')):
            t = load_trial(f)
            result['trials'].append({'id': f.stem, 'run_id': t.run_id, 'phase': t.phase,
                'source': t.source, 'samples': len(t.t_s), 'duration_s': float(t.t_s[-1]),
                'session_id': t.session_id, 'confidence': float(t.confidence.min())})
        result['response'] = read_json(p/'response.json') if (p/'response.json').exists() else None
        result['profiles'] = []
        for f in sorted((p/'profiles').glob('*.json')):
            v = load_profile(f)
            report = p/'reports'/(v.profile_id+'.json')
            result['profiles'].append({'id': v.profile_id, 'source': v.source,
                'duration_s': float(v.t_s[-1]), 'parent_id': v.parent_id,
                'report': read_json(report) if report.exists() else None})
        result['curve'] = None
        if result['active_profile']:
            active = self.profile(project_id)
            result['curve'] = {'t_s':active.t_s.tolist(),'uy_counts':active.uy_counts.tolist()}
        result['game_verified'] = False
        return result

    def profile(self, project_id: str, profile_id: str | None = None):
        p = self.directory(project_id)
        if not profile_id:
            profile_id = read_json(p/'project.json')['active_profile']
        if not profile_id:
            raise CalibrationError('请先拟合曲线')
        return load_profile(p/'profiles'/(safe_id(profile_id)+'.json'))

    def persist_profile(self, project_id: str, profile) -> dict:
        p = self.directory(project_id)
        save_profile(p/'profiles'/(profile.profile_id+'.json'), profile)
        m = read_json(p/'project.json')
        m['active_profile'] = profile.profile_id
        write_json(p/'project.json', m)
        return self.snapshot(project_id)

    def response(self, project_id: str, latency: float | None = None) -> dict:
        runs = self.trials(project_id, phase='response')
        candidates = []
        for lag in ([latency] if latency is not None else np.linspace(0, .15, 31)):
            try:
                r = fit_response(runs, float(lag))
                candidates.append(r)
            except CalibrationError:
                pass
        if not candidates:
            # Return the detailed core rejection rather than inventing a gain.
            fit_response(runs, float(latency or 0))
            raise CalibrationError('响应无法标定')
        response = min(candidates, key=lambda r: r.fit_rmse_px)
        p = self.directory(project_id)
        write_json(p/'response.json', asdict(response))
        write_json(p/'response-search.json', {'method': 'bounded_lag_grid' if latency is None else 'user_lag',
            'candidate_count': len(candidates), 'latency_is_estimate': latency is None,
            'response_id': response.response_id})
        return self.snapshot(project_id)

    def fit(self, project_id: str, ids: list[str] | None = None, refine: bool = False) -> dict:
        runs = self.trials(project_id, ids, 'train')
        if refine:
            previous = self.profile(project_id)
            runs = [t for t in runs if t.run_id not in previous.training_run_ids]
            candidate = refine_profile(previous, runs)
        else:
            response = Response(**read_json(self.directory(project_id)/'response.json'))
            candidate = fit_profile(runs, response)
        return self.persist_profile(project_id, candidate)

    def validate(self, project_id: str, ids: list[str] | None = None) -> dict:
        profile = self.profile(project_id)
        runs = self.trials(project_id, ids, 'validation')
        if ids is None:
            # Prior candidate replays remain stored, but cannot contaminate the
            # default validation set of a newly selected curve. Untagged imports
            # still undergo the core replay-consistency checks.
            runs = [t for t in runs if t.provenance.get('candidate_id') in (None, profile.profile_id)]
        report = validate_profile(profile, runs)
        write_json(self.directory(project_id)/'reports'/(profile.profile_id+'.json'), report)
        return report

    def execution_profile(self, project_id: str):
        p = self.directory(project_id)
        profile = self.profile(project_id)
        report_file = p/'reports'/(profile.profile_id+'.json')
        if read_json(p/'project.json')['demo'] or profile.source != 'recorded':
            raise CalibrationError('合成演示曲线禁止发送真实鼠标输入')
        if not report_file.exists():
            raise CalibrationError('先完成独立实测回放验证')
        # Re-run verification, not just trust a stored passed:true boolean.
        report = self.validate(project_id)
        if not (report['passed'] and report['evidence_kind'] == 'RECORDED_REPLAY' and report['measured_replay_pass']):
            raise CalibrationError('模型预测/失败结果不能作为实测通过')
        return profile

    def select(self, project_id: str, profile_id: str) -> dict:
        v = self.profile(project_id, profile_id)
        return self.persist_profile(project_id, v)

    def demo(self) -> dict:
        project = self.create({}, '内置全流程演示（非游戏实测）', demo=True)
        ident = project['id']
        for n in (10, 11): self.add(ident, response_trial(n))
        for n in (21, 22, 23): self.add(ident, recoil_trial(n, 'train'))
        self.response(ident, 0)
        self.fit(ident)
        initial = self.profile(ident)
        for n in (31, 32, 33): self.add(ident, recoil_trial(n, 'train', profile=initial))
        self.fit(ident, refine=True)
        candidate = self.profile(ident)
        for n in (41, 42, 43): self.add(ident, recoil_trial(n, 'validation', profile=candidate))
        self.validate(ident)
        return self.snapshot(ident)

    def import_trials(self, project_id: str, encoded: str) -> dict:
        if not isinstance(encoded, str) or len(encoded) > 16*1024*1024:
            raise CalibrationError('数据包过大')
        try:
            raw = base64.b64decode(encoded, validate=True)
            with zipfile.ZipFile(BytesIO(raw)) as z, tempfile.TemporaryDirectory() as td:
                infos = z.infolist()
                if len(infos)>120 or sum(i.file_size for i in infos)>24*1024*1024:
                    raise CalibrationError('数据包展开后超限')
                names = [i.filename for i in infos]
                if len(set(names)) != len(names): raise CalibrationError('重复ZIP条目')
                for i in infos:
                    name = i.filename
                    if (i.is_dir() or '/' in name or '\\' in name or not re.fullmatch(r'[a-zA-Z0-9_.-]+\.(json|csv)', name)):
                        raise CalibrationError('只接收同目录Trial JSON和CSV，不展开任意路径')
                    (Path(td)/name).write_bytes(z.read(i))
                runs = [load_trial(Path(td)/n) for n in names if n.endswith('.json')]
                if not runs: raise CalibrationError('包中没有Trial元数据')
                # Preflight entire batch before persisting any item.
                current = self.trials(project_id)
                context = read_json(self.directory(project_id)/'project.json')['context']
                for t in runs:
                    t.gate()
                    if t.context_hash != context_id(context): raise CalibrationError('数据配置不匹配')
                    if any(x.run_id == t.run_id or x.content_hash == t.content_hash for x in current):
                        raise CalibrationError('数据包包含重复测量')
                    current.append(t)
                meta = read_json(self.directory(project_id)/'project.json')
                if any((t.source=='synthetic') != meta['demo'] for t in runs):
                    raise CalibrationError('不得混合合成/真实数据')
                for t in runs: self.add(project_id, t)
        except (zipfile.BadZipFile, ValueError, KeyError, OSError) as exc:
            raise CalibrationError(f'无法导入数据包：{exc}') from exc
        return self.snapshot(project_id)

    def export(self, project_id: str) -> dict:
        p = self.directory(project_id)
        output = BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
            for f in sorted(p.rglob('*')):
                if f.is_file() and f.suffix in {'.json', '.csv'}:
                    z.write(f, f.relative_to(p).as_posix())
            try:
                v = self.profile(project_id)
                z.writestr('recorded-preview.json', json.dumps({'mode':'simulation_only', 'events':dry_run(v)}))
            except CalibrationError: pass
        return {'filename': 'calibration-project-'+project_id[:8]+'.zip',
                'zip_base64': base64.b64encode(output.getvalue()).decode('ascii')}
