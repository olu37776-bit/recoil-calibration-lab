"""Opt-in Windows desktop test backend. No game hooks, clicks, or evasion."""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import platform
import time

import numpy as np

from .contracts import CalibrationError

# Fixed widths also make the ABI layout testable on a non-Windows host.
class MOUSEINPUT(C.Structure):
    _fields_ = [('dx', C.c_int32), ('dy', C.c_int32), ('mouseData', C.c_uint32),
                ('dwFlags', C.c_uint32), ('time', C.c_uint32), ('dwExtraInfo', C.c_size_t)]

class KEYBDINPUT(C.Structure):
    _fields_ = [('wVk', C.c_uint16), ('wScan', C.c_uint16), ('dwFlags', C.c_uint32),
                ('time', C.c_uint32), ('dwExtraInfo', C.c_size_t)]

class HARDWAREINPUT(C.Structure):
    _fields_ = [('uMsg', C.c_uint32), ('wParamL', C.c_uint16), ('wParamH', C.c_uint16)]

class INPUT_UNION(C.Union):
    _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT), ('hi', HARDWAREINPUT)]

class INPUT(C.Structure):
    _anonymous_ = ('value',)
    _fields_ = [('type', C.c_uint32), ('value', INPUT_UNION)]


def dpi_awareness() -> None:
    if platform.system() == 'Windows':
        try:
            user = C.WinDLL('user32', use_last_error=True)
            user.SetProcessDpiAwarenessContext.argtypes = [C.c_void_p]
            user.SetProcessDpiAwarenessContext(C.c_void_p(-4))
        except (AttributeError, OSError):
            pass


class WindowsDesktop:
    def __init__(self):
        if platform.system() != 'Windows':
            raise CalibrationError('窗口采集和标准输入后端只在Windows上启用；离线流程仍可使用')
        dpi_awareness()
        self.user = C.WinDLL('user32', use_last_error=True)
        self.user.GetForegroundWindow.restype = W.HWND
        self.user.IsWindow.argtypes = [W.HWND]
        self.user.IsWindowVisible.argtypes = [W.HWND]
        self.user.IsIconic.argtypes = [W.HWND]
        self.user.GetWindowTextLengthW.argtypes = [W.HWND]
        self.user.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
        self.user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
        self.user.GetClientRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
        self.user.ClientToScreen.argtypes = [W.HWND, C.POINTER(W.POINT)]
        self.user.GetAsyncKeyState.argtypes = [C.c_int]
        self.user.GetAsyncKeyState.restype = C.c_short
        self.user.SendInput.argtypes = [C.c_uint, C.POINTER(INPUT), C.c_int]
        self.user.SendInput.restype = C.c_uint

    def down(self, key: int) -> bool:
        return bool(self.user.GetAsyncKeyState(key) & 0x8000)

    def interrupted(self) -> bool:
        # Commands are STOP signals, not inferred game state.
        return any(self.down(k) for k in (0x77, 0x1B, 0x09, 0x52, 0x47, 0x31,
                   0x32, 0x33, 0x43, 0x5A, 0x11, 0x10))

    def triggered(self, phase: str) -> bool:
        return self.down(0x76) and self.down(2) and (not self.down(1) if phase=='response' else self.down(1))

    def geometry(self, hwnd: int) -> tuple[int, int, int, int]:
        if not self.user.IsWindow(hwnd) or self.user.IsIconic(hwnd):
            raise CalibrationError('目标窗口不存在或已最小化')
        rect, point = W.RECT(), W.POINT()
        if not self.user.GetClientRect(hwnd, C.byref(rect)) or not self.user.ClientToScreen(hwnd, C.byref(point)):
            raise CalibrationError('无法读取目标窗口尺寸')
        w, h = rect.right-rect.left, rect.bottom-rect.top
        if w<64 or h<64 or w*h>12_000_000:
            raise CalibrationError('目标窗口尺寸无效或超过1200万像素')
        return point.x, point.y, w, h

    def pid(self, hwnd: int) -> int:
        value = W.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, C.byref(value))
        return value.value

    def check_window(self, hwnd: int, resolution: list[int], pid: int) -> None:
        if int(self.user.GetForegroundWindow() or 0) != hwnd:
            raise CalibrationError('焦点离开目标窗口，已停止')
        if self.pid(hwnd) != pid or list(self.geometry(hwnd)[2:]) != resolution:
            raise CalibrationError('窗口进程或尺寸变化，需重新选择/标定')
        if self.down(0x77) or self.down(0x1B):
            raise CalibrationError("F8/Esc急停")

    def check(self, hwnd: int, resolution: list[int], pid: int) -> None:
        self.check_window(hwnd, resolution, pid)
        if self.interrupted():
            raise CalibrationError('急停或换弹/切换/姿态指令：已停止，不自动恢复')

    def capture(self, hwnd: int, resolution: list[int], pid: int) -> np.ndarray:
        from PIL import ImageGrab
        self.check(hwnd, resolution, pid)
        x,y,w,h = self.geometry(hwnd)
        image = ImageGrab.grab(bbox=(x,y,x+w,y+h), all_screens=True).convert('L')
        self.check(hwnd, resolution, pid)
        result = np.asarray(image)
        if list(result.shape[::-1]) != resolution:
            raise CalibrationError('采集像素与窗口尺寸不一致；检查显示缩放')
        return result

    def capture_recognition(self, hwnd: int, resolution: list[int], pid: int) -> np.ndarray:
        """A fresh frame while action keys pause output, without cancelling the session."""
        from PIL import ImageGrab
        self.check_window(hwnd, resolution, pid)
        x,y,w,h = self.geometry(hwnd)
        result = np.asarray(ImageGrab.grab(bbox=(x,y,x+w,y+h), all_screens=True).convert('L'))
        self.check_window(hwnd, resolution, pid)
        if list(result.shape[::-1]) != resolution:
            raise CalibrationError('采集像素与窗口尺寸不一致；检查显示缩放')
        return result

    def move(self, dy: int, hwnd: int, resolution: list[int], pid: int, phase: str) -> None:
        if type(dy) is not int or abs(dy)>32:
            raise CalibrationError('单次输入超过32单位限制')
        self.check(hwnd, resolution, pid)
        if not self.triggered(phase):
            raise CalibrationError('释放F7、右键或开火键，已停止输入')
        if not dy: return
        event = INPUT(type=0, mi=MOUSEINPUT(0,dy,0,0x0001,0,0))
        if self.user.SendInput(1,C.byref(event),C.sizeof(INPUT)) != 1:
            raise CalibrationError('Windows拒绝了输入；不会提权或尝试绕过')

    def cue(self) -> None:
        """Optional system sound only; does not generate mouse or keyboard input."""
        import winsound
        winsound.PlaySound('SystemAsterisk', winsound.SND_ALIAS | winsound.SND_ASYNC)

    def windows(self) -> list[dict]:
        values = []
        callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        @callback_type
        def visit(hwnd, _):
            try:
                if self.user.IsWindowVisible(hwnd) and self.user.GetWindowTextLengthW(hwnd)>0:
                    title = C.create_unicode_buffer(512)
                    self.user.GetWindowTextW(hwnd,title,len(title))
                    values.append({'handle':int(hwnd),'title':title.value,'resolution':list(self.geometry(hwnd)[2:])})
            except CalibrationError: pass
            return True
        self.user.EnumWindows.argtypes = [callback_type, W.LPARAM]
        self.user.EnumWindows(visit,0)
        return values
