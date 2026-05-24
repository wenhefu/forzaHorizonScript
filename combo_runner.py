"""Combined buy-car and EventLab farming flow."""
import logging
import threading
import time

import config
import focus
from buy_car_detector import (
    STATE_CONFIRM_MODAL,
    STATE_CONTROLLER_DISCONNECTED,
    STATE_CREATIVE_HUB,
    STATE_EVENTLAB_EVENTS,
    STATE_EVENTLAB_FAVORITES,
    STATE_EVENTLAB_MENU,
    STATE_PAUSE_MENU,
    STATE_SKILL_POINTS_EXHAUSTED,
)
from buy_car_runner import BuyCarRunner
from screen_detector import (
    STATE_PRESTART,
    STATE_PRESTART_WRONG_SELECTION,
)
from smart_runner import SmartRunner


class ComboRunner:
    """Buy Subaru 22B until points run out, then route into EventLab farming."""

    def __init__(self, on_log=None, logger=None, pad_provider=None):
        self.on_log = on_log or (lambda msg: None)
        self.logger = logger or logging.getLogger("forza6helper")
        self.pad_provider = pad_provider
        self.buy_runner = BuyCarRunner(on_log=self.on_log, logger=self.logger, pad_provider=pad_provider)
        self.smart_runner = SmartRunner(on_log=self.on_log, logger=self.logger, pad_provider=pad_provider)
        self._thread = None
        self._stop = threading.Event()

    def is_running(self):
        return (
            self._thread is not None
            and self._thread.is_alive()
        ) or self.buy_runner.is_running() or self.smart_runner.is_running()

    def start(self, startup_delay=0.0, total_seconds=None, auto_focus=True, require_foreground=True):
        if self.is_running():
            self.logger.info("ComboRunner start ignored because it is already running")
            return
        self._stop.clear()
        self.logger.info(
            "ComboRunner starting startup_delay=%.2f total_seconds=%s auto_focus=%s require_foreground=%s",
            startup_delay,
            "unlimited" if total_seconds is None else f"{total_seconds:.2f}",
            auto_focus,
            require_foreground,
        )
        self._thread = threading.Thread(
            target=self._run,
            args=(startup_delay, total_seconds, auto_focus, require_foreground),
            name="combo-runner",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self.logger.info("ComboRunner stop requested")
        self._stop.set()
        self.buy_runner.stop()
        self.smart_runner.stop()

    def detect_once(self):
        return self.buy_runner.detect_once()

    def _sleep(self, seconds):
        end = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < end:
            if self._stop.is_set():
                return False
            time.sleep(min(0.05, max(0.0, end - time.monotonic())))
        return not self._stop.is_set()

    def _remaining(self, started, total_seconds):
        if total_seconds is None:
            return None
        remaining = total_seconds - (time.monotonic() - started)
        return max(0.0, remaining)

    def _tap(self, pad, button, hold=0.15, after=0.75):
        self.buy_runner._invalidate_ocr()
        pad.tap(button, hold=hold)
        self.buy_runner._invalidate_ocr()
        return self._sleep(after)

    def _tap_many(self, pad, button, count, after_each=0.55):
        for _ in range(count):
            if not self._tap(pad, button, hold=0.12, after=after_each):
                return False
        return True

    def _ensure_foreground(self, auto_focus, require_foreground):
        if not require_foreground or focus.is_foreground(config.GAME_TITLE):
            return True
        self.on_log("组合模式：游戏不在前台，先暂停输入并尝试切回。")
        if auto_focus:
            focus.activate_window(
                title_substr=config.GAME_TITLE,
                on_log=self.on_log,
                logger=self.logger,
            )
        return self._sleep(1.0)

    def _run(self, startup_delay, total_seconds, auto_focus, require_foreground):
        try:
            pad = self.pad_provider()
        except Exception as exc:
            self.logger.exception("Unable to start combo runner gamepad")
            self.on_log(f"无法启动虚拟手柄：{exc}")
            return

        started = time.monotonic()
        try:
            if startup_delay > 0:
                self.on_log(f"{startup_delay:.0f} 秒后开始组合模式：先买车加点，点数不足后去 EventLab 刷分。")
                if not self._sleep(startup_delay):
                    return

            remaining = self._remaining(started, total_seconds)
            if remaining is not None and remaining <= 0:
                self.on_log("组合模式：总运行时间已到，未启动买车阶段。")
                return

            self.on_log("组合模式：买车加点阶段开始，直到检测到技术点数不足。")
            self.buy_runner.start(
                startup_delay=0.0,
                total_seconds=remaining,
                auto_focus=auto_focus,
                require_foreground=require_foreground,
            )
            while self.buy_runner.is_running() and not self._stop.is_set():
                if not self._sleep(0.25):
                    break

            if self._stop.is_set():
                return
            if self.buy_runner.stop_reason != "points_exhausted":
                self.on_log("组合模式：买车阶段停止原因不是点数不足，先不继续切 EventLab。")
                return

            self.on_log("组合模式：确认是技术点数不足，开始退回自由漫游并打开 EventLab。")
            if not self._navigate_to_eventlab_prestart(pad, auto_focus, require_foreground):
                self.on_log("组合模式：没有稳定进入 EventLab 开始赛事菜单，已停止，避免乱按。")
                return

            remaining = self._remaining(started, total_seconds)
            if remaining is not None and remaining <= 0:
                self.on_log("组合模式：总运行时间已到，已进入 EventLab 但不再启动刷分。")
                return

            self.on_log("组合模式：已到 EventLab 开始赛事菜单，交给刷技能点模式继续跑。")
            self.smart_runner.start(
                startup_delay=0.0,
                total_seconds=remaining,
                auto_focus=auto_focus,
                require_foreground=require_foreground,
            )
            while self.smart_runner.is_running() and not self._stop.is_set():
                if not self._sleep(0.25):
                    break
        except Exception as exc:
            self.logger.exception("ComboRunner crashed")
            self.on_log(f"组合模式运行时出错：{exc}")
        finally:
            if self._stop.is_set():
                self.buy_runner.stop()
                self.smart_runner.stop()
            pad.neutral()
            self.on_log("组合模式已停止，手柄保持连接并已回正。")

    def _navigate_to_eventlab_prestart(self, pad, auto_focus, require_foreground):
        if not self._ensure_foreground(auto_focus, require_foreground):
            return False

        # We should be on the "not enough skill points" modal. Close it, then back
        # out through mastery -> upgrade -> vehicle -> free roam.
        if not self._confirm_or_close_points_modal(pad, auto_focus, require_foreground):
            return False
        if not self._tap(pad, "b", after=1.0):
            return False
        if not self._tap(pad, "b", after=1.0):
            return False
        if not self._tap(pad, "b", after=1.8):
            return False

        self.on_log("组合模式：已退到自由漫游附近，按 Menu 打开暂停菜单。")
        if not self._tap(pad, "start", after=1.3):
            return False

        if not self._wait_buy_state("暂停菜单", {STATE_PAUSE_MENU}, timeout=8.0, auto_focus=auto_focus, require_foreground=require_foreground):
            self.on_log("组合模式：未确认暂停菜单，补按一次 Menu。")
            if not self._tap(pad, "start", after=1.3):
                return False
            self._wait_buy_state("暂停菜单", {STATE_PAUSE_MENU}, timeout=4.0, auto_focus=auto_focus, require_foreground=require_foreground)

        if not self._move_to_creative_hub(pad, auto_focus, require_foreground):
            return False

        self.on_log("组合模式：创意中心页按 A 进入 EventLab。")
        if not self._tap(pad, "a", after=1.5):
            return False
        if not self._wait_buy_state("EventLab 首页", {STATE_EVENTLAB_MENU}, timeout=8.0, auto_focus=auto_focus, require_foreground=require_foreground):
            return False

        self.on_log("组合模式：EventLab 首页按 A 进入赛事。")
        if not self._tap(pad, "a", after=1.6):
            return False
        if not self._wait_buy_state("EventLab 赛事页", {STATE_EVENTLAB_EVENTS, STATE_EVENTLAB_FAVORITES}, timeout=10.0, auto_focus=auto_focus, require_foreground=require_foreground):
            return False

        if not self._move_to_eventlab_favorites(pad, auto_focus, require_foreground):
            return False

        if not self._tap(pad, "a", after=2.0):
            return False
        return self._wait_for_prestart(pad, auto_focus, require_foreground)

    def _confirm_or_close_points_modal(self, pad, auto_focus, require_foreground):
        detection = self._detect_buy(auto_focus, require_foreground)
        if detection and detection.state == STATE_SKILL_POINTS_EXHAUSTED:
            self.on_log("组合模式：点数不足弹窗已确认，按 A 关闭。")
        else:
            self.on_log("组合模式：准备按 A 关闭当前弹窗，再回到熟练度页。")
        return self._tap(pad, "a", after=1.0)

    def _move_to_creative_hub(self, pad, auto_focus, require_foreground):
        self.on_log("组合模式：切到创意中心，识别到就停，最多按 6 次 RB。")
        for press_index in range(0, 7):
            detection = self._detect_buy(auto_focus, require_foreground)
            if detection is None:
                return False
            if detection.state == STATE_CREATIVE_HUB:
                self.on_log("组合模式：已确认创意中心。")
                return True
            if press_index >= 6:
                break
            self.on_log(f"组合模式：还没到创意中心，按 RB（{press_index + 1}/6）。")
            if not self._tap(pad, "rb", after=0.65):
                return False
        self.on_log("组合模式：未能确认创意中心，停止在当前页面。")
        return False

    def _move_to_eventlab_favorites(self, pad, auto_focus, require_foreground):
        self.on_log("组合模式：切到 EventLab 我的收藏，识别到就停，最多按 9 次 RB。")
        for press_index in range(0, 10):
            detection = self._detect_buy(auto_focus, require_foreground)
            if detection is None:
                return False
            if detection.state == STATE_EVENTLAB_FAVORITES:
                self.on_log("组合模式：已确认我的收藏。")
                return True
            if press_index >= 9:
                break
            self.on_log(f"组合模式：还没到我的收藏，按 RB（{press_index + 1}/9）。")
            if not self._tap(pad, "rb", after=0.45):
                return False
        self.on_log("组合模式：未能确认我的收藏，停止在当前页面。")
        return False

    def _wait_buy_state(self, label, target_states, timeout, auto_focus, require_foreground, pad=None):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self._stop.is_set():
            detection = self._detect_buy(auto_focus, require_foreground)
            if detection is None:
                return False
            self.logger.info(
                "Combo wait %s state=%s confidence=%.3f",
                label,
                detection.state,
                detection.confidence,
            )
            if detection.state in target_states:
                self.on_log(f"组合模式：已确认 {label}。")
                return True
            if detection.state == STATE_CONTROLLER_DISCONNECTED:
                self.on_log("组合模式：检测到控制器未连接弹窗，按 A 恢复。")
                if not self._tap(pad or self.pad_provider(), "a", after=1.0):
                    return False
            elif detection.state == STATE_CONFIRM_MODAL:
                self.on_log("组合模式：遇到确认弹窗，按 A 继续。")
                if not self._tap(pad or self.pad_provider(), "a", after=1.0):
                    return False
            if not self._sleep(0.6):
                return False
        return False

    def _wait_for_prestart(self, pad, auto_focus, require_foreground):
        deadline = time.monotonic() + 18.0
        tapped_again = False
        while time.monotonic() < deadline and not self._stop.is_set():
            if not self._ensure_foreground(auto_focus, require_foreground):
                return False
            try:
                smart_detection = self.smart_runner.detect_once()
            except Exception as exc:
                self.logger.warning("Combo prestart smart detection failed: %s", exc)
                smart_detection = None
            if smart_detection and smart_detection.state in (STATE_PRESTART, STATE_PRESTART_WRONG_SELECTION):
                self.on_log("组合模式：已识别到 EventLab 开始赛事菜单。")
                return True

            buy_detection = self._detect_buy(auto_focus, require_foreground)
            if buy_detection and buy_detection.state == STATE_CONTROLLER_DISCONNECTED:
                self.on_log("组合模式：控制器弹窗，按 A 恢复。")
                if not self._tap(pad, "a", after=1.0):
                    return False
            elif buy_detection and buy_detection.state in (STATE_EVENTLAB_EVENTS, STATE_EVENTLAB_FAVORITES) and not tapped_again:
                self.on_log("组合模式：仍在 EventLab 列表，补按一次 A 进入当前收藏赛事。")
                tapped_again = True
                if not self._tap(pad, "a", after=2.0):
                    return False
            if not self._sleep(0.8):
                return False
        return False

    def _detect_buy(self, auto_focus, require_foreground):
        if not self._ensure_foreground(auto_focus, require_foreground):
            return None
        try:
            return self.buy_runner.detect_once()
        except Exception as exc:
            self.logger.warning("Combo buy-state detection failed: %s", exc)
            self.on_log(f"组合模式截图识别失败：{exc}")
            return None
