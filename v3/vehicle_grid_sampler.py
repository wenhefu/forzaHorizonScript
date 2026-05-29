from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

import focus
from gamepad import Gamepad
from ocr_engine import OcrReader
from v2.semantic import ForzaSemanticAnalyzer
from v3.frame_utils import timestamp_slug
from v3.hybrid import HybridVisionRecognizer
from v3.sample_collector import SampleCollector
from v3.yolo_detector import YoloOnnxDetector
from window_capture import capture_client, capture_client_printwindow


SAFE_GRID_BUTTONS = {
    "dpad_left",
    "dpad_right",
    "dpad_up",
    "dpad_down",
    "lb",
    "rb",
    "back",
}

KNOWN_CAPTURE_ONLY_SCREENS = {
    "design_grid",
    "color_select",
    "car_preview",
    "purchase_confirm",
    "modal_warning",
    "loading_transition",
    "idle_showcase",
}


@dataclass
class VehicleGridStep:
    index: int
    kind: str
    button: str
    screen: str
    ui_node: str
    active_tab: str
    selected_item: str
    control_hints: list[dict] = field(default_factory=list)
    scroll_state: dict = field(default_factory=dict)
    sample_dir: str = ""
    note: str = ""


@dataclass
class VehicleGridSampleReport:
    started_at: str
    title: str
    steps: list[VehicleGridStep] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class VehicleGridSampler:
    """Collect vehicle grid and manufacturer-list samples with safe focus moves.

    This V3-only tool uses normal ViGEm/vgamepad controller input. It does not
    inject, hook, fake focus, modify game files, or press A to buy/select a car.
    """

    def __init__(
        self,
        title: str = "Forza",
        raw_root: str | Path = "datasets/forza_ui/raw",
        report_dir: str | Path = "reports",
        max_steps: int = 18,
        hold: float = 0.12,
        settle: float = 0.65,
        min_confidence: float = 0.42,
        open_manufacturer: bool = True,
        dismiss_controller_modal: bool = True,
        input_mode: str = "gamepad",
        click_titlebar: bool = False,
        sequence: list[str] | None = None,
    ):
        self.title = title
        self.raw_root = Path(raw_root)
        self.report_dir = Path(report_dir)
        self.max_steps = max(0, int(max_steps))
        self.hold = hold
        self.settle = settle
        self.min_confidence = min_confidence
        self.open_manufacturer = open_manufacturer
        self.dismiss_controller_modal = dismiss_controller_modal
        self.input_mode = input_mode
        self.click_titlebar = click_titlebar
        self.sequence = list(sequence or [])
        self.ocr = OcrReader()
        self.analyzer = ForzaSemanticAnalyzer()
        self.detector = YoloOnnxDetector()
        self.recognizer = HybridVisionRecognizer(detector=self.detector, ocr_reader=self.ocr, analyzer=self.analyzer)
        self.collector = SampleCollector(raw_root=self.raw_root, min_confidence=min_confidence)
        self.pad: Gamepad | None = None
        self.report = VehicleGridSampleReport(datetime.now(timezone.utc).astimezone().isoformat(), title)
        self._step_index = 0

    def run(self) -> VehicleGridSampleReport:
        try:
            self.report_dir.mkdir(parents=True, exist_ok=True)
            if self.click_titlebar:
                self._click_titlebar()
            if self.input_mode == "gamepad":
                self.pad = Gamepad()
                self.pad.neutral()
            time.sleep(1.0)
            current = self.capture_and_save("vehicle_grid_sampler_start", "initial vehicle/manufacturer grid capture")
            if self.dismiss_controller_modal and self._is_controller_modal(current):
                current = self.tap("a", "vehicle_grid_dismiss_controller", "dismiss controller disconnected modal")
            if self.open_manufacturer and self._has_control(current, "manufacturer") and current.screen in (
                "vehicle_buy_grid",
                "eventlab_my_cars",
                "garage_my_cars",
            ):
                current = self.tap("back", "vehicle_grid_open_manufacturer", "open manufacturer list with View/Back")
            if self.sequence:
                self._sweep(self.sequence, "custom")
            elif current.screen == "manufacturer_grid":
                self._sweep(self._manufacturer_sequence(), "manufacturer_grid")
            elif current.screen in ("vehicle_buy_grid", "eventlab_my_cars", "garage_my_cars"):
                self._sweep(self._vehicle_sequence(), "vehicle_grid")
            elif current.screen in KNOWN_CAPTURE_ONLY_SCREENS:
                pass
            else:
                self.report.errors.append(f"current screen is not a known vehicle grid: {current.screen}")
        except Exception as exc:
            self.report.errors.append(str(exc))
        finally:
            if self.pad:
                self.pad.neutral()
            self.write_report()
        return self.report

    def _sweep(self, sequence: list[str], label: str) -> None:
        for index, button in enumerate(sequence):
            if self._step_index >= self.max_steps:
                break
            self.tap(button, f"{label}_{index:02d}_{button}", f"{label} focus move {button}")

    def _vehicle_sequence(self) -> list[str]:
        return [
            "dpad_right",
            "dpad_down",
            "dpad_down",
            "dpad_left",
            "dpad_up",
            "dpad_right",
            "dpad_right",
            "dpad_down",
            "dpad_left",
            "dpad_left",
            "dpad_up",
            "dpad_right",
        ]

    def _manufacturer_sequence(self) -> list[str]:
        return [
            "dpad_left",
            "dpad_right",
            "dpad_right",
            "dpad_down",
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
        ]

    def tap(self, button: str, label_hint: str, note: str):
        if button not in SAFE_GRID_BUTTONS and button != "a":
            raise ValueError(f"unsafe vehicle-grid sampler button: {button}")
        if button == "a" and label_hint != "vehicle_grid_dismiss_controller":
            raise ValueError("vehicle-grid sampler only allows A for controller-disconnected modal dismissal")
        if self._step_index >= self.max_steps:
            raise RuntimeError(f"max steps reached: {self.max_steps}")
        if self.click_titlebar:
            self._click_titlebar()
        if self.input_mode == "keyboard":
            self._tap_keyboard(button)
        else:
            if not self.pad:
                raise RuntimeError("gamepad is not initialized")
            self.pad.tap(button, hold=self.hold)
        time.sleep(self.settle)
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
        items = self.ocr.read_frame(frame, min_confidence=self.min_confidence)
        v2 = self.analyzer.analyze(frame, items)
        v3 = self.recognizer.analyze_frame(
            frame,
            ocr_items=items,
            run_full_ocr=False,
            run_region_ocr=True,
            min_confidence=self.min_confidence,
        )
        return frame, title, method, items, v2, v3

    def capture_and_save(self, label_hint: str, note: str, button: str = "", kind: str = "capture") -> VehicleGridStep:
        frame, title, method, items, v2, v3 = self.capture()
        sample_dir = self.collector.save_sample(
            frame,
            title,
            items,
            v3,
            candidates=v3.detections,
            capture_method=f"vehicle-grid-sampler:{method}",
            label_hint=label_hint,
            extra_metadata={"v2_understanding": v2},
        )
        sample_text = str(sample_dir)
        self.report.samples.append(sample_text)
        step = VehicleGridStep(
            index=self._step_index,
            kind=kind,
            button=button,
            screen=v3.screen,
            ui_node=v3.ui_node,
            active_tab=v3.active_tab,
            selected_item=v3.selected_item,
            control_hints=v3.control_hints,
            scroll_state=v3.scroll_state,
            sample_dir=sample_text,
            note=note,
        )
        self.report.steps.append(step)
        self.write_report()
        return step

    def _has_control(self, step: VehicleGridStep, action: str) -> bool:
        return any(hint.get("action") == action for hint in step.control_hints)

    def _is_controller_modal(self, step: VehicleGridStep) -> bool:
        text = f"{step.screen} {step.ui_node} {step.selected_item}"
        return "控制器未连接" in text or "重新连接控制器" in text

    def _tap_keyboard(self, button: str) -> None:
        key_map = {
            "dpad_left": 0x25,
            "dpad_up": 0x26,
            "dpad_right": 0x27,
            "dpad_down": 0x28,
            "lb": 0x51,  # Q
            "rb": 0x45,  # E
            "back": 0x08,  # Backspace
            "a": 0x0D,  # Enter
        }
        vk = key_map.get(button)
        if not vk:
            raise ValueError(f"no keyboard mapping for {button}")
        user32 = ctypes.windll.user32
        user32.keybd_event(vk, 0, 0, 0)
        time.sleep(self.hold)
        user32.keybd_event(vk, 0, 0x0002, 0)

    def _click_titlebar(self) -> bool:
        hwnd = focus.find_window(self.title)
        if not hwnd or not focus.user32:
            return False
        rect = wintypes.RECT()
        if not focus.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        x = int(rect.left + min(160, max(60, (rect.right - rect.left) * 0.10)))
        y = int(rect.top + 16)
        focus.user32.SetCursorPos(x, y)
        time.sleep(0.03)
        focus.user32.mouse_event(0x0002, 0, 0, 0, 0)
        time.sleep(0.03)
        focus.user32.mouse_event(0x0004, 0, 0, 0, 0)
        time.sleep(0.12)
        return True

    def write_report(self) -> None:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        data = asdict(self.report)
        path = self.report_dir / f"vehicle_grid_sampler_{timestamp_slug()}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        latest = self.report_dir / "vehicle_grid_sampler_latest.json"
        latest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect V3 vehicle-grid/manufacturer samples with safe vgamepad focus moves.")
    parser.add_argument("--title", default="Forza")
    parser.add_argument("--raw-root", default="datasets/forza_ui/raw")
    parser.add_argument("--report-dir", default="reports")
    parser.add_argument("--max-steps", type=int, default=18)
    parser.add_argument("--hold", type=float, default=0.12)
    parser.add_argument("--settle", type=float, default=0.65)
    parser.add_argument("--min-conf", type=float, default=0.42)
    parser.add_argument("--no-open-manufacturer", action="store_true")
    parser.add_argument("--no-dismiss-controller-modal", action="store_true")
    parser.add_argument("--input-mode", choices=("gamepad", "keyboard"), default="gamepad")
    parser.add_argument("--click-titlebar", action="store_true")
    parser.add_argument("--sequence", default="", help="Comma-separated safe buttons, e.g. dpad_down,dpad_down,dpad_right")
    args = parser.parse_args(argv)
    sampler = VehicleGridSampler(
        title=args.title,
        raw_root=args.raw_root,
        report_dir=args.report_dir,
        max_steps=args.max_steps,
        hold=args.hold,
        settle=args.settle,
        min_confidence=args.min_conf,
        open_manufacturer=not args.no_open_manufacturer,
        dismiss_controller_modal=not args.no_dismiss_controller_modal,
        input_mode=args.input_mode,
        click_titlebar=args.click_titlebar,
        sequence=[item.strip() for item in args.sequence.split(",") if item.strip()],
    )
    report = sampler.run()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 0 if not report.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
