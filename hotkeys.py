"""Global Windows hotkey support."""
import ctypes
import threading
from ctypes import wintypes


MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
VK_F8 = 0x77
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012


class POINT(ctypes.Structure):
    _fields_ = [
        ("x", wintypes.LONG),
        ("y", wintypes.LONG),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


class GlobalHotkey:
    def __init__(self, on_press, on_log=None, hotkey_id=0xF6F8):
        self.on_press = on_press
        self.on_log = on_log or (lambda msg: None)
        self.hotkey_id = hotkey_id
        self._thread = None
        self._thread_id = None
        self._stop = threading.Event()
        self._registered = threading.Event()
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        self._user32.RegisterHotKey.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            wintypes.UINT,
            wintypes.UINT,
        ]
        self._user32.RegisterHotKey.restype = wintypes.BOOL
        self._user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.UnregisterHotKey.restype = wintypes.BOOL
        self._user32.GetMessageW.argtypes = [
            ctypes.POINTER(MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        ]
        self._user32.GetMessageW.restype = wintypes.BOOL
        self._user32.PostThreadMessageW.argtypes = [
            wintypes.DWORD,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self._user32.PostThreadMessageW.restype = wintypes.BOOL
        self._kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._registered.clear()
        self._thread = threading.Thread(target=self._run, name="global-hotkey", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread_id:
            self._user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

    def _run(self):
        self._thread_id = self._kernel32.GetCurrentThreadId()
        modifiers = MOD_CONTROL | MOD_ALT | MOD_NOREPEAT
        if not self._user32.RegisterHotKey(None, self.hotkey_id, modifiers, VK_F8):
            error = ctypes.get_last_error()
            self.on_log(f"全局热键 Ctrl+Alt+F8 注册失败，错误码：{error}")
            return

        self._registered.set()
        self.on_log("全局热键已启用：Ctrl+Alt+F8 开始/停止（游戏保持前台时可用）。")
        msg = MSG()
        try:
            while not self._stop.is_set():
                result = self._user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result == 0 or result == -1:
                    break
                if msg.message == WM_HOTKEY and msg.wParam == self.hotkey_id:
                    self.on_press()
        finally:
            self._user32.UnregisterHotKey(None, self.hotkey_id)
            self.on_log("全局热键已关闭。")
