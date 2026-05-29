from __future__ import annotations

import argparse
import ctypes
from dataclasses import asdict, dataclass
import json
import time

import focus


SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010


@dataclass
class WindowSizeResult:
    hwnd: int
    title: str
    before: tuple[int, int, int, int]
    after: tuple[int, int, int, int]


def _window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = ctypes.wintypes.RECT()
    if not focus.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError("GetWindowRect failed")
    return rect.left, rect.top, rect.right, rect.bottom


def resize_window(title: str, width: int, height: int, x: int | None = None, y: int | None = None) -> WindowSizeResult:
    hwnd = focus.find_window(title)
    if not hwnd:
        raise RuntimeError(f"No window title contains {title!r}")
    before = _window_rect(hwnd)
    left, top, _, _ = before
    if x is None:
        x = left
    if y is None:
        y = top
    focus.user32.ShowWindow(hwnd, focus.SW_RESTORE)
    ok = focus.user32.SetWindowPos(hwnd, None, int(x), int(y), int(width), int(height), SWP_NOZORDER | SWP_NOACTIVATE)
    if not ok:
        raise RuntimeError("SetWindowPos failed")
    time.sleep(0.8)
    after = _window_rect(hwnd)
    return WindowSizeResult(hwnd=int(hwnd), title=focus.window_title(hwnd) or title, before=before, after=after)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resize the Forza window for multi-size Vision sampling.")
    parser.add_argument("--title", default="Forza")
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--x", type=int)
    parser.add_argument("--y", type=int)
    args = parser.parse_args(argv)
    result = resize_window(args.title, args.width, args.height, args.x, args.y)
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
