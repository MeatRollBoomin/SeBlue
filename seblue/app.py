"""Seblue's window.

One list. Flip the switch next to a pair of headphones and they start hearing
whatever this machine is playing. Nothing else to set up.

Every fixed pixel size goes through px(), because Tk sizes fonts in points (which
follow the display's DPI) but takes widget dimensions in raw pixels (which do
not). Without that the layout falls apart on a scaled display.
"""

from __future__ import annotations

import ctypes
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from PIL import Image
import pystray
from pystray import Menu, MenuItem
from tkinter_icons import FontAwesomeIcon

try:
    import miniaudio
    _MINIAUDIO_IMPORT_ERROR = ""
except ImportError as exc:
    miniaudio = None
    _MINIAUDIO_IMPORT_ERROR = str(exc)

from . import endpoints as ep
from . import theme as th
from .engine import Engine
from .theme import blend as _blend

_PALETTE = th.palette_for(True, th.DEFAULT_ACCENT)
BG = _PALETTE["bg"]
CARD = _PALETTE["card"]
HOVER = _PALETTE["hover"]
EDGE = _PALETTE["edge"]
TEXT = _PALETTE["text"]
DIM = _PALETTE["dim"]
FAINT = _PALETTE["faint"]
ACCENT = _PALETTE["accent"]
ACCENT_FG = _PALETTE["accent_fg"]
ACCENT_INK = _PALETTE["accent_ink"]
TRACK = _PALETTE["track"]
KNOB = _PALETTE["knob"]
DANGER = _PALETTE["danger"]

GLASS_KEYS = {True: "#010203", False: "#F2F2F3"}
MAGIC = GLASS_KEYS[True]
SURFACE = BG

UI = "Segoe UI"
APP_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home()))
SETTINGS = APP_DATA / "Seblue" / "settings.json"
APP_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
TEST_SOUND = APP_ROOT / "assets" / "Sony-DTS-Sound.mp3"
APP_ICON_ICO = APP_ROOT / "assets" / "seblue.ico"
APP_ICON_PNG = APP_ROOT / "assets" / "seblue.png"
SCAN_MS = 1500
MAX_DELAY = 0.30        # seconds of hand-tuned sync nudge per device

SCALE = 1.0
_DEVICE_ICONS = {}


def _device_info(device_name: str) -> tuple[str, str]:
    """Return an icon and a conservative type label from the friendly name."""
    name = device_name.casefold()
    if any(word in name for word in ("headphone", "headset", "earbud", "airpod")):
        return "headphones", "Headphones"
    if any(word in name for word in ("phone", "mobile", "iphone", "ipad", "tablet",
                                     "pixel", "galaxy")):
        return "mobile-screen-button", "Mobile device"
    if any(word in name for word in ("laptop", "notebook", "macbook", "pc")):
        return "laptop", "Laptop"
    return "volume-high", "Audio device"


def _fontawesome_image(icon_name: str, size: int, color: str):
    key = (icon_name, color, size)
    image = _DEVICE_ICONS.get(key)
    if image is None:
        image = FontAwesomeIcon(icon_name, size=size, color=color).image
        _DEVICE_ICONS[key] = image
    return image


def _image_with_left_gap(master, image, gap: int):
    """Add transparent space before an icon without indenting button text."""
    padded = tk.PhotoImage(master=master, width=image.width() + gap,
                           height=image.height())
    padded.tk.call(str(padded), "copy", str(image), "-to", gap, 0)
    return padded


def _make_device_icon(master, device_name: str):
    """Create a themed Font Awesome icon for the endpoint."""
    size = px(20)
    icon_name, _device_type = _device_info(device_name)
    image = _fontawesome_image(icon_name, size, ACCENT_FG)
    return tk.Label(master, image=image, bg=CARD, bd=0)


def _set_palette(theme: th.Theme) -> None:
    palette = theme.palette()
    for field in ("bg", "card", "hover", "edge", "text", "dim", "faint",
                  "track", "knob", "danger"):
        globals()[field.upper()] = palette[field]
    globals()["ACCENT"] = palette["accent"]
    globals()["ACCENT_FG"] = palette["accent_fg"]
    globals()["ACCENT_INK"] = palette["accent_ink"]


def px(value: float) -> int:
    return max(1, round(value * SCALE))


def _enable_dpi() -> None:
    """Render at the display's real pixel density instead of being upscaled."""
    global SCALE
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    try:
        SCALE = ctypes.windll.user32.GetDpiForSystem() / 96.0
    except Exception:
        SCALE = 1.0


class Tooltip:
    """Small delayed tooltip for a control or icon."""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self._job = None
        self._window = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        widget.bind("<Destroy>", self._destroyed, add="+")

    def _schedule(self, _event=None) -> None:
        self._cancel_job()
        self._job = self.widget.after(450, self._show)

    def _show(self) -> None:
        self._job = None
        if not self.widget.winfo_exists():
            return
        message = self.text() if callable(self.text) else self.text
        if not message:
            return
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.attributes("-topmost", True)
        tip.configure(bg=SURFACE)
        if SURFACE == MAGIC:
            tip.wm_attributes("-transparentcolor", MAGIC)
        panel = RoundedFrame(tip, fill=CARD, border=EDGE, corner_bg=SURFACE,
                             radius=px(8))
        panel.pack()
        tk.Label(panel, text=message, bg=CARD, fg=TEXT, font=(UI, 8),
                 justify="left", wraplength=px(280), padx=px(8), pady=px(5),
                 bd=0).pack(padx=px(4), pady=px(2))
        tip.update_idletasks()
        x = self.widget.winfo_pointerx() + px(12)
        y = self.widget.winfo_pointery() + px(18)
        x = min(x, tip.winfo_screenwidth() - tip.winfo_width() - px(8))
        y = min(y, tip.winfo_screenheight() - tip.winfo_height() - px(8))
        tip.wm_geometry("+%d+%d" % (max(0, x), max(0, y)))
        self._window = tip

    def _cancel_job(self) -> None:
        if self._job is not None:
            try:
                self.widget.after_cancel(self._job)
            except Exception:
                pass
            self._job = None

    def _hide(self, _event=None) -> None:
        self._cancel_job()
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None

    def _destroyed(self, event) -> None:
        if event.widget is self.widget:
            self._hide()


