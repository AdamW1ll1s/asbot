from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import threading
from typing import Callable

from .input import VIRTUAL_KEYS
from .windows import WindowsOnlyError


WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_NOREPEAT = 0x4000


class GlobalHotkeys:
    def __init__(self, bindings: dict[str, Callable[[], None]]) -> None:
        if os.name != "nt":
            raise WindowsOnlyError("Global hotkeys are only available on Windows.")
        self._bindings = bindings
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="global-hotkeys", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._thread_id = kernel32.GetCurrentThreadId()
        ids: dict[int, Callable[[], None]] = {}
        for index, (key, callback) in enumerate(self._bindings.items(), start=1):
            vk = VIRTUAL_KEYS.get(key.upper())
            if vk is None:
                raise ValueError(f"Unsupported hotkey: {key}")
            if not user32.RegisterHotKey(None, index, MOD_NOREPEAT, vk):
                raise ctypes.WinError(ctypes.get_last_error())
            ids[index] = callback
        try:
            message = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == WM_HOTKEY and message.wParam in ids:
                    ids[message.wParam]()
        finally:
            for identifier in ids:
                user32.UnregisterHotKey(None, identifier)

    def stop(self) -> None:
        if self._thread_id:
            ctypes.WinDLL("user32").PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
