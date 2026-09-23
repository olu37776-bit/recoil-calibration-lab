"""One application service for the complete local measurement workflow."""
from __future__ import annotations

import platform
import threading
from pathlib import Path

from .contracts import CalibrationError
from .desktop import WindowsDesktop
from .taught_runtime import PersonalNativeSession
from .workspace import Workspace


class Product:
    def __init__(self, directory: Path | None = None):
        self.store = Workspace(directory)
        self.native = PersonalNativeSession(self.store)
        from .teaching import Teaching
        self.teaching = Teaching(self.store)
        self.native.teaching = self.teaching
        self.lock = threading.RLock()

    def handle(self, request: dict) -> dict:
        if not isinstance(request,dict): raise CalibrationError('请求必须是对象')
        action=request.get('action'); ident=request.get('project_id')
        # Stop and status must not queue behind computation/storage operations.
        if action=='stop': return self.native.stop()
        if action=='status': return self.native.status()
        if action=='windows': return {'windows':WindowsDesktop().windows()}
        with self.lock:
            if action=='native': return self.native.start(request)
            if self.native.worker is not None and self.native.worker.is_alive():
                raise CalibrationError('桌面任务运行中；请先停止，再切换项目或修改校准')
            if action=='preflight':
                from .capture_support import preflight
                return preflight(self.native,request)
            if action=='diagnostic':
                from .capture_support import diagnostic
                return {'version':'0.8.0-rc1',**diagnostic(self.native,ident)}
            if action=='environment':
                return {'version':'0.8.0-rc1','platform':platform.system(),
                    'native_available':platform.system()=='Windows','data_directory':str(self.store.root),
                    'mode':'supervised_calibration','game_verified':False,
                    'notice':'默认关闭输出。先校准、教识别并验证；负重手动选择。F7使能，F8/Esc急停。不是预训练的全游戏识别器。'}
            if action=='preferences':
                from .usability import preferences
                return preferences(self.store.root, request.get('patch'))
            if action=='teach_list': return {'banks':self.teaching.list()}
            if action=='teach_create': return self.teaching.create(request)
            if action=='teach_add': return self.teaching.add(request.get('bank_id'),request)
            if action=='teach_remove': return self.teaching.remove(request.get('bank_id'),request.get('sample_id'))
            if action=='teach_verify': return self.teaching.verify(request.get('bank_id'))
            if action=='teach_query': return self.teaching.query(request.get('bank_id'),request.get('image'),request.get('weight','未记录'))
            if action=='projects': return {'projects':self.store.list()}
            if action=='create': return self.store.create(request.get('preset'),request.get('name',''))
            if action=='demo': return self.store.demo()
            if action=='open': return self.store.snapshot(ident)
            if action=='import': return self.store.import_trials(ident,request.get('zip_base64'))
            if action=='response': return self.store.response(ident,request.get('latency_s'))
            if action=='fit': return self.store.fit(ident,request.get('trial_ids'))
            if action=='refine': return self.store.fit(ident,request.get('trial_ids'),True)
            if action=='validate': return self.store.validate(ident,request.get('trial_ids'))
            if action=='select': return self.store.select(ident,request.get('profile_id'))
            if action=='export': return self.store.export(ident)
        raise CalibrationError('未知工作台操作')
