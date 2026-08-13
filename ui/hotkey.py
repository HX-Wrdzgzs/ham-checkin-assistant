"""Windows 全局快捷键（ctypes RegisterHotKey），后台线程消息循环。"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import threading

from PySide6.QtCore import QObject, Signal

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

_KEYMAP = {
    "SPACE": 0x20, "ENTER": 0x0D, "ESC": 0x1B, "TAB": 0x09,
}
for _i in range(10):
    _KEYMAP[str(_i)] = 0x30 + _i
for _i in range(26):
    _KEYMAP[chr(ord("A") + _i)] = 0x41 + _i
for _i in range(1, 13):
    _KEYMAP[f"F{_i}"] = 0x6F + _i


def parse_hotkey(text: str) -> tuple[int, int]:
    mods, key = 0, 0
    for part in (text or "").split("+"):
        p = part.strip().upper()
        if p in ("CTRL", "CONTROL"):
            mods |= MOD_CONTROL
        elif p == "ALT":
            mods |= MOD_ALT
        elif p == "SHIFT":
            mods |= MOD_SHIFT
        elif p in ("WIN", "META"):
            mods |= MOD_WIN
        else:
            key = _KEYMAP.get(p, 0)
    return mods, key


class GlobalHotkey(QObject):
    activated = Signal()

    def __init__(self, text: str = "Ctrl+Space", parent=None) -> None:
        super().__init__(parent)
        self._mods, self._vk = parse_hotkey(text)
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._vk == 0:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread and self._thread.ident:
            try:
                ctypes.windll.user32.PostThreadMessageW(self._thread.ident, WM_QUIT, 0, 0)
            except Exception:  # noqa: BLE001
                pass

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        try:
            ok = user32.RegisterHotKey(None, 1, self._mods, self._vk)
        except Exception:  # noqa: BLE001
            return
        if not ok:
            return
        msg = ctypes.wintypes.MSG()
        try:
            while True:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret <= 0:
                    break
                if msg.message == WM_HOTKEY:
                    self.activated.emit()
        finally:
            try:
                user32.UnregisterHotKey(None, 1)
            except Exception:  # noqa: BLE001
                pass
