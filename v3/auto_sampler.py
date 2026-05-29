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


PAUSE_TARGETS = list(PAUSE_TABS)
EVENTLAB_SCREENS = {
    "eventlab_home",
    "eventlab_events",
    "eventlab_favorites",
    "eventlab_my_cars",
    "eventlab_race_type",
    "eventlab_filter",
}


@dataclass
class StepRecord:
    index: int
    kind: str
    button: str
    before_screen: str
    before_tab: str
    before_item: str
    after_screen: str = ""
    after_tab: str = ""
    after_item: str = ""
    verified: bool = False
    sample_dir: str = ""
    note: str = ""


@dataclass
class SamplerReport:
    started_at: str
    title: str
    steps: list[StepRecord] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class VisionAutoSampler:
    """Controller-driven sampler for V3.

    This tool is allowed to send virtual Xbox controller input for sampling, but
    it does not inject, hook, fake focus, or modify game files.  Every navigation
    input is followed by a fresh recognition pass before the next input.
    """

    def __init__(
        self,
        title: str = "Forza",
        raw_root: str | Path = "datasets/forza_ui/raw",
        report_dir: str | Path = "reports",
        min_confidence: float = 0.42,
        hold: float = 0.12,
        settle: float = 0.75,
        max_steps: int = 40,
        aggressive: bool = False,
    ):
        self.title = title
        self.collector = SampleCollector(raw_root=raw_root, min_confidence=min_confidence)
        self.ocr = OcrReader()
        self.analyzer = ForzaSemanticAnalyzer()
        self.report_dir = Path(report_dir)
        self.hold = hold
        self.settle = settle
        self.max_steps = max_steps
        self.aggressive = aggressive
        self.pad: Gamepad | None = None
        self.report = SamplerReport(datetime.now(timezone.utc).astimezone().isoformat(), title)
        self._step_index = 0
        self._last_candidates = []

    def run(self) -> SamplerReport:
        try:
            self.report_dir.mkdir(parents=True, exist_ok=True)
            self._plain_activate()
            self.pad = Gamepad()
            self.pad.neutral()
            time.sleep(2.0)
            self._plain_activate()
            current = self.capture_and_save("start")

            if current.screen == "controller_disconnected":
                current = self._dismiss_controller_modal(current)
            if self.aggressive and current.screen == "modal_warning":
                current = self.tap_and_capture(
                    "a",
                    current,
                    "dismiss_modal_after_controller",
                    "confirm warning/search-result modal after controller reconnect",
                    settle=max(1.0, self.settle),
                )

            if not self._is_pause_or_eventlab(current):
                if self.aggressive:
                    try:
                        current = self.tap_and_verify(
                            "start",
                            current,
                            self._is_pause_or_eventlab,
                            "open_pause_menu",
                            "open pause menu with Menu/start",
                            retries=8,
                        )
                    except RuntimeError as exc:
                        self.report.errors.append(str(exc))
                        current = self.capture_and_save("aggressive_open_pause_failed")
                        current = self._ensure_pause_recoverable(current, "aggressive_initial_recover")
                else:
                    current = self.tap_and_verify(
                        "start",
                        current,
                        self._is_pause_or_eventlab,
                        "open_pause_menu",
                        "open pause menu with Menu/start",
                        retries=8,
                    )

            if self._is_eventlab(current):
                current = self._back_to_pause(current)

            current = self._sweep_pause_tabs(current)
            current = self._try_eventlab(current)
            if self.aggressive:
                current = self._aggressive_explore(current)
        except Exception as exc:
            self.report.errors.append(str(exc))
        finally:
            if self.pad:
                self.pad.neutral()
            self.write_report()
        return self.report

    def _dismiss_controller_modal(self, current):
        last = current
        for attempt in range(5):
            time.sleep(0.8 + attempt * 0.4)
            try:
                return self.tap_and_verify(
                    "a",
                    last,
                    lambda u: u.screen != "controller_disconnected",
                    "dismiss_controller_disconnected",
                    "close controller disconnected modal",
                    retries=4,
                )
            except RuntimeError as exc:
                self.report.errors.append(str(exc))
                last = self.capture_and_save(f"controller_disconnected_retry_{attempt + 1}")
        return last

    def capture(self):
        hwnd = focus.find_window(self.title)
        if not hwnd:
            raise RuntimeError(f"没找到标题包含“{self.title}”的窗口")
        try:
            frame = capture_client_printwindow(hwnd)
            method = "PrintWindow"
        except Exception:
            frame = capture_client(hwnd)
            method = "BitBlt"
        items = self.ocr.read_frame(frame, min_confidence=self.collector.min_confidence)
        understanding = self.analyzer.analyze(frame, items)
        candidates = detect_focus_candidates(frame, understanding)
        self._last_candidates = candidates
        return frame, focus.window_title(hwnd) or self.title, method, items, understanding, candidates

    def capture_and_save(self, label_hint: str):
        frame, title, method, items, understanding, candidates = self.capture()
        sample_dir = self.collector.save_sample(
            frame,
            title,
            items,
            understanding,
            candidates=candidates,
            capture_method=f"auto-sampler:{method}",
            label_hint=label_hint,
        )
        self.report.samples.append(str(sample_dir))
        return understanding

    def tap_and_verify(self, button, before, predicate, label_hint, note, retries=5):
        if self._step_index >= self.max_steps:
            raise RuntimeError(f"max steps reached: {self.max_steps}")
        if not self.pad:
            raise RuntimeError("gamepad is not initialized")
        record = StepRecord(
            index=self._step_index,
            kind="tap_and_verify",
            button=button,
            before_screen=before.screen,
            before_tab=before.active_tab,
            before_item=before.selected_item,
            note=note,
        )
        self._step_index += 1
        self._plain_activate()
        self.pad.tap(button, hold=self.hold)
        time.sleep(self.settle)
        last = before
        for _ in range(retries):
            try:
                frame, title, method, items, understanding, candidates = self.capture()
            except Exception as exc:
                self.report.errors.append(str(exc))
                time.sleep(self.settle)
                continue
            last = understanding
            if predicate(understanding):
                sample_dir = self.collector.save_sample(
                    frame,
                    title,
                    items,
                    understanding,
                    candidates=candidates,
                    capture_method=f"auto-sampler:{method}",
                    label_hint=label_hint,
                )
                record.after_screen = understanding.screen
                record.after_tab = understanding.active_tab
                record.after_item = understanding.selected_item
                record.verified = True
                record.sample_dir = str(sample_dir)
                self.report.samples.append(str(sample_dir))
                self.report.steps.append(record)
                return understanding
            time.sleep(self.settle)

        record.after_screen = last.screen
        record.after_tab = last.active_tab
        record.after_item = last.selected_item
        record.verified = False
        self.report.steps.append(record)
        self.write_report()
        raise RuntimeError(
            f"verification failed after {button}: {note}; "
            f"after={last.screen}/{last.active_tab}/{last.selected_item}"
        )

    def tap_and_capture(self, button, before, label_hint, note, settle=None):
        if self._step_index >= self.max_steps:
            raise RuntimeError(f"max steps reached: {self.max_steps}")
        if not self.pad:
            raise RuntimeError("gamepad is not initialized")
        record = StepRecord(
            index=self._step_index,
            kind="tap_and_capture",
            button=button,
            before_screen=before.screen,
            before_tab=before.active_tab,
            before_item=before.selected_item,
            note=note,
        )
        self._step_index += 1
        self._plain_activate()
        self.pad.tap(button, hold=self.hold)
        time.sleep(self.settle if settle is None else settle)
        frame, title, method, items, understanding, candidates = self.capture()
        sample_dir = self.collector.save_sample(
            frame,
            title,
            items,
            understanding,
            candidates=candidates,
            capture_method=f"auto-sampler:{method}",
            label_hint=label_hint,
        )
        record.after_screen = understanding.screen
        record.after_tab = understanding.active_tab
        record.after_item = understanding.selected_item
        record.verified = (understanding.screen, understanding.active_tab, understanding.selected_item) != (
            before.screen,
            before.active_tab,
            before.selected_item,
        )
        record.sample_dir = str(sample_dir)
        self.report.samples.append(str(sample_dir))
        self.report.steps.append(record)
        self.write_report()
        return understanding

    def wait_and_capture(self, current, seconds, label_hint, note):
        if self._step_index >= self.max_steps:
            raise RuntimeError(f"max steps reached: {self.max_steps}")
        record = StepRecord(
            index=self._step_index,
            kind="wait_and_capture",
            button="",
            before_screen=current.screen,
            before_tab=current.active_tab,
            before_item=current.selected_item,
            note=note,
        )
        self._step_index += 1
        time.sleep(seconds)
        frame, title, method, items, understanding, candidates = self.capture()
        sample_dir = self.collector.save_sample(
            frame,
            title,
            items,
            understanding,
            candidates=candidates,
            capture_method=f"auto-sampler:{method}",
            label_hint=label_hint,
        )
        record.after_screen = understanding.screen
        record.after_tab = understanding.active_tab
        record.after_item = understanding.selected_item
        record.verified = understanding.screen != current.screen
        record.sample_dir = str(sample_dir)
        self.report.samples.append(str(sample_dir))
        self.report.steps.append(record)
        self.write_report()
        return understanding

    def _sweep_pause_tabs(self, current):
        if not self._is_pause(current):
            return current
        for target in PAUSE_TARGETS:
            current = self._go_pause_tab(current, target)
            current = self._sweep_focus_on_current_tab(current)
        return current

    def _go_pause_tab(self, current, target):
        for _ in range(8):
            if current.active_tab == target or self._screen_matches_target(current.screen, target):
                self.capture_and_save(f"pause_tab_{target}")
                return current
            button = self._tab_button(current.active_tab, target)
            before_key = (current.screen, current.active_tab, current.selected_item)
            moved = False
            for candidate_button in [button, self._opposite_shoulder(button)]:
                if not candidate_button:
                    continue
                try:
                    current = self.tap_and_verify(
                        candidate_button,
                        current,
                        lambda u, key=before_key: self._is_pause(u) and (u.screen, u.active_tab, u.selected_item) != key,
                        f"pause_tab_{target}",
                        f"go to pause tab {target}",
                        retries=4,
                    )
                    moved = True
                    break
                except RuntimeError as exc:
                    self.report.errors.append(str(exc))
                    self.write_report()
            if not moved:
                return current
        return current

    def _sweep_focus_on_current_tab(self, current):
        if current.active_tab == "剧情" or current.screen == "pause_story":
            sequence = ["dpad_right", "dpad_down", "dpad_right", "dpad_down", "dpad_left", "dpad_up"]
        elif current.active_tab == "车辆" or current.screen in ("pause_vehicle", "pause_vehicle_entry"):
            sequence = ["dpad_right", "dpad_down", "dpad_right", "dpad_down", "dpad_down", "dpad_up", "dpad_left"]
        elif current.active_tab == "创意中心" or current.screen == "pause_creative_hub":
            sequence = ["dpad_right", "dpad_down", "dpad_left", "dpad_up"]
        elif current.active_tab in ("我的地平线", "在线", "商店") or current.screen in ("pause_my_horizon", "pause_online", "pause_store", "pause_menu"):
            sequence = ["dpad_right", "dpad_down", "dpad_right", "dpad_down", "dpad_left", "dpad_up"]
        else:
            return current

        for button in sequence:
            before_key = (current.screen, current.active_tab, current.selected_item)
            try:
                current = self.tap_and_verify(
                    button,
                    current,
                    lambda u, key=before_key: self._is_pause(u) and (u.screen, u.active_tab, u.selected_item) != key,
                    f"focus_{current.active_tab or current.screen}_{button}",
                    f"sweep focus with {button}",
                    retries=3,
                )
            except RuntimeError as exc:
                self.report.errors.append(str(exc))
                self.write_report()
                break
        return current

    def _try_eventlab(self, current):
        current = self._go_pause_tab(current, "创意中心")
        if not self._is_pause(current):
            return current
        current = self._move_creative_focus_to_eventlab(current)
        if not self._creative_focus_is_eventlab():
            self.report.errors.append("creative hub focus did not move to EventLab; skip A to avoid blind enter")
            self.write_report()
            return current
        try:
            current = self.tap_and_verify(
                "a",
                current,
                self._is_eventlab,
                "eventlab_entered",
                "enter EventLab/creative hub focused item",
                retries=8,
            )
        except RuntimeError as exc:
            self.report.errors.append(str(exc))
            self.write_report()
            return current

        for button in ["rb", "rb", "lb", "a"]:
            try:
                before_key = (current.screen, current.active_tab, current.selected_item)
                current = self.tap_and_verify(
                    button,
                    current,
                    lambda u, key=before_key: (self._is_eventlab(u) or u.screen == "modal_warning") and (u.screen, u.active_tab, u.selected_item) != key,
                    f"eventlab_{button}",
                    f"sample EventLab navigation with {button}",
                    retries=5,
                )
            except RuntimeError as exc:
                self.report.errors.append(str(exc))
                self.write_report()
                break
        return current

    def _aggressive_explore(self, current):
        current = self._ensure_pause_recoverable(current, "aggressive_start")
        for target in self._aggressive_pause_targets():
            if self._step_index >= self.max_steps:
                break
            current = self._ensure_pause_recoverable(current, f"aggressive_before_tab_{target}")
            current = self._go_pause_tab(current, target)
            self.capture_and_save(f"aggressive_pause_tab_{target}")
            current = self._aggressive_probe_current_focus(current, f"aggressive_enter_{target}_0")
            current = self._ensure_pause_recoverable(current, f"aggressive_after_enter_{target}_0")
            for index, move in enumerate(self._aggressive_focus_moves(current)):
                if self._step_index >= self.max_steps:
                    break
                try:
                    current = self.tap_and_capture(
                        move,
                        current,
                        f"aggressive_focus_{target}_{index}_{move}",
                        f"aggressive move focus on {target} with {move}",
                        settle=self.settle,
                    )
                except Exception as exc:
                    self.report.errors.append(str(exc))
                    self.write_report()
                    break
                if not self._is_pause(current):
                    current = self._ensure_pause_recoverable(current, f"aggressive_recover_focus_{target}_{index}")
                    continue
                current = self._aggressive_probe_current_focus(current, f"aggressive_enter_{target}_{index + 1}")
                current = self._ensure_pause_recoverable(current, f"aggressive_after_enter_{target}_{index + 1}")
        return current

    def _aggressive_probe_current_focus(self, current, label_hint):
        if not self._is_pause(current):
            return current
        try:
            current = self.tap_and_capture(
                "a",
                current,
                label_hint,
                "aggressive enter focused tile",
                settle=max(1.4, self.settle * 1.6),
            )
            current = self.wait_and_capture(
                current,
                max(1.2, self.settle),
                f"{label_hint}_settled",
                "capture after possible transition settles",
            )
            current = self._aggressive_inside_page(current, label_hint)
        except Exception as exc:
            self.report.errors.append(str(exc))
            self.write_report()
        return current

    def _aggressive_inside_page(self, current, label_hint):
        if self._is_pause(current):
            return current
        if current.screen == "controller_disconnected":
            return self._dismiss_controller_modal(current)
        if current.screen in ("eventlab_filter", "eventlab_race_type", "modal_warning"):
            return self.tap_and_capture("b", current, f"{label_hint}_modal_back", "back out of modal warning")
        if current.screen in ("race_hud", "post_race_next"):
            return current

        sequence = ["dpad_right", "dpad_down", "rb", "lb", "x", "y", "a"]
        for index, button in enumerate(sequence):
            if self._step_index >= self.max_steps or self._is_pause(current):
                break
            try:
                current = self.tap_and_capture(
                    button,
                    current,
                    f"{label_hint}_inside_{index}_{button}",
                    f"aggressive sample inside entered page with {button}",
                    settle=max(0.9, self.settle),
                )
                if button == "a":
                    current = self.wait_and_capture(
                        current,
                        max(1.6, self.settle * 1.4),
                        f"{label_hint}_inside_{index}_{button}_settled",
                        "capture after deeper aggressive enter",
                    )
                if current.screen in ("race_hud", "post_race_next"):
                    break
                if current.screen in ("eventlab_filter", "eventlab_race_type", "modal_warning"):
                    current = self.tap_and_capture(
                        "b",
                        current,
                        f"{label_hint}_inside_{index}_modal_back",
                        "back out of modal warning",
                    )
            except Exception as exc:
                self.report.errors.append(str(exc))
                self.write_report()
                break
        return current

    def _ensure_pause_recoverable(self, current, label_hint):
        if current.screen == "controller_disconnected":
            current = self._dismiss_controller_modal(current)
        if current.screen == "modal_warning":
            for button in ("a", "b"):
                if self._is_pause(current):
                    return current
                current = self.tap_and_capture(
                    button,
                    current,
                    f"{label_hint}_dismiss_modal_{button}",
                    f"dismiss modal warning with {button}",
                    settle=max(1.0, self.settle),
                )
        if self._is_pause(current):
            return current
        recovery = ["b", "b", "start", "b", "start"]
        for index, button in enumerate(recovery):
            if self._is_pause(current):
                return current
            if current.screen == "controller_disconnected":
                current = self._dismiss_controller_modal(current)
                if self._is_pause(current):
                    return current
            try:
                current = self.tap_and_capture(
                    button,
                    current,
                    f"{label_hint}_recover_{index}_{button}",
                    f"aggressive recovery toward pause with {button}",
                    settle=max(1.0, self.settle),
                )
            except Exception as exc:
                self.report.errors.append(str(exc))
                self.write_report()
                break
        return current

    def _aggressive_pause_targets(self):
        return [PAUSE_TABS[index] for index in (0, 1, 2, 3, 4) if index < len(PAUSE_TABS)]

    def _aggressive_focus_moves(self, current):
        if current.screen in ("pause_vehicle", "pause_vehicle_entry"):
            return ["dpad_right", "dpad_down", "dpad_right", "dpad_down", "dpad_left", "dpad_up"]
        if current.screen == "pause_creative_hub":
            return ["dpad_left", "dpad_right", "dpad_down", "dpad_up", "dpad_left"]
        return ["dpad_right", "dpad_down", "dpad_left", "dpad_up"]

    def _move_creative_focus_to_eventlab(self, current):
        for _ in range(4):
            if self._creative_focus_is_eventlab():
                self.capture_and_save("creative_eventlab_focus")
                return current
            try:
                current = self.tap_and_verify(
                    "dpad_left",
                    current,
                    lambda u: self._is_pause(u) and (u.active_tab == "创意中心" or u.screen == "pause_creative_hub"),
                    "creative_move_left",
                    "move creative hub focus toward EventLab",
                    retries=3,
                )
            except RuntimeError as exc:
                self.report.errors.append(str(exc))
                self.write_report()
                return current
        return current

    def _back_to_pause(self, current):
        for _ in range(5):
            if self._is_pause(current):
                return current
            current = self.tap_and_verify(
                "b",
                current,
                lambda u: self._is_pause(u) or not self._is_eventlab(u),
                "back_toward_pause",
                "return toward pause menu",
                retries=4,
            )
        return current

    def _plain_activate(self):
        hwnd = focus.find_window(self.title)
        if not hwnd or not focus.user32:
            return False
        try:
            focus.user32.ShowWindow(hwnd, focus.SW_RESTORE)
            focus.user32.BringWindowToTop(hwnd)
            focus.user32.SetForegroundWindow(hwnd)
            time.sleep(0.2)
            return True
        except Exception:
            return False

    def _is_pause_or_eventlab(self, understanding):
        return self._is_pause(understanding) or self._is_eventlab(understanding)

    def _is_pause(self, understanding):
        return bool(
            understanding
            and (
                str(understanding.screen).startswith("pause_")
                or understanding.screen == "pause_menu"
                or understanding.active_tab in PAUSE_TABS
            )
        )

    def _is_eventlab(self, understanding):
        return bool(understanding and understanding.screen in EVENTLAB_SCREENS)

    def _screen_matches_target(self, screen, target):
        mapping = {
            "剧情": "pause_story",
            "车辆": "pause_vehicle",
            "创意中心": "pause_creative_hub",
        }
        expected = mapping.get(target)
        return bool(expected and str(screen).startswith(expected))

    def _tab_button(self, active, target):
        if active in PAUSE_TABS and target in PAUSE_TABS:
            active_index = PAUSE_TABS.index(active)
            target_index = PAUSE_TABS.index(target)
            rb_steps = (target_index - active_index) % len(PAUSE_TABS)
            lb_steps = (active_index - target_index) % len(PAUSE_TABS)
            return "rb" if rb_steps <= lb_steps else "lb"
        return "rb"

    def _opposite_shoulder(self, button):
        if button == "rb":
            return "lb"
        if button == "lb":
            return "rb"
        return ""

    def _creative_focus_is_eventlab(self):
        for detection in self._last_candidates or []:
            if detection.label != "pause_creative_hub_focus":
                continue
            x1, _, x2, _ = detection.bbox
            cx = (x1 + x2) / 2.0
            if cx <= 0.55:
                return True
        return False

    def write_report(self):
        self.report_dir.mkdir(parents=True, exist_ok=True)
        path = self.report_dir / f"auto_sampler_{timestamp_slug()}.json"
        data = asdict(self.report)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        latest = self.report_dir / "auto_sampler_latest.json"
        latest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Automatically navigate Forza with vgamepad and save V3 samples.")
    parser.add_argument("--title", default="Forza")
    parser.add_argument("--raw-root", default="datasets/forza_ui/raw")
    parser.add_argument("--report-dir", default="reports")
    parser.add_argument("--min-conf", type=float, default=0.42)
    parser.add_argument("--hold", type=float, default=0.12)
    parser.add_argument("--settle", type=float, default=0.75)
    parser.add_argument("--max-steps", type=int, default=40)
    parser.add_argument("--aggressive", action="store_true", help="Enter focused tiles, save unknown pages, and try to recover with B/Menu.")
    args = parser.parse_args(argv)
    sampler = VisionAutoSampler(
        title=args.title,
        raw_root=args.raw_root,
        report_dir=args.report_dir,
        min_confidence=args.min_conf,
        hold=args.hold,
        settle=args.settle,
        max_steps=args.max_steps,
        aggressive=args.aggressive,
    )
    report = sampler.run()
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
