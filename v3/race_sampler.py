from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

import focus
from buy_car_detector import (
    BuyCarScreenDetector,
    STATE_CONFIRM_MODAL,
    STATE_CONTROLLER_DISCONNECTED as BUY_CONTROLLER_DISCONNECTED,
    STATE_CREATIVE_HUB,
    STATE_EVENTLAB_EVENTS,
    STATE_EVENTLAB_FAVORITES,
    STATE_EVENTLAB_FILTER,
    STATE_EVENTLAB_MENU,
    STATE_EVENTLAB_MY_CARS,
    STATE_EVENTLAB_MY_CARS_22B_READY,
    STATE_EVENTLAB_RACE_TYPE,
    STATE_PAUSE_MENU,
    STATE_POST_RACE_NEXT as BUY_POST_RACE_NEXT,
)
from combo_runner import ComboRunner
from gamepad import Gamepad
from ocr_engine import OcrReader
from screen_detector import (
    ForzaScreenDetector,
    STATE_CONFIRM_RESTART,
    STATE_CONTROLLER_DISCONNECTED,
    STATE_POST_RACE_NEXT,
    STATE_PRESTART,
    STATE_PRESTART_WRONG_SELECTION,
    STATE_RACING,
    STATE_RESULTS,
)
from v2.semantic import ForzaSemanticAnalyzer
from v3.candidates import detect_focus_candidates
from v3.frame_utils import timestamp_slug
from v3.sample_collector import SampleCollector
from window_capture import capture_client, capture_client_printwindow


RACE_SCREEN_BY_SMART_STATE = {
    STATE_PRESTART: "race_menu",
    STATE_PRESTART_WRONG_SELECTION: "race_menu",
    STATE_RACING: "race_hud",
    STATE_RESULTS: "race_result",
    STATE_POST_RACE_NEXT: "post_race_next",
    STATE_CONTROLLER_DISCONNECTED: "controller_disconnected",
}

RACE_SCREEN_BY_BUY_STATE = {
    BUY_CONTROLLER_DISCONNECTED: "controller_disconnected",
    BUY_POST_RACE_NEXT: "post_race_next",
    STATE_CONFIRM_MODAL: "modal_warning",
    STATE_EVENTLAB_RACE_TYPE: "modal_warning",
    STATE_EVENTLAB_FILTER: "modal_warning",
}

EVENTLAB_BUY_STATES = {
    STATE_EVENTLAB_MENU,
    STATE_EVENTLAB_EVENTS,
    STATE_EVENTLAB_FAVORITES,
    STATE_EVENTLAB_RACE_TYPE,
    STATE_EVENTLAB_MY_CARS,
    STATE_EVENTLAB_MY_CARS_22B_READY,
    STATE_EVENTLAB_FILTER,
}


@dataclass
class RaceSampleStep:
    index: int
    kind: str
    button: str
    semantic_screen: str
    active_tab: str
    selected_item: str
    ocr_text: str
    smart_state: str
    buy_state: str
    sample_dir: str
    note: str = ""


