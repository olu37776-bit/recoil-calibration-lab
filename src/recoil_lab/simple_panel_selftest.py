"""Native two-page acceptance checks. Never generates real Windows input."""
from pathlib import Path
import json
import os
import tempfile
import tkinter as tk
from .simple_core import Setting
from .simple_toggle import ToggleRunner, ToggleSession, Keys

TARGET = {'handle': 42, 'pid': 99, 'size': [1920,1080]}


class TestRunner(ToggleRunner):
    """Same event/stop/handshake logic with a fake, non-threaded desktop."""
    def __init__(self):
        super().__init__(lambda: None)
        self.starts = 0
        self.backend = TestBackend()
        self.clock = 0.0
    def start(self, setting, target, consent):
        assert consent is True
        self.starts += 1
        self.cancel.clear();self.active=True
        self.session_id = str(self.starts)
        self.controller = ToggleSession(setting,self.options,self.step,self.shortcuts)
        self.report = self._empty_report();self.report['listening']=True
        self.message = self.controller.message
    def tick(self, **keys):
        self.pulse();self.clock += .01
        self.backend.keys = Keys(**keys)
        self._step_toggle(self.backend,TARGET,self.clock)
    def activate(self):
        self.tick();self.tick(toggle=True);self.tick()


class TestBackend:
    def __init__(self):
        self.keys = Keys()
        self.events = []
    def sample(self, target, options): return self.keys
    def send(self, target, delta, options): self.events.append(delta)


def self_test(out):
    from .simple_panel import PanelApplication
    result=json.loads(Path(out).read_text(encoding='utf-8'))
    checks=[]
    with tempfile.TemporaryDirectory() as directory:
        root=tk.Tk();runner=TestRunner()
        app=PanelApplication(root,directory,runner=runner,windows_provider=lambda:[('WARDOGS',TARGET)])
        root.update()
        try:
            app.pulse_once();assert app.mode=='home' and not runner.active
            checks.append('panel_no_config_no_output')
            app.new_config();root.update();app.pulse_once()
            assert runner.active and not runner.snapshot()['enabled'] and runner.starts==1
            assert not hasattr(app,'start_button') and not hasattr(app,'consent')
            checks.append('panel_auto_ready_no_prepare_no_checkbox')
            runner.activate();assert runner.controller.enabled
            for _ in range(10):runner.tick(left=True)
            assert runner.backend.events
            checks.append('panel_one_key_draft_uses_same_toggle_engine')
            runner.tick();runner.tick(increase=True);app.pulse_once()
            assert app.draft.current.rate==25 and app.numeric.get()=='25'
            assert runner.controller.setting.rate==25 and runner.starts==1
            assert app.draft.dirty and not app.store.items()
            checks.append('panel_shortcut_updates_draft_without_save_or_restart')
            app.more.invoke();assert app.draft.current.rate==30
            app.undo();assert app.draft.current.rate==25
            checks.append('panel_draft_manual_strength_and_undo')
            app.save_button.invoke();assert not app.draft.dirty and len(app.store.items())==1
            app.show_home();root.update();app.pulse_once()
            assert app.mode=='home' and runner.active and not runner.controller.enabled
            assert runner.shortcuts is False
            checks.append('panel_save_returns_selectable_preset_not_auto_on')
            runner.activate();assert runner.controller.enabled
            runner.tick(left=True);runner.tick(left=True)
            checks.append('panel_home_and_config_identical_single_key')
            app.show_config();root.update();app.pulse_once()
            app.numeric.set('abc');app.pulse_once();assert not runner.active and not app.save_config()
            checks.append('panel_invalid_number_disables_and_blocks_save')
            app.numeric.set('31');app.pulse_once();assert runner.active and not runner.controller.enabled
            app.fields['weight'].set('背包方案A');app.save_config();assert len(app.store.items())==2
            checks.append('panel_manual_weight_and_multiple_profiles')
            app.show_home();app.key.set('鼠标侧键4');app.pulse_once()
            assert runner.options.key=='鼠标侧键4' and not runner.controller.enabled
            checks.append('panel_change_hotkey_never_arms')
            runner.stop('模拟监听失败');app.pulse_once()
            assert '未就绪' in app.state.get() and not runner.active
            app.ready.retry();app.pulse_once();assert runner.active and not runner.controller.enabled
            checks.append('panel_stopped_listener_not_presented_as_ready')
            app.show_config();app.draft.copy_as('第二套');app.load_form();app.save_config()
            assert len(app.store.items())==3
            checks.append('panel_copy_preserves_previous_preset')
            app.show_home();app.pulse_once()
            runner.activate();app.disable();assert not runner.controller.enabled and runner.active
            checks.append('panel_off_keeps_listener_ready_for_one_key')
            app.windows_provider=lambda:[('WARDOGS',TARGET),('WARDOGS',dict(TARGET,handle=43))]
            app.next_scan=0;app.pulse_once();assert app.target is None and not runner.active
            checks.append('panel_ambiguous_window_no_output')
            app.windows_provider=lambda:[('WARDOGS',TARGET)];app.next_scan=0;app.pulse_once()
            app.show_config();app.save_config()
            for mode in ('home','config'):
                app._show(mode);root.geometry('760x560');root.update()
                for button in (app.stop_button,)+( (app.save_button,) if mode=='config' else ()):
                    assert button.winfo_ismapped()
                    assert root.winfo_rooty()<=button.winfo_rooty()
                    assert button.winfo_rooty()+button.winfo_height()<=root.winfo_rooty()+root.winfo_height()
                assert app.pages[mode].winfo_ismapped() and not app.pages['config' if mode=='home' else 'home'].winfo_ismapped()
            checks.append('panel_only_two_pages_footer_visible_760x560')
            if os.environ.get('SIMPLE_SCREENSHOT'):
                from PIL import ImageGrab
                folder=Path(os.environ['SIMPLE_SCREENSHOT']).parent
                # Capture a size that fits the visible runner desktop.
                root.geometry(f'{min(900,root.winfo_screenwidth()-60)}x{min(730,root.winfo_screenheight()-100)}+10+10')
                for mode,name in (('home','panel-home.png'),('config','panel-config.png')):
                    app._show(mode);app.pulse_once();root.update()
                    ImageGrab.grab(bbox=(root.winfo_rootx(),root.winfo_rooty(),root.winfo_rootx()+root.winfo_width(),root.winfo_rooty()+root.winfo_height())).save(str(folder/name))
            app.close(force=True)
            root=tk.Tk();runner=TestRunner();app=PanelApplication(root,directory,runner=runner,windows_provider=lambda:[('WARDOGS',TARGET)])
            root.update();app.pulse_once()
            assert app.mode=='home' and runner.active and not runner.controller.enabled
            assert app.key.get()=='鼠标侧键4' and not app.diagnostic.get()
            assert app.selected() and app.selected().conditions['notes']=='第二套'
            checks.append('panel_restart_restores_selection_auto_ready_but_off')
            assert not any(k in app.option_store.path.read_text(encoding='utf-8') for k in ('enabled','consent','handle','pid'))
            checks.append('panel_no_runtime_permission_in_preferences')
        except Exception:
            result['status']='FAIL'
            raise
        finally:
            try:app.close(force=True)
            except tk.TclError:pass
            result['checks'].extend(checks)
            result['default_entrypoint']='PanelApplication'
            Path(out).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
