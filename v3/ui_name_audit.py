from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from v3.ui_names import fallback_ui_name, resolve_ui_name


DEFAULT_RAW_ROOT = Path("datasets/forza_ui/raw")
DEFAULT_OUTPUT = Path("reports/ui_name_audit_latest.json")


def audit_raw_samples(
    raw_root: str | Path = DEFAULT_RAW_ROOT,
    *,
    output: str | Path = DEFAULT_OUTPUT,
    limit: int = 0,
) -> dict:
    raw_root = Path(raw_root)
    rows = []
    label_counts: Counter[str] = Counter()
    resolved_counts: Counter[str] = Counter()
    unresolved_counts: Counter[str] = Counter()
    fallback_counts: Counter[str] = Counter()
    sample_dirs = sorted(path for path in raw_root.iterdir() if (path / "metadata.json").exists())
    if limit:
        sample_dirs = sample_dirs[:limit]

    for sample_dir in sample_dirs:
        try:
            metadata = json.loads((sample_dir / "metadata.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        ocr_items = metadata.get("ocr_raw") or []
        for candidate in metadata.get("candidates") or metadata.get("detections") or []:
            label = str(candidate.get("label", "") or "")
            bbox = candidate.get("bbox") or []
            if not label or len(bbox) != 4:
                continue
            source = str(candidate.get("source", "") or "")
            selected_item = str((metadata.get("understanding") or {}).get("selected_item", "") or "")
            text = _text_inside_bbox(ocr_items, bbox)
            name_text = text
            if source == "rule-fallback":
                name_text = selected_item
            official = resolve_ui_name(label, name_text)
            fallback = fallback_ui_name(name_text, allow_short=(label == "modal_button_focus"))
            label_counts[label] += 1
            if official:
                resolved_counts[(label, official)] += 1
            elif fallback:
                fallback_counts[(label, fallback)] += 1
            else:
                unresolved_counts[label] += 1
            rows.append(
                {
                    "sample_id": metadata.get("sample_id", sample_dir.name),
                    "label": label,
                    "screen": (metadata.get("understanding") or {}).get("screen", ""),
                    "selected_item": selected_item,
                    "source": source,
                    "raw_text": text,
                    "name_text": name_text,
                    "official_name": official,
                    "fallback_name": fallback if not official else "",
                    "bbox": bbox,
                }
            )

    summary = {
        "raw_root": str(raw_root),
        "samples": len(sample_dirs),
        "candidate_rows": len(rows),
        "labels": dict(sorted(label_counts.items())),
        "official_names": _counter_to_nested(resolved_counts),
        "fallback_names": _counter_to_nested(fallback_counts, limit_per_label=20),
        "unresolved": dict(sorted(unresolved_counts.items())),
        "examples": _examples(rows),
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path = output.with_suffix(".md")
    md_path.write_text(_summary_markdown(summary), encoding="utf-8")
    return summary


def _text_inside_bbox(ocr_items: list[dict], bbox: list[float]) -> str:
    x1, y1, x2, y2 = [float(value) for value in bbox]
    matches = []
    for item in ocr_items:
        ncx = float(item.get("ncx", 0.0) or 0.0)
        ncy = float(item.get("ncy", 0.0) or 0.0)
        if x1 <= ncx <= x2 and y1 <= ncy <= y2:
            matches.append(item)
    matches.sort(key=lambda item: (float(item.get("ncy", 0.0) or 0.0), float(item.get("ncx", 0.0) or 0.0)))
    return " | ".join(str(item.get("text", "") or "").strip() for item in matches if str(item.get("text", "") or "").strip())


def _counter_to_nested(counter: Counter, *, limit_per_label: int = 0) -> dict:
    grouped: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for (label, name), count in counter.items():
        grouped[str(label)].append((str(name), int(count)))
    result = {}
    for label, values in sorted(grouped.items()):
        ordered = sorted(values, key=lambda item: (-item[1], item[0]))
        if limit_per_label:
            ordered = ordered[:limit_per_label]
        result[label] = {name: count for name, count in ordered}
    return result


def _examples(rows: list[dict]) -> dict:
    examples = {"official": [], "fallback": [], "blank": []}
    seen = set()
    for row in rows:
        key = (row["label"], row["official_name"], row["fallback_name"], row["raw_text"][:120])
        if key in seen:
            continue
        seen.add(key)
        if row["official_name"] and len(examples["official"]) < 20:
            examples["official"].append(row)
        elif row["fallback_name"] and len(examples["fallback"]) < 30:
            examples["fallback"].append(row)
        elif not row["raw_text"] and len(examples["blank"]) < 20:
            examples["blank"].append(row)
    return examples


def _summary_markdown(summary: dict) -> str:
    lines = [
        "# UI Name Audit",
        "",
        f"- raw_root: `{summary['raw_root']}`",
        f"- samples: `{summary['samples']}`",
        f"- candidate_rows: `{summary['candidate_rows']}`",
        "",
        "## Labels",
        "",
    ]
    for label, count in summary["labels"].items():
        lines.append(f"- `{label}`: {count}")
    lines.extend(["", "## Official Names", ""])
    for label, names in summary["official_names"].items():
        joined = ", ".join(f"{name}={count}" for name, count in names.items())
        lines.append(f"- `{label}`: {joined}")
    lines.extend(["", "## Fallback Names To Review", ""])
    for label, names in summary["fallback_names"].items():
        joined = ", ".join(f"{name}={count}" for name, count in names.items())
        lines.append(f"- `{label}`: {joined}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit raw OCR candidate text against canonical UI names.")
    parser.add_argument("--raw-root", default=str(DEFAULT_RAW_ROOT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)
    summary = audit_raw_samples(args.raw_root, output=args.output, limit=args.limit)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