@dataclass
class RaceSampleReport:
    started_at: str
    title: str
    steps: list[RaceSampleStep] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class RaceStateSampler:
    """Navigate toward EventLab pre-race and collect race/result states.

    This is a V3-only sampling tool. It sends normal virtual Xbox controller
    input via ViGEmBus/vgamepad. It does not inject, hook, fake focus, or modify
    game files.
    """

    def __init__(
        self,
        title: str = "Forza",
        raw_root: str | Path = "datasets/forza_ui/raw",
        report_dir: str | Path = "reports",
        hold: float = 0.14,
        settle: float = 0.9,
        max_steps: int = 160,
        run_seconds: float = 0.0,
    ):
        self.title = title
        self.collector = SampleCollector(raw_root=raw_root)
        self.report_dir = Path(report_dir)
        self.hold = hold
        self.settle = settle
        self.max_steps = max_steps
        self.run_seconds = max(0.0, float(run_seconds))
        self.ocr = OcrReader()
        self.analyzer = ForzaSemanticAnalyzer()
        self.smart_detector = ForzaScreenDetector()
        self.buy_detector = BuyCarScreenDetector()
        self.pad: Gamepad | None = None
        self.report = RaceSampleReport(datetime.now(timezone.utc).astimezone().isoformat(), title)
        self._step_index = 0
        self._combo: ComboRunner | None = None

    def run(self) -> RaceSampleReport:
        try:
            self.report_dir.mkdir(parents=True, exist_ok=True)
            self._plain_activate()
            self.pad = Gamepad()
            self.pad.neutral()
            time.sleep(1.4)
            self.capture_and_save("race_sampler_start", "start")
            if self._navigate_to_prestart():
                self.capture_and_save("race_menu_prestart", "confirmed pre-race menu")
                if self.run_seconds > 0:
                    self._run_race_watch()
        except Exception as exc:
            self.report.errors.append(str(exc))
        finally:
            if self.pad:
                self.pad.neutral()
            self.write_report()
        return self.report

    def _navigate_to_prestart(self) -> bool:
        assert self.pad is not None
        self._combo = ComboRunner(on_log=self._log, pad_provider=lambda: self.pad)
        self._combo._stop.clear()
        current = self.capture_and_save("race_sampler_probe", "probe before pause recovery")
        if current.semantic_screen == "controller_disconnected":
            current = self.tap("a", "race_sampler_dismiss_controller", "dismiss controller disconnected")
        if current.semantic_screen == "race_menu" or current.smart_state in (STATE_PRESTART, STATE_PRESTART_WRONG_SELECTION):
            return True
        if current.semantic_screen == "post_race_next":
            current = self.tap("b", "race_sampler_leave_next_stop", "leave post-race next-stop page")
        if str(current.semantic_screen).startswith("eventlab") or current.buy_state in EVENTLAB_BUY_STATES:
            return self._finish_eventlab_to_prestart()
        if self._try_resume_eventlab():
            return True
        if not self._ensure_pause():
            self.report.errors.append("could not reach pause menu before EventLab navigation")
            return False
        if not self._move_to_creative_hub():
            return False
        if not self._enter_eventlab_menu():
            return False
        return self._finish_eventlab_to_prestart()

    def _try_resume_eventlab(self) -> bool:
        assert self.pad is not None and self._combo is not None
        self.capture_and_save("race_sampler_resume_probe", "try EventLab resume")
        ok = self._combo._try_resume_eventlab_prestart(self.pad, True, False)
        if ok:
            self.capture_and_save("race_sampler_resume_prestart", "resumed to pre-race menu")
        return bool(ok)

    def _ensure_pause(self) -> bool:
        for button in ("start", "b", "start", "b", "start"):
            state = self.capture_and_save("race_sampler_pause_check", "check pause state")
            if state.buy_state == STATE_PAUSE_MENU or str(state.semantic_screen).startswith("pause_"):
                return True
            self.tap(button, f"race_sampler_pause_{button}", "recover/open pause menu")
        state = self.capture_and_save("race_sampler_pause_final", "final pause check")
        return state.buy_state == STATE_PAUSE_MENU or str(state.semantic_screen).startswith("pause_")

    def _move_to_creative_hub(self) -> bool:
        assert self.pad is not None and self._combo is not None
        ok = self._combo._move_to_creative_hub(self.pad, True, False)
        self.capture_and_save("race_sampler_creative_hub", "after move to creative hub")
        return bool(ok)

    def _enter_eventlab_menu(self) -> bool:
        for attempt in range(4):
            state = self.capture_and_save("race_sampler_eventlab_check", "check EventLab menu")
            if state.buy_state == STATE_EVENTLAB_MENU or state.semantic_screen == "eventlab_home":
                return True
            if state.buy_state == STATE_CREATIVE_HUB or state.semantic_screen == "pause_creative_hub":
                self.tap("a", f"race_sampler_enter_eventlab_{attempt}", "enter EventLab")
                continue
            if state.semantic_screen == "controller_disconnected":
                self.tap("a", f"race_sampler_eventlab_controller_{attempt}", "dismiss controller modal")
                continue
            time.sleep(self.settle)
        return False

    def _finish_eventlab_to_prestart(self) -> bool:
        assert self.pad is not None and self._combo is not None
        state = self.capture_and_save("race_sampler_eventlab_menu_ready", "EventLab menu ready")
        if state.buy_state == STATE_EVENTLAB_MENU or state.semantic_screen == "eventlab_home":
            self.tap("a", "race_sampler_open_events", "open EventLab events")
        if not self._wait_eventlab_screen({"eventlab_events", "eventlab_favorites"}, 12.0, "events/favorites"):
            return False
        if not self._move_to_eventlab_playable_tab():
            return False
        self.capture_and_save("race_sampler_playable_tab", "playable EventLab tab selected")
        self.tap("a", "race_sampler_select_favorite", "select favorite event")
        if not self._wait_eventlab_screen(
            {"eventlab_race_type", "eventlab_my_cars", "race_menu"},
            12.0,
            "race type or my cars",
        ):
            return False
        state = self.capture_and_save("race_sampler_after_favorite", "after favorite event")
        if state.semantic_screen == "race_menu":
            return True
        if state.buy_state == STATE_EVENTLAB_RACE_TYPE or state.semantic_screen == "eventlab_race_type":
            self.tap("a", "race_sampler_single_player", "confirm single-player race type")
            if not self._wait_eventlab_screen({"eventlab_my_cars", "race_menu"}, 14.0, "my cars"):
                return False
        state = self.capture_and_save("race_sampler_before_car_select", "before car selection")
        if state.semantic_screen == "race_menu":
            return True
        if not self._combo._apply_favorite_filter(self.pad, True, False):
            return False
        if not self._combo._select_eventlab_22b(self.pad, True, False):
            return False
        return self._wait_smart_state({STATE_PRESTART, STATE_PRESTART_WRONG_SELECTION}, 18.0, "pre-race menu")

    def _move_to_eventlab_playable_tab(self) -> bool:
        for attempt in range(16):
            state = self.capture_and_save("race_sampler_event_tab_check", "check EventLab playable tab")
            if (
                state.semantic_screen in ("eventlab_events", "eventlab_favorites")
                and "找不到赛事" not in state.ocr_text
            ):
                return True
            if state.semantic_screen == "eventlab_home":
                self.tap("a", f"race_sampler_event_open_events_{attempt}", "open EventLab events")
                continue
            if not str(state.semantic_screen).startswith("eventlab"):
                self.report.errors.append(f"not in EventLab while moving to playable tab: {state.semantic_screen}")
                return False
            self.tap("rb", f"race_sampler_event_tab_{attempt}_rb", "move to next EventLab tab")
        self.report.errors.append("could not reach a playable EventLab tab")
        return False

    def _wait_eventlab_screen(self, screens: set[str], timeout: float, label: str) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and self._step_index < self.max_steps:
            state = self.capture_and_save(f"race_sampler_wait_{label}", f"wait for {label}")
            if state.semantic_screen in screens:
                return True
            if state.buy_state == BUY_CONTROLLER_DISCONNECTED:
                self.tap("a", "race_sampler_wait_controller", "dismiss controller disconnected")
            elif state.buy_state == STATE_CONFIRM_MODAL:
                self.tap("a", "race_sampler_wait_confirm", "accept confirmation modal")
            time.sleep(0.6)
        self.report.errors.append(f"timeout waiting for {label}")
        return False

    def _run_race_watch(self) -> None:
        deadline = time.monotonic() + self.run_seconds
        started = False
        while time.monotonic() < deadline and self._step_index < self.max_steps:
            state = self.capture_and_save("race_sampler_watch", "watch race/result state")
            if state.smart_state in (STATE_PRESTART, STATE_PRESTART_WRONG_SELECTION) and not started:
                self.tap("a", "race_sampler_start_race", "start race from pre-race menu", settle=2.5)
                started = True
                continue
            if state.smart_state == STATE_RACING:
                if not self.pad:
                    return
                self.pad.apply(throttle=1.0)
                time.sleep(1.0)
                self.pad.neutral()
                continue
            if state.smart_state in (STATE_RESULTS, STATE_CONFIRM_RESTART, STATE_POST_RACE_NEXT):
                self.capture_and_save("race_sampler_terminal_state", "captured result/post-race state")
                return
            time.sleep(max(0.8, self.settle))

    def _wait_buy_state(self, states: set[str], timeout: float, label: str) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and self._step_index < self.max_steps:
            state = self.capture_and_save(f"race_sampler_wait_{label}", f"wait for {label}")
            if state.buy_state in states:
                return True
            if state.buy_state == BUY_CONTROLLER_DISCONNECTED:
                self.tap("a", "race_sampler_wait_controller", "dismiss controller disconnected")
            elif state.buy_state == STATE_CONFIRM_MODAL:
                self.tap("a", "race_sampler_wait_confirm", "accept confirmation modal")
            time.sleep(0.6)
        self.report.errors.append(f"timeout waiting for {label}")
        return False

    def _wait_smart_state(self, states: set[str], timeout: float, label: str) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and self._step_index < self.max_steps:
            state = self.capture_and_save(f"race_sampler_wait_{label}", f"wait for {label}")
            if state.smart_state in states:
                return True
            time.sleep(0.7)
        self.report.errors.append(f"timeout waiting for {label}")
        return False

    def tap(self, button: str, label_hint: str, note: str, settle: float | None = None):
        if self._step_index >= self.max_steps:
            raise RuntimeError(f"max steps reached: {self.max_steps}")
        if not self.pad:
            raise RuntimeError("gamepad is not initialized")
        self._plain_activate()
        self.pad.tap(button, hold=self.hold)
        time.sleep(self.settle if settle is None else settle)
        self._step_index += 1
        return self.capture_and_save(label_hint, note, button=button, kind="tap")

    def capture(self):
        hwnd = focus.find_window(self.title)
        if not hwnd:
            raise RuntimeError(f"No window title contains {self.title!r}")
        try:
            frame = capture_client_printwindow(hwnd)
            method = "PrintWindow"
        except Exception:
            frame = capture_client(hwnd)
            method = "BitBlt"
        title = focus.window_title(hwnd) or self.title
        items = self.ocr.read_frame(frame, min_confidence=self.collector.min_confidence)
        understanding = self.analyzer.analyze(frame, items)
        smart = self.smart_detector.detect(frame)
        buy = self.buy_detector.detect(frame)
        override_screen = RACE_SCREEN_BY_SMART_STATE.get(smart.state) or RACE_SCREEN_BY_BUY_STATE.get(buy.state)
        if override_screen == "controller_disconnected" and understanding.screen != "controller_disconnected":
            if "控制器未连接" not in understanding.ocr_text and "重新连接控制器" not in understanding.ocr_text:
                override_screen = None
        if override_screen and override_screen != understanding.screen:
            understanding = replace(
                understanding,
                screen=override_screen,
                confidence=max(float(understanding.confidence), float(smart.confidence), float(buy.confidence)),
                reasons=[
                    *list(getattr(understanding, "reasons", []) or []),
                    f"race_sampler override from smart={smart.state} buy={buy.state}",
                ],
                actions=[],
            )
            understanding = replace(understanding, actions=self.analyzer._plan_actions(understanding))
        candidates = detect_focus_candidates(frame, understanding)
        return frame, title, method, items, understanding, candidates, smart, buy

    def capture_and_save(self, label_hint: str, note: str, button: str = "", kind: str = "capture"):
        frame, title, method, items, understanding, candidates, smart, buy = self.capture()
        sample_dir = self.collector.save_sample(
            frame,
            title,
            items,
            understanding,
            candidates=candidates,
            capture_method=f"race-sampler:{method}",
            label_hint=label_hint,
        )
        sample_text = str(sample_dir)
        self.report.samples.append(sample_text)
        self.report.steps.append(
            RaceSampleStep(
                index=self._step_index,
                kind=kind,
                button=button,
                semantic_screen=understanding.screen,
                active_tab=understanding.active_tab,
                selected_item=understanding.selected_item,
                ocr_text=understanding.ocr_text[:500],
                smart_state=smart.state,
                buy_state=buy.state,
                sample_dir=sample_text,
                note=note,
            )
        )
        self.write_report()
        return self.report.steps[-1]

    def _plain_activate(self) -> bool:
        hwnd = focus.find_window(self.title)
        if not hwnd or not focus.user32:
            return False
        try:
            focus.user32.ShowWindow(hwnd, focus.SW_RESTORE)
            focus.user32.BringWindowToTop(hwnd)
            focus.user32.SetForegroundWindow(hwnd)
            time.sleep(0.15)
            return True
        except Exception:
            return False

    def _log(self, message: str) -> None:
        if message:
            self.report.errors.append(f"log: {message}")
            self.write_report()

    def write_report(self) -> None:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        data = asdict(self.report)
        path = self.report_dir / f"race_sampler_{timestamp_slug()}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        latest = self.report_dir / "race_sampler_latest.json"
        latest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Collect V3 race menu/result samples with normal vgamepad input.")
    parser.add_argument("--title", default="Forza")
    parser.add_argument("--raw-root", default="datasets/forza_ui/raw")
    parser.add_argument("--report-dir", default="reports")
    parser.add_argument("--hold", type=float, default=0.14)
    parser.add_argument("--settle", type=float, default=0.9)
    parser.add_argument("--max-steps", type=int, default=160)
    parser.add_argument("--run-seconds", type=float, default=0.0)
    args = parser.parse_args(argv)
    sampler = RaceStateSampler(
        title=args.title,
        raw_root=args.raw_root,
        report_dir=args.report_dir,
        hold=args.hold,
        settle=args.settle,
        max_steps=args.max_steps,
        run_seconds=args.run_seconds,
    )
    report = sampler.run()
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
