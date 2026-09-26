"""Windows monitor and top-level-window discovery."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass


user32 = ctypes.windll.user32
user32.SetProcessDPIAware()


@dataclass(frozen=True)
class WindowInfo:
    pid: int
    title: str
    left: int
    top: int
    right: int
    bottom: int

    @property
    def center_x(self) -> float:
        return (self.left + self.right) / 2.0

    @property
    def area(self) -> int:
        return max(0, self.right - self.left) * max(0, self.bottom - self.top)


def virtual_desktop_bounds() -> tuple[int, int]:
    """Return horizontal bounds for the complete virtual desktop."""
    left = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
    width = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
    return left, left + width


def visible_windows_by_pid() -> dict[int, WindowInfo]:
    """Return the largest ordinary visible top-level window for each process."""
    result: dict[int, WindowInfo] = {}
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @enum_proc
    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        if user32.GetWindow(hwnd, 4):  # GW_OWNER: skip owned popups/tool windows
            return True

        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        title_buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, length + 1)

        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        info = WindowInfo(0, title_buffer.value, rect.left, rect.top, rect.right, rect.bottom)
        if info.area < 2_500:
            return True

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        info = WindowInfo(pid.value, info.title, info.left, info.top, info.right, info.bottom)
        existing = result.get(pid.value)
        if existing is None or info.area > existing.area:
            result[pid.value] = info
        return True

    user32.EnumWindows(callback, 0)
    return result

