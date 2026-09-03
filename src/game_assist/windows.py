from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os


if os.name == "nt":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
else:
    user32 = None


@dataclass(frozen=True)
class ClientRect:
    left: int
    top: int
    width: int
    height: int


@dataclass(frozen=True)
class VisibleWindow:
    """A user-selectable top-level window."""

    hwnd: int
    title: str
    process_id: int


class WindowsOnlyError(RuntimeError):
    pass


def _require_windows() -> None:
    if user32 is None:
        raise WindowsOnlyError("This command must run on Windows.")


def find_window(title_contains: str, process_id: int | None = None) -> int | None:
    _require_windows()
    matches: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, _: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, len(title))
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if process_id is not None and pid.value != process_id:
            return True
        if title_contains.casefold() in title.value.casefold():
            matches.append(hwnd)
            return False
        return True

    user32.EnumWindows(callback_type(callback), 0)
    return matches[0] if matches else None


def list_visible_windows() -> list[VisibleWindow]:
    """Return titled, visible top-level windows for the desktop picker."""
    _require_windows()
    windows: list[VisibleWindow] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, _: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, len(title))
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        windows.append(VisibleWindow(hwnd=hwnd, title=title.value, process_id=process_id.value))
        return True

    user32.EnumWindows(callback_type(callback), 0)
    return sorted(windows, key=lambda item: item.title.casefold())


def client_rect(hwnd: int) -> ClientRect | None:
    _require_windows()
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    point = wintypes.POINT(rect.left, rect.top)
    if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
        return None
    width, height = rect.right - rect.left, rect.bottom - rect.top
    return ClientRect(point.x, point.y, width, height) if width > 0 and height > 0 else None


def is_foreground(hwnd: int) -> bool:
    _require_windows()
    return user32.GetForegroundWindow() == hwnd
