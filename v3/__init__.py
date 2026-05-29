"""Experimental V3 hybrid vision recognizer.

V3 is intentionally isolated from the stable V1 automation runner.  It captures
screens, builds training samples, runs optional ONNX detection, and fuses model
signals with the existing V2 semantic analyzer.  It never sends controller
input.
"""

__all__ = [
    "types",
    "frame_utils",
    "candidates",
    "sample_collector",
    "dataset",
    "yolo_detector",
    "hybrid",
]
