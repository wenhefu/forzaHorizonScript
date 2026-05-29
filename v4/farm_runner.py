from __future__ import annotations

"""Vision-guided EventLab farm loop.

Drop-in replacement for the V1 SmartRunner farm loop, but driven by the
aspect-robust V3 hybrid recognizer (YOLO + V2 rules + OCR) instead of the
fixed-fraction ForzaScreenDetector. This is what lets the farm phase survive
different resolutions / aspect ratios.

It sends only normal virtual Xbox controller input (via the shared pad
provider). It does not inject, hook, fake focus, or modify game files. Full
throttle is applied with ``pad.apply`` and the virtual pad holds that state
between cycles, so the car keeps driving smoothly even while the recognizer
re-reads the screen.
"""

import logging
import threading
import time

import focus
from v4.decision import decide_farm_loop, normalize_button
from v4.recognizer import V4Recognizer


# Screens that mean "we have left the active race" -- used to end the loop
# cleanly after a graceful exit.
_LEFT_RACE_SCREENS = {
    "post_race_next",
    "free_roam_hud",
    "idle_showcase",
    "race_pause_menu",
    "pause_menu",
}


class VisionFarmRunner:
    """Run the EventLab farm loop from V3 hybrid recognition only.

    Mirrors the SmartRunner interface (start/stop/is_running/
    request_graceful_exit/exit_reason) so V4 can swap it in for the farm phase.
    """

    def __init__(
        self,
        title: str = "Forza",
        recognizer: V4Recognizer | None = None,
        on_log=None,
        logger=None,
        pad_provider=None,
        min_confidence: float = 0.42,
        stall_seconds: float = 120.0,
        race_poll: float = 1.2,
    ):
        self.title = title
        self.on_log = on_log or (lambda message: None)
        self.logger = logger or logging.getLogger("forza6helper.v4.farm")
        self.pad_provider = pad_provider
        self.recognizer = recognizer or V4Recognizer(
            title=title, min_confidence=min_confidence, logger=self.logger
        )
        self.stall_seconds = float(stall_seconds)
        self.race_poll = float(race_poll)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._graceful = threading.Event()
        self.exit_reason: str | None = None
        self.laps = 0

    # -- lifecycle ---------------------------------------------------------
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(
        self,
        startup_delay: float = 0.0,
        total_seconds: float | None = None,
        auto_focus: bool = False,
        require_foreground: bool = True,
    ) -> None:
        if self.is_running():
            return
        self._stop.clear()
        self._graceful.clear()
        self.exit_reason = None
        self._thread = threading.Thread(
            target=self._run,
            args=(startup_delay, total_seconds, auto_focus, require_foreground),
            name="vision-farm-runner",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self.exit_reason = self.exit_reason or "manual_stop"
        self._stop.set()

    def request_graceful_exit(self) -> None:
        if not self._graceful.is_set():
            self.on_log("视觉刷图：收到平滑退出请求，跑完当前比赛在结算页按 A 退出。")
        self._graceful.set()

    # -- helpers -----------------------------------------------------------
    def _sleep(self, seconds: float) -> bool:
        end = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < end:
            if self._stop.is_set():
                return False
            time.sleep(min(0.05, max(0.0, end - time.monotonic())))
        return not self._stop.is_set()

    def _activate(self) -> None:
        hwnd = focus.find_window(self.title)
        if not hwnd or not focus.user32:
            return
        try:
            focus.user32.ShowWindow(hwnd, focus.SW_RESTORE)
            focus.user32.BringWindowToTop(hwnd)
            focus.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def _race_poll_interval(self, race_started: float | None) -> float:
        if race_started is None:
            return min(0.6, self.race_poll)
        # Slightly tighter polling at the very start (countdown), then relax.
        return self.race_poll if (time.monotonic() - race_started) > 4.0 else min(0.6, self.race_poll)

    @staticmethod
    def _settle_for(name: str) -> float:
        if name in ("farm_start_race", "farm_confirm_restart"):
            return 1.8
        if name in ("farm_dismiss_controller", "farm_restart_results", "farm_graceful_exit_results"):
            return 1.3
        return 0.85

    # -- main loop ---------------------------------------------------------
    def _run(self, startup_delay, total_seconds, auto_focus, require_foreground) -> None:
        try:
            pad = self.pad_provider()
        except Exception as exc:
            self.logger.exception("vision farm pad init failed")
            self.on_log(f"无法启动虚拟手柄：{exc}")
            return

        self.exit_reason = None
        self.laps = 0
        if startup_delay > 0 and not self._sleep(startup_delay):
            pad.neutral()
            return

        started = time.monotonic()
        in_race = False
        race_started: float | None = None
        unknown_throttle_since: float | None = None
        launching = False
        launch_since = 0.0
        last_screen: str | None = None
        last_token: str | None = None
        last_progress = time.monotonic()
        self.on_log(
            "视觉刷图已启动：race_menu 按 A 开赛、race_hud 保持油门、结算页按 X 重开、"
            "暂停/赛后按 B 返回；全部基于 V3 模型/规则识别，按一步重新识别验证。"
        )

        try:
            while not self._stop.is_set():
                if total_seconds is not None and time.monotonic() - started >= total_seconds:
                    if not self._graceful.is_set():
                        self._graceful.set()
                        self.on_log("视觉刷图：总时长已到，进入平滑退出，跑完当前比赛后在结算页按 A 退出。")

                if require_foreground and not focus.is_foreground(self.title):
                    pad.neutral()
                    in_race = False
                    race_started = None
                    if auto_focus:
                        self._activate()
                    if not self._sleep(0.8):
                        break
                    continue

                try:
                    snapshot = self.recognizer.capture(full_ocr=True, region_ocr=True)
                except Exception as exc:
                    self.logger.warning("vision farm capture failed: %s", exc)
                    if not self._sleep(0.8):
                        break
                    continue

                v3 = snapshot.v3
                screen = str(getattr(v3, "screen", "") or "unknown")
                token = f"{screen}|{getattr(v3, 'selected_item', '')}"
                if token != last_token:
                    last_token = token
                    last_progress = time.monotonic()
                if screen != last_screen:
                    self.on_log(f"视觉刷图识别：{screen}")
                    last_screen = screen

                if time.monotonic() - last_progress > self.stall_seconds:
                    self.exit_reason = self.exit_reason or "stall"
                    self.on_log(
                        f"视觉刷图：{self.stall_seconds:.0f} 秒没有语义进展，停止并把控制权交回上层。"
                    )
                    break

                decision = decide_farm_loop(v3, graceful_exit=self._graceful.is_set())
                name = decision.name

                # Launch window: right after pressing A to start a race, the
                # countdown / loading / start-line frames can mis-read as
                # race_menu/idle/loading. Hold full throttle through that window
                # (so the car actually launches) until the HUD confirms. We must
                # NEVER press DpadUp here -- in-race that opens Photo Mode.
                if launching:
                    if name == "race_drive_throttle":
                        launching = False  # HUD confirmed -> normal racing below
                    elif name in (
                        "farm_wait_race_menu_focus",
                        "farm_wait_loading",
                        "farm_wait_unknown",
                    ) and (time.monotonic() - launch_since) <= 12.0:
                        in_race = True
                        if race_started is None:
                            race_started = time.monotonic()
                        pad.apply(throttle=1.0)
                        if not self._sleep(0.5):
                            break
                        continue
                    else:
                        launching = False  # results / pause / modal, or timed out

                # 1) Active race: hold throttle (state persists between cycles).
                if name == "race_drive_throttle":
                    in_race = True
                    if race_started is None:
                        race_started = time.monotonic()
                    unknown_throttle_since = None
                    pad.apply(throttle=1.0)
                    if not self._sleep(self._race_poll_interval(race_started)):
                        break
                    continue

                # 2) Loading/transition: never throttle, just wait.
                if name == "farm_wait_loading":
                    in_race = False
                    race_started = None
                    unknown_throttle_since = None
                    pad.neutral()
                    if not self._sleep(0.7):
                        break
                    continue

                # 3) Unknown or unconfirmed race-menu focus: if we were just
                #    racing, keep throttle briefly (transient mid-race frame);
                #    otherwise wait. Never press DpadUp here.
                if name in ("farm_wait_unknown", "farm_wait_race_menu_focus"):
                    if in_race:
                        if unknown_throttle_since is None:
                            unknown_throttle_since = time.monotonic()
                        if time.monotonic() - unknown_throttle_since <= 6.0:
                            pad.apply(throttle=1.0)
                            if not self._sleep(0.5):
                                break
                            continue
                        in_race = False
                        race_started = None
                        unknown_throttle_since = None
                    pad.neutral()
                    if not self._sleep(0.85):
                        break
                    continue

                # 4) A menu/modal action: release throttle, then a single tap.
                button = normalize_button(decision.button)
                in_race = False
                race_started = None
                unknown_throttle_since = None
                pad.neutral()
                if not button:
                    if not self._sleep(0.85):
                        break
                    continue
                if name in ("farm_restart_results", "farm_graceful_exit_results"):
                    self.laps += 1
                    self.on_log(f"视觉刷图：第 {self.laps} 圈完成。")
                self.on_log(f"视觉刷图按键：{decision.button} -> {button}；{name}。")
                pad.tap(button, hold=0.15)
                if name == "farm_start_race":
                    launching = True
                    launch_since = time.monotonic()
                if name == "farm_graceful_exit_results" or (decision.terminal and self._graceful.is_set()):
                    self.exit_reason = self.exit_reason or "graceful_exit"
                    self._sleep(self._settle_for(name))
                    self.on_log("视觉刷图：平滑退出，已在结算/赛后页把控制权交回上层。")
                    break
                if not self._sleep(self._settle_for(name)):
                    break
        except Exception as exc:
            self.logger.exception("VisionFarmRunner crashed")
            self.on_log(f"视觉刷图运行出错：{exc}")
        finally:
            try:
                pad.neutral()
            except Exception:
                pass
            self.on_log("视觉刷图已停止，手柄保持连接并已回正。")
