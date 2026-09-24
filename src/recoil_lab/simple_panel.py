"""Home = choose and toggle. Config = edit and try with the SAME toggle."""
from __future__ import annotations

from dataclasses import replace
import json
import math
import platform
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import time

from .simple_app import load_catalog, NONE, Feedback
from .simple_core import Setting, Store, LABELS, VERSION
from .simple_desktop import Desktop
from .simple_toggle import ToggleRunner, ToggleOptions, OptionsStore, HOTKEYS, TRIGGERS
from .simple_toggle_desktop import ToggleDesktop
from .simple_panel_model import AutoReady, PanelDraft, TargetRule
from .simple_tuning import Preferences, read_setting, write_setting


class PanelApplication:
    def __init__(self, root, directory=None, *, runner=None, windows_provider=None):
        self.root = root
        root.title('RecoilLab · '+VERSION)
        root.geometry(f'{min(900,root.winfo_screenwidth()-50)}x{min(760,root.winfo_screenheight()-90)}')
        root.minsize(760, 560)
        self.store = Store(directory)
        self.catalog = load_catalog()
        self.preferences = Preferences(self.store.directory)
        self.rules = TargetRule(self.store.directory)
        self.option_store = OptionsStore(self.store.directory)
        # Physical right-button gating confused users with toggle-ADS. A new
        # installation defaults explicitly to left-only; old preferences stay.
        options = self.option_store.read() if self.option_store.path.exists() else ToggleOptions(trigger='left')
        self.runner = runner or ToggleRunner(Desktop, ToggleDesktop)
        self.ready = AutoReady(self.runner)
        self.windows_provider = windows_provider or self._windows
        self.window_values = []
        self.target = None
        self.target_text = '尚未发现游戏窗口'
        self.next_scan = 0.0
        self.mode = 'home'
        self.selected_key = self.preferences.read()
        self.draft = PanelDraft(self.store, self.catalog)
        self.silent = False
        self.form_error = ''
        self.notice = tk.StringVar(value='打开软件后选配置，去游戏按一下启停键即可。')
        self.state = tk.StringVar(value='已关闭')
        self.action = tk.StringVar()
        self.summary = tk.StringVar()
        self.draft_state = tk.StringVar()
        self.report_text = tk.StringVar()
        self.key = tk.StringVar(value=options.key)
        self.trigger = tk.StringVar(value=next(k for k,v in TRIGGERS.items() if v == options.trigger))
        self.step = tk.StringVar(value='5')
        self.diagnostic = tk.BooleanVar(value=False)
        self.preset = tk.StringVar()
        self.window = tk.StringVar()
        self.numeric = tk.StringVar(value='20')
        self.duration = tk.StringVar(value='2')
        self.fields = {k:tk.StringVar() for k in LABELS}
        self.combos = {}
        self.items = []
        self._build()
        for v in self.fields.values():
            v.trace_add('write', lambda *_: self.form_changed())
        self.numeric.trace_add('write', lambda *_: self.form_changed())
        self.duration.trace_add('write', lambda *_: self.form_changed())
        self.key.trace_add('write', lambda *_: self.options_changed())
        self.trigger.trace_add('write', lambda *_: self.options_changed())
        self.step.trace_add('write', lambda *_: self.options_changed())
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.bind('<Escape>', lambda _:self.disable())
        self.refresh_presets()
        self._show('home')
        self.timer = root.after(60, self.pulse)

    @staticmethod
    def _windows():
        if platform.system() != 'Windows':
            return []
        return ToggleDesktop().windows()

    def _build(self):
        root = self.root
        font = ('Microsoft YaHei UI' if platform.system() == 'Windows' else 'Noto Sans CJK SC', 10)
        style = ttk.Style(root); style.theme_use('clam')
        style.configure('.', font=font)
        style.configure('TFrame', background='#f4f6fa')
        style.configure('TLabel', background='#f4f6fa')
        style.configure('TLabelframe', background='#f4f6fa')
        style.configure('TLabelframe.Label', background='#f4f6fa', font=(font[0],10,'bold'))
        style.configure('Big.TLabel', font=(font[0],23,'bold'), foreground='#193552')
        style.configure('Primary.TButton', padding=(16,10), font=(font[0],11,'bold'))
        root.configure(background='#f4f6fa')
        top=ttk.Frame(root,padding=(22,16,22,8));top.pack(fill='x')
        ttk.Label(top,text='RecoilLab',font=(font[0],19,'bold')).pack(side='left')
        ttk.Button(top,text='使用',command=self.show_home).pack(side='right',padx=4)
        ttk.Button(top,text='配置管理',command=self.show_config).pack(side='right',padx=4)
        self.footer=ttk.Frame(root,padding=(22,10));self.footer.pack(side='bottom',fill='x')
        self.stop_button=ttk.Button(self.footer,text='关闭  F8',command=self.disable)
        self.stop_button.pack(side='right')
        ttk.Label(self.footer,textvariable=self.notice,wraplength=590).pack(side='left',fill='x',expand=True)
        self.host=ttk.Frame(root,padding=(22,0,22,8));self.host.pack(fill='both',expand=True)
        banner=ttk.Frame(self.host,padding=(14,10));banner.pack(fill='x')
        ttk.Label(banner,textvariable=self.state,style='Big.TLabel').pack(anchor='w')
        ttk.Label(banner,textvariable=self.action,wraplength=790).pack(anchor='w',pady=(5,0))
        self.summary_label=ttk.Label(banner,textvariable=self.summary,wraplength=790,foreground='#52637b')
        self.summary_label.pack(anchor='w',pady=(6,0))
        self.pages_host=ttk.Frame(self.host);self.pages_host.pack(fill='both',expand=True,pady=(10,0))
        self.pages={name:ttk.Frame(self.pages_host) for name in ('home','config')}
        home=self.pages['home']
        choose=ttk.LabelFrame(home,text='使用哪一套？',padding=16);choose.pack(fill='x',pady=5)
        self.preset_combo=ttk.Combobox(choose,textvariable=self.preset,state='readonly',height=12)
        self.preset_combo.pack(fill='x',pady=(0,12))
        self.preset_combo.bind('<<ComboboxSelected>>',self.select_preset)
        ttk.Button(choose,text='编辑这套 / 调力度',style='Primary.TButton',command=self.show_config).pack(side='left')
        ttk.Button(choose,text='新建配置',command=self.new_config).pack(side='left',padx=10)
        info=ttk.LabelFrame(home,text='平时就这样用',padding=18);info.pack(fill='x',pady=12)
        ttk.Label(info,text='选好配置 → 去游戏按启停键 → 正常开火\n再按一次启停键关闭。没有“准备”按钮，不用等倒计时。',
                  font=(font[0],12),wraplength=740).pack(anchor='w')
        ttk.Label(info,text='保存的是你手动调好的参数；选枪和配件不会自动计算力度。',wraplength=740,foreground='#61728b').pack(anchor='w',pady=(10,0))
        config=self.pages['config']
        buttons=ttk.Frame(config,padding=(0,8));buttons.pack(side='bottom',fill='x')
        self.save_button=ttk.Button(buttons,text='保存配置',style='Primary.TButton',command=self.save_config)
        self.save_button.pack(side='left')
        ttk.Button(buttons,text='复制为另一套',command=self.copy_config).pack(side='left',padx=7)
        ttk.Button(buttons,text='返回使用',command=self.show_home).pack(side='right')
        ttk.Label(buttons,textvariable=self.draft_state,foreground='#52637b').pack(side='left',padx=8)
        area=ttk.Frame(config);area.pack(fill='both',expand=True)
        self.canvas=tk.Canvas(area,bg='#f4f6fa',highlightthickness=0)
        bar=ttk.Scrollbar(area,orient='vertical',command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set);bar.pack(side='right',fill='y');self.canvas.pack(side='left',fill='both',expand=True)
        inside=ttk.Frame(self.canvas,padding=(0,0,12,0));wid=self.canvas.create_window((0,0),window=inside,anchor='nw')
        inside.bind('<Configure>',lambda _:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(wid,width=e.width))
        root.bind('<MouseWheel>', self.scroll)
        tuner=ttk.LabelFrame(inside,text='力度与试调（同一个启停键）',padding=12);tuner.pack(fill='x',pady=(0,9))
        row=ttk.Frame(tuner);row.pack(fill='x')
        ttk.Label(row,text='下拉力度').pack(side='left')
        self.rate_entry=ttk.Entry(row,textvariable=self.numeric,width=9);self.rate_entry.pack(side='left',padx=8)
        self.less=ttk.Button(row,text='− 减弱',command=lambda:self.adjust(-int(self.step.get())));self.less.pack(side='left',padx=3)
        self.more=ttk.Button(row,text='＋ 增强',command=lambda:self.adjust(int(self.step.get())));self.more.pack(side='left',padx=3)
        ttk.Label(row,text='每次调').pack(side='left',padx=(18,4))
        ttk.Combobox(row,textvariable=self.step,values=['1','5','10'],state='readonly',width=4).pack(side='left')
        self.slider_widget=ttk.Scale(tuner,from_=0,to=400,command=self.slider)
        self.slider_widget.pack(fill='x',pady=8)
        row=ttk.Frame(tuner);row.pack(fill='x')
        ttk.Label(row,text='最长连续下拉（秒）').pack(side='left')
        ttk.Combobox(row,textvariable=self.duration,values=['0.5','1','2','3','4','5','6'],width=6).pack(side='left',padx=8)
        ttk.Button(row,text='撤销调节',command=self.undo).pack(side='right')
        ttk.Label(tuner,text='上飘就增强，压过头就减弱。松开鼠标后 F5− / F6＋，调好保存。',
                  wraplength=730,foreground='#52637b').pack(anchor='w',pady=(8,0))
        form=ttk.LabelFrame(inside,text='配置条件',padding=12);form.pack(fill='x',before=tuner,pady=(0,8))
        ttk.Label(form,text='配置名称').grid(row=0,column=0,sticky='w',pady=5)
        ttk.Entry(form,textvariable=self.fields['notes']).grid(row=0,column=1,columnspan=3,sticky='ew',pady=5)
        labels={'weapon':'枪械','sight':'瞄准镜','pose':'姿态','weight':'负重'}
        for index,key in enumerate(labels):
            r=1+index//2;c=(index%2)*2
            ttk.Label(form,text=labels[key],width=12).grid(row=r,column=c,sticky='w',pady=5)
            values=([w['name'] for w in self.catalog['weapons'].values()] if key=='weapon' else
                    ['站姿','蹲姿','卧姿'] if key=='pose' else
                    ['未记录','轻装','中装','重装'] if key=='weight' else [NONE])
            box=ttk.Combobox(form,textvariable=self.fields[key],values=values,
                             state='normal' if key=='weight' else 'readonly',width=22)
            box.grid(row=r,column=c+1,sticky='ew',padx=(0,10),pady=5);self.combos[key]=box
        form.columnconfigure(1,weight=1);form.columnconfigure(3,weight=1)
        parts=ttk.Frame(inside)
        parts_visible=[False]
        def expand_parts():
            parts_visible[0]=not parts_visible[0]
            if parts_visible[0]:parts.pack(fill='x',after=parts_button,pady=5)
            else:parts.pack_forget()
        parts_button=ttk.Button(inside,text='其他配件：枪口 / 握把 / 弹匣 / 弹药',command=expand_parts)
        parts_button.pack(anchor='w',pady=5)
        for index,(key,label) in enumerate({'muzzle':'枪口','underbarrel':'握把 / 脚架','magazine':'弹匣','ammo':'弹药'}.items()):
            r=index//2;c=index%2*2
            ttk.Label(parts,text=label,width=12).grid(row=r,column=c,sticky='w',pady=4)
            box=ttk.Combobox(parts,textvariable=self.fields[key],values=[NONE],state='readonly',width=22)
            box.grid(row=r,column=c+1,sticky='ew',padx=(0,10),pady=4);self.combos[key]=box
        parts.columnconfigure(1,weight=1);parts.columnconfigure(3,weight=1)
        extra=ttk.Frame(inside,padding=(0,10));extra.pack(fill='x')
        ttk.Button(extra,text='导出这套',command=self.export_config).pack(side='left')
        ttk.Button(extra,text='导入配置',command=self.import_config).pack(side='left',padx=6)
        ttk.Button(extra,text='弹着截图（可选）',command=self.feedback).pack(side='left')
        ttk.Button(self.host,text='键位与游戏窗口 / 诊断',command=self.open_settings).pack(anchor='w',pady=(10,0))
        ttk.Label(self.host,text='按启停键开启，即允许向选中的游戏窗口发送鼠标移动。仅在明确允许的环境使用。',
                  wraplength=790,foreground='#64748b').pack(anchor='w',pady=(7,0))

    def scroll(self,event):
        if self.mode=='config':
            self.canvas.yview_scroll(-1 if event.delta>0 else 1,'units')

    def default_setting(self):
        weapon=next((w for w in self.catalog['weapons'].values() if 'Galil' in w['name']),next(iter(self.catalog['weapons'].values())))
        c={k:NONE for k in LABELS};c.update(weapon=weapon['name'],pose='站姿',weight='未记录',notes='新配置')
        return Setting(c)

    def selected(self):
        return dict(self.store.items()).get(self.selected_key)

    def current(self):
        if self.mode=='config':
            return None if self.form_error else self.draft.current
        return self.selected()

    def current_options(self):
        return ToggleOptions(self.key.get(),TRIGGERS[self.trigger.get()],self.diagnostic.get())

    @staticmethod
    def caption(s):
        c=s.conditions
        return f"{c['notes'] or c['weapon']}  ·  {c['weapon']} / {c['pose']} / {c['weight']}  ·  力度 {s.rate:g}"

    def refresh_presets(self):
        self.items=self.store.items()
        if self.selected_key not in dict(self.items):
            self.selected_key=self.items[0][0] if self.items else None
        self.preset_combo['values']=[self.caption(s) for _,s in self.items]
        if self.selected_key:
            self.preset_combo.current(next(i for i,(k,_) in enumerate(self.items) if k==self.selected_key))
        else:
            self.preset.set('还没有配置；点击“新建配置”调一套。')

    def select_preset(self,event=None):
        index=self.preset_combo.current()
        if index<0:return
        self.disable();self.selected_key=self.items[index][0]
        self.preferences.remember(self.items[index][1])
        self.notice.set('已切换配置；去游戏按启停键开启。')

    def _show(self,mode):
        for frame in self.pages.values():frame.pack_forget()
        self.pages[mode].pack(fill='both',expand=True)
        self.mode=mode
        if mode=='config':self.summary_label.pack_forget()
        else:self.summary_label.pack(anchor='w',pady=(6,0))

    def discard_prompt(self):
        if self.mode!='config' or (not self.draft.dirty and not self.form_error):return True
        self.disable()
        answer=messagebox.askyesnocancel('配置未保存','保存本次调整吗？\n“否”放弃调整；“取消”继续编辑。',parent=self.root)
        if answer is None:return False
        return self.save_config() if answer else True

    def show_home(self):
        if not self.discard_prompt():return
        self.disable();self._show('home');self.refresh_presets()
        self.notice.set('使用页只选配置；修改和调教在“配置管理”。')

    def show_config(self):
        if self.mode=='config':return
        self.disable();self.draft.load(self.selected() or self.default_setting())
        self.load_form();self._show('config')
        self.notice.set('本页可直接试草稿：去游戏按同一个启停键，调好保存。')

    def new_config(self):
        if not self.discard_prompt():return
        self.disable();self.draft.load(self.default_setting());self.load_form();self._show('config')
        self.notice.set('新配置：选择条件、试力度，满意后保存。')

    def compatibility(self):
        w=next((w for w in self.catalog['weapons'].values() if w['name']==self.fields['weapon'].get()),None)
        if not w:raise ValueError('请选择目录中的枪械')
        for slot,ids in w['compatibility'].items():
            self.combos[slot]['values']=[NONE]+[self.catalog['parts'][i]['name'] for i in ids]
            if self.fields[slot].get() not in self.combos[slot]['values']:self.fields[slot].set(NONE)
        ammo=[NONE]+[a['name'] for a in self.catalog['ammo'].values() if a['caliber']==w['caliber']]
        self.combos['ammo']['values']=ammo
        if self.fields['ammo'].get() not in ammo:self.fields['ammo'].set(NONE)

    def load_form(self):
        self.silent=True
        try:
            s=self.draft.current
            for k,v in s.conditions.items():self.fields[k].set(v)
            self.numeric.set(f'{s.rate:g}');self.duration.set(f'{s.duration:g}')
            self.compatibility();self.slider_widget.set(s.rate)
            self.form_error=''
        finally:self.silent=False
        self.draft_state.set('尚未保存' if self.draft.dirty else '已保存')

    def form_changed(self):
        if self.silent or self.mode!='config':return
        self.disable()
        try:
            self.silent=True;self.compatibility()
            s=Setting({k:v.get().strip() for k,v in self.fields.items()},float(self.numeric.get()),float(self.duration.get()))
            self.draft.change(s);self.slider_widget.set(s.rate);self.form_error=''
            self.draft_state.set('尚未保存' if self.draft.dirty else '已保存')
            self.notice.set('修改已用于当前草稿；去游戏按启停键试，保存后才覆盖配置。')
        except (ValueError,tk.TclError) as exc:
            self.form_error='请填写完整数值：力度 0～400，连续下拉 0.5～6 秒。'
            self.draft_state.set('数值不完整');self.notice.set(self.form_error)
        finally:self.silent=False

    def slider(self,value):
        if not self.silent and self.mode=='config':self.numeric.set(str(round(float(value))))

    def adjust(self,delta):
        self.disable()
        try:self.draft.adjust(delta);self.load_form()
        except ValueError as exc:self.notice.set(str(exc))

    def undo(self):
        self.disable()
        try:self.draft.edit.undo();self.load_form();self.notice.set('已撤销；同一个启停键可继续试。')
        except ValueError as exc:self.notice.set(str(exc))

    def save_config(self):
        self.disable()
        if self.form_error:
            self.notice.set(self.form_error);return False
        try:
            s=self.draft.save();self.selected_key=s.key;self.preferences.remember(s)
            self.refresh_presets();self.draft_state.set('已保存')
            self.notice.set('已保存。继续调，或返回使用；启停键不变。')
            return True
        except (ValueError,OSError) as exc:self.notice.set(str(exc));return False

    def copy_config(self):
        self.disable()
        name=simpledialog.askstring('复制配置','新配置名称（原配置保留）：',parent=self.root)
        if not name:return
        try:self.draft.copy_as(name);self.load_form();self.notice.set('已复制成新草稿；改条件或力度后保存。')
        except ValueError as exc:self.notice.set(str(exc))

    def export_config(self):
        self.disable()
        if self.form_error:return
        p=filedialog.asksaveasfilename(parent=self.root,defaultextension='.json',filetypes=[('配置','*.json')])
        if p:
            try:write_setting(p,self.draft.current);self.notice.set('已导出这套配置。')
            except (ValueError,OSError) as exc:self.notice.set(str(exc))

    def import_config(self):
        self.disable()
        if not self.discard_prompt():return
        p=filedialog.askopenfilename(parent=self.root,filetypes=[('配置','*.json')])
        if p:
            try:self.draft.load(read_setting(p));self.load_form();self.notice.set('已导入为草稿；保存后加入配置列表。')
            except (ValueError,OSError) as exc:self.notice.set(str(exc))

    def feedback(self):
        self.disable();Feedback(self.root)

    def options_changed(self):
        if self.silent:return
        self.disable()
        try:self.option_store.save(self.current_options())
        except (ValueError,OSError,KeyError) as exc:self.notice.set(str(exc))

    def disable(self):
        self.ready.disable(f'已关闭；按 {self.key.get()} 开启')

    def scan(self):
        try:
            self.window_values=self.windows_provider()
            self.target,self.target_text=self.rules.resolve(self.window_values)
        except Exception as exc:
            self.target=None;self.target_text='读取窗口失败：'+str(exc)
        self.next_scan=time.monotonic()+1.0

    def choose_window(self,title):
        self.disable();self.rules.save(title);self.next_scan=0
        self.notice.set('已记住游戏窗口名称；以后自动寻找，不需要点准备。')

    def open_settings(self):
        self.disable()
        win=tk.Toplevel(self.root);win.title('键位与游戏窗口');win.geometry('680x570')
        host=ttk.Frame(win,padding=18);host.pack(fill='both',expand=True)
        ttk.Label(host,text='设置一次即可；关闭这个窗口后直接去游戏按启停键。',wraplength=620).pack(anchor='w',pady=(0,14))
        row=ttk.Frame(host);row.pack(fill='x',pady=5)
        ttk.Label(row,text='启停键',width=14).pack(side='left')
        ttk.Combobox(row,textvariable=self.key,values=list(HOTKEYS),state='readonly',width=26).pack(side='left')
        row=ttk.Frame(host);row.pack(fill='x',pady=5)
        ttk.Label(row,text='何时下拉',width=14).pack(side='left')
        ttk.Combobox(row,textvariable=self.trigger,values=list(TRIGGERS),state='readonly',width=35).pack(side='left')
        ttk.Label(host,text='仅左键：按住左键就下拉，腰射也触发；右键＋左键：必须同时按住。',wraplength=620).pack(anchor='w',pady=6)
        rule=ttk.LabelFrame(host,text='游戏窗口（默认自动查找 WARDOGS / 战狗）',padding=12);rule.pack(fill='x',pady=8)
        self.scan();choices=[t for t,_ in self.window_values]
        self.window.set(self.rules.title or (self.target_text if self.target else ''))
        box=ttk.Combobox(rule,textvariable=self.window,values=choices,state='readonly',width=58);box.pack(fill='x')
        def picked(_):
            try:self.choose_window(self.window.get())
            except (ValueError,OSError) as exc:self.notice.set(str(exc))
        box.bind('<<ComboboxSelected>>',picked)
        def refresh():self.scan();box.configure(values=[t for t,_ in self.window_values])
        ttk.Button(rule,text='刷新列表',command=refresh).pack(side='left',pady=6)
        def reset():self.disable();self.rules.reset();self.next_scan=0;self.window.set('')
        ttk.Button(rule,text='恢复自动查找',command=reset).pack(side='left',padx=8)
        ttk.Label(host,text='如果没有效果，只看下面有没有读到按键、有没有发送。不要先乱加力度。',wraplength=620).pack(anchor='w',pady=(8,5))
        ttk.Checkbutton(host,text='只检测按键，不发送移动（排查用）',variable=self.diagnostic,command=self.options_changed).pack(anchor='w')
        ttk.Label(host,textvariable=self.report_text,wraplength=620).pack(anchor='w',pady=8)
        def copy():self.root.clipboard_clear();self.root.clipboard_append(self.diagnostic_report)
        ttk.Button(host,text='复制诊断',command=copy).pack(side='left',padx=3)
        ttk.Button(host,text='异常后重试监听',command=self.ready.retry).pack(side='left',padx=3)
        ttk.Button(host,text='完成',command=win.destroy).pack(side='right')

    def sync_edits(self):
        for event in self.runner.take_events():
            if self.mode!='config' or self.form_error or self.draft.current is None:
                self.disable();continue
            if event.get('before')!=self.draft.current.record():
                self.disable();continue
            try:
                s=Setting.from_record(event['after'])
                if self.runner.acknowledge(event,s):
                    self.draft.change(s);self.load_form()
                    self.ready.accept_edit(s,self.target,self.current_options(),shortcuts=True,step=int(self.step.get()))
                    self.notice.set(f'力度 {s.rate:g}，尚未保存；松开鼠标后可继续试。')
            except (ValueError,KeyError) as exc:
                self.disable();self.notice.set('调节没有采用：'+str(exc))

    def pulse_once(self):
        self.runner.pulse();self.sync_edits()
        if time.monotonic()>=self.next_scan:self.scan()
        current=self.current()
        self.ready.update(current,self.target,self.current_options(),shortcuts=self.mode=='config',step=int(self.step.get()))
        report=self.runner.snapshot()
        if self.ready.error or (report['reason']=='ERROR' and not self.runner.active):
            self.state.set('已停止 · 需要检查')
            self.action.set(self.ready.error or self.runner.message)
        elif self.form_error and self.mode=='config':
            self.state.set('已关闭 · 请填完整数值');self.action.set(self.form_error)
        elif current is None:
            self.state.set('先选择一套配置');self.action.set('已有配置直接选择；没有就点“新建配置”。')
        elif self.target is None:
            self.state.set('等待游戏窗口');self.action.set(self.target_text)
        elif current.rate<=0:
            self.state.set('已关闭 · 力度为 0');self.action.set('到配置管理设置非零力度，之后按启停键试。')
        elif not self.runner.active and self.ready.bound is not None and self.ready.pending is None:
            self.state.set('未就绪 · 监听已停止');self.action.set('请到“键位与窗口 / 诊断”查看原因并重试。'+self.runner.message)
        elif report['enabled']:
            self.state.set('已开启  ·  '+self.key.get()+' 关闭')
            self.action.set(self.runner.message.replace('已准备','已就绪'))
        else:
            self.state.set('已关闭  ·  '+self.key.get()+' 开启')
            self.action.set(f'去游戏按一下 {self.key.get()} 开启，再按一下关闭。'+(' 本页试当前未保存草稿。' if self.mode=='config' else ''))
        self.summary.set((self.caption(current)+f'  / 最长 {current.duration:g} 秒' if current else '')+
                         ('\n仅左键：腰射也触发。' if self.current_options().trigger=='left' else '\n右键＋左键：须同时按住。'))
        self.diagnostic_report=json.dumps({'version':VERSION,'page':self.mode,'target_found':self.target is not None,
            'hotkey':self.key.get(),'trigger':self.current_options().trigger,**report},ensure_ascii=False,indent=2)
        keys=report['keys']
        self.report_text.set(f"监听：{'就绪' if report['listening'] else '未启动'}  / 开关：{'开启' if report['enabled'] else '关闭'}\n"
            f"游戏前台：{keys.get('foreground','未知')}；左键：{keys.get('left','未知')}；右键：{keys.get('right','未知')}\n"
            f"尝试 {report['attempted_events']} 次 / Windows 接收 {report['accepted_events']} 次，{report['accepted_counts']} 单位\n"
            f"系统信息：{report['system_error'] or '无报错'}\nWindows 接收不等于游戏已采用输入。")

    def pulse(self):
        try:self.pulse_once()
        except Exception as exc:
            self.runner.stop(str(exc));self.ready.error=str(exc);self.notice.set('已停止：'+str(exc))
        self.timer=self.root.after(60,self.pulse)

    def close(self,force=False):
        self.disable()
        if not force and not self.discard_prompt():return
        self.ready.close()
        try:self.root.after_cancel(self.timer)
        except (tk.TclError,AttributeError):pass
        self.root.destroy()
