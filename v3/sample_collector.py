from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterable

import focus
from ocr_engine import OcrReader
from v2.semantic import ForzaSemanticAnalyzer
from v3.candidates import detect_focus_candidates
from v3.frame_utils import load_frame_from_image, safe_slug, save_frame_png, timestamp_slug
from window_capture import capture_client, capture_client_printwindow


DEFAULT_RAW_ROOT = Path("datasets/forza_ui/raw")


def _safe_json(value):
    if is_dataclass(value):
        return _safe_json(asdict(value))
    if isinstance(value, dict):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_json(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def ocr_items_to_dicts(items) -> list[dict]:
    rows = []
    for item in items or []:
        rows.append(
            {
                "text": str(getattr(item, "text", "") or ""),
                "confidence": float(getattr(item, "confidence", 0.0) or 0.0),
                "box": _safe_json(getattr(item, "box", [])),
                "x1": float(getattr(item, "x1", 0.0) or 0.0),
                "y1": float(getattr(item, "y1", 0.0) or 0.0),
                "x2": float(getattr(item, "x2", 0.0) or 0.0),
                "y2": float(getattr(item, "y2", 0.0) or 0.0),
                "nx1": float(getattr(item, "nx1", 0.0) or 0.0),
                "ny1": float(getattr(item, "ny1", 0.0) or 0.0),
                "nx2": float(getattr(item, "nx2", 0.0) or 0.0),
                "ny2": float(getattr(item, "ny2", 0.0) or 0.0),
                "ncx": float(getattr(item, "ncx", 0.0) or 0.0),
                "ncy": float(getattr(item, "ncy", 0.0) or 0.0),
            }
        )
    return rows


def understanding_to_dict(understanding) -> dict:
    if not understanding:
        return {}
    data = _safe_json(understanding)
    data["text"] = understanding.as_text()
    return data


class SampleCollector:
    def __init__(self, raw_root: str | Path = DEFAULT_RAW_ROOT, min_confidence: float = 0.42):
        self.raw_root = Path(raw_root)
        self.min_confidence = min_confidence
        self.ocr = OcrReader()
        self.analyzer = ForzaSemanticAnalyzer()

    def capture_window(self, title: str = "Forza"):
        hwnd = focus.find_window(title)
        if not hwnd:
            raise RuntimeError(f"没找到标题包含“{title}”的窗口")
        try:
            frame = capture_client_printwindow(hwnd)
            capture_method = "PrintWindow"
        except Exception:
            frame = capture_client(hwnd)
            capture_method = "BitBlt"
        window_title = focus.window_title(hwnd) or title
        return frame, window_title, capture_method

    def analyze_frame(self, frame):
        ocr_items = self.ocr.read_frame(frame, min_confidence=self.min_confidence)
        understanding = self.analyzer.analyze(frame, ocr_items)
        candidates = detect_focus_candidates(frame, understanding)
        return ocr_items, understanding, candidates

    def save_sample(
        self,
        frame,
        window_title: str,
        ocr_items,
        understanding,
        candidates=None,
        source_path: str = "",
        capture_method: str = "",
        label_hint: str = "",
        extra_metadata: dict | None = None,
    ) -> Path:
        candidates = list(candidates or detect_focus_candidates(frame, understanding))
        screen = getattr(understanding, "screen", "unknown") or "unknown"
        selected = safe_slug(getattr(understanding, "selected_item", "") or label_hint or "sample")
        sample_id = f"{timestamp_slug()}_{safe_slug(screen)}_{selected}"
        sample_dir = self.raw_root / sample_id
        sample_dir.mkdir(parents=True, exist_ok=True)
        image_path = sample_dir / "image.png"
        metadata_path = sample_dir / "metadata.json"
        save_frame_png(frame, image_path)
        metadata = {
            "schema": "forza_ui_raw_sample_v1",
            "sample_id": sample_id,
            "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "window": {
                "title": window_title,
                "width": int(frame.width),
                "height": int(frame.height),
                "capture_method": capture_method,
            },
            "source_path": source_path,
            "label_hint": label_hint,
            "image": "image.png",
            "ocr_raw": ocr_items_to_dicts(ocr_items),
            "understanding": understanding_to_dict(understanding),
            "candidates": [candidate.to_dict() for candidate in candidates],
        }
        if extra_metadata:
            metadata["extra"] = _safe_json(extra_metadata)
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return sample_dir

    def capture_and_save(self, title: str = "Forza") -> Path:
        frame, window_title, capture_method = self.capture_window(title)
        ocr_items, understanding, candidates = self.analyze_frame(frame)
        return self.save_sample(
            frame,
            window_title,
            ocr_items,
            understanding,
            candidates=candidates,
            capture_method=capture_method,
        )

    def import_images(self, paths: Iterable[str | Path], title: str = "local screenshot") -> list[Path]:
        saved = []
        for path in paths:
            path = Path(path)
            if not path.exists():
                continue
            frame = load_frame_from_image(path)
            ocr_items, understanding, candidates = self.analyze_frame(frame)
            saved.append(
                self.save_sample(
                    frame,
                    title,
                    ocr_items,
                    understanding,
                    candidates=candidates,
                    source_path=str(path),
                    capture_method="local-image",
                )
            )
        return saved


def _capture_glob(patterns: list[str], limit: int = 0) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        paths.extend(Path().glob(pattern) if not Path(pattern).is_absolute() else Path(pattern).parent.glob(Path(pattern).name))
    unique = sorted(dict.fromkeys(path.resolve() for path in paths if path.is_file()))
    if limit:
        unique = unique[:limit]
    return unique


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect Forza UI raw training samples.")
    parser.add_argument("--title", default="Forza", help="Window title substring for live capture.")
    parser.add_argument("--raw-root", default=str(DEFAULT_RAW_ROOT), help="Raw sample output directory.")
    parser.add_argument("--min-conf", type=float, default=0.42, help="OCR confidence threshold.")
    parser.add_argument("--capture", action="store_true", help="Capture the live game window once.")
    parser.add_argument("--import", dest="imports", nargs="*", default=[], help="Image files or glob patterns to import.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum imported image count.")
    args = parser.parse_args(argv)

    collector = SampleCollector(args.raw_root, min_confidence=args.min_conf)
    saved: list[Path] = []
    if args.capture:
        saved.append(collector.capture_and_save(args.title))
    if args.imports:
        paths = _capture_glob(args.imports, limit=args.limit)
        saved.extend(collector.import_images(paths, title="local screenshot"))
    if not saved:
        parser.error("Use --capture or --import to create samples.")
    for path in saved:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