class RoundedFrame(tk.Frame):
    """A regular Tk frame with a rounded, antialiased-looking card surface."""

    def __init__(self, master, *, fill=CARD, border=EDGE, corner_bg=BG,
                 radius=10, **kwargs):
        super().__init__(master, bg=corner_bg, bd=0, highlightthickness=0, **kwargs)
        self._fill = fill
        self._border = border
        self._corner_bg = corner_bg
        self._radius = radius
        self._surface = tk.Canvas(self, bg=corner_bg, bd=0,
                                  highlightthickness=0, takefocus=False)
        self._surface.place(x=0, y=0, relwidth=1, relheight=1)
        self.bind("<Configure>", self._draw_surface, add="+")

    def set_fill(self, fill: str) -> None:
        self._fill = fill
        self._draw_surface()

    def set_border(self, border: str) -> None:
        self._border = border
        self._draw_surface()

    def _shape(self, x0, y0, x1, y1, radius, color) -> None:
        canvas = self._surface
        radius = max(0, min(radius, (x1 - x0) // 2, (y1 - y0) // 2))
        if radius == 0:
            canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline="")
            return
        canvas.create_rectangle(x0 + radius, y0, x1 - radius, y1,
                                fill=color, outline="")
        canvas.create_rectangle(x0, y0 + radius, x1, y1 - radius,
                                fill=color, outline="")
        for x, y in ((x0, y0), (x1 - 2 * radius, y0),
                     (x0, y1 - 2 * radius), (x1 - 2 * radius, y1 - 2 * radius)):
            canvas.create_oval(x, y, x + 2 * radius, y + 2 * radius,
                               fill=color, outline="")

    def _draw_surface(self, _event=None) -> None:
        if not self.winfo_exists():
            return
        width, height = self.winfo_width(), self.winfo_height()
        self._surface.configure(bg=self._corner_bg)
        self._surface.delete("all")
        if width < 3 or height < 3:
            return
        radius = min(self._radius, width // 2, height // 2)
        self._shape(0, 0, width - 1, height - 1, radius, self._border)
        self._shape(1, 1, width - 2, height - 2, max(0, radius - 1), self._fill)


class Toggle(tk.Canvas):
    """A pill switch that animates between off and on."""

    def __init__(self, master, command=None, bg=None):
        if bg is None:
            bg = CARD
        self.w, self.h, self.pad = px(44), px(24), px(3)
        super().__init__(master, width=self.w, height=self.h, bg=bg,
                         highlightthickness=2, highlightbackground=bg,
                         highlightcolor=ACCENT, bd=0, cursor="hand2",
                         takefocus=True)
        self.command = command
        self.on = False
        self._t = 0.0
        self._job = None
        self.bind("<Button-1>", self._clicked)
        self.bind("<space>", self._key_clicked)
        self.bind("<Return>", self._key_clicked)
        self._render()

    def set(self, on: bool, animate: bool = True) -> None:
        if on == self.on:
            return
        self.on = on
        if animate:
            self._animate()
        else:
            self._t = 1.0 if on else 0.0
            self._render()

    def _clicked(self, _event=None) -> str:
        self.set(not self.on)
        if self.command:
            self.command(self.on)
        return "break"

    def _key_clicked(self, event) -> str:
        return self._clicked(event)

    def _animate(self) -> None:
        if self._job:
            self.after_cancel(self._job)
        target = 1.0 if self.on else 0.0
        step = 0.18 if self.on else -0.18

        def tick():
            self._t = max(0.0, min(1.0, self._t + step))
            self._render()
            self._job = self.after(12, tick) if self._t != target else None

        tick()

    def destroy(self) -> None:
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        super().destroy()

    def _render(self) -> None:
        self.delete("all")
        r = (self.h - 2 * self.pad) / 2
        colour = _blend(TRACK, ACCENT, self._t)
        y0, y1 = self.pad, self.h - self.pad
        self.create_oval(self.pad, y0, self.pad + 2 * r, y1, fill=colour, outline="")
        self.create_oval(self.w - self.pad - 2 * r, y0, self.w - self.pad, y1,
                         fill=colour, outline="")
        self.create_rectangle(self.pad + r, y0, self.w - self.pad - r, y1,
                              fill=colour, outline="")
        kr = r - px(2)
        cx = self.pad + r + self._t * (self.w - 2 * self.pad - 2 * r)
        cy = self.h / 2
        self.create_oval(cx - kr, cy - kr, cx + kr, cy + kr, fill=KNOB, outline="")


class Slider(tk.Canvas):
    """Thin volume slider, grabbed anywhere along its length."""

    def __init__(self, master, command=None, bg=None):
        if bg is None:
            bg = CARD
        self.h, self.knob = px(20), px(6)
        super().__init__(master, width=px(150), height=self.h, bg=bg,
                         highlightthickness=1, highlightbackground=bg,
                         highlightcolor=ACCENT, bd=0, cursor="hand2",
                         takefocus=True)
        self.command = command
        self.value = 1.0
        self.enabled = True
        self._span = px(150)
        self.bind("<Button-1>", self._drag)
        self.bind("<B1-Motion>", self._drag)
        for key in ("Left", "Down", "Right", "Up", "Home", "End",
                    "Prior", "Next"):
            self.bind("<KeyPress-%s>" % key, self._keyboard_adjust)
        self.bind("<Configure>", self._resized)
        self._render()

    def set(self, value: float) -> None:
        self.value = max(0.0, min(1.0, value))
        self._render()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)
        self.configure(cursor="hand2" if self.enabled else "arrow")
        self.configure(takefocus=self.enabled)
        self._render()

    def _resized(self, event) -> None:
        self._span = event.width
        self._render()

    def _drag(self, event) -> None:
        if not self.enabled:
            return
        self.focus_set()
        usable = max(1, self._span - 2 * self.knob)
        self.value = max(0.0, min(1.0, (event.x - self.knob) / usable))
        self._render()
        if self.command:
            self.command(self.value)

    def _keyboard_adjust(self, event):
        if not self.enabled:
            return "break"
        if event.keysym in ("Left", "Down"):
            value = self.value - 0.02
        elif event.keysym in ("Right", "Up"):
            value = self.value + 0.02
        elif event.keysym == "Prior":
            value = self.value + 0.10
        elif event.keysym == "Next":
            value = self.value - 0.10
        elif event.keysym == "Home":
            value = 0.0
        else:
            value = 1.0
        self.set(value)
        if self.command:
            self.command(self.value)
        return "break"

    def _render(self) -> None:
        self.delete("all")
        y = self.h / 2
        x0, x1 = self.knob, max(self.knob + 1, self._span - self.knob)
        track = TRACK if self.enabled else EDGE
        value_color = ACCENT if self.enabled else FAINT
        knob_color = KNOB if self.enabled else DIM
        self.create_line(x0, y, x1, y, fill=track, width=px(4), capstyle=tk.ROUND)
        cx = x0 + self.value * (x1 - x0)
        if cx > x0:
            self.create_line(x0, y, cx, y, fill=value_color,
                             width=px(4), capstyle=tk.ROUND)
        self.create_oval(cx - self.knob, y - self.knob, cx + self.knob, y + self.knob,
                         fill=knob_color, outline="")


class QualityIndicator(tk.Canvas):
    """Four bars showing recent playback stability for an output device."""

    def __init__(self, master):
        self.width, self.height = px(18), px(14)
        super().__init__(master, width=self.width, height=self.height,
                         bg=CARD, highlightthickness=0, bd=0)
        self.level = None
        self._render()

    def set_level(self, level: int | None) -> None:
        self.level = None if level is None else max(0, min(4, level))
        self._render()

    def _render(self) -> None:
        self.delete("all")
        heights = (px(3), px(5), px(8), px(11))
        bar_width, gap = px(3), px(1)
        if self.level is None or self.level == 0:
            active_color = EDGE
        elif self.level == 1:
            active_color = "#EF4444"
        elif self.level == 2:
            active_color = "#F59E0B"
        else:
            active_color = "#22C55E"

        baseline = self.height - px(1)
        for index, height in enumerate(heights):
            x0 = px(1) + index * (bar_width + gap)
            color = active_color if self.level is not None and index < self.level else EDGE
            self.create_rectangle(x0, baseline - height, x0 + bar_width,
                                  baseline, fill=color, outline="")


class DeviceRow(RoundedFrame):
    """One output device: name, on/off switch, and volume once it is on."""

    def __init__(self, master, app, device):
        super().__init__(master, fill=CARD, border=EDGE, corner_bg=SURFACE,
                         radius=px(10))
        self.app = app
        self.device = device

        head = tk.Frame(self, bg=CARD)
        head.pack(fill="x", padx=px(14), pady=(px(10), 0))

        self.device_icon = _make_device_icon(head, device.name)
        if self.device_icon is not None:
            self.device_icon.pack(side="left", padx=(0, px(10)))

        labels = tk.Frame(head, bg=CARD)
        labels.pack(side="left", fill="x", expand=True)
        name_row = tk.Frame(labels, bg=CARD)
        name_row.pack(fill="x")
        self.name = tk.Label(name_row, text=app._device_name(device), bg=CARD, fg=TEXT,
                             font=(UI, 10), anchor="w", justify="left",
                             wraplength=px(240))
        self.name.pack(side="left", anchor="w")
        self._name_row = name_row
        self._name_entry = None
        self._rename_buttons = ()
        self.quality = QualityIndicator(name_row)
        self.quality.pack(side="left", padx=(px(5), 0))
        _icon, device_type = _device_info(device.name)
        self.type_label = tk.Label(labels, text=device_type, bg=CARD, fg=FAINT,
                                   font=(UI, 8), anchor="w")
        self.type_label.pack(fill="x")
        self.note_row = tk.Frame(labels, bg=CARD)
        self.note = tk.Label(self.note_row, text="", bg=CARD, fg=FAINT,
                             font=(UI, 8), anchor="w")
        self.note.pack(side="left", fill="x", expand=True)
        self.retry_button = tk.Button(
            self.note_row, text="Retry", command=self._retry,
            bg=CARD, fg=ACCENT_FG, activebackground=HOVER,
            activeforeground=ACCENT_FG, relief="flat", bd=0,
            highlightthickness=1, highlightbackground=CARD,
            highlightcolor=ACCENT, font=(UI, 8), padx=px(5), pady=0,
            cursor="hand2", takefocus=True)

        self.toggle = Toggle(head, command=self._toggled)
        self.toggle.pack(side="right", padx=(px(10), 0))

        self.volume_row = tk.Frame(self, bg=CARD)
        self._mute_images = {
            False: _fontawesome_image("volume-high", px(16), ACCENT_FG),
            True: _fontawesome_image("volume-xmark", px(16), ACCENT_FG),
        }
        self._muted = False
        self.mute_button = tk.Button(
            self.volume_row, image=self._mute_images[False],
            command=self._toggle_mute,
            bg=CARD, fg=ACCENT_FG, activebackground=HOVER,
            activeforeground=ACCENT_FG, relief="flat", bd=0,
            highlightthickness=1, highlightbackground=CARD,
            highlightcolor=ACCENT, font=(UI, 8), padx=px(4), pady=0,
            cursor="hand2", takefocus=True)
        self.mute_button.pack(side="left", padx=(0, px(6)))
        self.slider = Slider(self.volume_row, command=self._volume)
        self.slider.pack(side="left", fill="x", expand=True)
        self.percent = tk.Label(self.volume_row, text="", bg=CARD, fg=DIM,
                                font=(UI, 8), width=4, anchor="e")
        self.percent.pack(side="right", padx=(px(8), 0))

        self.sync_row = tk.Frame(self, bg=CARD)
        tk.Label(self.sync_row, text="delay", bg=CARD, fg=FAINT, font=(UI, 8),
                 anchor="w").pack(side="left", padx=(0, px(8)))
        self.sync = Slider(self.sync_row, command=self._delay)
        self.sync.pack(side="left", fill="x", expand=True)
        self.sync_value = tk.Label(self.sync_row, text="0 ms", bg=CARD, fg=DIM,
                                   font=(UI, 8), width=6, anchor="e")
        self.sync_value.pack(side="right", padx=(px(8), 0))

        self.test_row = tk.Frame(labels, bg=CARD)
        icon_gap = px(4)
        self._test_play_image = _image_with_left_gap(
            self.test_row, _fontawesome_image("play", px(11), ACCENT_FG), icon_gap)
        self._test_pause_image = _image_with_left_gap(
            self.test_row, _fontawesome_image("pause", px(11), ACCENT_FG), icon_gap)
        self._test_loading_image = _image_with_left_gap(
            self.test_row, _fontawesome_image("spinner", px(11), ACCENT_FG), icon_gap)
        self.test_button = tk.Button(
            self.test_row, text="Test Sound", image=self._test_play_image,
            compound="right", command=self._test_sound,
            bg=CARD, fg=ACCENT_FG, activebackground=HOVER,
            activeforeground=ACCENT_FG, relief="flat", bd=0,
            highlightthickness=1, highlightbackground=CARD,
            highlightcolor=ACCENT, font=(UI, 8), padx=0, pady=0,
            cursor="hand2", takefocus=True)
        self.test_button.pack(side="left")
        self._name_tooltip = Tooltip(self.name, app._device_name(device))
        self._tooltips = [
            self._name_tooltip,
            Tooltip(self.quality, self._quality_tooltip),
            Tooltip(self.toggle, self._toggle_tooltip),
            Tooltip(self.slider, "Adjust this device's output volume."),
            Tooltip(self.mute_button, self._mute_tooltip),
            Tooltip(self.sync, "Adjust playback delay to sync this device."),
            Tooltip(self.retry_button, "Retry connecting this device."),
            Tooltip(self.test_button, self._test_tooltip),
        ]
        for widget in (self.toggle, self.slider, self.mute_button, self.sync,
                       self.retry_button, self.test_button):
            widget.bind(
                "<FocusIn>",
                lambda _event, row=self: row.app._ensure_device_visible(row),
                add="+",
            )

        # Make the whole card a right-click target, including its labels and
        # controls, so renaming does not depend on finding a narrow empty area.
        for widget in (self, head, labels, name_row, self.name, self.quality,
                       self.type_label, self.note_row, self.note, self.retry_button,
                       self.toggle, self.volume_row, self.mute_button, self.slider,
                       self.percent, self.sync_row, self.sync, self.sync_value,
                       self.test_row, self.test_button):
            widget.bind("<Button-3>", self._context_menu, add="+")

        self.spacer = tk.Frame(self, bg=CARD, height=px(10))
        self.spacer.bind("<Button-3>", self._context_menu, add="+")
        self.spacer.pack(fill="x", padx=px(10))

    def _toggled(self, on: bool) -> None:
        self.app.set_selected(self.device.id, on)

    def _context_menu(self, event):
        menu = tk.Menu(self, tearoff=0, bg=CARD, fg=TEXT, bd=0,
                       activebackground=ACCENT, activeforeground=ACCENT_INK,
                       font=(UI, 9))
        menu.add_command(label="Rename device…",
                         command=self._begin_rename)
        menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def _begin_rename(self) -> None:
        if self._name_entry is not None:
            self._name_entry.focus_set()
            return

        self.name.pack_forget()
        self.quality.pack_forget()
        entry = tk.Entry(
            self._name_row, bg=CARD, fg=TEXT, insertbackground=TEXT,
            selectbackground=ACCENT, selectforeground=ACCENT_INK,
            relief="flat", bd=0, highlightthickness=1,
            highlightbackground=EDGE, highlightcolor=ACCENT,
            font=(UI, 10), takefocus=True)
        entry.insert(0, self.app._device_name(self.device))
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", self._commit_rename)
        entry.bind("<Escape>", self._cancel_rename)
        self._name_entry = entry

        reset_image = _fontawesome_image("arrow-rotate-left", px(12), ACCENT_FG)
        cancel_image = _fontawesome_image("xmark", px(12), ACCENT_FG)
        reset = tk.Button(
            self._name_row, image=reset_image,
            command=self._reset_name, bg=CARD, fg=ACCENT_FG,
            activebackground=HOVER, activeforeground=ACCENT_FG,
            relief="flat", bd=0, padx=px(4), pady=0, cursor="hand2",
            takefocus=True, highlightthickness=1,
            highlightbackground=CARD, highlightcolor=ACCENT)
        cancel = tk.Button(
            self._name_row, image=cancel_image,
            command=self._cancel_rename, bg=CARD, fg=ACCENT_FG,
            activebackground=HOVER, activeforeground=ACCENT_FG,
            relief="flat", bd=0, padx=px(4), pady=0, cursor="hand2",
            takefocus=True, highlightthickness=1,
            highlightbackground=CARD, highlightcolor=ACCENT)
        reset.image = reset_image
        cancel.image = cancel_image
        reset.pack(side="right")
        cancel.pack(side="right")
        self._rename_buttons = (reset, cancel)
        Tooltip(reset, "Reset to the original device name.")
        Tooltip(cancel, "Cancel renaming.")
        entry.focus_set()
        entry.selection_range(0, "end")

    def _commit_rename(self, _event=None):
        if self._name_entry is None:
            return "break"
        name = self._name_entry.get().strip()
        if not name:
            self._name_entry.focus_set()
            return "break"
        self.app._set_device_name(self.device, name)
        self._finish_rename(self.app._device_name(self.device))
        return "break"

    def _cancel_rename(self, _event=None):
        self._finish_rename(self.app._device_name(self.device))
        return "break"

    def _reset_name(self) -> None:
        self.app._set_device_name(self.device, None)
        self._finish_rename(self.device.name)

    def _finish_rename(self, name: str) -> None:
        for button in self._rename_buttons:
            button.destroy()
        self._rename_buttons = ()
        if self._name_entry is not None:
            self._name_entry.destroy()
            self._name_entry = None
        self.name.configure(text=name)
        self._name_tooltip.text = name
        self.name.pack(side="left", anchor="w")
        self.quality.pack(side="left", padx=(px(5), 0))

    def _toggle_tooltip(self) -> str:
        action = "Stop routing audio to" if self.device.id in self.app.selected else "Route audio to"
        return "%s %s." % (action, self.device.name)

    def _mute_tooltip(self) -> str:
        return "Unmute this device." if self._muted else "Mute this device."

    def _test_tooltip(self) -> str:
        if self.app._test_state.get(self.device.id) == "Playing test sound":
            return "Pause the test sound."
        if self.app._test_state.get(self.device.id) == "Test sound paused":
            return "Resume the test sound."
        return "Play a test sound on this device."

    def _quality_tooltip(self) -> str:
        if self.quality.level is None:
            return "Playback stability is unavailable until this device is connected."
        descriptions = {
            0: "No playback stability data yet.",
            1: "Weak playback stability: frequent audio underruns.",
            2: "Medium playback stability: occasional audio underruns.",
            3: "Strong playback stability: few recent audio underruns.",
            4: "Strong playback stability: no recent audio underruns.",
        }
        return descriptions[self.quality.level] + " This is not Bluetooth signal strength."

    def _retry(self) -> None:
        self.retry_button.configure(state="disabled", text="Retrying…")
        self.app.retry_device(self.device.id)

    def _test_sound(self) -> None:
        self.app.test_device(self.device.id)

    def set_test_button(self, mode: str) -> None:
        if mode == "preparing":
            self.test_button.configure(state="disabled", text="Test Sound",
                                       image=self._test_loading_image)
        else:
            image = (self._test_pause_image if mode == "playing"
                     else self._test_play_image)
            self.test_button.configure(state="normal", text="Test Sound", image=image)

    def _volume(self, value: float) -> None:
        self.percent.configure(text="%d%%" % round(value * 100))
        ep.set_volume(self.device.id, value)

    def _show_mute_state(self, muted: bool) -> None:
        self._muted = muted
        self.mute_button.configure(image=self._mute_images[muted])
        self.slider.set_enabled(not muted)
        self.percent.configure(fg=FAINT if muted else DIM)

    def _toggle_mute(self) -> None:
        muted = not self._muted
        if ep.set_mute(self.device.id, muted):
            self._show_mute_state(muted)

    def _delay(self, value: float) -> None:
        seconds = value * MAX_DELAY
        self.sync_value.configure(text="%d ms" % round(seconds * 1000))
        self.app.set_delay(self.device.id, seconds)

    def show_selected(self, selected: bool, animate: bool = True) -> None:
        self.toggle.set(selected, animate=animate)
        if selected:
            level = ep.get_volume(self.device.id)
            if level is not None:
                self.slider.set(level)
                self.percent.configure(text="%d%%" % round(level * 100))
            muted = ep.get_mute(self.device.id)
            if muted is not None:
                self._show_mute_state(muted)
            seconds = self.app.delays.get(self.device.id, 0.0)
            self.sync.set(seconds / MAX_DELAY)
            self.sync_value.configure(text="%d ms" % round(seconds * 1000))
            self.volume_row.pack(fill="x", padx=px(14), pady=(px(8), 0),
                                 before=self.spacer)
            self.sync_row.pack(fill="x", padx=px(14), pady=(px(4), 0),
                               before=self.spacer)
            self.test_row.pack(fill="x", pady=(px(4), 0))
        else:
            self.volume_row.pack_forget()
            self.sync_row.pack_forget()
            self.test_row.pack_forget()

    def show_note(self, text: str, bad: bool = False, retry: bool = False) -> None:
        if text:
            self.note.configure(text=text, fg=DANGER if bad else FAINT)
            self.note_row.pack(fill="x")
            if retry:
                self.retry_button.configure(text="Retry", state="normal")
                self.retry_button.pack(side="right")
            else:
                self.retry_button.pack_forget()
                self.retry_button.configure(text="Retry", state="normal")
        else:
            self.note_row.pack_forget()
            self.retry_button.pack_forget()
            self.retry_button.configure(text="Retry", state="normal")


class AddDeviceButton(RoundedFrame):
    """The obvious way to bring another pair of headphones into the list."""

    def __init__(self, master, command):
        super().__init__(master, fill=CARD, border=EDGE, corner_bg=SURFACE,
                         radius=px(10), cursor="hand2", takefocus=True)
        self.command = command
        self.bind("<KeyPress-space>", self._keyboard_activate)
        self.bind("<KeyPress-Return>", self._keyboard_activate)
        self.bind("<FocusIn>", lambda _event: self.set_border(ACCENT), add="+")
        self.bind("<FocusOut>", lambda _event: self.set_border(EDGE), add="+")
        inner = tk.Frame(self, bg=CARD)
        inner.pack(fill="x", padx=px(14), pady=px(9))
        icon_size = px(22)
        self.icon_image = _fontawesome_image("circle-plus", icon_size, ACCENT_FG)
        icon = tk.Label(inner, image=self.icon_image, bg=CARD, bd=0)
        icon.pack(side="left", padx=(0, px(10)))
        caption = tk.Label(inner, text="Add a Bluetooth device", bg=CARD, fg=ACCENT_FG,
                           font=(UI, 10), anchor="w")
        caption.pack(side="left", fill="x", expand=True)

        self._parts = (self, inner, icon, caption)
        self._tooltips = [
            Tooltip(widget, "Open Bluetooth settings to add a device.")
            for widget in self._parts
        ]
        for widget in self._parts:
            widget.configure(cursor="hand2")
            widget.bind("<Button-1>", lambda e: self.command())
            widget.bind("<Enter>", lambda e: self._tint(HOVER))
            widget.bind("<Leave>", lambda e: self._tint(CARD))

    def _tint(self, colour: str) -> None:
        self.set_fill(colour)
        for widget in self._parts[1:]:
            widget.configure(bg=colour)

    def _keyboard_activate(self, _event=None):
        self.command()
        return "break"


class Worker(threading.Thread):
    """Applies the wanted routing off the UI thread, coalescing rapid changes."""

    def __init__(self, engine: Engine, results: queue.Queue,
                 test_sound: Path):
        super().__init__(daemon=True)
        self.engine = engine
        self.results = results
        self.test_sound = test_sound
        self._wake = threading.Event()
        self._wanted = None
        self._applied = object()
        self._retry = None
        self._test_requests = []
        self._report = None
        self._stopping = False

    def request(self, source: str, listeners: list) -> None:
        self._wanted = (source, tuple(listeners))
        self._wake.set()

    def retry_device(self, key: str, name: str) -> None:
        self._retry = (key, name)
        self._wake.set()

    def test_device(self, key: str) -> None:
        self._test_requests.append(key)
        self._wake.set()

    def cancel_test_requests(self) -> None:
        self._test_requests.clear()

    def shutdown(self) -> None:
        self._stopping = True
        self._wanted = None
        self._wake.set()

    def run(self) -> None:
        ep.com_init()
        while True:
            self._wake.wait()
            self._wake.clear()
            if self._stopping:
                self.engine.stop()
                return
            wanted = self._wanted
            if wanted is not None and wanted != self._applied:
                self._applied = wanted
                source, listeners = wanted
                if not listeners:
                    self.engine.stop()
                    report = {"source": source, "ok": [], "failed": {}, "missing": []}
                else:
                    report = self.engine.start(source, list(listeners))
                self._report = report
                if self._wanted == wanted:      # nothing newer arrived meanwhile
                    self.results.put(report)
                continue

            if self._test_requests:
                if wanted is None:
                    continue
                test_key = self._test_requests.pop(0)
                _source, listeners = wanted
                if miniaudio is None:
                    self.results.put({
                        "test_error": test_key,
                        "detail": "The MP3 decoder could not load: "
                                  + (_MINIAUDIO_IMPORT_ERROR or "unknown import error"),
                    })
                    continue
                if any(key == test_key for key, _ in listeners):
                    try:
                        sound = miniaudio.decode_file(
                            str(self.test_sound),
                            output_format=miniaudio.SampleFormat.FLOAT32,
                            nchannels=2,
                            sample_rate=48000,
                        )
                        if self._wanted != wanted:
                            continue
                        duration = self.engine.play_test_sound(
                            test_key, sound.samples, sound.nchannels,
                            sound.sample_rate)
                        if duration > 0:
                            if self._wanted == wanted:
                                self.results.put({"test": test_key,
                                                  "duration": duration})
                        else:
                            self.results.put({
                                "test_error": test_key,
                                "detail": "The selected device is not currently playing.",
                            })
                    except Exception as exc:
                        self.results.put({"test_error": test_key,
                                          "detail": str(exc) or type(exc).__name__})
                continue

            retry = self._retry
            self._retry = None
            if retry is None or wanted is None:
                continue
            key, name = retry
            source, listeners = wanted
            if not any(listener_key == key for listener_key, _ in listeners):
                continue

            outcome, detail = self.engine.retry_listener(key, name)
            if outcome == "restart":
                report = self.engine.start(source, list(listeners))
            else:
                report = dict(self._report or {
                    "source": source, "ok": [], "failed": {}, "missing": []})
                report["ok"] = list(report.get("ok", []))
                report["failed"] = dict(report.get("failed", {}))
                report["missing"] = list(report.get("missing", []))
                report["source"] = source
                if outcome == "ok":
                    if key not in report["ok"]:
                        report["ok"].append(key)
                    report["failed"].pop(key, None)
                    report["missing"] = [item for item in report["missing"]
                                         if item != key]
                elif outcome == "missing":
                    report["failed"].pop(key, None)
                    if key not in report["missing"]:
                        report["missing"].append(key)
                else:
                    report["ok"] = [item for item in report["ok"] if item != key]
                    report["missing"] = [item for item in report["missing"]
                                         if item != key]
                    report["failed"][key] = detail
                report["latency_ms"] = {
                    listener_key: int(stats["latency_ms"])
                    for listener_key, stats in self.engine.stats().items()
                }
            self._report = report
            if self._wanted == wanted:
                self.results.put(report)


class App(tk.Tk):
    def __init__(self, theme: th.Theme | None = None, start_hidden: bool = False):
        global SURFACE
        super().__init__()
        ep.com_init()

        self._theme = theme or th.read_theme()
        _set_palette(self._theme)
        self._mica_failed = False
        self._glass = bool(self._theme.transparency and th.mica_supported())
        key = GLASS_KEYS[self._theme.dark]
        SURFACE = key if self._glass else BG

        self.title("Seblue")
        try:
            self.wm_iconbitmap(str(APP_ICON_ICO))
        except tk.TclError:
            pass
        try:
            self._window_icon = tk.PhotoImage(file=str(APP_ICON_PNG))
            self.iconphoto(True, self._window_icon)
        except tk.TclError:
            self._window_icon = None
        self.configure(bg=SURFACE)
        self.wm_attributes("-transparentcolor", key if self._glass else "")
        self.geometry("%dx%d" % (px(430), px(560)))
        self.minsize(px(380), px(440))

        self.engine = Engine()
        self.results: queue.Queue = queue.Queue()
        self.worker = Worker(self.engine, self.results, TEST_SOUND)
        self.worker.start()

        self.devices: list = []
        self.source = None
        self.selected: set = set()
        self.delays: dict = {}
        self.device_names: dict[str, str] = {}
        self.rows: dict = {}
        self._signature = None
        self._report = None
        self._test_state: dict = {}
        self._test_jobs: dict = {}
        self._test_remaining: dict = {}
        self._test_started_at: dict = {}
        self._quality_last_underruns: dict[str, int] = {}
        self._scan_job = None
        self._theme_job = None
        self._quality_job = None
        self._tray_icon = None
        self._tray_actions: queue.Queue[str] = queue.Queue()
        self._closing = False

        self._build()
        self._apply_window_theme(rebuild=False)
        self._load_settings()
        self.protocol("WM_DELETE_WINDOW", self._hide_to_tray)
        self.bind("<Unmap>", self._on_minimize, add="+")
        self.bind_all("<MouseWheel>", self._wheel)
        self.bind("<Map>", self._mapped)
        self._scan()
        self._drain()
        self._theme_job = self.after(1500, self._watch_theme)
        self._quality_job = self.after(1000, self._refresh_quality)
        if start_hidden:
            self.after_idle(self._hide_to_tray)

    # -- layout ------------------------------------------------------------

    def _build(self) -> None:
        outer = tk.Frame(self, bg=SURFACE)
        outer.pack(fill="both", expand=True, padx=px(18), pady=px(16))

        tk.Label(outer, text="Seblue", bg=SURFACE, fg=TEXT,
                 font=(UI, 17, "bold"), anchor="w").pack(fill="x")
        self.subtitle = tk.Label(outer, text="Play your audio on several headphones at once",
                                 bg=SURFACE, fg=DIM, font=(UI, 9), anchor="w",
                                 justify="left")
        self.subtitle.pack(fill="x", pady=(px(2), px(14)))

        self._caption(outer, "PLAYING FROM")
        source_card = RoundedFrame(outer, fill=CARD, border=EDGE,
                                  corner_bg=SURFACE, radius=px(10))
        source_card.pack(fill="x", pady=(px(6), px(14)))
        inner = tk.Frame(source_card, bg=CARD)
        inner.pack(fill="x", padx=px(14), pady=px(10))
        self.source_label = tk.Label(inner, text="Looking...", bg=CARD, fg=TEXT,
                                     font=(UI, 10), anchor="w")
        self.source_label.pack(side="left", fill="x", expand=True)
        self.change = tk.Label(inner, text="Change", bg=CARD, fg=ACCENT_FG,
                               font=(UI, 9), cursor="hand2", takefocus=True,
                               highlightthickness=1,
                               highlightbackground=CARD,
                               highlightcolor=ACCENT)
        self.change.pack(side="right")
        self.change.bind("<Button-1>", self._choose_source)
        self.change.bind("<KeyPress-Return>", self._choose_source_key)
        self.change.bind("<KeyPress-space>", self._choose_source_key)
        self._source_tooltip = Tooltip(
            self.change, "Choose which Windows output device Seblue shares audio from.")

        self._caption(outer, "ALSO PLAYING TO")

        # Footer is packed before the list so a long list can never push the
        # add button and status off the bottom of the window.
        self.status = tk.Label(outer, text="", bg=SURFACE, fg=DIM, font=(UI, 8),
                               anchor="w", justify="left")
        self.status.pack(side="bottom", fill="x", pady=(px(9), 0))
        footer = tk.Frame(outer, bg=SURFACE)
        footer.pack(side="bottom", fill="x")
        tk.Frame(footer, bg=EDGE, height=px(1)).pack(
            fill="x", pady=(0, px(12)))
        AddDeviceButton(footer, self._open_bluetooth).pack(fill="x")

        holder = tk.Frame(outer, bg=SURFACE)
        holder.pack(fill="both", expand=True, pady=(px(6), 0))
        self.canvas = tk.Canvas(holder, bg=SURFACE, highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.list = tk.Frame(self.canvas, bg=SURFACE)
        self._window = self.canvas.create_window((0, 0), window=self.list, anchor="nw")
        self.list.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(
            self._window, width=e.width))
        self.bind("<Configure>", self._rewrap)

    def _caption(self, parent, text: str) -> None:
        tk.Label(parent, text=text, bg=SURFACE, fg=FAINT, font=(UI, 8, "bold"),
                 anchor="w").pack(fill="x")

    # -- theme -------------------------------------------------------------

    def _apply_window_theme(self, rebuild: bool = True) -> None:
        global MAGIC, SURFACE
        _set_palette(self._theme)

        glass = bool(self._theme.transparency and th.mica_supported()
                     and not self._mica_failed)
        if glass:
            glass = th.apply_mica(self, self._theme.dark)
            if not glass:
                self._mica_failed = True
        self._glass = glass

        MAGIC = GLASS_KEYS[self._theme.dark]
        new_surface = MAGIC if glass else BG
        changed = new_surface != SURFACE
        SURFACE = new_surface
        self.wm_attributes("-transparentcolor", MAGIC if glass else "")
        self.configure(bg=SURFACE)
        th.style_titlebar(self, self._theme.dark, BG, EDGE, TEXT)

        if rebuild or changed:
            self._rebuild_ui()

    def _rebuild_ui(self) -> None:
        position = 0.0
        try:
            position = self.canvas.yview()[0]
        except Exception:
            pass

        for child in self.winfo_children():
            child.destroy()
        self.rows = {}
        self._build()
        self._rebuild_rows()
        self._paint_notes()
        self._paint_status()
        if position:
            try:
                self.canvas.yview_moveto(position)
            except Exception:
                pass

    def _watch_theme(self) -> None:
        theme = th.read_theme()
        if theme.state() != self._theme.state():
            if theme.transparency and not self._theme.transparency:
                self._mica_failed = False
            self._theme = theme
            self._apply_window_theme()
        self._theme_job = self.after(1500, self._watch_theme)

    def _mapped(self, event) -> None:
        if event.widget is self and self._glass:
            self.after_idle(self._reapply_glass)

    def _reapply_glass(self) -> None:
        if self._glass:
            th.apply_mica(self, self._theme.dark)
            th.style_titlebar(self, self._theme.dark, BG, EDGE, TEXT)

    def _rewrap(self, event) -> None:
        if event.widget is self:
            width = max(px(200), event.width - px(40))
            self.subtitle.configure(wraplength=width)
            self.status.configure(wraplength=width)

    def _wheel(self, event) -> None:
        box = self.canvas.bbox("all")
        if box and box[3] > self.canvas.winfo_height():
            self.canvas.yview_scroll(-int(event.delta / 60), "units")

    # -- devices -----------------------------------------------------------

    def _scan(self) -> None:
        try:
            devices = ep.list_render_endpoints()
            default = ep.get_default_id()
        except Exception:
            devices, default = [], None

        self.devices = devices
        self.source = next((d for d in devices if d.id == default), None)
        if self.source is None and devices:
            self.source = devices[0]

        signature = (tuple(sorted((d.id, d.name) for d in devices)),
                     self.source.id if self.source else None)
        if signature != self._signature:
            self._signature = signature
            self._rebuild_rows()
            self._apply()
        self._scan_job = self.after(SCAN_MS, self._scan)

    def _rebuild_rows(self) -> None:
        self.source_label.configure(
            text=self.source.name if self.source else "No output device")

        others = [d for d in self.devices if not self.source or d.id != self.source.id]
        for row in self.rows.values():
            row.destroy()
        self.rows = {}

        if not others:
            empty = tk.Label(self.list, bg=CARD, fg=DIM, font=(UI, 9),
                             text="Nothing else connected yet.\nUse + below to pair "
                                  "another pair of headphones.",
                             justify="left", anchor="w", padx=px(14), pady=px(14))
            empty.pack(fill="x")
            self.rows["__empty__"] = empty
            return

        for device in others:
            row = DeviceRow(self.list, self, device)
            row.pack(fill="x", pady=(0, px(8)))
            row.show_selected(device.id in self.selected, animate=False)
            self.rows[device.id] = row
        self._paint_notes()

    # -- routing -----------------------------------------------------------

    def set_selected(self, device_id: str, on: bool) -> None:
        self._cancel_all_tests()
        if on:
            self.selected.add(device_id)
        else:
            self._cancel_test(device_id)
            self.selected.discard(device_id)
        row = self.rows.get(device_id)
        if isinstance(row, DeviceRow):
            row.show_selected(on)
        self._save_settings()
        self._apply()

    def set_delay(self, device_id: str, seconds: float) -> None:
        """Shift one device in time; takes effect immediately, no restart."""
        self.delays[device_id] = seconds
        self.engine.set_delay(device_id, seconds)
        self._save_settings()

    def retry_device(self, device_id: str) -> None:
        row = self.rows.get(device_id)
        if (self.source is None or device_id not in self.selected
                or not isinstance(row, DeviceRow)):
            return
        row.show_note("Retrying…")
        self.worker.retry_device(device_id, row.device.name)

    def test_device(self, device_id: str) -> None:
        row = self.rows.get(device_id)
        if (device_id not in self.selected
                or not isinstance(row, DeviceRow)):
            return
        state = self._test_state.get(device_id)
        if state == "Preparing test sound":
            return
        if state == "Playing test sound":
            if self.engine.toggle_test_sound(device_id) == "paused":
                remaining = self._test_remaining.get(device_id, 0.0)
                started = self._test_started_at.pop(device_id, time.monotonic())
                self._test_remaining[device_id] = max(
                    0.0, remaining - (time.monotonic() - started))
                job = self._test_jobs.pop(device_id, None)
                if job is not None:
                    self.after_cancel(job)
                self._test_state[device_id] = "Test sound paused"
                self._paint_notes()
            return
        if state == "Test sound paused":
            if self.engine.toggle_test_sound(device_id) == "playing":
                self._test_state[device_id] = "Playing test sound"
                self._schedule_test_finish(device_id)
            else:
                self._test_state[device_id] = "Preparing test sound"
                self.worker.test_device(device_id)
            self._paint_notes()
            return
        self._test_state[device_id] = "Preparing test sound"
        self._paint_notes()
        self.worker.test_device(device_id)

    def _test_started(self, device_id: str, duration: float) -> None:
        self._test_state[device_id] = "Playing test sound"
        self._test_remaining[device_id] = duration
        self._schedule_test_finish(device_id)
        self._paint_notes()

    def _schedule_test_finish(self, device_id: str) -> None:
        self._test_started_at[device_id] = time.monotonic()
        self._test_jobs[device_id] = self.after(
            max(1, round(self._test_remaining.get(device_id, 0.0) * 1000)),
            lambda key=device_id: self._finish_test(key))

    def _test_failed(self, device_id: str, detail: str = "") -> None:
        self._test_state.pop(device_id, None)
        self._test_remaining.pop(device_id, None)
        self._test_started_at.pop(device_id, None)
        job = self._test_jobs.pop(device_id, None)
        if job is not None:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        row = self.rows.get(device_id)
        if isinstance(row, DeviceRow):
            row.set_test_button("idle")
            message = "Test sound unavailable"
            if detail:
                message += ": " + detail.replace("\n", " ")[:180]
            row.show_note(message, bad=True)

    def _finish_test(self, device_id: str) -> None:
        self._test_jobs.pop(device_id, None)
        self._test_state.pop(device_id, None)
        self._test_remaining.pop(device_id, None)
        self._test_started_at.pop(device_id, None)
        row = self.rows.get(device_id)
        if isinstance(row, DeviceRow):
            row.set_test_button("idle")
        self._paint_notes()

    def _cancel_test(self, device_id: str) -> None:
        self._test_state.pop(device_id, None)
        self._test_remaining.pop(device_id, None)
        self._test_started_at.pop(device_id, None)
        job = self._test_jobs.pop(device_id, None)
        if job is not None:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        row = self.rows.get(device_id)
        if isinstance(row, DeviceRow):
            row.set_test_button("idle")

    def _cancel_all_tests(self) -> None:
        for device_id in tuple(self._test_state):
            self._cancel_test(device_id)
        self.worker.cancel_test_requests()

    def _apply(self) -> None:
        if self.source is None:
            self.status.configure(text="No output device to share.", fg=DIM)
            return
        by_id = {d.id: d.name for d in self.devices}
        listeners = [
            (device_id, by_id[device_id])
            for device_id in sorted(self.selected)
            if device_id in by_id
            and (self.source is None or device_id != self.source.id)
        ]
        self.engine.delays = dict(self.delays)
        self.worker.request(self.source.name, listeners)
        if listeners:
            self.status.configure(text="Connecting...", fg=DIM)
        else:
            self.status.configure(text="Turn on anyone who should hear this too.",
                                  fg=DIM)

    def _drain(self) -> None:
        self._drain_tray_actions()
        arrived = False
        try:
            while True:
                report = self.results.get_nowait()
                if "test" in report:
                    self._test_started(report["test"], report["duration"])
                elif "test_error" in report:
                    self._test_failed(report["test_error"], report.get("detail", ""))
                else:
                    self._report = report
                    arrived = True
        except queue.Empty:
            pass
        if arrived:
            self._paint_notes()
            self._paint_status()
        self.after(120, self._drain)

    def _ensure_tray_icon(self) -> None:
        if self._tray_icon is not None:
            return
        image = Image.open(APP_ICON_ICO).convert("RGBA")
        menu = Menu(
            MenuItem("Open Seblue", self._queue_tray_open, default=True),
            MenuItem("Exit", self._queue_tray_exit),
        )
        self._tray_icon = pystray.Icon("Seblue", image, "Seblue", menu)
        self._tray_icon.run_detached()

    def _queue_tray_open(self, _icon=None, _item=None) -> None:
        self._tray_actions.put("open")

    def _queue_tray_exit(self, _icon=None, _item=None) -> None:
        self._tray_actions.put("exit")

    def _drain_tray_actions(self) -> None:
        try:
            while True:
                action = self._tray_actions.get_nowait()
                if action == "open":
                    self._restore_from_tray()
                elif action == "exit":
                    self._close()
        except queue.Empty:
            pass

    def _hide_to_tray(self) -> None:
        if self._closing:
            return
        try:
            self._ensure_tray_icon()
        except Exception as exc:
            self.status.configure(
                text="Could not open the system tray icon: %s" % exc, fg=DANGER)
            return
        self.withdraw()

    def _on_minimize(self, event) -> None:
        if event.widget is not self:
            return
        self.after_idle(self._hide_if_iconified)

    def _hide_if_iconified(self) -> None:
        if not self._closing and self.state() == "iconic":
            self._hide_to_tray()

    def _restore_from_tray(self) -> None:
        if self._closing:
            return
        self.deiconify()
        self.state("normal")
        self.lift()
        self.focus_force()

    def _refresh_quality(self) -> None:
        try:
            stats = self.engine.stats()
        except Exception:
            stats = {}

        for device_id, row in self.rows.items():
            if not isinstance(row, DeviceRow):
                continue
            device_stats = stats.get(device_id) if device_id in self.selected else None
            if device_stats is None:
                self._quality_last_underruns.pop(device_id, None)
                row.quality.set_level(None)
                continue

            underruns = int(device_stats.get("underruns", 0))
            previous = self._quality_last_underruns.get(device_id, underruns)
            recent = max(0, underruns - previous)
            self._quality_last_underruns[device_id] = underruns
            if recent == 0:
                level = 4
            elif recent <= 2:
                level = 3
            elif recent <= 8:
                level = 2
            else:
                level = 1
            row.quality.set_level(level)

        self._quality_job = self.after(1000, self._refresh_quality)

    def _paint_notes(self) -> None:
        report = self._report or {}
        failed = report.get("failed", {})
        missing = set(report.get("missing", []))
        for device_id, row in self.rows.items():
            if not isinstance(row, DeviceRow):
                continue
            if device_id in failed:
                row.set_test_button("idle")
                row.show_note("Couldn’t connect", bad=True, retry=True)
            elif device_id in missing:
                row.set_test_button("idle")
                row.show_note("Not reachable", bad=True, retry=True)
            elif device_id in self._test_state:
                state = self._test_state[device_id]
                row.show_note("")
                if state == "Preparing test sound":
                    row.set_test_button("preparing")
                elif state == "Playing test sound":
                    row.set_test_button("playing")
                else:
                    row.set_test_button("idle")
            else:
                row.set_test_button("idle")
                row.show_note("")

    def _paint_status(self) -> None:
        report = self._report or {}
        if report.get("failed", {}).get("*"):
            self.status.configure(text=report["failed"]["*"], fg=DANGER)
            return
        count = len(report.get("ok", []))
        broken = len(report.get("failed", {})) + len(report.get("missing", []))
        if count and not broken:
            others = "1 other device" if count == 1 else "%d other devices" % count
            self.status.configure(
                text="Playing to %s alongside %s." % (others, report.get("source", "you")),
                fg=ACCENT_FG)
        elif count:
            self.status.configure(
                text="Playing to %d, but %d could not be opened." % (count, broken),
                fg=DANGER)
        elif broken:
            self.status.configure(text="Could not open the selected device.", fg=DANGER)
        else:
            self.status.configure(text="Turn on anyone who should hear this too.",
                                  fg=DIM)

    # -- source picker -----------------------------------------------------

    def _choose_source_key(self, event=None):
        self._choose_source(event)
        return "break"

    def _choose_source(self, _event) -> None:
        menu = tk.Menu(self, tearoff=0, bg=CARD, fg=TEXT, bd=0,
                       activebackground=ACCENT, activeforeground=ACCENT_INK,
                       font=(UI, 9))
        for device in self.devices:
            mark = "• " if device is self.source else "    "
            menu.add_command(label=mark + device.name,
                             command=lambda d=device: self._set_source(d))
        menu.add_separator()
        menu.add_command(label="    Open Windows sound settings",
                         command=lambda: os.startfile("ms-settings:sound"))
        menu.tk_popup(self.change.winfo_rootx(),
                      self.change.winfo_rooty() + self.change.winfo_height() + px(4))

    def _ensure_device_visible(self, row: DeviceRow) -> None:
        def scroll_into_view():
            try:
                if not row.winfo_exists():
                    return
                top = self.canvas.canvasy(
                    row.winfo_rooty() - self.canvas.winfo_rooty())
                bottom = top + row.winfo_height()
                visible_top = self.canvas.canvasy(0)
                visible_bottom = visible_top + self.canvas.winfo_height()
                bounds = self.canvas.bbox("all")
                if not bounds:
                    return
                content_height = max(1, bounds[3] - bounds[1])
                target = visible_top
                if top < visible_top:
                    target = top
                elif bottom > visible_bottom:
                    target = bottom - self.canvas.winfo_height()
                else:
                    return
                self.canvas.yview_moveto(max(0.0, target / content_height))
            except Exception:
                pass

        self.after_idle(scroll_into_view)

    def _set_source(self, device) -> None:
        if not ep.set_default_id(device.id):
            self.status.configure(text="Windows would not switch output device.",
                                  fg=DANGER)
            return
        self.selected.discard(device.id)
        self._save_settings()
        self._scan_now()

    def _scan_now(self) -> None:
        self._signature = None
        if self._scan_job is not None:
            try:
                self.after_cancel(self._scan_job)
            except Exception:
                pass
            self._scan_job = None
        self._scan()

    def _open_bluetooth(self) -> None:
        try:
            os.startfile("ms-settings:bluetooth")
        except Exception:
            self.status.configure(text="Could not open Bluetooth settings.", fg=DANGER)

    # -- settings ----------------------------------------------------------

    def _device_name(self, device) -> str:
        return self.device_names.get(device.id, device.name)

    def _set_device_name(self, device, name: str | None) -> None:
        name = name.strip() if name is not None else ""
        if not name or name == device.name:
            self.device_names.pop(device.id, None)
        else:
            self.device_names[device.id] = name
        self._save_settings()

    def _load_settings(self) -> None:
        try:
            saved = json.loads(SETTINGS.read_text(encoding="utf-8-sig"))
            self.selected = set(saved.get("selected", []))
            self.delays = {k: float(v) for k, v in saved.get("delays", {}).items()}
            self.device_names = {
                str(k): str(v) for k, v in saved.get("device_names", {}).items()
                if isinstance(v, str) and v.strip()
            }
        except Exception:
            self.selected, self.delays, self.device_names = set(), {}, {}

    def _save_settings(self) -> None:
        try:
            SETTINGS.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS.write_text(
                json.dumps({"selected": sorted(self.selected),
                            "delays": {k: round(v, 4)
                                       for k, v in self.delays.items() if v},
                            "device_names": self.device_names}),
                encoding="utf-8")
        except Exception:
            pass

    def _close(self) -> None:
        if self._closing:
            return
        self._closing = True
        for job in (self._scan_job, self._theme_job, self._quality_job,
                    *self._test_jobs.values()):
            if job is not None:
                try:
                    self.after_cancel(job)
                except Exception:
                    pass
        if self._tray_icon is not None:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
        self.worker.shutdown()
        try:
            self.engine.stop()
        except Exception:
            pass
        self.destroy()


def main() -> None:
    _enable_dpi()
    App(start_hidden="--minimized" in sys.argv[1:]).mainloop()
