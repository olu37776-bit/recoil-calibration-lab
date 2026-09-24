"""Windows standard input only. No live capture, hooks, clicks or evasion."""
from __future__ import annotations
import ctypes as C
from ctypes import wintypes as W
import platform

class Mouse(C.Structure):
    _fields_=[('dx',C.c_int32),('dy',C.c_int32),('mouseData',C.c_uint32),('dwFlags',C.c_uint32),('time',C.c_uint32),('extra',C.c_size_t)]
class Keyboard(C.Structure):
    _fields_=[('key',C.c_uint16),('scan',C.c_uint16),('flags',C.c_uint32),('time',C.c_uint32),('extra',C.c_size_t)]
class Hardware(C.Structure):
    _fields_=[('msg',C.c_uint32),('low',C.c_uint16),('high',C.c_uint16)]
class Union(C.Union):
    _fields_=[('mouse',Mouse),('keyboard',Keyboard),('hardware',Hardware)]
class Input(C.Structure):
    _anonymous_=('value',)
    _fields_=[('type',C.c_uint32),('value',Union)]

class Desktop:
    def __init__(self):
        if platform.system()!='Windows': raise ValueError('真实输出仅在Windows可用；其他系统可查看和调节配置')
        self.u=C.WinDLL('user32',use_last_error=True); self.target=None
        try:
            self.u.SetProcessDpiAwarenessContext.argtypes=[C.c_void_p]
            self.u.SetProcessDpiAwarenessContext(C.c_void_p(-4))
        except (AttributeError,OSError): pass
        self.u.GetForegroundWindow.restype=W.HWND
        for name in ('IsWindow','IsWindowVisible','IsIconic','GetWindowTextLengthW'):
            getattr(self.u,name).argtypes=[W.HWND]
        self.u.GetWindowTextW.argtypes=[W.HWND,W.LPWSTR,C.c_int]
        self.u.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)]
        self.u.GetClientRect.argtypes=[W.HWND,C.POINTER(W.RECT)]
        self.u.GetAsyncKeyState.argtypes=[C.c_int];self.u.GetAsyncKeyState.restype=C.c_short
        self.u.SendInput.argtypes=[C.c_uint,C.POINTER(Input),C.c_int];self.u.SendInput.restype=C.c_uint
    def down(self,k): return bool(self.u.GetAsyncKeyState(k)&0x8000)
    def keys(self): return self.down(1),self.down(2),self.down(0x76)
    def info(self,handle):
        if not self.u.IsWindow(handle) or self.u.IsIconic(handle): raise ValueError('窗口关闭或已最小化，请重新选择')
        r=W.RECT();p=W.DWORD()
        if not self.u.GetClientRect(handle,C.byref(r)): raise ValueError('无法读取窗口尺寸')
        self.u.GetWindowThreadProcessId(handle,C.byref(p))
        return {'handle':int(handle),'pid':int(p.value),'size':[r.right-r.left,r.bottom-r.top]}
    def check(self,target,foreground=True):
        current=self.info(target['handle'])
        if current['pid']!=target['pid'] or (foreground and current['size']!=target['size']):
            raise ValueError('窗口或尺寸变化；已停止，请刷新并重选窗口')
        if self.down(0x77) or self.down(0x1B): raise ValueError('F8 / Esc 已急停')
        if foreground:
            if int(self.u.GetForegroundWindow() or 0)!=target['handle']: raise ValueError('已切出目标窗口，已停止；调整好后重新开始')
            if any(self.down(k) for k in (0x09,0x52,0x47,0x31,0x32,0x33,0x43,0x5A)):
                raise ValueError('换弹、背包、切枪或姿态切换：已停止；重新选择条件后再开始')
        self.target=target
    def acquire(self,target):
        fresh=self.info(target['handle'])
        if fresh['pid']!=target['pid']:raise ValueError('目标进程变化，请重新选择')
        self.check(fresh)
        return fresh
    def move(self,delta):
        if type(delta) is not int or not 0<=delta<=32: raise ValueError('移动范围无效')
        if self.target is None: raise ValueError('未选择窗口')
        self.check(self.target)
        if not all(self.keys()): raise ValueError('已释放使能，停止输出')
        if delta:
            event=Input(type=0,mouse=Mouse(0,delta,0,1,0,0))
            if self.u.SendInput(1,C.byref(event),C.sizeof(Input))!=1:
                raise ValueError('Windows拒绝输入；不提权、不绕过。请停止测试')
    def windows(self):
        values=[];callback=C.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
        @callback
        def visit(handle,_):
            try:
                if self.u.IsWindowVisible(handle) and self.u.GetWindowTextLengthW(handle)>0:
                    value=self.info(handle)
                    if min(value['size'])<64:return True
                    title=C.create_unicode_buffer(512);self.u.GetWindowTextW(handle,title,len(title))
                    values.append((title.value,value))
            except ValueError:pass
            return True
        self.u.EnumWindows.argtypes=[callback,W.LPARAM]
        self.u.EnumWindows(visit,0)
        return values
