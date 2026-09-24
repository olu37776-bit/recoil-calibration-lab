"""Daily-use panel: save first, select target, configure a single toggle key."""
from __future__ import annotations
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from .simple_toggle import HOTKEYS, TRIGGERS, OptionsStore, ToggleOptions

class DailyControls:
    def __init__(self,app,parent):
        self.app=app
        self.options_store=OptionsStore(app.store.directory)
        options=self.options_store.read()
        self.key=tk.StringVar(value=options.key)
        self.trigger=tk.StringVar(value=next(k for k,v in TRIGGERS.items() if v==options.trigger))
        self.legacy=tk.BooleanVar(value=False)
        self.diagnostic=tk.BooleanVar(value=False)
        self.banner=tk.StringVar(value='未准备 · 选窗口，然后到游戏按一下启停键')
        self.details=tk.StringVar(value='已发送：0 次。发送到Windows ≠ 游戏接受。')
        self.instructions=tk.StringVar()
        self.frame=ttk.Frame(parent)
        self.refresh_text()
        g=app.guide
        g.text(self.frame,'日常使用：调好了就从这里开',title=True)
        g.text(self.frame,'选已保存的配装，准备一次。之后在目标窗口按启停键，不必一直按住。',muted=True)
        row=ttk.Frame(self.frame);row.pack(fill='x',pady=6)
        ttk.Label(row,text='已保存配装：').pack(side='left')
        self.saved_combo=ttk.Combobox(row,textvariable=app.saved,state='readonly')
        self.saved_combo.pack(side='left',fill='x',expand=True)
        self.saved_combo.bind('<<ComboboxSelected>>',app.load_selected)
        ttk.Button(row,text='返回调教 / 改配件',command=lambda:g.show(0)).pack(side='left',padx=6)
        g.text(self.frame,variable=g.summary)
        g.text(self.frame,'注意：当前单次时长到点就停止下拉。长连射需要回调教页调整“时长”（最多6秒）。',muted=True)
        settings=ttk.LabelFrame(self.frame,text='启停设置（会记住，下次不用重设）',padding=10);settings.pack(fill='x',pady=6)
        row=ttk.Frame(settings);row.pack(fill='x')
        ttk.Label(row,text='按一下开/关：').pack(side='left')
        self.key_combo=ttk.Combobox(row,textvariable=self.key,values=list(HOTKEYS),state='readonly',width=14)
        self.key_combo.pack(side='left',padx=5);self.key_combo.bind('<<ComboboxSelected>>',self.changed)
        self.trigger_combo=ttk.Combobox(row,textvariable=self.trigger,values=list(TRIGGERS),state='readonly',width=28)
        self.trigger_combo.pack(side='left',padx=5);self.trigger_combo.bind('<<ComboboxSelected>>',self.changed)
        g.text(settings,variable=self.instructions,muted=True)
        row=ttk.Frame(self.frame);row.pack(fill='x',pady=6)
        self.window_combo=ttk.Combobox(row,textvariable=app.window,state='readonly',width=36)
        self.window_combo.pack(side='left',fill='x',expand=True);self.window_combo.bind('<<ComboboxSelected>>',app.select_window)
        ttk.Button(row,text='刷新游戏窗口',command=app.refresh_windows).pack(side='left',padx=(6,0))
        ttk.Checkbutton(self.frame,text='本次在明确允许的环境使用；我了解游戏规则风险',variable=app.consent,command=app.consent_changed).pack(anchor='w',pady=5)
        card=ttk.LabelFrame(self.frame,text='启用与输入状态',padding=10);card.pack(fill='x',pady=6)
        g.text(card,variable=self.banner,title=True)
        g.text(card,variable=self.details,muted=True)
        row=ttk.Frame(card);row.pack(fill='x')
        ttk.Checkbutton(row,text='只检测按键，不移动鼠标',variable=self.diagnostic,command=self.changed).pack(side='left')
        ttk.Button(row,text='复制诊断状态',command=self.copy_diagnostics).pack(side='right')
        g.text(self.frame,'保存之后：点“准备完成” → 切回游戏 → 按一下启停键 → 正常开镜开火。\nR换弹只暂停本次；切出窗口、切枪、姿态变化后开关关闭，核对配装后再按启停键。',muted=True)
    def current_options(self):
        return ToggleOptions(self.key.get(),TRIGGERS[self.trigger.get()],self.diagnostic.get())
    def refresh_text(self):
        key=self.key.get()
        warning='右键必须一直按住；游戏是按一下开镜时，改选“仅左键”。' if TRIGGERS[self.trigger.get()]=='both' else '仅左键不检查开镜：腰射也会下拉；不用时按启停键关闭。'
        self.instructions.set(f'{key}：按一下开启，再按一下关闭。F8 / Esc关闭。\n{warning} 键位不会被本程序吞掉，请避开游戏已有绑定。')
    def changed(self,event=None):
        self.app.stop();self.refresh_text()
        try:self.options_store.save(self.current_options())
        except (OSError,ValueError) as exc:self.app.error(exc)
        self.app.guide.refresh()
    def refresh(self):
        self.saved_combo['values']=self.app.saved_combo['values']
        self.window_combo['values']=self.app.window_combo['values']
        report=self.app.runner.snapshot()
        if report['listening']:
            self.banner.set(self.app.runner.message)
        else:
            self.banner.set(self.app.status.get())
        keys=report['keys']
        if keys:
            seen=f'前台：{"是" if keys["foreground"] else "否"}　左键：{"按住" if keys["left"] else "松开"}　右键：{"按住" if keys["right"] else "松开"}　启停键：{"按住" if keys["toggle"] else "松开"}'
        else:seen='尚未监听：点击底部“准备完成”，再切回目标窗口按启停键。'
        self.details.set(seen+f'\n本次尝试 {report["attempted_events"]} 次，Windows接收 {report["accepted_events"]} 次 / {report["accepted_counts"]} 单位；只诊断 {report["diagnostic_steps"]} 步。\n输入送入Windows不代表游戏已接受。'+(f'\n错误：{report["system_error"]}' if report['system_error'] else ''))
    def copy_diagnostics(self):
        report=self.app.runner.snapshot()
        report['version']=__import__('recoil_lab.simple_core',fromlist=['VERSION']).VERSION
        report['toggle_key']=self.key.get();report['trigger']=TRIGGERS[self.trigger.get()]
        self.app.stop()
        self.app.root.clipboard_clear();self.app.root.clipboard_append(json.dumps(report,ensure_ascii=False,indent=2))
        self.app.status.set('已复制本次输入状态；不包含窗口标题、路径或截图。监听已停止。')
