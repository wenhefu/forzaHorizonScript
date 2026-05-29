from __future__ import annotations

import argparse
import json
from pathlib import Path

from ocr_engine import OcrItem
from v2.semantic import ForzaSemanticAnalyzer
from v3.candidates import detect_focus_candidates
from v3.frame_utils import load_frame_from_image
from v3.sample_collector import understanding_to_dict


def _ocr_items_from_metadata(metadata: dict) -> list[OcrItem]:
    items: list[OcrItem] = []
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


def relabel_raw_samples(raw_root: str | Path = "datasets/forza_ui/raw") -> dict:
    raw_root = Path(raw_root)
    analyzer = ForzaSemanticAnalyzer()
    updated = 0
    skipped = 0
    screen_counts: dict[str, int] = {}
    class_counts: dict[str, int] = {}

    for metadata_path in sorted(raw_root.glob("*/metadata.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        image_path = metadata_path.parent / metadata.get("image", "image.png")
        if not image_path.exists():
            skipped += 1
            continue
        frame = load_frame_from_image(image_path)
        items = _ocr_items_from_metadata(metadata)
        understanding = analyzer.analyze(frame, items)
        candidates = detect_focus_candidates(frame, understanding)
        metadata["understanding"] = understanding_to_dict(understanding)
        metadata["candidates"] = [candidate.to_dict() for candidate in candidates]
        metadata["relabel"] = {
            "tool": "v3.relabel_raw_samples",
            "uses_existing_ocr_raw": True,
        }
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        updated += 1
        screen_counts[understanding.screen] = screen_counts.get(understanding.screen, 0) + 1
        for candidate in candidates:
            class_counts[candidate.label] = class_counts.get(candidate.label, 0) + 1

    return {
        "raw_root": str(raw_root),
        "updated": updated,
        "skipped": skipped,
        "screen_counts": dict(sorted(screen_counts.items())),
        "class_counts": dict(sorted(class_counts.items())),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh V3 raw sample understanding/candidates with current rules.")
    parser.add_argument("--raw-root", default="datasets/forza_ui/raw")
    args = parser.parse_args(argv)
    print(json.dumps(relabel_raw_samples(args.raw_root), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
