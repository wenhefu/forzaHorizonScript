"""Optional, NON-injecting 'keep the game active' helper (Windows only).

Periodically tells the game window it is active (WM_ACTIVATE), so some games don't
pause when unfocused. It does NOT inject into or modify the game process, so it
won't trip anti-cheat. May or may not work depending on how the game detects focus
- Borderless Windowed mode is the more reliable, zero-tool fix to try first.
"""
import ctypes
import threading
import time

try:
    user32 = ctypes.windll.user32
    from ctypes import wintypes
except (AttributeError, ValueError):
    user32 = None  # not on Windows; KeepActive will no-op

if user32:
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL

WM_ACTIVATE = 0x0006
WA_ACTIVE = 1


def find_window(title_substr):
    """HWND of the first visible top-level window whose title contains the keyword."""
    if not user32:
        return None
    found = {"hwnd": None}
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _):
        n = user32.GetWindowTextLengthW(hwnd)
        if n and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if title_substr.lower() in buf.value.lower():
                found["hwnd"] = hwnd
                return False  # stop enumerating
        return True

    user32.EnumWindows(proto(callback), 0)
    return found["hwnd"]


class KeepActive:
    def __init__(self, title_substr="Forza", interval=1.0, on_log=None):
        self.title_substr = title_substr
        self.interval = interval
        self.on_log = on_log or (lambda m: None)
        self._thread = None
        self._stop = threading.Event()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        if not user32:
            self.on_log("保持活动仅支持 Windows。")
            return
        hwnd = find_window(self.title_substr)
        if not hwnd:
            self.on_log(f"没找到标题含“{self.title_substr}”的窗口，保持活动未生效。")
            return
        self.on_log("保持活动已开启（实验性）。")
        while not self._stop.is_set():
            user32.PostMessageW(hwnd, WM_ACTIVATE, WA_ACTIVE, 0)
            time.sleep(self.interval)
