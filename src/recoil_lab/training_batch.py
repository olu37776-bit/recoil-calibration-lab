"""A training-only desktop facade: any attempted movement is a hard failure."""
from .contracts import CalibrationError


class NoMotionDesktop:
    def __init__(self, desktop):
        self.desktop = desktop

    def check_window(self, *args):
        return self.desktop.check_window(*args)

    def check(self, *args):
        return self.desktop.check(*args)

    def down(self, key):
        return self.desktop.down(key)

    def triggered(self, phase):
        if phase != 'train':
            raise CalibrationError('批量入口仅允许未补偿训练')
        return self.desktop.triggered(phase)

    def interrupted(self):
        return self.desktop.interrupted()

    def capture(self, *args):
        return self.desktop.capture(*args)

    def move(self, *args):
        raise CalibrationError('批量训练禁止发送任何鼠标移动')
