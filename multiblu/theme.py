"""Windows theme colours and the Mica backdrop.

The app follows Windows' light/dark setting and accent colour.  Mica is applied
through DWM: the window is made layered with a colour key, and every pixel that
uses that key lets the system backdrop show through.  Only the header and outer
margins use the key; cards and the device list stay opaque.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass

import winreg

DEFAULT_ACCENT = "#3ED598"

PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
DWM_KEY = r"Software\Microsoft\Windows\DWM"
EXPLORER_ACCENT = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent"

DARK = {
    "bg": "#0B0C0F",
    "card": "#15171C",
    "hover": "#1C2027",
    "edge": "#22252D",
    "text": "#EDEEF2",
    "dim": "#767D8B",
    "faint": "#4A505C",
    "track": "#2A2E37",
    "knob": "#FFFFFF",
    "danger": "#F2777A",
}

LIGHT = {
    "bg": "#F3F3F3",
    "card": "#FFFFFF",
    "hover": "#F7F7F8",
    "edge": "#E1E3E7",
    "text": "#1B1C1F",
    "dim": "#5C626D",
    "faint": "#8B919C",
    "track": "#DDE0E5",
    "knob": "#FFFFFF",
    "danger": "#C42B1C",
}


@dataclass(frozen=True)
class Theme:
    dark: bool
    accent: str
    transparency: bool

    def state(self) -> tuple:
        return (self.dark, self.accent, self.transparency)

    def palette(self) -> dict:
        return palette_for(self.dark, self.accent)


def blend(a: str, b: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    ar, ag, ab = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
    br, bg, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
    return "#%02x%02x%02x" % (
        round(ar + (br - ar) * t),
        round(ag + (bg - ag) * t),
        round(ab + (bb - ab) * t),
    )


def _channel(value: int) -> float:
    value /= 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def luminance(colour: str) -> float:
    r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def contrast_ink(colour: str) -> str:
    """Black or white, whichever reads better on top of *colour*."""
    if contrast_ratio(colour, "#000000") >= contrast_ratio(colour, "#FFFFFF"):
        return "#000000"
    return "#FFFFFF"


def readable_accent(accent: str, backgrounds: tuple, ink: str,
                    minimum: float = 4.0) -> str:
    """Darken or lighten an accent until it is readable as text."""
    for step in range(0, 10):
        candidate = blend(accent, ink, step / 10.0)
        if all(contrast_ratio(candidate, bg) >= minimum for bg in backgrounds):
            return candidate
    return ink


def palette_for(dark: bool, accent: str) -> dict:
    palette = dict(DARK if dark else LIGHT)
    palette["accent"] = accent
    palette["accent_ink"] = contrast_ink(accent)
    palette["accent_fg"] = readable_accent(
        accent, (palette["bg"], palette["card"]), palette["text"])
    return palette


def abgr_to_hex(value: int | None) -> str | None:
    if value is None:
        return None
    return "#%02X%02X%02X" % (value & 0xFF, (value >> 8) & 0xFF,
                              (value >> 16) & 0xFF)


def _read_int(path: str, name: str, default):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            value, _kind = winreg.QueryValueEx(key, name)
        return int(value)
    except (OSError, TypeError, ValueError):
        return default


def read_theme() -> Theme:
    dark = _read_int(PERSONALIZE, "AppsUseLightTheme", 0) == 0
    transparency = _read_int(PERSONALIZE, "EnableTransparency", 1) != 0
    accent = None
    for path, name in ((DWM_KEY, "AccentColor"),
                       (EXPLORER_ACCENT, "AccentColorMenu")):
        value = _read_int(path, name, None)
        if value is not None:
            accent = abgr_to_hex(value)
            break
    return Theme(dark, accent or DEFAULT_ACCENT, transparency)


def mica_supported() -> bool:
    try:
        return sys.getwindowsversion().build >= 22000
    except Exception:
        return False


class _Margins(ctypes.Structure):
    _fields_ = [("left", ctypes.c_int), ("right", ctypes.c_int),
                ("top", ctypes.c_int), ("bottom", ctypes.c_int)]


def _hwnd(window) -> int:
    window.update_idletasks()
    user32 = ctypes.windll.user32
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    return int(user32.GetParent(window.winfo_id()) or 0)


def _set_int(hwnd: int, attribute: int, value: int) -> int:
    dwm = ctypes.windll.dwmapi
    dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD,
                                          ctypes.c_void_p, wintypes.DWORD]
    dwm.DwmSetWindowAttribute.restype = ctypes.c_long
    data = ctypes.c_int(value)
    return int(dwm.DwmSetWindowAttribute(
        hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data)))


def _dark_mode(hwnd: int, dark: bool) -> None:
    for attribute in (20, 19):
        if _set_int(hwnd, attribute, 1 if dark else 0) == 0:
            return


def _colorref(colour: str) -> int:
    r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return (b << 16) | (g << 8) | r


def style_titlebar(window, dark: bool, bg: str, edge: str, text: str) -> None:
    """Match the native caption to the current palette."""
    try:
        hwnd = _hwnd(window)
        if not hwnd:
            return
        _dark_mode(hwnd, dark)
        _set_int(hwnd, 34, _colorref(edge))     # DWMWA_BORDER_COLOR
        _set_int(hwnd, 35, _colorref(bg))       # DWMWA_CAPTION_COLOR
        _set_int(hwnd, 36, _colorref(text))     # DWMWA_TEXT_COLOR
    except Exception:
        pass


def apply_mica(window, dark: bool) -> bool:
    """Turn on the Windows 11 Mica backdrop.  Returns False if unavailable."""
    try:
        hwnd = _hwnd(window)
        if not hwnd:
            return False

        dwm = ctypes.windll.dwmapi
        dwm.DwmExtendFrameIntoClientArea.argtypes = [
            wintypes.HWND, ctypes.POINTER(_Margins)]
        dwm.DwmExtendFrameIntoClientArea.restype = ctypes.c_long
        margins = _Margins(-1, -1, -1, -1)
        if dwm.DwmExtendFrameIntoClientArea(
                hwnd, ctypes.byref(margins)) != 0:
            return False

        _dark_mode(hwnd, dark)
        build = sys.getwindowsversion().build
        enabled = False
        if build >= 22621:
            enabled = _set_int(hwnd, 38, 2) == 0    # DWMSBT_MAINWINDOW
        if not enabled:
            enabled = _set_int(hwnd, 1029, 1) == 0  # legacy Mica attribute
        return enabled
    except Exception:
        return False
