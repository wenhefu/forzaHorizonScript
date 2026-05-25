"""Application controller that keeps GUI concerns away from runners."""
import logging
import threading

import config
import focus
from buy_car_runner import BuyCarRunner
from combo_runner import ComboRunner
from gamepad import Gamepad
from modes import RUNNER_BUY_CAR, RUNNER_COMBO, RUNNER_LEGACY, RUNNER_SMART, get_mode
from runner import Runner
from sequences import farm_sequence
from settings import RuntimeSettings
from smart_runner import SmartRunner


class AppController:
    """Owns device and runner lifecycle for one GUI instance."""

    def __init__(self, on_log=None, logger=None):
        self.on_log = on_log or (lambda msg: None)
        self.logger = logger or logging.getLogger("forza6helper")
        self.pad = None
        self.pad_error = None
        self.pad_lock = threading.Lock()
        self.keeper = None
        self.current_settings = None

        self.runner = Runner(on_log=self.on_log, logger=self.logger, pad_provider=self.get_gamepad)
        self.smart_runner = SmartRunner(on_log=self.on_log, logger=self.logger, pad_provider=self.get_gamepad)
        self.buy_car_runner = BuyCarRunner(on_log=self.on_log, logger=self.logger, pad_provider=self.get_gamepad)
        self.combo_runner = ComboRunner(on_log=self.on_log, logger=self.logger, pad_provider=self.get_gamepad)

    def connect_gamepad_async(self):
        threading.Thread(target=self._connect_gamepad_worker, name="gamepad-connect", daemon=True).start()

    def _connect_gamepad_worker(self):
        try:
            self.get_gamepad()
            self.on_log("虚拟手柄已常驻连接。")
        except Exception as exc:
            self.logger.exception("Persistent gamepad connection failed")
            self.on_log(f"虚拟手柄连接失败：{exc}")

    def get_gamepad(self):
        with self.pad_lock:
            if self.pad:
                return self.pad
            if self.pad_error:
                raise self.pad_error
            try:
                self.pad = Gamepad(logger=self.logger)
                return self.pad
            except Exception as exc:
                self.pad_error = exc
                raise

    def is_running(self):
        return (
            self.runner.is_running()
            or self.smart_runner.is_running()
            or self.buy_car_runner.is_running()
            or self.combo_runner.is_running()
        )

    def start(self, settings: RuntimeSettings):
        if self.is_running():
            self.logger.info("Start ignored because a runner is already active")
            return False

        self.current_settings = settings
        mode = get_mode(settings.mode_id)
        self.logger.info(
            "Start requested source=%s mode=%s startup=%.2f drive=%.2f minutes=%.2f keep_active=%s auto_focus=%s require_foreground=%s resume=%s no_activate=%s",
            settings.source,
            mode.mode_id,
            settings.startup_delay,
            settings.drive_seconds,
            settings.total_minutes,
            settings.keep_active,
            settings.auto_focus,
            settings.require_foreground,
            settings.resume_after_focus,
            settings.no_activate,
        )

        if settings.auto_focus:
            self.activate_game()
        if settings.keep_active:
            self.keeper = focus.KeepActive(title_substr=config.GAME_TITLE, on_log=self.on_log)
            self.keeper.start()

        if mode.runner_kind == RUNNER_SMART:
            self._log_smart_runtime(settings)
            self.smart_runner.start(
                startup_delay=settings.startup_delay,
                total_seconds=settings.total_seconds,
                auto_focus=settings.auto_focus,
                require_foreground=settings.require_foreground,
            )
            return True

        if mode.runner_kind == RUNNER_BUY_CAR:
            self.buy_car_runner.start(
                startup_delay=settings.startup_delay,
                total_seconds=None,
                auto_focus=settings.auto_focus,
                require_foreground=settings.require_foreground,
            )
            return True

        if mode.runner_kind == RUNNER_COMBO:
            self.combo_runner.start(
                startup_delay=settings.startup_delay,
                total_seconds=settings.total_seconds,
                auto_focus=settings.auto_focus,
                require_foreground=settings.require_foreground,
            )
            return True

        if mode.runner_kind == RUNNER_LEGACY:
            self.runner.start(
                farm_sequence(drive_seconds=settings.drive_seconds),
                startup_delay=settings.startup_delay,
                total_seconds=settings.total_seconds,
                resume_button=settings.resume_button,
                require_foreground=settings.require_foreground,
                foreground_check=lambda: focus.is_foreground(config.GAME_TITLE),
                on_focus_lost=self._on_focus_lost,
                on_focus_restored=self._on_focus_restored,
            )
            return True

        self.on_log(f"未知运行模式：{mode.mode_id}")
        return False

    def stop(self, source="button"):
        self.logger.info("Stop requested source=%s", source)
        self.runner.stop()
        self.smart_runner.stop()
        self.buy_car_runner.stop()
        self.combo_runner.stop()
        self._stop_keeper()

    def close(self):
        self.stop(source="close")
        if self.pad:
            self.pad.neutral()

    def toggle(self, settings_factory, source="hotkey"):
        if self.is_running():
            self.stop(source=source)
            return
        self.start(settings_factory(source))

    def activate_game(self):
        return focus.activate_window(
            title_substr=config.GAME_TITLE,
            on_log=self.on_log,
            logger=self.logger,
        )

    def tap_button(self, name, auto_focus=True):
        if auto_focus:
            self.activate_game()
        try:
            pad = self.get_gamepad()
            pad.tap(name, hold=0.15)
            self.on_log(f"已按 {name.upper()}。")
        except Exception as exc:
            self.logger.exception("Manual tap failed")
            self.on_log(f"按键失败：{exc}")

    def detect_once(self, mode_id):
        mode = get_mode(mode_id)
        if mode.runner_kind == RUNNER_COMBO:
            return self.combo_runner.detect_once()
        if mode.runner_kind == RUNNER_BUY_CAR:
            return self.buy_car_runner.detect_once()
        return self.smart_runner.detect_once()

    def _stop_keeper(self):
        if self.keeper:
            self.keeper.stop()
            self.keeper = None

    def _log_smart_runtime(self, settings):
        if settings.total_seconds is None:
            self.on_log("刷技能点模式：总运行时间为 0，会一直跑到你手动停止。")
        else:
            self.on_log(
                f"刷技能点模式：总运行时间为 {settings.total_minutes:.1f} 分钟，到点会自动停止并回正手柄。"
            )

    def _on_focus_lost(self):
        if self.current_settings and self.current_settings.auto_focus:
            focus.activate_window(
                title_substr=config.GAME_TITLE,
                on_log=self.on_log,
                logger=self.logger,
            )

    def _on_focus_restored(self):
        # Leave menu recovery to the user or the explicit checkbox.
        pass
