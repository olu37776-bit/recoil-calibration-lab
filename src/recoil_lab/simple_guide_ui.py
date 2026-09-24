"""Four-step native interface over the unchanged manual runner and store."""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk

from .simple_guide import STAGES, NO_EFFECT, Notice, preparation_issue, run_notice

BG = '#f4f6f9'
INK = '#142238'
MUTED = '#526176'
BLUE = '#2356ba'

class GuideView:
    def __init__(self, app, font):
        self.app = app
        self.stage = 0
        self.outcome = False
        self.saved_here = False
        self.hint = tk.StringVar()
        self.start_error = tk.StringVar()
        self.live_title = tk.StringVar()
        self.live_action = tk.StringVar()
        self.summary = tk.StringVar()
        self.saved_title = tk.StringVar(value='满意了，就把这套参数保存下来')
        root = app.root
        style = ttk.Style(root)
        style.configure('Guide.TLabel', background=BG, foreground=INK)
        style.configure('Title.Guide.TLabel', font=(font[0], 18, 'bold'))
        style.configure('Muted.Guide.TLabel', foreground=MUTED)
        style.configure('Primary.TButton', padding=(16, 9), font=(font[0], 11, 'bold'), foreground='white', background=BLUE)
        style.map('Primary.TButton', background=[('active', '#19458f'), ('disabled', '#bdc7d8')], foreground=[('disabled', '#45566e')])
        style.configure('Step.TButton', padding=(8, 7))
        style.configure('Selected.Step.TButton', background='#dce8ff', foreground=BLUE, font=(font[0], 10, 'bold'))
        root.geometry(f'{min(960, root.winfo_screenwidth()-70)}x{min(750, root.winfo_screenheight()-80)}')
        root.minsize(780, 550)
        header = ttk.Frame(root, padding=(18, 12, 18, 7)); header.pack(fill='x')
        ttk.Label(header, text='RecoilLab  /  跟着这 4 步走', style='Title.Guide.TLabel').pack(anchor='w')
        ttk.Label(header, text='手动试调版：不录屏，不填DPI，不自动识别枪械。', style='Muted.Guide.TLabel').pack(anchor='w', pady=(3, 7))
        steps = ttk.Frame(header); steps.pack(fill='x')
        self.step_buttons = []
        for index, title in enumerate(STAGES):
            button = ttk.Button(steps, text=f'{index+1}  {title}', style='Step.TButton', command=lambda i=index: self.show(i))
            button.pack(side='left', fill='x', expand=True, padx=(0, 5)); self.step_buttons.append(button)
        self.footer = ttk.Frame(root, padding=(18, 8, 18, 12)); self.footer.pack(side='bottom', fill='x')
        ttk.Label(self.footer, textvariable=self.hint, style='Muted.Guide.TLabel', wraplength=720).pack(anchor='w', pady=(0, 7))
        buttons = ttk.Frame(self.footer); buttons.pack(fill='x')
        self.back = ttk.Button(buttons, text='上一步', command=lambda: self.show(max(0, self.stage-1))); self.back.pack(side='left')
        self.stop_button = ttk.Button(buttons, text='立即停止  F8 / Esc', command=app.stop); self.stop_button.pack(side='right', padx=(8, 0))
        app.start_button = ttk.Button(buttons, style='Primary.TButton', command=self.primary); app.start_button.pack(side='right')
        host = ttk.Frame(root); host.pack(fill='both', expand=True)
        scroll = tk.Canvas(host, background=BG, highlightthickness=0)
        bar = ttk.Scrollbar(host, orient='vertical', command=scroll.yview); bar.pack(side='right', fill='y')
        scroll.configure(yscrollcommand=bar.set); scroll.pack(side='left', fill='both', expand=True)
        outer = ttk.Frame(scroll, padding=(18, 8, 18, 14)); item = scroll.create_window((0, 0), window=outer, anchor='nw')
        outer.bind('<Configure>', lambda _: scroll.configure(scrollregion=scroll.bbox('all')))
        scroll.bind('<Configure>', lambda e: scroll.itemconfigure(item, width=e.width))
        root.bind('<MouseWheel>', lambda e: scroll.yview_scroll(-int(e.delta/120), 'units'))
        app.scroll = scroll
        self.pages = [ttk.Frame(outer) for _ in STAGES]
        self._config(self.pages[0], font)
        self._prepare(self.pages[1], font)
        self._test(self.pages[2], font)
        self._save(self.pages[3], font)
        self._last_notice = None
        self._last_conditions = None
        self.show(0, stop=False)

    def text(self, parent, text=None, variable=None, *, title=False, muted=False):
        options = {'style': 'Title.Guide.TLabel' if title else 'Muted.Guide.TLabel' if muted else 'Guide.TLabel', 'wraplength': 720, 'justify': 'left'}
        if variable is not None: options['textvariable'] = variable
        else: options['text'] = text
        widget = ttk.Label(parent, **options); widget.pack(anchor='w', fill='x', pady=(2, 6))
        return widget

    def collapsible(self, parent, caption):
        container = ttk.Frame(parent); container.pack(fill='x', pady=5)
        inside = ttk.Frame(container, padding=(8, 7))
        opened = [False]
        def toggle():
            self.app.stop()
            opened[0] = not opened[0]
            if opened[0]: inside.pack(fill='x')
            else: inside.pack_forget()
            button.configure(text=('收起：' if opened[0] else '展开：')+caption)
        button = ttk.Button(container, text='展开：'+caption, command=toggle); button.pack(anchor='w')
        return inside

    def _config(self, page, font):
        app = self.app
        self.text(page, '① 先选你这次要调的配装', title=True)
        self.text(page, '先调一套。配装只用于区分保存的参数，不会自动替你算出力度。', muted=True)
        saved = ttk.Frame(page); saved.pack(fill='x', pady=(4, 12))
        ttk.Label(saved, text='用以前保存的：').pack(side='left')
        app.saved_combo = ttk.Combobox(saved, textvariable=app.saved, state='readonly', width=38)
        app.saved_combo.pack(side='left', fill='x', expand=True); app.saved_combo.bind('<<ComboboxSelected>>', app.load_selected)
        ttk.Button(saved, text='导入配置', command=app.import_current).pack(side='left', padx=(8, 0))
        first = ttk.LabelFrame(page, text='或者选择本次实际条件', padding=10); first.pack(fill='x')
        app.combos = {}
        app.combo(first, 'weapon', '枪械', [w['name'] for w in app.catalog['weapons'].values()], 0, 0)
        app.combo(first, 'sight', '瞄准镜', [], 0, 2)
        app.combo(first, 'pose', '姿态', ['站姿', '蹲姿', '卧姿'], 1, 0)
        app.combo(first, 'weight', '负重', ['未记录', '轻装', '中装', '重装'], 1, 2, editable=True)
        more = ttk.Frame(first); more.grid(row=2, column=0, columnspan=4, sticky='ew', pady=6)
        app.more = ttk.Frame(first); app.more_open = False
        ttk.Button(more, text='核对其他配件 / 写备注', command=app.toggle_more).pack(anchor='w')
        for i, (key, label) in enumerate([('muzzle', '枪口'), ('underbarrel', '握把'), ('magazine', '弹匣'), ('ammo', '弹药')]):
            app.combo(app.more, key, label, [], i//2, (i%2)*2)
        ttk.Label(app.more, text='备注').grid(row=2, column=0, sticky='w')
        ttk.Entry(app.more, textvariable=app.fields['notes']).grid(row=2, column=1, columnspan=3, sticky='ew')
        self.text(page, '负重是你自己选的标签。不知道就保留“未记录”；不用称重或安装鼠标驱动。', muted=True)
        app.fields['weapon'].set('Galil'); app.fields['pose'].set('站姿'); app.fields['weight'].set('未记录'); app.weapon_changed()
        details = self.collapsible(page, '已选配件摘要')
        self.text(details, variable=app.condition_text, muted=True)

    def _prepare(self, page, font):
        app = self.app
        self.text(page, '② 先准备好，再开始', title=True)
        self.text(page, '1  打开允许测试的场景，固定配装和姿态，对准墙面。\n2  回到这里，刷新列表并选择游戏窗口。\n3  确认后点底部蓝色按钮，5秒内切回游戏。')
        row = ttk.Frame(page); row.pack(fill='x', pady=8)
        app.window_combo = ttk.Combobox(row, textvariable=app.window, state='readonly', width=40)
        app.window_combo.pack(side='left', fill='x', expand=True); app.window_combo.bind('<<ComboboxSelected>>', app.select_window)
        ttk.Button(row, text='刷新窗口列表', command=app.refresh_windows).pack(side='left', padx=(8, 0))
        self.text(page, '列表为空？先打开游戏，再刷新。不需要填写显示器分辨率。', muted=True)
        ttk.Checkbutton(page, text='本次仅在明确允许的受控场景试用；我了解游戏规则风险', variable=app.consent, command=app.consent_changed).pack(anchor='w', pady=(6, 10))
        self.text(page, variable=self.start_error)
        self.text(page, variable=self.summary)
        self.text(page, '首次保留力度20、每轮2秒即可。这只是试调起点，不是准确预设。', muted=True)
        self.text(page, '切回后要同时按住：F7（允许下拉）＋ 鼠标右键（开镜）＋ 左键（开火）。\n只按一下F7不会持续生效。松手即停；弹打完也要松开。')

    def _test(self, page, font):
        app = self.app
        self.text(page, '③ 试一次，再告诉我效果', title=True)
        status = ttk.LabelFrame(page, text='现在该做什么', padding=12); status.pack(fill='x', pady=5)
        self.status_card = status
        self.text(status, variable=self.live_title, title=True)
        self.text(status, variable=self.live_action)
        self.instructions = ttk.Frame(page); self.instructions.pack(fill='x', pady=5)
        self.text(self.instructions, '按键顺序：先全部松开 → 按住F7 → 按住右键 → 按住左键。\n试射时三个键都保持按住；试完松手，切回这里。')
        self.text(self.instructions, 'F8 / Esc 随时停止。换弹、切枪或切出窗口后，需要重新点开始。', muted=True)
        row = ttk.Frame(self.instructions); row.pack(fill='x', pady=6)
        self.finish_button = ttk.Button(row, text='我已试射，看效果', command=self.finish); self.finish_button.pack(side='left')
        ttk.Button(row, text='还没试射：回到准备', command=lambda: self.show(1)).pack(side='left', padx=8)
        self.results = ttk.Frame(page)
        self.text(self.results, '刚才是下面哪一种？这是你的观察，不是程序自动判断。', muted=True)
        row = ttk.Frame(self.results); row.pack(fill='x', pady=5)
        app.more_button = ttk.Button(row, text='往上飘 → 增强一点', command=lambda: self.adjust(1)); app.more_button.pack(side='left', expand=True, fill='x', padx=(0, 5))
        app.less_button = ttk.Button(row, text='往下压 → 减弱一点', command=lambda: self.adjust(-1)); app.less_button.pack(side='left', expand=True, fill='x', padx=5)
        ttk.Button(row, text='基本合适 → 去保存', command=lambda: self.show(3)).pack(side='left', expand=True, fill='x', padx=(5, 0))
        row = ttk.Frame(self.results); row.pack(fill='x', pady=5)
        ttk.Button(row, text='没有作用？检查原因', command=self.no_effect).pack(side='left')
        ttk.Button(row, text='只是左右散 / 呼吸晃', command=self.sway).pack(side='left', padx=8)
        self.feedback_note = tk.StringVar(value='先看一轮再调整。不要因为左右散，就一直增加向下力度。')
        self.text(self.results, variable=self.feedback_note, muted=True)
        row = ttk.Frame(page); row.pack(fill='x', pady=6)
        ttk.Label(row, text='当前力度').pack(side='left')
        ttk.Label(row, textvariable=app.amount, font=(font[0], 23, 'bold')).pack(side='left', padx=10)
        ttk.Label(row, text='每次调').pack(side='left', padx=(10, 3))
        step = ttk.Combobox(row, textvariable=app.step, values=['1', '5', '10'], state='readonly', width=4); step.pack(side='left')
        step.bind('<<ComboboxSelected>>', app.step_changed)
        ttk.Label(row, text='每轮最多').pack(side='left', padx=(14, 3))
        ttk.Combobox(row, textvariable=app.duration, values=['0.5', '1', '1.5', '2', '3', '4', '5', '6'], state='readonly', width=4).pack(side='left')
        ttk.Label(row, text='秒').pack(side='left', padx=3)
        advanced = self.collapsible(page, '精细调节、快捷键和状态小窗（可选）'); app.quick_host = advanced
        row = ttk.Frame(advanced); row.pack(fill='x')
        ttk.Label(row, text='直接输入力度').pack(side='left')
        entry = ttk.Entry(row, textvariable=app.numeric, width=7); entry.pack(side='left', padx=5); entry.bind('<Return>', lambda _: app.set_numeric())
        ttk.Button(row, text='采用数值', command=app.set_numeric).pack(side='left')
        app.scale = ttk.Scale(advanced, from_=0, to=400, variable=app.rate, command=app.slider); app.scale.pack(fill='x', pady=6)
        row = ttk.Frame(advanced); row.pack(fill='x')
        app.undo_button = ttk.Button(row, text='撤销上次调节', command=app.undo_edit); app.undo_button.pack(side='left')
        ttk.Button(row, text='暂时记住这组数值', command=app.remember_reference).pack(side='left', padx=5)
        app.restore_button = ttk.Button(row, text='恢复暂存数值', command=app.restore_reference); app.restore_button.pack(side='left')
        self.text(advanced, variable=app.reference_text, muted=True)
        raw = self.collapsible(page, '详细状态 / 截图辅助')
        self.text(raw, variable=app.status, muted=True)
        ttk.Button(raw, text='手动标注弹着截图（可选）', command=app.open_feedback).pack(anchor='w')
        self.troubleshooting = ttk.Frame(page)
        for line in NO_EFFECT: self.text(self.troubleshooting, '• '+line)

    def _save(self, page, font):
        app = self.app
        self.text(page, '④ 保存，下次不用从头调', title=True)
        self.text(page, variable=self.saved_title)
        self.text(page, variable=self.summary, title=True)
        self.text(page, variable=app.condition_text, muted=True)
        self.text(page, variable=app.dirty_text)
        self.text(page, '点底部“保存这套”保存在本机。下次打开会恢复参数，\n但仍要选择游戏窗口、确认并开始，不会自动运行。')
        row = ttk.Frame(page); row.pack(fill='x', pady=12)
        ttk.Button(row, text='导出一份备份', command=app.export_current).pack(side='left')
        ttk.Button(row, text='恢复以前的保存值', command=app.undo).pack(side='left', padx=8)
        self.text(page, '“满意”是你的试用判断，不是游戏验证结果。此版本不会自动换枪、消除呼吸或识别弹孔。', muted=True)

    def issue(self):
        app = self.app
        try:
            setting = app.setting(); valid = True; rate = setting.rate
        except (ValueError, tk.TclError): valid = False; rate = 0
        return preparation_issue(valid=valid, pending=app.pending_numeric(), target=app.target is not None,
                                 consent=app.consent.get(), rate=rate)

    def show(self, stage, *, stop=True):
        if not 0 <= stage < len(STAGES): raise ValueError('Invalid guide stage')
        if stop: self.app.stop()
        self.stage = stage
        for i, page in enumerate(self.pages):
            if i == stage: page.pack(fill='both', expand=True)
            else: page.pack_forget()
            self.step_buttons[i].configure(style='Selected.Step.TButton' if i == stage else 'Step.TButton')
        self.app.scroll.yview_moveto(0)
        self.refresh()

    def refresh(self):
        app = self.app
        self.summary.set(f'{app.fields["weapon"].get()} / {app.fields["pose"].get()} / {app.fields["weight"].get()}　力度 {app.amount.get()}　每轮 {app.duration.get()} 秒')
        conditions = tuple(v.get() for v in app.fields.values())
        if self._last_conditions is not None and conditions != self._last_conditions:
            self.outcome = False; self.saved_here = False
            self.results.pack_forget(); self.troubleshooting.pack_forget()
            self.instructions.pack(fill='x', after=self.status_card, pady=5)
            self.feedback_note.set('配装已改变：先试一轮，再按这套配装的结果调整。')
        self._last_conditions = conditions
        issue = self.issue()
        self.back.configure(state='disabled' if self.stage == 0 else 'normal')
        if self.stage == 0:
            caption, hint = '下一步：准备试射', '配装选好后，点右下方蓝色按钮。不用在这一页调力度。'
            try: app.setting()
            except (ValueError, tk.TclError): hint = '请先把本次实际配装选完整，再继续。'
        elif self.stage == 1:
            caption, hint = '开始5秒倒计时', issue or '准备好了。点开始后，请在5秒内切回刚选的游戏窗口。'
        elif self.stage == 2:
            if self.outcome: caption = f'用力度 {app.amount.get()} 再试一次'
            else: caption = '我已试射，看效果'
            hint = '调整不会自动开始。每次试射仍需主动点开始。' if self.outcome else '试完全部松手，切回本程序，再点“我已试射，看效果”。'
        else:
            caption = '再试一次：回到准备' if self.saved_here and not app.has_edits else '保存这套'
            hint = '保存在本机；备份和更多操作不是必做项。'
            if app.has_edits: self.saved_title.set('当前有未保存参数，满意后请点“保存这套”。')
            elif self.saved_here: self.saved_title.set('已保存在本机。现在可以关闭程序，参数不会丢。')
            else: self.saved_title.set('当前参数已有保存记录；下次可直接载入。')
        app.start_button.configure(text=caption, state='disabled' if self.stage == 1 and issue else 'normal')
        self.hint.set(hint)
        notice = run_notice(app.status.get(), app.runner.active)
        if self.stage == 2 and self.outcome and not app.runner.active and notice.kind != 'warning':
            notice = Notice('已停止：现在按你的观察调整', '不用按F7。选择下方结果；调整后点底部蓝色按钮再试，合适就保存。')
        if notice != self._last_notice:
            self.live_title.set(notice.title); self.live_action.set(notice.action); self._last_notice = notice

    def primary(self):
        app = self.app
        if self.stage == 0:
            try: app.setting()
            except (ValueError, tk.TclError) as exc: app.error(exc); return
            self.show(1)
        elif self.stage == 1 or (self.stage == 2 and self.outcome):
            if self.issue(): self.show(1); return
            self.begin()
        elif self.stage == 2: self.finish()
        elif self.saved_here and not app.has_edits: self.show(1)
        elif app.save():
            self.saved_here = True
            self.saved_title.set('已保存在本机。现在可以关闭程序，参数不会丢。')
            self.refresh()

    def begin(self):
        self.start_error.set('')
        self.app.start()
        if not self.app.runner.active:
            self.start_error.set('上次未能开始：'+self.app.status.get())
            self.show(1); self.refresh(); return
        self.outcome = False
        self.results.pack_forget(); self.troubleshooting.pack_forget()
        self.instructions.pack(fill='x', after=self.status_card, pady=5)
        self.show(2, stop=False)

    def finish(self):
        self.app.stop(); self.outcome = True
        self.instructions.pack_forget()
        self.results.pack(fill='x', after=self.status_card, pady=5)
        self.refresh()

    def adjust(self, direction):
        before = self.app.rate.get(); self.app.adjust(direction*int(self.app.step.get()))
        after = self.app.rate.get()
        self.saved_here = False
        self.feedback_note.set(f'力度 {before:g} → {after:g}，尚未保存。点底部蓝色按钮再试一次；合适后再保存。')
        self.refresh()

    def no_effect(self):
        self.app.stop()
        self.troubleshooting.pack(fill='x', after=self.results, pady=8)
        self.feedback_note.set('先检查有没有启用，不要先加大力度。详细状态在下方可展开。')
        self.refresh()

    def sway(self):
        self.app.stop()
        self.feedback_note.set('先保持力度不变。这个版本只做固定向下移动，不能消除随机左右散布或呼吸晃动。')
        self.refresh()


def self_test(out):
    """Exercise actual Tk navigation with fake start only, never hardware input."""
    import json
    import os
    from pathlib import Path
    import tempfile
    from .simple_app import Application
    from PIL import ImageGrab

    result = json.loads(Path(out).read_text(encoding='utf-8'))
    checks = []
    with tempfile.TemporaryDirectory() as directory:
        root = tk.Tk(); app = Application(root, directory); root.update()
        try:
            g = app.guide
            assert g.stage == 0 and not app.runner.active and not app.consent.get()
            assert g.pages[0].winfo_ismapped() and sum(p.winfo_ismapped() for p in g.pages) == 1
            checks.append('guide_one_step_default_off')
            assert not app.more.winfo_ismapped() and not app.scale.winfo_ismapped()
            checks.append('guide_optional_controls_collapsed')
            app.start_button.invoke(); root.update()
            assert g.stage == 1 and str(app.start_button.cget('state')) == 'disabled'
            assert '刷新' in g.hint.get() and app.target is None
            checks.append('guide_missing_window_explained')
            g.primary()
            assert not app.runner.active
            checks.append('guide_missing_conditions_never_start')
            app.window_values = [('测试窗口', {'handle': 123, 'pid': 456, 'size': [1920,1080]})]
            app.window_combo['values'] = ['测试窗口（自检）']
            app.window_combo.current(0); app.select_window(); g.refresh()
            assert '确认' in g.hint.get() and str(app.start_button.cget('state')) == 'disabled'
            checks.append('guide_explicit_consent_still_required')
            app.consent.set(True); g.refresh()
            assert not app.runner.active and str(app.start_button.cget('state')) == 'normal'
            checks.append('guide_readiness_is_not_execution')
            calls = []
            def fake_start(setting, target, consent):
                calls.append((setting, target, consent)); app.runner.active = True
                app.runner.cancel.clear(); app.runner.message = '5秒准备：切到所选窗口，先松开左键'
            app.runner.start = fake_start
            g.primary(); root.update()
            assert len(calls) == 1 and g.stage == 2 and not g.outcome
            assert app.runner.active and '5' in g.live_title.get()
            checks.append('guide_explicit_start_enters_countdown')
            app.runner.message = '待命：F7＋右键＋左键；释放左键后可开始下一轮'
            app.status.set(app.runner.message); g.refresh()
            assert '试用已开启' in g.live_title.get() and not g.outcome
            checks.append('guide_waiting_not_claimed_as_shot_complete')
            app.runner.stop('已切出目标窗口，已停止；调整好后重新开始')
            app.status.set(app.runner.message); g.refresh()
            assert '切回' in g.live_title.get() and '正常停止' in g.live_action.get()
            checks.append('guide_focus_stop_has_recovery')
            g.finish(); root.update()
            assert g.outcome and g.results.winfo_ismapped() and not app.runner.active
            checks.append('guide_user_reports_result')
            before = app.rate.get(); g.adjust(1)
            assert app.rate.get() == before+5 and len(calls) == 1 and not app.runner.active
            assert '再试一次' in app.start_button.cget('text')
            checks.append('guide_feedback_is_manual_and_no_autostart')
            g.adjust(-1); assert app.rate.get() == before
            checks.append('guide_downward_feedback_reduces_rate')
            g.no_effect(); root.update()
            assert g.troubleshooting.winfo_ismapped() and app.rate.get() == before and not app.runner.active
            checks.append('guide_no_effect_does_not_increase_rate')
            g.sway(); assert app.rate.get() == before and '保持力度不变' in g.feedback_note.get()
            checks.append('guide_sway_not_treated_as_vertical_recoil')
            g.show(3); g.primary(); root.update()
            assert g.saved_here and not app.has_edits and len(app.store.items()) == 1
            assert '已保存在本机' in g.saved_title.get() and not app.runner.active
            checks.append('guide_save_receipt_without_permission')
            g.primary(); assert g.stage == 1 and len(calls) == 1
            checks.append('guide_saved_next_step_does_not_start')
            app.numeric.set('not-a-number'); g.refresh()
            assert str(app.start_button.cget('state')) == 'disabled' and '数值' in g.hint.get()
            app.numeric.set(f'{app.rate.get():g}')
            checks.append('guide_pending_numeric_blocks_start')
            def failed_start(*_): raise ValueError('Windows拒绝输入；请停止测试')
            app.runner.start = failed_start
            g.primary(); root.update()
            assert '上次未能开始' in g.start_error.get() and not app.runner.active and g.stage == 1
            checks.append('guide_failed_start_visible_in_prepare')
            app.runner.active = True; g.show(0); assert not app.runner.active
            checks.append('guide_navigation_stops_output')
            for stage in range(4):
                g.show(stage); root.geometry('820x580'); root.update()
                for button in (app.start_button, g.stop_button, g.back):
                    assert button.winfo_ismapped()
                    assert button.winfo_rooty() >= root.winfo_rooty()
                    assert button.winfo_rooty()+button.winfo_height() <= root.winfo_rooty()+root.winfo_height()
            checks.append('guide_footer_visible_all_steps_820x580')
            root.geometry('940x720'); g.start_error.set(''); app.status.set('未启用')
            app.target = None; app.window.set(''); app.consent.set(False)
            g.show(0); root.update()
            shot = os.environ.get('SIMPLE_SCREENSHOT')
            if shot:
                ImageGrab.grab(bbox=(root.winfo_rootx(), root.winfo_rooty(),
                                    root.winfo_rootx()+root.winfo_width(), root.winfo_rooty()+root.winfo_height())).save(shot)
                g.show(1); root.update()
                ImageGrab.grab(bbox=(root.winfo_rootx(), root.winfo_rooty(),
                                    root.winfo_rootx()+root.winfo_width(), root.winfo_rooty()+root.winfo_height())).save(str(Path(shot).with_name('guide-prepare.png')))
                g.show(2); g.finish(); g.troubleshooting.pack_forget()
                g.feedback_note.set('还没找到合适力度就用步长5；接近合适时换步长1。')
                root.update()
                ImageGrab.grab(bbox=(root.winfo_rootx(), root.winfo_rooty(),
                                    root.winfo_rootx()+root.winfo_width(), root.winfo_rooty()+root.winfo_height())).save(str(Path(shot).with_name('guide-feedback.png')))
            app.close(force=True)
            root = tk.Tk(); app = Application(root, directory); root.update()
            assert app.guide.stage == 0 and app.target is None and not app.consent.get() and not app.runner.active
            assert app.rate.get() == before
            checks.append('guide_restart_keeps_parameter_not_authorization')
        except Exception:
            result['status'] = 'FAIL'
            raise
        finally:
            try: app.close(force=True)
            except tk.TclError: pass
            result['checks'].extend(checks)
            Path(out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
