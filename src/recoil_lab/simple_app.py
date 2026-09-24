"""Native manual-tuning UI. Optional screenshots never drive live input."""
from __future__ import annotations
import argparse
from pathlib import Path
import json
import math
import os
import platform
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from .simple_core import VERSION, LABELS, Setting, Store, impact_summary
from .simple_quick import QuickRunner as Runner
from .simple_quick_ui import QuickControls
from .simple_desktop import Desktop
from .simple_tuning import (EditHistory, Preferences, read_setting, write_setting,
                            setting_caption, validate_catalog_setting)

CATALOG=Path(__file__).with_name('simple_catalog.json')
NONE='未装 / 未记录'

def load_catalog():
    if CATALOG.exists():return json.loads(CATALOG.read_text(encoding='utf-8'))
    # Source installs can reuse the curated catalog. Frozen builds include JSON.
    from .catalog import public_catalog
    return public_catalog()

class Application:
    def __init__(self,root,directory=None):
        self.root=root;root.title('RecoilLab 简易调教版 · '+VERSION)
        root.geometry(f'{min(940,root.winfo_screenwidth()-60)}x{min(860,root.winfo_screenheight()-60)}');root.minsize(800,580)
        self.catalog=load_catalog();self.store=Store(directory);self.runner=Runner(Desktop)
        self.preferences=Preferences(self.store.directory);self.history=None;self.has_edits=False;self.touched=False
        self.selection_label='';self.dirty_text=tk.StringVar(value='新配装 · 尚未保存')
        self.reference_text=tk.StringVar();self.condition_text=tk.StringVar()
        self.step=tk.StringVar(value='5');self.numeric=tk.StringVar(value='20')
        self.target=None;self.window_values=[];self.saved_values=[];self.silent=True
        self.fields={k:tk.StringVar(value='') for k in LABELS}
        self.rate=tk.DoubleVar(value=20);self.duration=tk.StringVar(value='2')
        self.consent=tk.BooleanVar(value=False);self.status=tk.StringVar(value='未启用 · 先选配装，再小步调节')
        self.saved=tk.StringVar();self.window=tk.StringVar();self.amount=tk.StringVar(value='20')
        style=ttk.Style(root);style.theme_use('clam')
        font=('Microsoft YaHei UI' if platform.system()=='Windows' else 'Noto Sans CJK SC',10)
        style.configure('.',font=font)
        style.configure('TFrame',background='#f3f5f7');style.configure('TLabel',background='#f3f5f7')
        style.configure('TLabelframe',background='#f3f5f7');style.configure('TLabelframe.Label',background='#f3f5f7')
        style.configure('Primary.TButton',padding=9,font=(font[0],11,'bold'));root.configure(background='#f3f5f7')
        from .simple_guide_ui import GuideView
        self.guide=GuideView(self,font)
        for key,var in self.fields.items():var.trace_add('write',lambda *_,k=key:self.field_changed(k))
        self.duration.trace_add('write',lambda *_:self.edited())
        root.protocol('WM_DELETE_WINDOW',self.close);root.bind('<Escape>',lambda e:self.stop())
        self.history=EditHistory(self.setting())
        self.silent=False;self.refresh_saved();self.refresh_edit_state()
        self.quick=QuickControls(self)
        self.timer=root.after(80,self.pulse)
        last_key=self.preferences.read()
        saved_settings=dict(self.store.items())
        if last_key in saved_settings:
            try:
                self.apply(saved_settings[last_key])
                self.saved_combo.current(next(i for i,(key,_) in enumerate(self.saved_values) if key==last_key))
                self.selection_label=self.saved.get()
                self.status.set('已恢复上次保存的配装；输出关闭，请重新选择窗口并确认。')
            except ValueError as exc:self.error(exc)
        elif self.preferences.warning:self.status.set(self.preferences.warning)
        self.guide.refresh()

    def combo(self,parent,key,label,values,row,col,editable=False):
        ttk.Label(parent,text=label,width=8).grid(row=row,column=col,sticky='w',pady=4)
        widget=ttk.Combobox(parent,textvariable=self.fields[key],values=values,state='normal' if editable else 'readonly',width=27)
        widget.grid(row=row,column=col+1,sticky='ew',padx=(0,12),pady=4);parent.columnconfigure(col+1,weight=1);self.combos[key]=widget
        if key=='weapon':widget.bind('<<ComboboxSelected>>',lambda _:self.weapon_changed())
    def toggle_more(self):
        self.more_open=not self.more_open
        if self.more_open:self.more.grid(row=3,column=0,columnspan=4,sticky='ew',pady=5)
        else:self.more.grid_remove()
    def weapon_changed(self):
        weapon=next((w for w in self.catalog['weapons'].values() if w['name']==self.fields['weapon'].get()),None)
        if not weapon:return
        for slot,ids in weapon['compatibility'].items():
            options=[NONE]+[self.catalog['parts'][i]['name'] for i in ids];self.combos[slot]['values']=options
            if self.fields[slot].get() not in options:self.fields[slot].set(NONE)
        options=[NONE]+[v['name'] for v in self.catalog['ammo'].values() if v['caliber']==weapon['caliber']]
        self.combos['ammo']['values']=options
        if self.fields['ammo'].get() not in options:self.fields['ammo'].set(NONE)
    def field_changed(self,key):
        if not self.silent:self.edited()
    def edited(self):
        if self.silent:return
        self.touched=True
        self.runner.stop('参数已修改，输出已停；试好后保存，再重新开始');self.status.set(self.runner.message)
        try:
            if self.history is not None:self.history.change(self.setting())
            self.refresh_edit_state()
        except (ValueError,tk.TclError):
            self.has_edits=True;self.dirty_text.set('有未保存修改 · 请先完成当前字段')
    def set_rate(self,value):
        self.rate.set(value);self.amount.set(f'{value:g}');self.numeric.set(f'{value:g}');self.edited()
    def slider(self,value):
        if not self.silent:self.set_rate(round(float(value)))
    def adjust(self,delta):self.set_rate(round(max(0,min(400,self.rate.get()+delta)),4))
    def setting(self):
        for key,combo in self.combos.items():
            if key!='weight' and self.fields[key].get() not in combo['values']:raise ValueError('请重新选择配装项目：'+key)
        return Setting({k:v.get().strip() for k,v in self.fields.items()},float(self.rate.get()),float(self.duration.get()))
    def label(self,s):
        return setting_caption(s)+' · '+s.key[:6]
    def refresh_saved(self):
        self.saved_values=self.store.items();self.saved_combo['values']=[self.label(s) for _,s in self.saved_values]
    def refresh_edit_state(self):
        current=self.setting();last=dict(self.store.items()).get(current.key)
        self.has_edits=last is None or current.record()!=last.record()
        self.dirty_text.set('有未保存修改' if self.has_edits else '当前参数已保存')
        c=current.conditions
        self.condition_text.set('当前实际条件：'+' / '.join(c[k] for k in ('weapon','sight','pose','weight'))+
                                '\n枪口：'+c['muzzle']+'；握把：'+c['underbarrel']+'；弹匣：'+c['magazine']+'；弹药：'+c['ammo'])
        if self.history is not None:
            self.reference_text.set(self.history.reference_text())
            self.undo_button.configure(state='normal' if self.history.previous else 'disabled')
            self.restore_button.configure(state='normal' if self.history.reference is not None else 'disabled')
    def step_changed(self,event=None):
        self.less_button.configure(text='压过头了  −'+self.step.get())
        self.more_button.configure(text='还往上飘  ＋'+self.step.get())
        if hasattr(self,'quick'):self.quick.options_changed()
    def pending_numeric(self):
        try:return float(self.numeric.get().strip())!=self.rate.get()
        except (ValueError,tk.TclError):return True
    def set_numeric(self):
        self.stop()
        try:
            value=float(self.numeric.get().strip())
            if not math.isfinite(value) or not 0<=value<=400:raise ValueError('力度请输入0～400的数值，原力度未改动')
            self.set_rate(value)
            return True
        except (ValueError,tk.TclError):
            self.error('力度请输入0～400的数值，原力度未改动');return False
    def undo_edit(self):
        self.stop()
        try:
            self.apply(self.history.undo(),reset_history=False)
            self.status.set('已撤销上次调节；输出关闭，核对后重新开始。')
        except ValueError as exc:self.error(exc)
    def remember_reference(self):
        self.stop()
        try:
            self.history.change(self.setting());self.history.remember_reference();self.refresh_edit_state()
            self.status.set('已记住本次手感；继续微调，随时恢复。长期保留仍需点保存这套。')
        except ValueError as exc:self.error(exc)
    def restore_reference(self):
        self.stop()
        try:
            self.apply(self.history.restore_reference(),reset_history=False)
            self.status.set('已恢复本次记住的值；未宣称通过游戏验证，输出仍关闭。')
        except ValueError as exc:self.error(exc)
    def remember_saved(self,s):
        try:self.preferences.remember(s)
        except OSError:self.status.set('配装已载入/保存，但记住上次选择失败；下次请手动选择。')
    def save(self):
        if hasattr(self,'quick'):self.quick.sync()
        if self.pending_numeric() and not self.set_numeric():return False
        try:
            self.runner.stop('已停止；配置保存中');s=self.setting();self.store.save(s);self.refresh_saved()
            self.saved_combo.current(next(i for i,(key,_) in enumerate(self.saved_values) if key==s.key))
            self.selection_label=self.saved.get();self.refresh_edit_state();self.touched=False
            self.status.set('已保存手动参数；下次打开会恢复这套，但不会自动启用。')
            self.remember_saved(s)
            return True
        except (ValueError,OSError) as e:self.error(e);return False
    def discard_pending(self):
        self.stop()
        if not ((self.has_edits and self.touched) or self.pending_numeric()):return True
        answer=messagebox.askyesnocancel('保留当前调节？','当前有未保存修改。要先保存吗？\n是：保存后继续；否：放弃修改；取消：留在当前页面。',parent=self.root)
        if answer is None:return False
        return self.save() if answer else True
    def apply(self,s,reset_history=True):
        self.runner.stop('已载入手动参数，尚未启用')
        validate_catalog_setting(s,self.catalog)
        self.silent=True
        try:
            self.fields['weapon'].set(s.conditions['weapon']);self.weapon_changed()
            for k,v in s.conditions.items():self.fields[k].set(v)
            self.rate.set(s.rate);self.amount.set(f'{s.rate:g}');self.numeric.set(f'{s.rate:g}');self.duration.set(f'{s.duration:g}')
        finally:self.silent=False
        if self.history is not None and reset_history:self.history.reset(s)
        self.consent.set(False);self.target=None;self.window.set('');self.refresh_edit_state();self.touched=self.has_edits
        self.status.set('已载入手动参数；重新核对窗口并确认后才可试用')
    def load_selected(self,event=None):
        i=self.saved_combo.current()
        if i<0:return
        selected=self.saved_values[i][1]
        if not self.discard_pending():self.saved.set(self.selection_label);return
        try:
            self.apply(selected);self.saved.set(self.label(selected));self.selection_label=self.saved.get()
            self.remember_saved(selected)
        except ValueError as e:self.error(e)
    def undo(self):
        try:
            current=self.setting();items=dict(self.store.items())
            if current.key not in items:raise ValueError('这套配装还没有保存值')
            last=items[current.key];selected=last if current.record()!=last.record() else self.store.previous(current.key)
            self.history.change(selected);self.apply(selected,reset_history=False)
            self.status.set('已恢复保存值；需要时重新试用，再保存')
        except ValueError as e:self.error(e)
    def export_path(self,path):
        self.stop()
        if self.pending_numeric() and not self.set_numeric():return
        write_setting(path,self.setting());self.status.set('已导出这套手动参数；不含截图、窗口或输入许可。备注也在文件中，分享前请检查。')
    def export_current(self):
        self.stop()
        path=filedialog.asksaveasfilename(parent=self.root,title='导出这套手动参数',defaultextension='.json',initialfile='RecoilLab-手动配置.json',filetypes=[('手动配置','*.json')])
        if not path:return
        try:self.export_path(path)
        except (ValueError,OSError) as exc:self.error(exc)
    def import_path(self,path):
        self.stop()
        setting=read_setting(path);validate_catalog_setting(setting,self.catalog)
        if not self.discard_pending():return False
        self.apply(setting);self.saved.set('');self.selection_label=''
        self.status.set('已导入为待核对草稿；未覆盖已保存配置，未启用输出。核对后点保存这套。')
        return True
    def import_current(self):
        self.stop()
        path=filedialog.askopenfilename(parent=self.root,title='导入一套手动配置',filetypes=[('手动配置','*.json')])
        if not path:return
        try:self.import_path(path)
        except (ValueError,OSError) as exc:self.error(exc)
    def refresh_windows(self):
        self.stop();self.target=None;self.window.set('')
        try:
            self.window_values=Desktop().windows()
            self.window_combo['values']=[f'{name} [{v["size"][0]}×{v["size"][1]} · {v["handle"]}]' for name,v in self.window_values]
            self.status.set('请选择测试窗口；不用手填显示器或游戏分辨率')
        except ValueError as e:self.error(e)
    def select_window(self,event=None):
        self.stop();i=self.window_combo.current();self.target=self.window_values[i][1] if i>=0 else None;self.status.set('目标已选好；开始后5秒内切回该窗口')
    def consent_changed(self):
        if not self.consent.get():self.stop()
    def start(self):
        if self.pending_numeric() and not self.set_numeric():return
        try:
            self.quick.prepare()
            self.runner.start(self.setting(),self.target,self.consent.get());self.status.set(self.runner.message)
        except (ValueError,OSError) as e:self.error(e)
    def stop(self):
        self.runner.stop()
        if hasattr(self,'quick'):self.quick.sync()
        self.status.set(self.runner.message)
    def pulse(self):
        self.quick.sync()
        message=self.runner.pulse()
        if self.runner.active or getattr(self,'was_active',False):self.status.set(message)
        self.was_active=self.runner.active
        self.guide.refresh()
        self.timer=self.root.after(80,self.pulse)
    def error(self,e):self.runner.stop();self.status.set(str(e))
    def open_feedback(self):self.stop();Feedback(self.root)
    def close(self,force=False):
        self.stop()
        if not force and not self.discard_pending():return
        self.runner.stop('已退出');self.root.after_cancel(self.timer);self.root.destroy()

