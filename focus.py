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
    kernel32 = ctypes.windll.kernel32
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
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.AttachThreadInput.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.SetActiveWindow.argtypes = [wintypes.HWND]
    user32.SetActiveWindow.restype = wintypes.HWND
    user32.SetFocus.argtypes = [wintypes.HWND]
    user32.SetFocus.restype = wintypes.HWND
    user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
    user32.AllowSetForegroundWindow.restype = wintypes.BOOL
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD

WM_ACTIVATE = 0x0006
WA_ACTIVE = 1
SW_RESTORE = 9
ASFW_ANY = 0xFFFFFFFF
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

if user32:
    _LONG_PTR = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
    try:
        GetWindowLongPtr = user32.GetWindowLongPtrW
        SetWindowLongPtr = user32.SetWindowLongPtrW
    except AttributeError:
        GetWindowLongPtr = user32.GetWindowLongW
        SetWindowLongPtr = user32.SetWindowLongW
    GetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int]
    GetWindowLongPtr.restype = _LONG_PTR
    SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, _LONG_PTR]
    SetWindowLongPtr.restype = _LONG_PTR
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL


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


def window_title(hwnd):
    if not user32 or not hwnd:
        return ""
    n = user32.GetWindowTextLengthW(hwnd)
    if not n:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def foreground_title():
    if not user32:
        return ""
    return window_title(user32.GetForegroundWindow())


def is_foreground(title_substr="Forza"):
    title = foreground_title()
    return bool(title_substr and title_substr.lower() in title.lower())


def activate_window(title_substr="Forza", attempts=5, on_log=None, logger=None):
    """Bring the matching game window back to the foreground."""
    on_log = on_log or (lambda m: None)
    if not user32:
        on_log("切回游戏仅支持 Windows。")
        return False

    hwnd = find_window(title_substr)
    if not hwnd:
        on_log(f"没找到标题含“{title_substr}”的游戏窗口。")
        return False

    title = window_title(hwnd)
    if logger:
        logger.info("Activating game window hwnd=%s title=%r", hwnd, title)

    current_thread = kernel32.GetCurrentThreadId()
    for attempt in range(1, attempts + 1):
        foreground = user32.GetForegroundWindow()
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)
        foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0

        attached = []
        for thread_id in {target_thread, foreground_thread}:
            if thread_id and thread_id != current_thread:
                if user32.AttachThreadInput(current_thread, thread_id, True):
                    attached.append(thread_id)

        try:
            user32.AllowSetForegroundWindow(ASFW_ANY)
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.BringWindowToTop(hwnd)
            user32.SetActiveWindow(hwnd)
            user32.SetFocus(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.PostMessageW(hwnd, WM_ACTIVATE, WA_ACTIVE, 0)
        finally:
            for thread_id in attached:
                user32.AttachThreadInput(current_thread, thread_id, False)

        time.sleep(0.15)
        active = user32.GetForegroundWindow()
        active_title = window_title(active)
        if logger:
            logger.info(
                "Activate attempt %d target=%s foreground=%s foreground_title=%r",
                attempt,
                hwnd,
                active,
                active_title,
            )
        if active == hwnd:
            on_log(f"已切回游戏窗口：{title}")
            return True

    on_log(f"尝试切回游戏失败；当前前台窗口：{foreground_title() or '未知'}")
    return False


def set_no_activate(hwnd, enabled=True, topmost=True, logger=None):
    """Make a helper window clickable without becoming the foreground window."""
    if not user32 or not hwnd:
        return False

    current_style = int(GetWindowLongPtr(hwnd, GWL_EXSTYLE))
    new_style = current_style | WS_EX_NOACTIVATE if enabled else current_style & ~WS_EX_NOACTIVATE
    SetWindowLongPtr(hwnd, GWL_EXSTYLE, _LONG_PTR(new_style))

    insert_after = HWND_TOPMOST if topmost else HWND_NOTOPMOST
    flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED
    ok = bool(user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, flags))
    if logger:
        logger.info(
            "set_no_activate hwnd=%s enabled=%s topmost=%s style_before=%s style_after=%s ok=%s",
            hwnd,
            enabled,
            topmost,
            current_style,
            new_style,
            ok,
        )
    return ok


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
