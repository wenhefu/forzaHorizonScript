from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ocr_engine import OcrReader
from ocr_engine import OcrItem
from v2.semantic import ForzaSemanticAnalyzer
from v3.frame_utils import load_frame_from_image, resize_frame
from v3.hybrid import HybridVisionRecognizer
from v3.yolo_detector import YoloOnnxDetector


CAPTURES = Path(r"C:/Users/fu/Videos/Captures")


def item(text, x=0.5, y=0.5, confidence=0.90):
    width = 0.05
    height = 0.02
    return SimpleNamespace(
        text=text,
        confidence=confidence,
        nx1=max(0.0, x - width),
        ny1=max(0.0, y - height),
        nx2=min(1.0, x + width),
        ny2=min(1.0, y + height),
        ncx=x,
        ncy=y,
    )


def vehicle_items():
    return [
        item("剧情", 0.30, 0.22),
        item("车辆", 0.38, 0.22),
        item("我的地平线", 0.47, 0.22),
        item("在线", 0.55, 0.22),
        item("创意中心", 0.62, 0.22),
        item("商店", 0.69, 0.22),
        item("购买新车与二手车", 0.20, 0.58),
        item("更换车辆", 0.42, 0.40),
        item("车辆熟练度", 0.40, 0.62),
        item("秘藏座驾", 0.62, 0.55),
        item("车房宝物", 0.62, 0.62),
        item("礼物掉落箱", 0.62, 0.69),
        item("汽车喇叭", 0.62, 0.76),
        item("调校车辆", 0.78, 0.58),
    ]


@dataclass
class Fixture:
    path: Path
    expected: str


def local_fixtures(limit: int = 0) -> list[Fixture]:
    first = next(CAPTURES.glob("*5_46_45.png"), CAPTURES / "missing-5_46_45.png")
    rows = [
        Fixture(first, "购买新车与二手车"),
        Fixture(CAPTURES / "Forza Horizon 6 2026_5_28 5_46_47.png", "更换车辆"),
        Fixture(CAPTURES / "Forza Horizon 6 2026_5_28 5_46_49.png", "车辆熟练度"),
        Fixture(CAPTURES / "Forza Horizon 6 2026_5_28 5_46_50.png", "秘藏座驾"),
        Fixture(CAPTURES / "Forza Horizon 6 2026_5_28 5_46_52.png", "车房宝物"),
        Fixture(CAPTURES / "Forza Horizon 6 2026_5_28 5_46_53.png", "礼物掉落箱"),
        Fixture(CAPTURES / "Forza Horizon 6 2026_5_28 5_46_55.png", "汽车喇叭"),
        Fixture(CAPTURES / "Forza Horizon 6 2026_5_28 5_46_56.png", "调校车辆"),
    ]
    rows = [row for row in rows if row.path.exists()]
    if limit:
        rows = rows[:limit]
    return rows