class Feedback:
    """Single user-selected image in RAM, explicit manual impact annotations."""
    def __init__(self,parent):
        self.win=tk.Toplevel(parent);self.win.title('弹着截图 · 只看结果，不实时采集');self.win.geometry('940x650')
        self.image=None;self.photo=None;self.points=[];self.aim=None;self.factor=1
        toolbar=ttk.Frame(self.win,padding=8);toolbar.pack(fill='x')
        ttk.Button(toolbar,text='打开截图',command=self.load).pack(side='left')
        ttk.Button(toolbar,text='粘贴截图',command=self.paste).pack(side='left',padx=5)
        ttk.Button(toolbar,text='撤销最后一个',command=self.undo).pack(side='left',padx=5)
        ttk.Button(toolbar,text='重新标记',command=self.reset).pack(side='left')
        ttk.Label(self.win,text='第一下：点墙上原来的瞄准位置。后面：点可见弹孔。不是点当前准星。',padding=8).pack(anchor='w')
        self.canvas=tk.Canvas(self.win,background='#202b38',highlightthickness=0);self.canvas.pack(fill='both',expand=True,padx=8)
        self.canvas.bind('<Button-1>',self.click);self.canvas.bind('<Configure>',lambda e:self.draw())
        self.text=tk.StringVar(value='可导入原始截图；图片不自动保存、不上传。');ttk.Label(self.win,textvariable=self.text,wraplength=900,padding=10).pack(fill='x')
    def set_image(self,image):
        if image.width*image.height>12_000_000:raise ValueError('截图超过1200万像素')
        self.image=image.convert('RGB').copy();self.points=[];self.aim=None;self.draw();self.text.set('先点原始瞄准位置，再点弹孔。呼吸、散布和弹孔重叠仍可能影响结果。')
    def load(self):
        path=filedialog.askopenfilename(parent=self.win,filetypes=[('截图','*.png *.jpg *.jpeg *.webp')])
        if not path:return
        try:
            from PIL import Image
            if Path(path).stat().st_size>20_000_000:raise ValueError('图片文件过大')
            with Image.open(path) as im:self.set_image(im)
        except Exception as e:self.text.set('无法读取截图：'+str(e))
    def paste(self):
        try:
            from PIL import ImageGrab,Image
            im=ImageGrab.grabclipboard()
            if not isinstance(im,Image.Image):raise ValueError('剪贴板里不是图片，请先复制截图')
            self.set_image(im)
        except Exception as e:self.text.set(str(e))
    def draw(self):
        if self.image is None:return
        from PIL import ImageTk,Image
        w=max(1,self.canvas.winfo_width());h=max(1,self.canvas.winfo_height());self.factor=min(w/self.image.width,h/self.image.height,1.)
        size=(max(1,int(self.image.width*self.factor)),max(1,int(self.image.height*self.factor)))
        self.photo=ImageTk.PhotoImage(self.image.resize(size,Image.Resampling.LANCZOS));self.canvas.delete('all');self.canvas.create_image(0,0,anchor='nw',image=self.photo)
        for p,color in ([(self.aim,'#49dc94')] if self.aim is not None else [])+[(p,'#ffbb50') for p in self.points]:
            x,y=[v*self.factor for v in p];self.canvas.create_oval(x-4,y-4,x+4,y+4,outline=color,width=2)
    def click(self,event):
        if self.image is None:return
        p=(event.x/self.factor,event.y/self.factor)
        if not 0<=p[0]<self.image.width or not 0<=p[1]<self.image.height:return
        if self.aim is None:self.aim=p
        elif len(self.points)<1000:self.points.append(p)
        self.draw();self.text.set(impact_summary(self.aim,self.points))
    def reset(self):self.aim=None;self.points=[];self.draw();self.text.set('请重新点原始瞄准位置')
    def undo(self):
        if self.points:self.points.pop()
        else:self.aim=None
        self.draw();self.text.set(impact_summary(self.aim,self.points))

