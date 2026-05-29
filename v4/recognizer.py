from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Any

import focus
from ocr_engine import OcrReader
from screen_detector import ForzaScreenDetector
from v2.semantic import ForzaSemanticAnalyzer
from v3.hybrid import HybridVisionRecognizer
from v3.yolo_detector import DEFAULT_MODEL, YoloOnnxDetector
from window_capture import capture_client, capture_client_printwindow


@dataclass
class V4Snapshot:
    frame: Any
    window_title: str
    capture_method: str
    ocr_items: list
    v3: Any
    smart_state: str = ""
    smart_confidence: float = 0.0
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "window_title": self.window_title,
            "capture_method": self.capture_method,
            "ocr_items": len(self.ocr_items),
            "v3": self.v3.to_dict() if hasattr(self.v3, "to_dict") else {},
            "smart_state": self.smart_state,
            "smart_confidence": self.smart_confidence,
            "elapsed_ms": self.elapsed_ms,
        }


class V4Recognizer:
    """Capture Forza and run the V3 hybrid recognizer plus V1 race detector."""

    def __init__(
        self,
        title: str = "Forza",
        model_path: str | None = None,
        min_confidence: float = 0.42,
        logger=None,
    ):
        self.title = title
        self.min_confidence = float(min_confidence)
        self.logger = logger or logging.getLogger("forza6helper.v4")
        self.ocr = OcrReader(logger=self.logger)
        self.analyzer = ForzaSemanticAnalyzer()
        self.detector = YoloOnnxDetector(model_path=model_path or DEFAULT_MODEL)
        self.hybrid = HybridVisionRecognizer(
            detector=self.detector,
            ocr_reader=self.ocr,
            analyzer=self.analyzer,
        )
        self.smart_detector = ForzaScreenDetector()

    def capture(self, full_ocr: bool = True, region_ocr: bool = True) -> V4Snapshot:
        start = time.perf_counter()
        hwnd = focus.find_window(self.title)
        if not hwnd:
            raise RuntimeError(f"No game window title contains {self.title!r}")
        title = focus.window_title(hwnd) or self.title
        try:
            frame = capture_client_printwindow(hwnd)
            method = "PrintWindow"
        except Exception:
            frame = capture_client(hwnd)
            method = "BitBlt"

        items = []
        if full_ocr:
            items = self.ocr.read_frame(frame, min_confidence=self.min_confidence)
        v3 = self.hybrid.analyze_frame(
            frame,
            ocr_items=items,
            run_full_ocr=False,
            run_region_ocr=region_ocr,
            min_confidence=self.min_confidence,
        )
        smart = self.smart_detector.detect(frame)
        elapsed = (time.perf_counter() - start) * 1000.0
        return V4Snapshot(
            frame=frame,
            window_title=title,
            capture_method=method,
            ocr_items=items,
            v3=v3,
            smart_state=getattr(smart, "state", ""),
            smart_confidence=float(getattr(smart, "confidence", 0.0) or 0.0),
            elapsed_ms=elapsed,
        )

