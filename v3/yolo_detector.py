from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
import time

from v3.types import VISION_CLASSES, VisionDetection, clamp_bbox


DEFAULT_MODEL = Path("v3/models/forza_ui_yolo.onnx")
BOOTSTRAP_MODEL = Path("v3/models/bootstrap_empty.onnx")
DEFAULT_CLASSES = Path("v3/models/classes.txt")


@dataclass
class DetectorStats:
    loaded: bool
    model_path: str
    provider: str
    last_latency_ms: float = 0.0
    error: str = ""


def load_class_names(path: str | Path = DEFAULT_CLASSES) -> list[str]:
    path = resolve_asset_path(path)
    if path.exists():
        names = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if names:
            return names
    return list(VISION_CLASSES)


def _asset_bases() -> list[Path]:
    bases = [Path.cwd()]
    module_root = Path(__file__).resolve().parents[1]
    bases.append(module_root)
    bundle_root = getattr(sys, "_MEIPASS", "")
    if bundle_root:
        bases.append(Path(bundle_root))
    exe = getattr(sys, "executable", "")
    if exe:
        bases.append(Path(exe).resolve().parent)
    unique: list[Path] = []
    for base in bases:
        try:
            resolved = base.resolve()
        except Exception:
            resolved = base
        if resolved not in unique:
            unique.append(resolved)
    return unique


def resolve_asset_path(path: str | Path) -> Path:
    raw = Path(path)
    if raw.is_absolute():
        return raw
    for base in _asset_bases():
        candidate = base / raw
        if candidate.exists():
            return candidate
    return Path.cwd() / raw


