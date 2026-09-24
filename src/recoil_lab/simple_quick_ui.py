"""Native controls for explicitly enabled, between-burst manual adjustments."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk

from .simple_core import Setting
from .simple_tuning import validate_catalog_setting


class QuickControls:
    def __init__(self, app):
        self.app = app
        self.enabled = tk.BooleanVar(value=False)
        self.window = None
        self.caption = tk.StringVar()
        self.hint = tk.StringVar(value='快捷调节关闭；开启后，仅在本次前台试用中生效')
        host = ttk.Frame(getattr(app, 'quick_host', app.scale.master))
        host.pack(fill='x', pady=(8, 2))
        ttk.Checkbutton(host, text='松手后用 F5 / F6 调节（可选）',
                        variable=self.enabled, command=self.options_changed).pack(side='left')
        ttk.Button(host, text='显示状态小窗', command=self.show_status).pack(side='right')
        ttk.Label(app.scale.master, textvariable=self.hint, foreground='#536173',
                  wraplength=810).pack(anchor='w', pady=3)

    def options_changed(self):
        self.app.stop()
        self.update_hint()

    def update_hint(self):
        if self.enabled.get():
            self.hint.set(f'全部松手后：F5 −{self.app.step.get()} / F6 ＋{self.app.step.get()}；'
                          '按住不连调，开火时不改。F8 / Esc 停止。')
        else:
            self.hint.set('快捷调节关闭；使用原来的按钮调节。按键与游戏冲突时保持关闭。')

    def prepare(self):
        self.sync()
        self.app.runner.configure(self.enabled.get(), int(self.app.step.get()))
        self.update_hint()

    def accept(self, event):
        """The UI must accept exactly the proposed rate-only edit before new output."""
        app = self.app
        if event.get('session_id') != app.runner.session_id:
            app.runner.stop('调节来自过期会话，未采用；请重新开始')
            return False
        before = Setting.from_record(event['before'])
        after = Setting.from_record(event['after'])
        validate_catalog_setting(after, app.catalog)
        if (before.key != after.key or before.duration != after.duration
                or app.pending_numeric() or app.setting().record() != before.record()):
            app.runner.stop('快捷调节与界面草稿冲突，未覆盖；请核对当前参数再开始')
            app.status.set(app.runner.message)
            return False
        app.silent = True
        try:
            app.rate.set(after.rate)
            app.amount.set(f'{after.rate:g}')
            app.numeric.set(f'{after.rate:g}')
        finally:
            app.silent = False
        app.history.change(after)
        app.touched = True
        app.refresh_edit_state()
        acknowledged = app.runner.acknowledge(event, after)
        if not acknowledged:
            app.runner.message = '调节已保留为未保存草稿；输出已停止，核对后重新开始'
        app.status.set(app.runner.message)
        return True

    def sync(self):
        self.caption.set(' / '.join(self.app.fields[k].get() for k in ('weapon','pose','weight')))
        for event in self.app.runner.take_events():
            try:
                self.accept(event)
            except (ValueError, KeyError, TypeError, tk.TclError):
                self.app.error('快捷调节同步失败，已停止；请核对当前参数')

    def show_status(self):
        self.app.stop()
        if self.window is not None and self.window.winfo_exists():
            self.window.lift()
            return
        win = tk.Toplevel(self.app.root)
        self.window = win
        win.title('RecoilLab · 当前手动配置')
        win.geometry('430x275-25+50')
        win.minsize(360, 210)
        win.attributes('-topmost', True)
        outer = ttk.Frame(win, padding=12)
        outer.pack(fill='both', expand=True)
        self.sync()
        ttk.Label(outer, textvariable=self.caption, wraplength=400).pack(anchor='w', pady=(0, 5))
        ttk.Label(outer, text='当前下拉力度', foreground='#536173').pack(anchor='w')
        ttk.Label(outer, textvariable=self.app.amount, font=('', 25, 'bold')).pack(anchor='w')
        ttk.Label(outer, textvariable=self.app.guide.live_title, wraplength=400).pack(anchor='w', pady=6)
        ttk.Label(outer, textvariable=self.hint, wraplength=400,
                  foreground='#536173').pack(anchor='w')
        ttk.Button(outer, text='立即停止  F8 / Esc', command=self.app.stop).pack(anchor='e', pady=6)
        win.protocol('WM_DELETE_WINDOW', self.close_status)
        win.bind('<Escape>', lambda _: self.app.stop())

    def close_status(self):
        self.app.stop()
        if self.window is not None:
            self.window.destroy()
            self.window = None


def self_test(out):
    """Extend the real native UI checks, using fake input only."""
    from .simple_app import Application
    from .simple_quick import QuickSession
    from PIL import ImageGrab
    import os

    result = json.loads(Path(out).read_text(encoding='utf-8'))
    checks = []
    with tempfile.TemporaryDirectory() as directory:
        root = tk.Tk()
        app = Application(root, directory)
        root.update()
        try:
            assert not app.quick.enabled.get() and not app.runner.active
            checks.append('quick_default_off')
            app.quick.enabled.set(True)
            app.quick.options_changed()
            app.step.set('1')
            app.step_changed()
            app.quick.prepare()
            assert app.runner.shortcuts and app.runner.step == 1
            checks.append('quick_step_prepared_without_input')
            before = app.setting()
            app.runner.controller = controller = QuickSession(before, 1)
            app.runner.cancel.clear()
            app.runner.active = True
            app.runner.pulse()
            controller.tick(0, (False,)*3, (False,)*2)
            _, event = controller.tick(.01, (False,)*3, (False, True))
            event['session_id'] = app.runner.session_id
            app.runner.events.append(event)
            app.quick.sync()
            assert app.rate.get() == before.rate+1 and controller.setting.rate == before.rate+1
            assert app.has_edits and app.touched and controller.neutral_required
            checks.append('quick_ack_updates_native_fields_and_draft')
            app.undo_edit()
            assert app.rate.get() == before.rate and not app.runner.active
            checks.append('quick_edit_undo')
            # A stale event must never overwrite a newer manual UI edit.
            app.adjust(10)
            current = app.setting()
            assert not app.quick.accept(event)
            assert app.setting().record() == current.record() and not app.runner.active
            checks.append('quick_conflict_keeps_newer_draft')
            app.quick.show_status()
            root.update()
            assert app.quick.window.winfo_exists() and not app.runner.active
            checks.append('quick_status_window_is_opt_in')
            app.quick.close_status()
            assert app.quick.window is None and not app.runner.active
            checks.append('quick_status_close_stops')
            app.quick.show_status()
            app.save()
            if os.environ.get('SIMPLE_SCREENSHOT'):
                app.scroll.yview_moveto(.23)
                root.update()
                ImageGrab.grab(bbox=(root.winfo_rootx(),root.winfo_rooty(),
                                    root.winfo_rootx()+root.winfo_width(),
                                    root.winfo_rooty()+root.winfo_height())).save(os.environ['SIMPLE_SCREENSHOT'])
            app.close(force=True)
            root = tk.Tk()
            app = Application(root, directory)
            root.update()
            assert not app.quick.enabled.get() and app.quick.window is None
            assert not app.runner.active and app.target is None and not app.consent.get()
            assert app.rate.get() == current.rate
            checks.append('quick_restart_keeps_settings_not_permission')
        except Exception:
            result['status'] = 'FAIL'
            raise
        finally:
            try: app.close(force=True)
            except tk.TclError: pass
            result['checks'].extend(checks)
            Path(out).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
