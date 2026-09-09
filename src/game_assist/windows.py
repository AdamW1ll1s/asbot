from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os


if os.name == "nt":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = (WNDENUMPROC, wintypes.LPARAM)
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    user32.GetClientRect.restype = wintypes.BOOL
    user32.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
    user32.ClientToScreen.restype = wintypes.BOOL
    user32.GetForegroundWindow.argtypes = ()
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    user32.SetForegroundWindow.restype = wintypes.BOOL
else:
    user32 = None
    WNDENUMPROC = None


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

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return matches[0] if matches else None


def list_visible_windows() -> list[VisibleWindow]:
    """Return titled, visible top-level windows for the desktop picker."""
    _require_windows()
    windows: list[VisibleWindow] = []

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

    user32.EnumWindows(WNDENUMPROC(callback), 0)
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


def activate_window(hwnd: int) -> bool:
    """Request foreground focus for a visible target window.

    Windows may decline this request due to its foreground-lock rules; callers
    must still verify focus before sending input.
    """
    _require_windows()
    if is_foreground(hwnd):
        return True
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE: restore a minimized target first.
    return bool(user32.SetForegroundWindow(hwnd))