def mean_ms(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def ocr_items_from_metadata(metadata: dict) -> list[OcrItem]:
    items = []
    for row in metadata.get("ocr_raw", []) or []:
        items.append(
            OcrItem(
                text=str(row.get("text", "") or ""),
                confidence=float(row.get("confidence", 0.0) or 0.0),
                box=row.get("box", []),
                x1=float(row.get("x1", 0.0) or 0.0),
                y1=float(row.get("y1", 0.0) or 0.0),
                x2=float(row.get("x2", 0.0) or 0.0),
                y2=float(row.get("y2", 0.0) or 0.0),
                nx1=float(row.get("nx1", 0.0) or 0.0),
                ny1=float(row.get("ny1", 0.0) or 0.0),
                nx2=float(row.get("nx2", 0.0) or 0.0),
                ny2=float(row.get("ny2", 0.0) or 0.0),
                ncx=float(row.get("ncx", 0.0) or 0.0),
                ncy=float(row.get("ncy", 0.0) or 0.0),
            )
        )
    return items


def raw_sample_fixtures(raw_root: str | Path, limit: int = 0) -> list[tuple[Path, dict, set[str]]]:
    rows = []
    for metadata_path in sorted(Path(raw_root).glob("*/metadata.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        image_path = metadata_path.parent / metadata.get("image", "image.png")
        if not image_path.exists():
            continue
        labels = {
            str(candidate.get("label", ""))
            for candidate in metadata.get("candidates", []) or []
            if str(candidate.get("label", ""))
        }
        if not labels:
            continue
        rows.append((image_path, metadata, labels))
    if limit:
        rows = rows[:limit]
    return rows


def run_benchmark(
    scales: list[float],
    model_path: str,
    max_images: int = 0,
    with_ocr: bool = False,
    ocr_max: int = 2,
    raw_root: str | Path = "",
    raw_max: int = 0,
) -> dict:
    fixtures = local_fixtures(limit=max_images)
    analyzer = ForzaSemanticAnalyzer()
    detector = YoloOnnxDetector(model_path=model_path)
    ocr = OcrReader()
    hybrid = HybridVisionRecognizer(detector=detector, ocr_reader=ocr, analyzer=analyzer)
    rows = []
    semantic_ms = []
    yolo_ms = []
    hybrid_ms = []
    ocr_ms = []
    semantic_correct = 0
    hybrid_correct = 0
    total = 0
    raw_rows = []
    raw_total = 0
    raw_model_hit = 0
    raw_hybrid_hit = 0
    raw_model_ms = []
    raw_hybrid_ms = []
    raw_per_label = defaultdict(lambda: {"cases": 0, "model_hits": 0, "hybrid_hits": 0})

    for fixture_index, fixture in enumerate(fixtures):
        original = load_frame_from_image(fixture.path)
        for scale in scales:
            frame = resize_frame(original, scale=scale) if scale != 1.0 else original
            ocr_items = vehicle_items()
            started = time.perf_counter()
            v2 = analyzer.analyze(frame, ocr_items)
            semantic_elapsed = (time.perf_counter() - started) * 1000.0

            started = time.perf_counter()
            model_detections = detector.predict(frame)
            yolo_elapsed = (time.perf_counter() - started) * 1000.0

            started = time.perf_counter()
            v3 = hybrid.analyze_frame(frame, ocr_items=ocr_items, run_full_ocr=False, run_region_ocr=False)
            hybrid_elapsed = (time.perf_counter() - started) * 1000.0

            v2_ok = v2.selected_item == fixture.expected
            v3_ok = v3.selected_item == fixture.expected
            semantic_correct += int(v2_ok)
            hybrid_correct += int(v3_ok)
            total += 1
            semantic_ms.append(semantic_elapsed)
            yolo_ms.append(yolo_elapsed)
            hybrid_ms.append(hybrid_elapsed)
            row = {
                "image": str(fixture.path),
                "scale": scale,
                "expected": fixture.expected,
                "v2_selected": v2.selected_item,
                "v3_selected": v3.selected_item,
                "v2_ok": v2_ok,
                "v3_ok": v3_ok,
                "semantic_ms": semantic_elapsed,
                "yolo_ms": yolo_elapsed,
                "hybrid_ms": hybrid_elapsed,
                "model_detections": len(model_detections),
            }
            if with_ocr and fixture_index < ocr_max and scale == 1.0:
                started = time.perf_counter()
                real_items = ocr.read_frame(frame, min_confidence=0.42)
                real_v2 = analyzer.analyze(frame, real_items)
                ocr_elapsed = (time.perf_counter() - started) * 1000.0
                ocr_ms.append(ocr_elapsed)
                row["full_ocr_v2_ms"] = ocr_elapsed
                row["full_ocr_items"] = len(real_items)
                row["full_ocr_screen"] = real_v2.screen
                row["full_ocr_selected"] = real_v2.selected_item
            rows.append(row)

    if raw_root:
        for image_path, metadata, expected_labels in raw_sample_fixtures(raw_root, raw_max):
            original = load_frame_from_image(image_path)
            ocr_items = ocr_items_from_metadata(metadata)
            for scale in scales:
                frame = resize_frame(original, scale=scale) if scale != 1.0 else original
                started = time.perf_counter()
                detections = detector.predict(frame)
                model_elapsed = (time.perf_counter() - started) * 1000.0
                started = time.perf_counter()
                hybrid_result = hybrid.analyze_frame(frame, ocr_items=ocr_items, run_full_ocr=False, run_region_ocr=False)
                hybrid_elapsed = (time.perf_counter() - started) * 1000.0
                model_labels = {detection.label for detection in detections}
                hybrid_labels = {detection.label for detection in hybrid_result.detections}
                model_ok = bool(model_labels & expected_labels)
                hybrid_ok = bool(hybrid_labels & expected_labels)
                for label in expected_labels:
                    raw_per_label[label]["cases"] += 1
                    raw_per_label[label]["model_hits"] += int(label in model_labels)
                    raw_per_label[label]["hybrid_hits"] += int(label in hybrid_labels)
                raw_total += 1
                raw_model_hit += int(model_ok)
                raw_hybrid_hit += int(hybrid_ok)
                raw_model_ms.append(model_elapsed)
                raw_hybrid_ms.append(hybrid_elapsed)
                raw_rows.append(
                    {
                        "image": str(image_path),
                        "scale": scale,
                        "expected_labels": sorted(expected_labels),
                        "model_labels": sorted(model_labels),
                        "hybrid_labels": sorted(hybrid_labels),
                        "model_ok": model_ok,
                        "hybrid_ok": hybrid_ok,
                        "model_ms": model_elapsed,
                        "hybrid_ms": hybrid_elapsed,
                        "screen": metadata.get("understanding", {}).get("screen", ""),
                    }
                )

    raw_per_label_recall = {}
    for label, stats in sorted(raw_per_label.items()):
        cases = int(stats["cases"])
        raw_per_label_recall[label] = {
            "cases": cases,
            "model_recall": (stats["model_hits"] / cases) if cases else 0.0,
            "hybrid_recall": (stats["hybrid_hits"] / cases) if cases else 0.0,
        }

    summary = {
        "fixtures": len(fixtures),
        "cases": total,
        "scales": scales,
        "detector": {
            "model_path": detector.stats.model_path,
            "loaded": detector.stats.loaded,
            "provider": detector.stats.provider,
            "error": detector.stats.error,
        },
        "semantic_rule_mean_ms": mean_ms(semantic_ms),
        "yolo_onnx_mean_ms": mean_ms(yolo_ms),
        "hybrid_mean_ms": mean_ms(hybrid_ms),
        "full_ocr_v2_mean_ms": mean_ms(ocr_ms),
        "semantic_focus_accuracy": semantic_correct / total if total else 0.0,
        "hybrid_focus_accuracy": hybrid_correct / total if total else 0.0,
        "raw_label_cases": raw_total,
        "raw_model_label_recall": raw_model_hit / raw_total if raw_total else 0.0,
        "raw_hybrid_label_recall": raw_hybrid_hit / raw_total if raw_total else 0.0,
        "raw_model_mean_ms": mean_ms(raw_model_ms),
        "raw_hybrid_mean_ms": mean_ms(raw_hybrid_ms),
        "raw_per_label_recall": raw_per_label_recall,
        "notes": [
            "Focus accuracy uses local screenshots plus scaled variants with synthetic OCR boxes from the V2 tests.",
            "Raw label recall uses saved V3 sample metadata as the expected label set across the same scales.",
            "full_ocr_v2_mean_ms is measured on a small subset because RapidOCR is much slower than detector/rule passes.",
            "If the loaded model is bootstrap_empty.onnx, YOLO timing proves the ONNX path only; it is not a trained detector.",
        ],
    }
    return {"summary": summary, "rows": rows, "raw_rows": raw_rows}


def write_report(result: dict, output_dir: str | Path = "reports") -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    json_path = output_dir / f"vision_benchmark_{stamp}.json"
    md_path = output_dir / f"vision_benchmark_{stamp}.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = result["summary"]
    lines = [
        "# Vision Benchmark",
        "",
        f"- cases: {summary['cases']}",
        f"- detector loaded: {summary['detector']['loaded']}",
        f"- detector model: `{summary['detector']['model_path']}`",
        f"- provider: `{summary['detector']['provider']}`",
        f"- V2 semantic/rule mean: {summary['semantic_rule_mean_ms']:.2f} ms",
        f"- YOLO ONNX mean: {summary['yolo_onnx_mean_ms']:.2f} ms",
        f"- Hybrid mean: {summary['hybrid_mean_ms']:.2f} ms",
        f"- Full OCR+V2 mean subset: {summary['full_ocr_v2_mean_ms']:.2f} ms",
        f"- V2 focus accuracy: {summary['semantic_focus_accuracy']:.3f}",
        f"- Hybrid focus accuracy: {summary['hybrid_focus_accuracy']:.3f}",
        f"- Raw V3 label cases: {summary['raw_label_cases']}",
        f"- Raw YOLO label recall: {summary['raw_model_label_recall']:.3f}",
        f"- Raw Hybrid label recall: {summary['raw_hybrid_label_recall']:.3f}",
        f"- Raw YOLO mean: {summary['raw_model_mean_ms']:.2f} ms",
        f"- Raw Hybrid mean: {summary['raw_hybrid_mean_ms']:.2f} ms",
        "",
    ]
    if summary.get("raw_per_label_recall"):
        lines.append("## Raw Per-Label Recall")
        lines.append("")
        for label, stats in summary["raw_per_label_recall"].items():
            lines.append(
                f"- {label}: cases={stats['cases']} "
                f"YOLO={stats['model_recall']:.3f} Hybrid={stats['hybrid_recall']:.3f}"
            )
        lines.append("")
    lines.append("## Notes")
    for note in summary["notes"]:
        lines.append(f"- {note}")
    lines.append("")
    lines.append(f"Raw JSON: `{json_path}`")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark V2 OCR/rules, YOLO ONNX, and V3 hybrid recognition.")
    parser.add_argument("--model", default="v3/models/forza_ui_yolo.onnx")
    parser.add_argument("--scales", default="1.0,0.65")
    parser.add_argument("--max-images", type=int, default=0)
    parser.add_argument("--with-ocr", action="store_true")
    parser.add_argument("--ocr-max", type=int, default=2)
    parser.add_argument("--raw-root", default="")
    parser.add_argument("--raw-max", type=int, default=0)
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args(argv)
    scales = [float(value.strip()) for value in args.scales.split(",") if value.strip()]
    result = run_benchmark(
        scales=scales,
        model_path=args.model,
        max_images=args.max_images,
        with_ocr=args.with_ocr,
        ocr_max=args.ocr_max,
        raw_root=args.raw_root,
        raw_max=args.raw_max,
    )
    report = write_report(result, args.output_dir)
    print(report)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
