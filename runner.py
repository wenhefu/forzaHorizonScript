"""Runs an action sequence on the virtual gamepad in a background thread."""
import threading
import time


class Runner:
    def __init__(self, on_log=None):
        self.on_log = on_log or (lambda msg: None)
        self._thread = None
        self._stop = threading.Event()

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, sequence, startup_delay=5.0, total_seconds=None):
        if self.is_running():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(sequence, startup_delay, total_seconds),
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _sleep(self, seconds):
        """Sleep, but wake early if Stop was pressed. Returns False if interrupted."""
        end = time.time() + seconds
        while time.time() < end:
            if self._stop.is_set():
                return False
            time.sleep(min(0.05, max(0.0, end - time.time())))
        return not self._stop.is_set()

    def _run(self, sequence, startup_delay, total_seconds):
        try:
            from gamepad import Gamepad  # imported here so the GUI still opens even if
            pad = Gamepad()              # ViGEmBus is missing (we show a friendly error)
        except Exception as e:
            self.on_log(f"无法启动虚拟手柄：{e}")
            return

        self.on_log(f"{startup_delay:.0f} 秒后开始，请切换到地平线…")
        if not self._sleep(startup_delay):
            pad.neutral()
            self.on_log("已取消。")
            return

        deadline = None if not total_seconds else time.time() + total_seconds
        self.on_log("开始运行（按停止可随时中断）。")
        lap = 0
        try:
            while not self._stop.is_set() and (deadline is None or time.time() < deadline):
                lap += 1
                self.on_log(f"第 {lap} 圈…")
                for step in sequence:
                    if self._stop.is_set():
                        break
                    pad.apply(
                        throttle=step.get("throttle", 0.0),
                        brake=step.get("brake", 0.0),
                        steer=step.get("steer", 0.0),
                        buttons=step.get("buttons", ()),
                    )
                    if not self._sleep(step.get("duration", 0.5)):
                        break
                    if deadline is not None and time.time() >= deadline:
                        break
        finally:
            pad.neutral()  # never leave throttle stuck on
            self.on_log("已停止，手柄已释放。")
