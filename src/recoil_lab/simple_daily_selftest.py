"""Native UI integration tests; all input backends are fake."""
from pathlib import Path
import json
import os
import tempfile
import tkinter as tk
from .simple_toggle import ToggleOptions,Keys

def self_test(out):
    from .simple_app import Application
    result=json.loads(Path(out).read_text(encoding='utf-8'));checks=[]
    with tempfile.TemporaryDirectory() as directory:
        root=tk.Tk();app=Application(root,directory);root.update()
        try:
            assert not app.daily.legacy.get() and not app.daily.diagnostic.get()
            assert app.daily.key.get()=='F9' and not app.runner.active
            checks.append('toggle_default_click_not_hold_and_off')
            app.guide.show(3);app.guide.primary();root.update()
            assert not app.has_edits and app.guide.stage==4
            assert app.guide.stage==4 and app.daily.frame.winfo_ismapped()
            checks.append('saved_then_daily_no_recalibration')
            assert '刷新' in app.guide.hint.get() and not app.runner.active
            checks.append('daily_requires_selected_target')
            app.daily.key.set('鼠标侧键4');app.daily.changed()
            assert app.daily.current_options().key=='鼠标侧键4'
            assert not app.runner.active and not app.consent.get()
            checks.append('configurable_mouse_side_toggle_no_activation')
            app.daily.trigger.set('仅左键（腰射也会触发）');app.daily.changed()
            assert app.daily.current_options().trigger=='left' and '腰射' in app.daily.instructions.get()
            checks.append('left_only_mode_explicit_warning')
            app.window_values=[('test',{'handle':123,'pid':42,'size':[1920,1080]})]
            app.window_combo['values']=['test'];app.window_combo.current(0);app.select_window()
            app.consent.set(True);app.guide.refresh();root.update()
            assert app.daily.window_combo.current()==0
            calls=[]
            def fake_start(setting,target,consent):
                calls.append((setting,target,consent));app.runner.active=True;app.runner.cancel.clear()
                app.runner.message='已准备，尚未开启：到游戏按鼠标侧键4'
                app.runner.report.update(listening=True,enabled=False)
            app.runner.start=fake_start
            app.guide.primary();root.update()
            assert len(calls)==1 and app.runner.options==ToggleOptions('鼠标侧键4','left')
            assert not app.runner.snapshot()['enabled'] and '5秒' not in app.daily.banner.get()
            checks.append('prepare_listens_without_five_seconds_or_output')
            assert '监听' in app.start_button['text']
            checks.append('listening_distinct_from_enabled')
            app.runner.report.update(enabled=True,reason='OUTPUT',keys={'left':True,'right':False,'toggle':False,'foreground':True},attempted_events=2,accepted_events=2,accepted_counts=3)
            app.runner.message='已开启，正在下拉';app.status.set(app.runner.message);app.daily.refresh();root.update()
            assert '接收 2 次' in app.daily.details.get() and '不代表' in app.daily.details.get()
            checks.append('event_counts_are_not_game_acceptance')
            app.daily.diagnostic.set(True);app.daily.changed();assert not app.runner.active
            app.guide.primary();assert app.runner.options.diagnostic
            checks.append('diagnostic_requires_new_explicit_prepare')
            app.stop();app.save();app.guide.show(4)
            app.runner.report['keys']={}
            app.status.set('已保存 · 未准备');app.daily.refresh()
            for size in ('820x580','940x750'):
                root.geometry(size);root.update()
                for b in (app.start_button,app.guide.stop_button):
                    assert b.winfo_ismapped()
                    assert b.winfo_rooty()+b.winfo_height()<=root.winfo_rooty()+root.winfo_height()
            checks.append('daily_footer_visible_820x580')
            if os.environ.get('SIMPLE_SCREENSHOT'):
                from PIL import ImageGrab
                root.geometry('940x750');root.update()
                ImageGrab.grab(bbox=(root.winfo_rootx(),root.winfo_rooty(),root.winfo_rootx()+root.winfo_width(),root.winfo_rooty()+root.winfo_height())).save(str(Path(os.environ['SIMPLE_SCREENSHOT']).with_name('daily-toggle.png')))
            app.close(force=True);root=tk.Tk();app=Application(root,directory);root.update()
            assert app.guide.stage==4 and app.daily.key.get()=='鼠标侧键4'
            assert app.daily.current_options().trigger=='left' and not app.daily.diagnostic.get()
            assert not app.runner.active and app.target is None and not app.consent.get()
            checks.append('daily_restart_recovers_preferences_not_permission')
        except Exception:
            result['status']='FAIL';raise
        finally:
            try:app.close(force=True)
            except tk.TclError:pass
            result['checks'].extend(checks)
            Path(out).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
