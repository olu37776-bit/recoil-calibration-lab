"""User-selected conditions; labels do not imply a recoil multiplier."""
from .contracts import CalibrationError


def weight_label(value='未记录') -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 32 or any(ord(c) < 32 for c in value):
        raise CalibrationError('负重标签需为1至32字；可选择轻装/中装/重装或自定义')
    return value.strip()
