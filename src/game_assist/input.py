from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import threading

from .windows import WindowsOnlyError


KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


VIRTUAL_KEYS = {
    **{chr(code): code for code in range(ord("0"), ord("9") + 1)},
    **{f"F{key}": 0x6F + key for key in range(1, 25)},
}


class KeyboardExecutor:
    """Tracks held keys so cancellation and exceptions cannot leave them pressed."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise WindowsOnlyError("Keyboard output is only available on Windows.")
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._held: set[int] = set()
        self._lock = threading.Lock()

    def tap(self, key: str, duration_ms: int, cancelled: threading.Event) -> bool:
        vk = self._virtual_key(key)
        if cancelled.is_set():
            return False
        self._send(vk, down=True)
        with self._lock:
            self._held.add(vk)
        try:
            return not cancelled.wait(duration_ms / 1000)
        finally:
            self._send(vk, down=False)
            with self._lock:
                self._held.discard(vk)

    def release_all(self) -> None:
        with self._lock:
            held, self._held = self._held, set()
        for vk in held:
            self._send(vk, down=False)

    @staticmethod
    def _virtual_key(key: str) -> int:
        try:
            return VIRTUAL_KEYS[key.upper()]
        except KeyError as error:
            raise ValueError(f"Unsupported key: {key}") from error

    def _send(self, vk: int, down: bool) -> None:
        flags = 0 if down else KEYEVENTF_KEYUP
        event = INPUT(
            type=INPUT_KEYBOARD,
            ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=None),
        )
        result = self._user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))
        if result != 1:
            raise ctypes.WinError(ctypes.get_last_error())
