from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import threading

from .windows import WindowsOnlyError


KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG), ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_void_p),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


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
    "BACKSPACE": 0x08,
    "CAPSLOCK": 0x14,
    "PAGEUP": 0x21,
    "PAGEDOWN": 0x22,
    "END": 0x23,
    "HOME": 0x24,
    "INSERT": 0x2D,
    "DELETE": 0x2E,
}


def virtual_key_name(vk: int) -> str:
    """Return a stable DSL name even for keys not in the friendly-name table."""
    return next((name for name, value in VIRTUAL_KEYS.items() if value == vk), f"VK_{vk:02X}")


def parse_single_key(name: str) -> int:
    normalized = name.strip().upper()
    if normalized in VIRTUAL_KEYS:
        return VIRTUAL_KEYS[normalized]
    if normalized.startswith("VK_"):
        try:
            value = int(normalized[3:], 16)
        except ValueError as error:
            raise ValueError(f"Unsupported key: {name}") from error
        if 1 <= value <= 0xFE:
            return value
    raise ValueError(f"Unsupported key: {name}")


def parse_key_expression(expression: str) -> tuple[tuple[int, ...], ...]:
    """Parse ``CTRL+1,2`` into a validated sequence of key chords."""
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("Key expression cannot be empty")
    sequence: list[tuple[int, ...]] = []
    for raw_chord in expression.split(","):
        names = [part.strip().upper() for part in raw_chord.split("+")]
        if not names or any(not name for name in names):
            raise ValueError(f"Invalid key expression: {expression}")
        chord = tuple(parse_single_key(name) for name in names)
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
        self._user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
        self._user32.GetSystemMetrics.restype = ctypes.c_int
        self._held: set[int] = set()
        self._held_mouse: set[str] = set()
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
            held_mouse, self._held_mouse = self._held_mouse, set()
        for vk in held:
            try:
                self._send(vk, down=False)
            except OSError:
                # Try every tracked key even if Windows rejects one event.
                continue
        for button in held_mouse:
            try:
                self._mouse_button(button, down=False)
            except (OSError, ValueError):
                continue

    def perform(
        self,
        action_type: str,
        *,
        key: str = "",
        duration_ms: int = 0,
        x: int | None = None,
        y: int | None = None,
        button: str | None = None,
        wheel_delta: int = 0,
        client_origin: tuple[int, int] | None = None,
        cancelled: threading.Event,
    ) -> bool:
        """Execute one host-approved keyboard or mouse action."""
        if cancelled.is_set():
            return False
        if action_type == "key_tap":
            return self.tap(key, duration_ms, cancelled)
        if action_type in {"key_down", "key_up"}:
            vk = parse_single_key(key)
            self._send(vk, down=action_type == "key_down")
            with self._lock:
                (self._held.add if action_type == "key_down" else self._held.discard)(vk)
            return True
        if action_type == "mouse_move":
            self._move_mouse(x, y, client_origin)
            return True
        if action_type in {"mouse_down", "mouse_up"}:
            self._move_mouse(x, y, client_origin)
            button_name = (button or "left").lower()
            is_down = action_type == "mouse_down"
            self._mouse_button(button_name, is_down)
            with self._lock:
                (self._held_mouse.add if is_down else self._held_mouse.discard)(button_name)
            return True
        if action_type in {"mouse_wheel", "mouse_hwheel"}:
            self._move_mouse(x, y, client_origin)
            self._send_mouse(
                MOUSEEVENTF_WHEEL if action_type == "mouse_wheel" else MOUSEEVENTF_HWHEEL,
                mouse_data=wheel_delta,
            )
            return True
        raise ValueError(f"Unsupported input action: {action_type}")

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

    def _move_mouse(self, x: int | None, y: int | None, client_origin: tuple[int, int] | None) -> None:
        if x is None or y is None or client_origin is None:
            raise ValueError("Mouse action requires client-relative coordinates")
        screen_x, screen_y = client_origin[0] + x, client_origin[1] + y
        virtual_left = self._user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
        virtual_top = self._user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
        virtual_width = self._user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
        virtual_height = self._user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
        if virtual_width <= 1 or virtual_height <= 1:
            raise OSError("Windows virtual desktop dimensions are unavailable")
        normalized_x = round((screen_x - virtual_left) * 65535 / (virtual_width - 1))
        normalized_y = round((screen_y - virtual_top) * 65535 / (virtual_height - 1))
        self._send_mouse(
            MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
            dx=max(0, min(65535, normalized_x)),
            dy=max(0, min(65535, normalized_y)),
        )

    def _mouse_button(self, button: str, down: bool) -> None:
        flags = {
            ("left", True): MOUSEEVENTF_LEFTDOWN,
            ("left", False): MOUSEEVENTF_LEFTUP,
            ("right", True): MOUSEEVENTF_RIGHTDOWN,
            ("right", False): MOUSEEVENTF_RIGHTUP,
            ("middle", True): MOUSEEVENTF_MIDDLEDOWN,
            ("middle", False): MOUSEEVENTF_MIDDLEUP,
            ("x1", True): MOUSEEVENTF_XDOWN,
            ("x1", False): MOUSEEVENTF_XUP,
            ("x2", True): MOUSEEVENTF_XDOWN,
            ("x2", False): MOUSEEVENTF_XUP,
        }
        try:
            flag = flags[(button.lower(), down)]
        except KeyError as error:
            raise ValueError(f"Unsupported mouse button: {button}") from error
        self._send_mouse(flag, mouse_data=2 if button.lower() == "x2" else 1 if button.lower() == "x1" else 0)

    def _send_mouse(self, flags: int, *, dx: int = 0, dy: int = 0, mouse_data: int = 0) -> None:
        event = INPUT(
            type=INPUT_MOUSE,
            mi=MOUSEINPUT(dx=dx, dy=dy, mouseData=mouse_data & 0xFFFFFFFF, dwFlags=flags, time=0, dwExtraInfo=None),
        )
        result = self._user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))
        if result != 1:
            raise ctypes.WinError(ctypes.get_last_error())
