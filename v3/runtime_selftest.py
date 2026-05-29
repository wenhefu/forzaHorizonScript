from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from v3.yolo_detector import YoloOnnxDetector, resolve_asset_path


def run_self_test(model_path: str = "v3/models/forza_ui_yolo.onnx") -> dict:
    resolved = resolve_asset_path(model_path)
    detector = YoloOnnxDetector(model_path=model_path)
    return {
        "ok": bool(detector.available()),
        "requested_model": model_path,
        "resolved_model": str(resolved),
        "resolved_exists": resolved.exists(),
        "stats": detector.stats.__dict__,
        "cwd": str(Path.cwd()),
        "executable": sys.executable,
        "bundle_root": str(getattr(sys, "_MEIPASS", "")),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Forza6HelperVision runtime self-test")
    parser.add_argument("--model", default="v3/models/forza_ui_yolo.onnx")
    parser.add_argument("--output", default="reports/vision_runtime_selftest_latest.json")
    args = parser.parse_args(argv)

    result = run_self_test(args.model)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