class YoloOnnxDetector:
    """ONNXRuntime wrapper for YOLO-style object detection.

    The parser accepts common Ultralytics ONNX outputs:
    - [1, N, 4 + classes] with xywh boxes and class probabilities
    - [1, N, 5 + classes] with xywh, objectness, class probabilities
    - [1, N, 6] with xyxy, score, class id
    """

    def __init__(
        self,
        model_path: str | Path | None = None,
        classes_path: str | Path = DEFAULT_CLASSES,
        input_size: int = 640,
        conf_threshold: float = 0.25,
        iou_threshold: float = 0.45,
        prefer_directml: bool = False,
    ):
        self.model_path = resolve_asset_path(model_path or DEFAULT_MODEL)
        if not self.model_path.exists():
            bootstrap = resolve_asset_path(BOOTSTRAP_MODEL)
            if bootstrap.exists():
                self.model_path = bootstrap
        self.class_names = load_class_names(classes_path)
        self.input_size = int(input_size)
        self.conf_threshold = float(conf_threshold)
        self.iou_threshold = float(iou_threshold)
        self.prefer_directml = prefer_directml
        self.session = None
        self.input_name = ""
        self.output_names: list[str] = []
        self.stats = DetectorStats(False, str(self.model_path), "none")
        self._load()

    def _load(self) -> None:
        if not self.model_path.exists():
            self.stats.error = f"model not found: {self.model_path}"
            return
        try:
            import onnxruntime as ort

            available = ort.get_available_providers()
            providers = ["CPUExecutionProvider"]
            if self.prefer_directml and "DmlExecutionProvider" in available:
                providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
            self.session = ort.InferenceSession(str(self.model_path), providers=providers)
            model_input = self.session.get_inputs()[0]
            self.input_name = model_input.name
            self._adopt_static_input_size(model_input.shape)
            self.output_names = [output.name for output in self.session.get_outputs()]
            provider = self.session.get_providers()[0] if self.session.get_providers() else "unknown"
            self.stats = DetectorStats(True, str(self.model_path), provider)
        except Exception as exc:
            self.session = None
            self.stats = DetectorStats(False, str(self.model_path), "none", error=str(exc))

    def available(self) -> bool:
        return bool(self.session)

    def _adopt_static_input_size(self, shape) -> None:
        if not shape or len(shape) < 4:
            return
        height, width = shape[-2], shape[-1]
        if isinstance(height, int) and isinstance(width, int) and height == width and height > 0:
            self.input_size = int(height)

    def predict(self, frame) -> list[VisionDetection]:
        if not self.session:
            return []
        import numpy as np

        blob, meta = self._preprocess(frame)
        started = time.perf_counter()
        outputs = self.session.run(self.output_names or None, {self.input_name: blob})
        self.stats.last_latency_ms = (time.perf_counter() - started) * 1000.0
        if not outputs:
            return []
        rows = self._normalize_output(outputs[0])
        detections = self._rows_to_detections(rows, meta)
        return self._nms(detections)

    def _preprocess(self, frame):
        import numpy as np
        from PIL import Image
        from v3.frame_utils import frame_to_pil

        image = frame_to_pil(frame).convert("RGB")
        orig_w, orig_h = image.size
        scale = min(self.input_size / float(orig_w), self.input_size / float(orig_h))
        new_w = max(1, int(round(orig_w * scale)))
        new_h = max(1, int(round(orig_h * scale)))
        resized = image.resize((new_w, new_h), Image.BILINEAR)
        canvas = Image.new("RGB", (self.input_size, self.input_size), (114, 114, 114))
        pad_x = (self.input_size - new_w) // 2
        pad_y = (self.input_size - new_h) // 2
        canvas.paste(resized, (pad_x, pad_y))
        arr = np.asarray(canvas, dtype=np.float32) / 255.0
        blob = arr.transpose(2, 0, 1)[None, :, :, :]
        return blob, {
            "orig_w": orig_w,
            "orig_h": orig_h,
            "scale": scale,
            "pad_x": pad_x,
            "pad_y": pad_y,
        }

    def _normalize_output(self, output):
        import numpy as np

        arr = np.asarray(output)
        if arr.ndim == 3:
            arr = arr[0]
        if arr.ndim != 2:
            return np.empty((0, 0), dtype=np.float32)
        # YOLO exports often return (channels, anchors).  Do not key this only
        # off classes.txt length: during V3 development we may append new labels
        # before the ONNX has been retrained with those classes.
        if arr.shape[0] < arr.shape[1] and 6 <= arr.shape[0] <= 256:
            arr = arr.T
        return arr.astype(np.float32, copy=False)

    def _rows_to_detections(self, rows, meta) -> list[VisionDetection]:
        import numpy as np

        detections: list[VisionDetection] = []
        if rows.size == 0:
            return detections
        for row in rows:
            parsed = self._parse_row(row)
            if not parsed:
                continue
            xyxy, score, class_id = parsed
            if score < self.conf_threshold or class_id < 0 or class_id >= len(self.class_names):
                continue
            bbox = self._map_box_to_original(xyxy, meta)
            detections.append(
                VisionDetection(
                    label=self.class_names[class_id],
                    confidence=float(score),
                    bbox=bbox,
                    source="onnx-yolo",
                    meta={"class_id": int(class_id)},
                )
            )
        return detections

    def _parse_row(self, row):
        import numpy as np

        if row.shape[0] == 6:
            x1, y1, x2, y2, score, class_id = row.tolist()
            return (x1, y1, x2, y2), float(score), int(round(class_id))
        available_scores = row.shape[0] - 4
        if available_scores <= 0:
            return None
        box = row[:4]
        class_count = min(len(self.class_names), available_scores)
        class_scores = row[4 : 4 + class_count]
        objectness = 1.0
        if row.shape[0] >= 5 + class_count:
            maybe_objectness = float(row[4])
            if 0.0 <= maybe_objectness <= 1.0:
                objectness = maybe_objectness
                class_count = min(len(self.class_names), row.shape[0] - 5)
                if class_count <= 0:
                    return None
                class_scores = row[5 : 5 + class_count]
        class_id = int(np.argmax(class_scores))
        score = float(class_scores[class_id]) * float(objectness)
        cx, cy, width, height = [float(v) for v in box]
        xyxy = (cx - width / 2.0, cy - height / 2.0, cx + width / 2.0, cy + height / 2.0)
        return xyxy, score, class_id

    def _map_box_to_original(self, xyxy, meta) -> tuple[float, float, float, float]:
        x1, y1, x2, y2 = [float(v) for v in xyxy]
        if max(abs(x1), abs(y1), abs(x2), abs(y2)) <= 1.5:
            return clamp_bbox((x1, y1, x2, y2))
        scale = max(0.000001, float(meta["scale"]))
        pad_x = float(meta["pad_x"])
        pad_y = float(meta["pad_y"])
        orig_w = float(meta["orig_w"])
        orig_h = float(meta["orig_h"])
        x1 = (x1 - pad_x) / scale / orig_w
        x2 = (x2 - pad_x) / scale / orig_w
        y1 = (y1 - pad_y) / scale / orig_h
        y2 = (y2 - pad_y) / scale / orig_h
        return clamp_bbox((x1, y1, x2, y2))

    def _nms(self, detections: list[VisionDetection]) -> list[VisionDetection]:
        kept: list[VisionDetection] = []
        for detection in sorted(detections, key=lambda item: item.confidence, reverse=True):
            if any(detection.label == other.label and _iou(detection.bbox, other.bbox) >= self.iou_threshold for other in kept):
                continue
            kept.append(detection)
        return kept


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = clamp_bbox(a)
    bx1, by1, bx2, by2 = clamp_bbox(b)
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0.0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    return inter / max(0.000001, area_a + area_b - inter)
