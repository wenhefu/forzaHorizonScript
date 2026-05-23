"""Runs an action sequence on the virtual gamepad in a background thread."""
import logging
import threading
import time


class Runner:
    def __init__(self, on_log=None, logger=None, pad_provider=None):
        self.on_log = on_log or (lambda msg: None)
        self.logger = logger or logging.getLogger("forza6helper")
        self.pad_provider = pad_provider
        self.require_foreground = False
        self.foreground_check = None
        self.on_focus_lost = None
        self.on_focus_restored = None
        self._waiting_for_focus = False
        self._thread = None
        self._stop = threading.Event()

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, sequence, startup_delay=5.0, total_seconds=None, resume_button=None,
              require_foreground=False, foreground_check=None,
              on_focus_lost=None, on_focus_restored=None):
        if self.is_running():
            self.logger.info("Runner start ignored because it is already running")
            return
        self._stop.clear()
        self.require_foreground = require_foreground
        self.foreground_check = foreground_check
        self.on_focus_lost = on_focus_lost
        self.on_focus_restored = on_focus_restored
        self._waiting_for_focus = False
        self.logger.info(
            "Runner starting startup_delay=%.2f total_seconds=%s sequence_steps=%d resume_button=%s require_foreground=%s",
            startup_delay,
            "unlimited" if total_seconds is None else f"{total_seconds:.2f}",
            len(sequence),
            resume_button,
            require_foreground,
        )
        self._thread = threading.Thread(
            target=self._run,
            args=(sequence, startup_delay, total_seconds, resume_button),
            name="farm-runner",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self.logger.info("Runner stop requested")
        self._stop.set()

    def _sleep(self, seconds):
        """Sleep, but wake early if Stop was pressed. Returns False if interrupted."""
        remaining = max(0.0, seconds)
        last = time.monotonic()
        while remaining > 0:
            if self._stop.is_set():
                self.logger.info("Sleep interrupted by stop request")
                return False

            now = time.monotonic()
            elapsed = now - last
            last = now

            if self._game_time_can_advance():
                remaining -= elapsed
                if self._waiting_for_focus:
                    self._waiting_for_focus = False
                    self.logger.info("Forza foreground restored; resuming timer")
                    self.on_log("游戏已回到前台，继续计时。")
                    if self.on_focus_restored:
                        self.on_focus_restored()
            elif not self._waiting_for_focus:
                self._waiting_for_focus = True
                self.logger.info("Forza is not foreground; pausing timer with %.2fs remaining", remaining)
                self.on_log(f"检测到游戏失焦，暂停脚本计时（剩余 {remaining:.1f} 秒）。")
                if self.on_focus_lost:
                    self.on_focus_lost()

            time.sleep(min(0.05, max(0.0, remaining)))
        if self._stop.is_set():
            self.logger.info("Sleep completed with stop already requested")
            return False
        return True

    def _game_time_can_advance(self):
        if not self.require_foreground:
            return True
        if not self.foreground_check:
            return True
        try:
            return bool(self.foreground_check())
        except Exception:
            self.logger.exception("Foreground check failed; allowing timer to continue")
            return True

    def _run(self, sequence, startup_delay, total_seconds, resume_button):
        try:
            if self.pad_provider:
                pad = self.pad_provider()
            else:
                # Imported here so the GUI still opens even if ViGEmBus is missing.
                from gamepad import Gamepad
                pad = Gamepad(logger=self.logger)
        except Exception as e:
            self.logger.exception("Unable to start virtual gamepad")
            self.on_log(f"无法启动虚拟手柄：{e}")
            return

        self.on_log("虚拟手柄已连接；如果游戏仍提示未连接，请先点“按A确认”。")
        if resume_button:
            self.on_log(f"尝试按 {resume_button.upper()} 处理当前菜单…")
            self.logger.info("Sending resume button before startup delay: %s", resume_button)
            if not self._sleep(0.3):
                pad.neutral()
                self.on_log("已取消。")
                return
            pad.tap(resume_button, hold=0.12)
            if not self._sleep(0.6):
                pad.neutral()
                self.on_log("已取消。")
                return

        self.on_log(f"{startup_delay:.0f} 秒后开始，请切换到地平线…")
        if not self._sleep(startup_delay):
            pad.neutral()
            self.on_log("已取消。")
            return

        total_remaining = None if not total_seconds else float(total_seconds)
        self.on_log("开始运行（按停止可随时中断）。")
        lap = 0
        try:
            while not self._stop.is_set() and (total_remaining is None or total_remaining > 0):
                lap += 1
                self.on_log(f"第 {lap} 圈…")
                for index, step in enumerate(sequence, start=1):
                    if self._stop.is_set():
                        break
                    self.logger.debug(
                        "lap=%d step=%d throttle=%s brake=%s steer=%s buttons=%s duration=%s",
                        lap,
                        index,
                        step.get("throttle", 0.0),
                        step.get("brake", 0.0),
                        step.get("steer", 0.0),
                        step.get("buttons", ()),
                        step.get("duration", 0.5),
                    )
                    pad.apply(
                        throttle=step.get("throttle", 0.0),
                        brake=step.get("brake", 0.0),
                        steer=step.get("steer", 0.0),
                        buttons=step.get("buttons", ()),
                    )
                    duration = step.get("duration", 0.5)
                    if not self._sleep(duration):
                        break
                    if total_remaining is not None:
                        total_remaining -= duration
                        if total_remaining <= 0:
                            self.logger.info("Total runtime deadline reached")
                            break
        except Exception as exc:
            self.logger.exception("Runner crashed while applying sequence")
            self.on_log(f"运行时出错：{exc}")
        finally:
            pad.neutral()  # never leave throttle stuck on
            self.on_log("已停止，手柄保持连接并已回正。")
