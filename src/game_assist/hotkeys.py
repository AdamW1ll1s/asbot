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


class HotkeyRegistrationError(RuntimeError):
    """Raised when Windows cannot reserve one of the configured hotkeys."""


class GlobalHotkeys:
    def __init__(self, bindings: dict[str, Callable[[], None]]) -> None:
        if os.name != "nt":
            raise WindowsOnlyError("Global hotkeys are only available on Windows.")
        self._bindings = bindings
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self._start_error: Exception | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._ready.clear()
        self._start_error = None
        self._thread_id = None
        self._thread = threading.Thread(target=self._run, name="global-hotkeys", daemon=True)
        self._thread.start()
        # Registration happens on the message-loop thread.  Wait until it has
        # completed so a failure is reported to the caller, not as an uncaught
        # exception in a background thread.
        if not self._ready.wait(timeout=2):
            raise HotkeyRegistrationError("Timed out while registering global hotkeys")
        if self._start_error is not None:
            raise self._start_error

    def _run(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._thread_id = kernel32.GetCurrentThreadId()
        ids: dict[int, Callable[[], None]] = {}
        try:
            for index, (key, callback) in enumerate(self._bindings.items(), start=1):
                vk = VIRTUAL_KEYS.get(key.upper())
                if vk is None:
                    raise ValueError(f"Unsupported hotkey: {key}")
                if not user32.RegisterHotKey(None, index, MOD_NOREPEAT, vk):
                    error = ctypes.get_last_error()
                    if error == 1409:
                        raise HotkeyRegistrationError(
                            f"Global hotkey {key} is already registered by another application. "
                            "Close the other application or choose a different hotkey."
                        )
                    raise ctypes.WinError(error)
                ids[index] = callback
            self._ready.set()
            message = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == WM_HOTKEY and message.wParam in ids:
                    ids[message.wParam]()
        except Exception as error:
            self._start_error = error
            self._ready.set()
        finally:
            for identifier in ids:
                user32.UnregisterHotKey(None, identifier)
            self._thread_id = None

    def stop(self) -> None:
        if self._thread_id:
            ctypes.WinDLL("user32").PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
