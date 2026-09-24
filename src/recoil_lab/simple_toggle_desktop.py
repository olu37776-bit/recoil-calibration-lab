"""Standard Windows input backend for the explicitly opted-in toggle session."""
from __future__ import annotations
import ctypes as C
from ctypes import wintypes as W
from .simple_desktop import Desktop, Input, Mouse
from .simple_toggle import HOTKEYS, Keys

class ToggleDesktop(Desktop):
    def info(self,handle):
        # A minimized target can be selected but can never receive output.
        if not self.u.IsWindow(handle): raise ValueError('目标窗口已关闭，请刷新并重选')
        r=W.RECT();p=W.DWORD()
        if not self.u.GetClientRect(handle,C.byref(r)): raise ValueError('无法读取窗口尺寸')
        self.u.GetWindowThreadProcessId(handle,C.byref(p))
        return {'handle':int(handle),'pid':int(p.value),'size':[r.right-r.left,r.bottom-r.top]}
    def in_foreground(self,target):
        return not self.u.IsIconic(target['handle']) and int(self.u.GetForegroundWindow() or 0)==target['handle']
    def inspect(self,target,check_size=True):
        fresh=self.info(target['handle'])
        if fresh['pid']!=target['pid']: raise ValueError('目标进程已更换，请重新选择窗口')
        if check_size and (fresh['size']!=target['size'] or min(fresh['size'])<64):
            raise ValueError('目标窗口尺寸变化，请重新准备；没有发送移动')
        return fresh
    def sample(self,target,options):
        foreground=self.in_foreground(target)
        self.inspect(target,check_size=foreground)
        return Keys(left=self.down(1),right=self.down(2),toggle=self.down(HOTKEYS[options.key]),
                    foreground=foreground,reload=self.down(0x52),
                    changed=any(self.down(k) for k in (0x09,0x47,0x31,0x32,0x33,0x43,0x5A)),
                    emergency=self.down(0x77) or self.down(0x1B),
                    decrease=self.down(0x74),increase=self.down(0x75))
    def send(self,target,delta,options):
        if type(delta) is not int or not 0<delta<=32: raise ValueError('单次移动超过范围')
        keys=self.sample(target,options)
        if (not keys.foreground or not keys.left or (options.trigger=='both' and not keys.right) or
            keys.toggle or keys.reload or keys.changed or keys.emergency or keys.decrease or keys.increase):
            raise ValueError('发送前状态变化，已关闭；回目标窗口重新按启停键')
        C.set_last_error(0)
        event=Input(type=0,mouse=Mouse(0,delta,0,1,0,0))
        accepted=self.u.SendInput(1,C.byref(event),C.sizeof(Input))
        if accepted!=1:
            code=C.get_last_error()
            raise ValueError(f'Windows未接受输入（返回{accepted}，错误码{code}）。不是力度问题；不提权或绕过。')
