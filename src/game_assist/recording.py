from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
import threading
import time

from .input import virtual_key_name
from .windows import WindowsOnlyError, client_rect, is_foreground


WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
HC_ACTION = 0
WM_QUIT = 0x0012
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
WM_MOUSEHWHEEL = 0x020E
LLKHF_INJECTED = 0x10
LLMHF_INJECTED = 0x01
STOP_RECORDING_VK = 0x79  # F10


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


@dataclass(frozen=True)
class RecordedEvent:
    offset_ms: int
    kind: str
    key: str = ""
    x: int = 0
    y: int = 0
    button: str = ""
    delta: int = 0


def recorded_events_to_script(events: tuple[RecordedEvent, ...], name: str = "录制宏") -> str:
    if not events:
        raise ValueError("没有录制到事件；请确认目标窗口在前台后再操作")
    if not name.strip() or "\n" in name or "\r" in name:
        raise ValueError("宏名称必须是非空单行文本")
    lines = [f"macro {name.strip()}", "trigger start", "when always", "repeat 1"]
    previous = 0
    for event in events:
        delay = event.offset_ms - previous
        if delay >= 2:
            lines.append(f"wait {delay}ms")
        previous = event.offset_ms
        if event.kind in {"key_down", "key_up"}:
            lines.append(f"{event.kind} {event.key}")
        elif event.kind == "move":
            lines.append(f"move {event.x} {event.y}")
        elif event.kind in {"mouse_down", "mouse_up"}:
            lines.append(f"{event.kind} {event.button} {event.x} {event.y}")
        elif event.kind in {"wheel", "hwheel"}:
            lines.append(f"{event.kind} {event.delta} {event.x} {event.y}")
        else:
            raise ValueError(f"不支持的录制事件：{event.kind}")
    lines.append("end")
    return "\n".join(lines) + "\n"