def self_test(out):
    """Real native GUI and persistence; no physical input or game acceptance claim."""
    from PIL import Image
    result={'status':'FAIL','version':VERSION,'physical_input_tested':False,'game_tested':False}
    with tempfile.TemporaryDirectory() as directory:
        root=tk.Tk();app=Application(root,directory);root.update()
        try:
            assert app.rate.get()==20 and not app.consent.get() and not app.runner.active
            app.adjust(5);assert app.setting().rate==25
            app.save();app.adjust(5);app.save();assert app.setting().rate==30
            app.undo();assert app.setting().rate==25 and app.target is None and not app.consent.get()
            app.remember_reference();app.step.set('1');app.step_changed();app.more_button.invoke();assert app.setting().rate==26
            app.undo_button.invoke();assert app.setting().rate==25
            app.adjust(10);app.restore_reference();assert app.setting().rate==25
            app.numeric.set('30.5');app.set_numeric();assert app.setting().rate==30.5
            app.numeric.set('31');app.set_numeric();assert app.setting().rate==31
            app.numeric.set('nan');app.set_numeric();assert app.setting().rate==31
            assert app.save() is False
            app.numeric.set('31')
            app.save();export=Path(directory)/'portable.json';app.export_path(export)
            original=app.setting();app.adjust(1)
            from unittest.mock import patch
            with patch.object(messagebox,'askyesnocancel',return_value=None):
                assert app.import_path(export) is False and app.setting().rate==32
            with patch.object(messagebox,'askyesnocancel',return_value=False):
                assert app.import_path(export) is True and app.setting().rate==31
            assert app.target is None and not app.consent.get() and not app.runner.active
            corrupt=Path(directory)/'bad.json';corrupt.write_text('{bad',encoding='utf-8')
            try:app.import_path(corrupt)
            except ValueError:pass
            else:raise AssertionError('invalid import was accepted')
            assert app.setting().record()==original.record()
            app.save()
            app.toggle_more();root.update();app.fields['weapon'].set('M249 轻机枪');app.weapon_changed();app.fields['weight'].set('自定义25公斤');app.save();assert len(app.store.items())==2
            f=Feedback(root);root.update();f.set_image(Image.new('RGB',(2560,1440),'#eeeeee'));f.aim=(50,50);f.points=[(50,30)]
            assert '纵向 -20.0' in impact_summary(f.aim,f.points);f.draw();root.update();f.win.destroy()
            if platform.system()=='Windows':
                import ctypes
                from .simple_desktop import Input
                desktop=Desktop();assert len(desktop.windows())>0;assert ctypes.sizeof(Input)==40
            if os.environ.get('SIMPLE_SCREENSHOT'):
                from PIL import ImageGrab
                app.toggle_more();root.update()
                ImageGrab.grab(bbox=(root.winfo_rootx(),root.winfo_rooty(),root.winfo_rootx()+root.winfo_width(),root.winfo_rooty()+root.winfo_height())).save(os.environ['SIMPLE_SCREENSHOT'])
            app.close(force=True);root=tk.Tk();app=Application(root,directory);root.update()
            assert len(app.store.items())==2 and not app.runner.active and not app.consent.get()
            assert app.fields['weapon'].get()=='M249 轻机枪' and app.target is None and not app.window.get()
            root.geometry('820x580');root.update()
            assert app.start_button.winfo_rooty()>=root.winfo_rooty()
            assert app.start_button.winfo_rooty()+app.start_button.winfo_height()<=root.winfo_rooty()+root.winfo_height()
            result.update(status='PASS',checks=['native_tk_window','manual_adjust','save','previous_value','weapon_compatibility','manual_weight','2560x1440_feedback','restart_without_permission','fine_step_1','undo_edit','manual_reference_restore','numeric_validation','portable_export_import','cancel_unsaved_discard','bad_import_preserves_draft','restore_last_saved_without_target','sticky_start_at_820x580','invalid_pending_number_blocks_save'])
        finally:
            try:app.close(force=True)
            except tk.TclError:pass
            Path(out).parent.mkdir(parents=True,exist_ok=True);Path(out).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    p=argparse.ArgumentParser();p.add_argument('--self-test');args=p.parse_args()
    if args.self_test:
        self_test(args.self_test)
        from .simple_quick_ui import self_test as quick_test
        quick_test(args.self_test)
        from .simple_guide_ui import self_test as guide_test
        guide_test(args.self_test)
        return
    try:
        if platform.system()=='Windows':Desktop()
        root=tk.Tk();Application(root);root.mainloop()
    except Exception as e:
        try:messagebox.showerror('RecoilLab 启动失败',str(e)+'\n未启用任何输入。')
        except Exception:pass
        raise

if __name__=='__main__':main()
