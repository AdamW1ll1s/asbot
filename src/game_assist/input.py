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
    **{chr(code): code for code in range(ord("A"), ord("Z") + 1)},
    **{f"F{key}": 0x6F + key for key in range(1, 25)},
    "CTRL": 0x11,
    "SHIFT": 0x10,
    "ALT": 0x12,
    "SPACE": 0x20,
    "ENTER": 0x0D,
    "TAB": 0x09,
    "ESC": 0x1B,
    "UP": 0x26,
    "DOWN": 0x28,
    "LEFT": 0x25,
    "RIGHT": 0x27,
}


def parse_key_expression(expression: str) -> tuple[tuple[int, ...], ...]:
    """Parse ``CTRL+1,2`` into a validated sequence of key chords."""
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("Key expression cannot be empty")
    sequence: list[tuple[int, ...]] = []
    for raw_chord in expression.split(","):
        names = [part.strip().upper() for part in raw_chord.split("+")]
        if not names or any(not name for name in names):
            raise ValueError(f"Invalid key expression: {expression}")
        try:
            chord = tuple(VIRTUAL_KEYS[name] for name in names)
        except KeyError as error:
            raise ValueError(f"Unsupported key: {error.args[0]}") from error
        if len(set(chord)) != len(chord):
            raise ValueError(f"Duplicate key in chord: {raw_chord.strip()}")
        sequence.append(chord)
    return tuple(sequence)


class KeyboardExecutor:
    """Tracks held keys so cancellation and exceptions cannot leave them pressed."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise WindowsOnlyError("Keyboard output is only available on Windows.")
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
        self._user32.SendInput.restype = wintypes.UINT
        self._held: set[int] = set()
        self._lock = threading.Lock()

    def tap(self, key: str, duration_ms: int, cancelled: threading.Event) -> bool:
        # Comma separates a sequence; plus creates a chord, e.g. CTRL+1,2.
        for keys in parse_key_expression(key):
            if cancelled.is_set():
                return False
            pressed: list[int] = []
            try:
                for vk in keys:
                    self._send(vk, down=True)
                    pressed.append(vk)
                    with self._lock:
                        self._held.add(vk)
                completed = not cancelled.wait(duration_ms / 1000)
            finally:
                release_error: OSError | None = None
                for vk in reversed(pressed):
                    try:
                        self._send(vk, down=False)
                    except OSError as error:
                        release_error = release_error or error
                    finally:
                        with self._lock:
                            self._held.discard(vk)
                if release_error is not None:
                    raise release_error
            if not completed:
                return False
        return True

    def release_all(self) -> None:
        with self._lock:
            held, self._held = self._held, set()
        for vk in held:
            try:
                self._send(vk, down=False)
            except OSError:
                # Try every tracked key even if Windows rejects one event.
                continue

    @staticmethod
    def _virtual_key(key: str) -> int:
        return parse_key_expression(key)[0][0]

    def _send(self, vk: int, down: bool) -> None:
        flags = 0 if down else KEYEVENTF_KEYUP
        event = INPUT(
            type=INPUT_KEYBOARD,
            ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=None),
        )
        result = self._user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))
        if result != 1:
            raise ctypes.WinError(ctypes.get_last_error())