class InputRecorder:
    """Foreground-scoped Win32 low-level keyboard and mouse recorder."""

    def __init__(self, hwnd: int, *, sample_interval_ms: int = 20, max_events: int = 5_000) -> None:
        if os.name != "nt":
            raise WindowsOnlyError("Input recording is only available on Windows.")
        self.hwnd = hwnd
        self.sample_interval_ms = sample_interval_ms
        self.max_events = max_events
        self._events: list[RecordedEvent] = []
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self._finished = threading.Event()
        self._stop_requested = threading.Event()
        self._first_event_at: float | None = None
        self._last_move_at = -1.0
        self._last_position: tuple[int, int] | None = None
        self._held_keys: set[str] = set()
        self._held_buttons: set[str] = set()
        self.error: Exception | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop_requested.is_set()

    @property
    def event_count(self) -> int:
        with self._lock:
            return len(self._events)

    @property
    def finished(self) -> bool:
        return self._finished.is_set()

    def start(self) -> None:
        if self.running:
            return
        self._ready.clear()
        self._finished.clear()
        self._stop_requested.clear()
        self.error = None
        self._thread = threading.Thread(target=self._run, name="input-recorder", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=2):
            raise RuntimeError("录制器启动超时")
        if self.error is not None:
            raise self.error

    def stop(self) -> None:
        self._stop_requested.set()
        thread_id = self._thread_id
        if thread_id:
            ctypes.WinDLL("user32", use_last_error=True).PostThreadMessageW(thread_id, WM_QUIT, 0, 0)

    def events(self) -> tuple[RecordedEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def to_script(self, name: str = "录制宏") -> str:
        return recorded_events_to_script(self.events(), name)

    def _run(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        hook_proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.SetWindowsHookExW.argtypes = (ctypes.c_int, hook_proc_type, wintypes.HINSTANCE, wintypes.DWORD)
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        self._thread_id = kernel32.GetCurrentThreadId()

        def keyboard_proc(code: int, message: int, data_address: int) -> int:
            if code == HC_ACTION:
                data = ctypes.cast(data_address, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if data.vkCode == STOP_RECORDING_VK:
                    if message in {WM_KEYDOWN, WM_SYSKEYDOWN}:
                        self.stop()
                    return 1
                if not data.flags & LLKHF_INJECTED and is_foreground(self.hwnd):
                    if message in {WM_KEYDOWN, WM_SYSKEYDOWN, WM_KEYUP, WM_SYSKEYUP}:
                        self._record_key(data.vkCode, message in {WM_KEYDOWN, WM_SYSKEYDOWN})
            return user32.CallNextHookEx(None, code, message, data_address)

        def mouse_proc(code: int, message: int, data_address: int) -> int:
            if code == HC_ACTION:
                data = ctypes.cast(data_address, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                if not data.flags & LLMHF_INJECTED and is_foreground(self.hwnd):
                    self._record_mouse(message, data)
            return user32.CallNextHookEx(None, code, message, data_address)

        keyboard_callback = hook_proc_type(keyboard_proc)
        mouse_callback = hook_proc_type(mouse_proc)
        keyboard_hook = mouse_hook = None
        try:
            keyboard_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, keyboard_callback, None, 0)
            if not keyboard_hook:
                raise ctypes.WinError(ctypes.get_last_error())
            mouse_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, mouse_callback, None, 0)
            if not mouse_hook:
                raise ctypes.WinError(ctypes.get_last_error())
            self._ready.set()
            message = wintypes.MSG()
            while not self._stop_requested.is_set() and user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        except Exception as error:
            self.error = error
            self._ready.set()
        finally:
            if mouse_hook:
                user32.UnhookWindowsHookEx(mouse_hook)
            if keyboard_hook:
                user32.UnhookWindowsHookEx(keyboard_hook)
            self._close_held_inputs()
            self._stop_requested.set()
            self._thread_id = None
            self._finished.set()

    def _timestamp(self) -> int:
        now = time.monotonic()
        if self._first_event_at is None:
            self._first_event_at = now
        return round((now - self._first_event_at) * 1000)

    def _append(self, event: RecordedEvent) -> None:
        with self._lock:
            if len(self._events) >= self.max_events:
                self.error = RuntimeError(f"录制事件超过上限 {self.max_events}，已自动停止")
                self.stop()
                return
            self._events.append(event)

    def _record_key(self, vk: int, down: bool) -> None:
        key = virtual_key_name(int(vk))
        if down and key in self._held_keys:  # Ignore OS key-repeat; hold duration is retained by key_up timing.
            return
        if not down and key not in self._held_keys:
            return
        if down:
            self._held_keys.add(key)
        else:
            self._held_keys.discard(key)
        self._append(RecordedEvent(self._timestamp(), "key_down" if down else "key_up", key=key))

    def _record_mouse(self, message: int, data: MSLLHOOKSTRUCT) -> None:
        rect = client_rect(self.hwnd)
        if rect is None:
            return
        x, y = int(data.pt.x - rect.left), int(data.pt.y - rect.top)
        now = time.monotonic()
        if message == WM_MOUSEMOVE:
            if self._last_position == (x, y) or (now - self._last_move_at) * 1000 < self.sample_interval_ms:
                return
            self._last_move_at = now
            self._last_position = (x, y)
            self._append(RecordedEvent(self._timestamp(), "move", x=x, y=y))
            return
        button_messages = {
            WM_LBUTTONDOWN: ("left", True), WM_LBUTTONUP: ("left", False),
            WM_RBUTTONDOWN: ("right", True), WM_RBUTTONUP: ("right", False),
            WM_MBUTTONDOWN: ("middle", True), WM_MBUTTONUP: ("middle", False),
        }
        if message in {WM_XBUTTONDOWN, WM_XBUTTONUP}:
            button = "x2" if ((int(data.mouseData) >> 16) & 0xFFFF) == 2 else "x1"
            button_messages[message] = (button, message == WM_XBUTTONDOWN)
        if message in button_messages:
            button, down = button_messages[message]
            if down:
                self._held_buttons.add(button)
            else:
                self._held_buttons.discard(button)
            self._last_position = (x, y)
            self._append(RecordedEvent(self._timestamp(), "mouse_down" if down else "mouse_up", x=x, y=y, button=button))
        elif message in {WM_MOUSEWHEEL, WM_MOUSEHWHEEL}:
            raw_delta = (int(data.mouseData) >> 16) & 0xFFFF
            delta = raw_delta - 0x10000 if raw_delta & 0x8000 else raw_delta
            self._append(RecordedEvent(self._timestamp(), "hwheel" if message == WM_MOUSEHWHEEL else "wheel", x=x, y=y, delta=delta))

    def _close_held_inputs(self) -> None:
        offset = self._events[-1].offset_ms + 1 if self._events else 0
        for key in sorted(self._held_keys):
            self._append(RecordedEvent(offset, "key_up", key=key))
        x, y = self._last_position or (0, 0)
        for button in sorted(self._held_buttons):
            self._append(RecordedEvent(offset, "mouse_up", x=x, y=y, button=button))
        self._held_keys.clear()
        self._held_buttons.clear()
