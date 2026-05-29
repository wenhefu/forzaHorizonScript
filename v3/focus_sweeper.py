from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import focus
from gamepad import Gamepad
from ocr_engine import OcrReader
from v2.semantic import ForzaSemanticAnalyzer, PAUSE_TABS
from v3.candidates import detect_focus_candidates
from v3.frame_utils import timestamp_slug
from v3.sample_collector import SampleCollector
from window_capture import capture_client, capture_client_printwindow


PAUSE_SCREEN_BY_TAB = {
    "剧情": "pause_story",
    "车辆": "pause_vehicle",
    "我的地平线": "pause_my_horizon",
    "在线": "pause_online",
    "创意中心": "pause_creative_hub",
    "商店": "pause_store",
}


@dataclass
class SweepStep:
    index: int
    kind: str
    button: str
    screen: str
    tab: str
    selected_item: str
    focus_key: str
    sample_dir: str
    note: str = ""


@dataclass
class FocusSweepReport:
    started_at: str
    title: str
    steps: list[SweepStep] = field(default_factory=list)
    unique_focus: dict[str, str] = field(default_factory=dict)
    samples: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class FocusSweeper:
    """Capture every visible focus state, even when OCR/semantic state does not change."""

    def __init__(
        self,
        title: str = "Forza",
        raw_root: str | Path = "datasets/forza_ui/raw",
        report_dir: str | Path = "reports",
        min_confidence: float = 0.42,
        hold: float = 0.14,
        settle: float = 0.75,
        max_steps: int = 180,
        enter_focused: bool = False,
        enter_limit: int = 20,
    ):
        self.title = title
        self.collector = SampleCollector(raw_root=raw_root, min_confidence=min_confidence)
        self.ocr = OcrReader()
        self.analyzer = ForzaSemanticAnalyzer()
        self.report_dir = Path(report_dir)
        self.hold = hold
        self.settle = settle
        self.max_steps = max_steps
        self.enter_focused = enter_focused
        self.enter_limit = enter_limit
        self.pad: Gamepad | None = None
        self.report = FocusSweepReport(datetime.now(timezone.utc).astimezone().isoformat(), title)
        self._step_index = 0
        self._enter_count = 0
        self._entered_focus: set[str] = set()

    def run(self) -> FocusSweepReport:
        try:
            self.report_dir.mkdir(parents=True, exist_ok=True)
            self._plain_activate()
            self.pad = Gamepad()
            self.pad.neutral()
            time.sleep(1.6)
            current = self.capture_and_save("focus_sweep_start", "start")
            current = self._ensure_pause(current)
            for tab in PAUSE_TABS:
                if self._step_index >= self.max_steps:
                    break
                current = self._go_tab(current, tab)
                current = self._sweep_current_tab(current, tab)
        except Exception as exc:
            self.report.errors.append(str(exc))
        finally:
            if self.pad:
                self.pad.neutral()
            self.write_report()
        return self.report

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
        items = self.ocr.read_frame(frame, min_confidence=self.collector.min_confidence)
        understanding = self.analyzer.analyze(frame, items)
        candidates = detect_focus_candidates(frame, understanding)
        return frame, focus.window_title(hwnd) or self.title, method, items, understanding, candidates

    def capture_and_save(self, label_hint: str, note: str, button: str = "", kind: str = "capture"):
        frame, title, method, items, understanding, candidates = self.capture()
        focus_key = self._focus_key(understanding, candidates)
        sample_dir = self.collector.save_sample(
            frame,
            title,
            items,
            understanding,
            candidates=candidates,
            capture_method=f"focus-sweeper:{method}",
            label_hint=label_hint,
        )
        sample_text = str(sample_dir)
        self.report.samples.append(sample_text)
        if focus_key not in self.report.unique_focus:
            self.report.unique_focus[focus_key] = sample_text
        self.report.steps.append(
            SweepStep(
                index=self._step_index,
                kind=kind,
                button=button,
                screen=understanding.screen,
                tab=understanding.active_tab,
                selected_item=understanding.selected_item,
                focus_key=focus_key,
                sample_dir=sample_text,
                note=note,
            )
        )
        self.write_report()
        return understanding

    def tap_capture(self, button: str, label_hint: str, note: str, settle: float | None = None):
        if self._step_index >= self.max_steps:
            raise RuntimeError(f"max steps reached: {self.max_steps}")
        if not self.pad:
            raise RuntimeError("gamepad is not initialized")
        self._plain_activate()
        self.pad.tap(button, hold=self.hold)
        time.sleep(self.settle if settle is None else settle)
        self._step_index += 1
        return self.capture_and_save(label_hint, note, button=button, kind="tap_capture")

    def _ensure_pause(self, current):
        if current.screen == "controller_disconnected":
            current = self.tap_capture("a", "focus_sweep_dismiss_controller", "dismiss controller disconnected")
            time.sleep(0.4)
        if self._is_pause(current):
            return current
        for button in ("b", "b", "start", "b", "start"):
            if self._is_pause(current):
                break
            current = self.tap_capture(button, f"focus_sweep_recover_{button}", "recover toward pause")
        return current

    def _go_tab(self, current, target_tab: str):
        current = self._ensure_pause(current)
        if not self._is_pause(current):
            self.report.errors.append(
                f"could not recover to pause before tab {target_tab}: {current.screen}/{current.selected_item}"
            )
            return current
        for _ in range(8):
            if self._is_target_tab(current, target_tab):
                return self.capture_and_save(f"focus_tab_{target_tab}", f"arrived at tab {target_tab}")
            button = self._tab_button(current.active_tab, target_tab)
            current = self.tap_capture(button, f"focus_tab_{target_tab}_{button}", f"go to tab {target_tab}")
        self.report.errors.append(f"could not reach tab {target_tab}: {current.screen}/{current.active_tab}")
        return current

    def _sweep_current_tab(self, current, target_tab: str):
        current = self.capture_and_save(f"focus_sweep_{target_tab}_initial", f"sweep initial {target_tab}")
        if not self._is_pause(current):
            current = self._ensure_pause(current)
            if not self._is_pause(current):
                self.report.errors.append(
                    f"skip sweep outside pause tab {target_tab}: {current.screen}/{current.selected_item}"
                )
                return current
        for index, button in enumerate(self._sequence_for_tab(target_tab)):
            if self._step_index >= self.max_steps:
                break
            current = self.tap_capture(button, f"focus_sweep_{target_tab}_{index:02d}_{button}", f"select focus with {button}")
            if self.enter_focused:
                current = self._enter_and_back(current, target_tab, index)
            if not self._is_pause(current):
                current = self._ensure_pause(current)
                if not self._is_pause(current):
                    self.report.errors.append(
                        f"stop sweep outside pause after {button}: {current.screen}/{current.selected_item}"
                    )
                    return current
            if not self._is_target_tab(current, target_tab):
                current = self._go_tab(current, target_tab)
                if not self._is_target_tab(current, target_tab):
                    return current
        return current

    def _enter_and_back(self, current, target_tab: str, index: int):
        if self._enter_count >= self.enter_limit or not self._is_pause(current):
            return current
        focus_key = self._latest_focus_key(current)
        if focus_key in self._entered_focus:
            return current
        if self._looks_dangerous(current):
            self.report.errors.append(f"skip dangerous enter: {current.screen}/{current.selected_item}")
            return current
        self._entered_focus.add(focus_key)
        self._enter_count += 1
        current = self.tap_capture("a", f"focus_enter_{target_tab}_{index:02d}", "enter focused tile", settle=max(1.2, self.settle))
        current = self.capture_and_save(f"focus_enter_{target_tab}_{index:02d}_settled", "after enter settled")
        for back_index in range(4):
            if self._is_pause(current) and self._is_target_tab(current, target_tab):
                return current
            current = self.tap_capture("b", f"focus_enter_{target_tab}_{index:02d}_back_{back_index}", "back after enter", settle=max(0.9, self.settle))
            if current.screen == "controller_disconnected":
                current = self._ensure_pause(current)
        current = self._ensure_pause(current)
        if not self._is_pause(current):
            self.report.errors.append(
                f"entered page did not return to pause: {current.screen}/{current.selected_item}"
            )
        return current

    def _latest_focus_key(self, understanding) -> str:
        _, _, _, _, refreshed, candidates = self.capture()
        return self._focus_key(refreshed, candidates)

    def _sequence_for_tab(self, tab: str) -> list[str]:
        serpentine = [
            "dpad_left",
            "dpad_up",
            "dpad_right",
            "dpad_right",
            "dpad_down",
            "dpad_left",
            "dpad_left",
            "dpad_down",
            "dpad_right",
            "dpad_right",
            "dpad_up",
            "dpad_left",
            "dpad_down",
            "dpad_right",
            "dpad_up",
            "dpad_up",
        ]
        if tab == "车辆":
            return [
                "dpad_left",
                "dpad_up",
                "dpad_right",
                "dpad_right",
                "dpad_down",
                "dpad_left",
                "dpad_down",
                "dpad_left",
                "dpad_up",
                "dpad_right",
                "dpad_down",
                "dpad_right",
                "dpad_up",
                "dpad_left",
            ]
        if tab == "创意中心":
            return [
                "dpad_left",
                "dpad_right",
                "dpad_right",
                "dpad_down",
                "dpad_left",
                "dpad_left",
                "dpad_up",
                "dpad_right",
                "dpad_down",
                "dpad_right",
            ]
        return serpentine

    def _focus_key(self, understanding, candidates) -> str:
        best = max(candidates or [], key=lambda item: item.confidence, default=None)
        if not best:
            return f"{understanding.screen}|{understanding.active_tab}|{understanding.selected_item}|no-focus"
        x1, y1, x2, y2 = best.bbox
        bucket = ",".join(str(round(value / 0.025)) for value in (x1, y1, x2, y2))
        return f"{understanding.screen}|{understanding.active_tab}|{best.label}|{bucket}|{understanding.selected_item}"

    def _is_pause(self, understanding) -> bool:
        return bool(
            understanding
            and (
                str(understanding.screen).startswith("pause_")
                or understanding.screen == "pause_menu"
            )
        )

    def _is_target_tab(self, understanding, tab: str) -> bool:
        if not self._is_pause(understanding):
            return False
        expected_screen = PAUSE_SCREEN_BY_TAB.get(tab, "")
        return bool(
            understanding
            and (
                understanding.active_tab == tab
                or (expected_screen and str(understanding.screen).startswith(expected_screen))
                or (tab == "商店" and understanding.screen == "pause_menu" and understanding.active_tab == "商店")
            )
        )

    def _looks_dangerous(self, understanding) -> bool:
        text = (
            f"{understanding.screen} {understanding.active_tab} "
            f"{understanding.selected_item} {getattr(understanding, 'ocr_text', '')}"
        )
        if understanding.screen == "external_overlay" or understanding.active_tab == "商店":
            return True
        return any(keyword in text for keyword in ("退出游戏", "返回游戏", "STEAM", "Exit", "QUIT"))

    def _tab_button(self, active: str, target: str) -> str:
        if active in PAUSE_TABS and target in PAUSE_TABS:
            active_index = PAUSE_TABS.index(active)
            target_index = PAUSE_TABS.index(target)
            rb_steps = (target_index - active_index) % len(PAUSE_TABS)
            lb_steps = (active_index - target_index) % len(PAUSE_TABS)
            return "rb" if rb_steps <= lb_steps else "lb"
        return "rb"

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

    def write_report(self):
        self.report_dir.mkdir(parents=True, exist_ok=True)
        data = asdict(self.report)
        path = self.report_dir / f"focus_sweep_{timestamp_slug()}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        latest = self.report_dir / "focus_sweep_latest.json"
        latest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture every visible Forza pause-menu focus state.")
    parser.add_argument("--title", default="Forza")
    parser.add_argument("--raw-root", default="datasets/forza_ui/raw")
    parser.add_argument("--report-dir", default="reports")
    parser.add_argument("--min-conf", type=float, default=0.42)
    parser.add_argument("--hold", type=float, default=0.14)
    parser.add_argument("--settle", type=float, default=0.75)
    parser.add_argument("--max-steps", type=int, default=180)
    parser.add_argument("--enter-focused", action="store_true")
    parser.add_argument("--enter-limit", type=int, default=20)
    args = parser.parse_args(argv)
    sweeper = FocusSweeper(
        title=args.title,
        raw_root=args.raw_root,
        report_dir=args.report_dir,
        min_confidence=args.min_conf,
        hold=args.hold,
        settle=args.settle,
        max_steps=args.max_steps,
        enter_focused=args.enter_focused,
        enter_limit=args.enter_limit,
    )
    report = sweeper.run()
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
