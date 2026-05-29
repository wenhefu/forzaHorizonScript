from __future__ import annotations

"""Human-in-the-loop capture-on-change sampler.

The user navigates the game with a real controller (or any input). This tool
sends NO input at all -- it only screenshots the Forza window, and saves a raw
training sample (image + OCR + V2/V3 understanding + candidate boxes) whenever
the screen visibly changes. A cheap downscaled-grayscale diff gates the
expensive OCR/analysis so the game does not stutter, a minimum save interval
keeps looping animations from flooding near-duplicate frames, and a semantic
de-dupe avoids re-saving the same page+focus while only a 3D car rotates behind
a static menu.

Understanding uses the V3 HybridVisionRecognizer (same as the other samplers),
so labels match the rest of the pipeline -- including race_pause_menu, which
the V2 analyzer alone cannot detect. If the ONNX detector cannot be loaded it
falls back to the V2 analyzer.

It is a V3-only data tool. It does not inject, hook, fake focus, send input, or
modify game files.

Stop it by creating the stop-flag file (default: reports/coop_capture_stop.flag)
or just let it reach --max-seconds.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import focus
from v3.hybrid import HybridVisionRecognizer
from v3.sample_collector import SampleCollector
from v3.yolo_detector import YoloOnnxDetector
from window_capture import capture_client, capture_client_printwindow


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _small_signature(frame):
    """Downscaled grayscale fingerprint for cheap change detection."""
    import numpy as np

    arr = np.frombuffer(frame.bgra, dtype=np.uint8).reshape((frame.height, frame.width, 4))
    gray = arr[:, :, :3].mean(axis=2)
    ys = max(1, frame.height // 36)
    xs = max(1, frame.width // 64)
    return gray[::ys, ::xs].astype("float32")


def _grab(title: str):
    hwnd = focus.find_window(title)
    if not hwnd:
        return None, None, None
    try:
        frame = capture_client_printwindow(hwnd)
        method = "PrintWindow"
    except Exception:
        frame = capture_client(hwnd)
        method = "BitBlt"
    window_title = focus.window_title(hwnd) or title
    return frame, window_title, method


def run(
    title: str = "Forza",
    raw_root: str = "datasets/forza_ui/raw",
    report_dir: str = "reports",
    max_seconds: float = 1200.0,
    poll: float = 0.5,
    diff_threshold: float = 6.0,
    min_interval: float = 1.0,
    resave_cooldown: float = 4.0,
    settle: float = 0.35,
    min_conf: float = 0.42,
    stop_flag: str = "reports/coop_capture_stop.flag",
) -> int:
    import numpy as np

    collector = SampleCollector(raw_root=raw_root, min_confidence=min_conf)
    # Prefer the V3 hybrid recognizer so labels match the rest of the pipeline
    # (e.g. race_pause_menu). Fall back to the V2 analyzer if ONNX won't load.
    try:
        recognizer = HybridVisionRecognizer(
            detector=YoloOnnxDetector(), ocr_reader=collector.ocr, analyzer=collector.analyzer
        )
    except Exception as exc:
        recognizer = None
        print(f"hybrid recognizer unavailable, falling back to V2 analyzer: {exc}", flush=True)

    report_path = Path(report_dir)
    report_path.mkdir(parents=True, exist_ok=True)
    status_path = report_path / "coop_capture_status.json"
    log_path = report_path / "coop_capture_latest.json"
    stop_path = Path(stop_flag)
    try:
        stop_path.unlink()
    except FileNotFoundError:
        pass

    prev = None
    saved = 0
    seen = 0
    skipped_same = 0
    last_save_t = 0.0
    last_key = None
    entries: list[dict] = []
    start = time.monotonic()

    def write_status(stopped: bool = False, last_screen: str = "") -> None:
        status_path.write_text(
            json.dumps(
                {
                    "running": not stopped,
                    "recognizer": "v3-hybrid" if recognizer is not None else "v2",
                    "saved": saved,
                    "seen": seen,
                    "skipped_same_state": skipped_same,
                    "last_screen": last_screen,
                    "elapsed": round(time.monotonic() - start, 1),
                    "updated_at": _now_iso(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    label = "v3-hybrid" if recognizer is not None else "v2"
    print(f"coop capture started title={title!r} recognizer={label} max={max_seconds}s stop_flag={stop_path}", flush=True)
    write_status()
    last_screen = ""
    while True:
        if stop_path.exists():
            print("stop flag detected", flush=True)
            break
        if (time.monotonic() - start) > max_seconds:
            print("max-seconds reached", flush=True)
            break
        frame, wtitle, method = _grab(title)
        if frame is None:
            time.sleep(poll)
            continue
        seen += 1
        try:
            sig = _small_signature(frame)
        except Exception:
            time.sleep(poll)
            continue
        changed = (
            prev is None
            or sig.shape != prev.shape
            or float(np.abs(sig - prev).mean()) > diff_threshold
        )
        now = time.monotonic()
        if changed and (now - last_save_t) >= min_interval:
            # Let the transition settle, then re-grab so we save the final page.
            time.sleep(settle)
            f2, t2, m2 = _grab(title)
            if f2 is not None:
                frame, wtitle, method = f2, t2, m2
                try:
                    sig = _small_signature(frame)
                except Exception:
                    pass
            try:
                if recognizer is not None:
                    items = collector.ocr.read_frame(frame, min_confidence=min_conf)
                    und = recognizer.analyze_frame(
                        frame, ocr_items=items, run_full_ocr=False, run_region_ocr=True, min_confidence=min_conf
                    )
                    cand = getattr(und, "detections", None) or []
                else:
                    items, und, cand = collector.analyze_frame(frame)
                screen = getattr(und, "screen", "unknown") or "unknown"
                selected = getattr(und, "selected_item", "") or ""
                key = (screen, selected)
                if key == last_key and (now - last_save_t) < resave_cooldown:
                    # Same page + same focused item saved very recently (e.g. a
                    # 3D car rotating behind a static menu) -> skip the dupe.
                    skipped_same += 1
                    prev = sig
                else:
                    sample_dir = collector.save_sample(
                        frame,
                        wtitle,
                        items,
                        und,
                        candidates=cand,
                        capture_method=f"coop:{method}",
                        label_hint="coop_walk",
                    )
                    saved += 1
                    last_save_t = now
                    last_key = key
                    last_screen = screen
                    prev = sig
                    entry = {
                        "ts": _now_iso(),
                        "screen": screen,
                        "selected_item": selected,
                        "active_tab": getattr(und, "active_tab", ""),
                        "sample_dir": str(sample_dir),
                    }
                    entries.append(entry)
                    log_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
                    write_status(last_screen=screen)
                    print(f"saved#{saved:<3} screen={screen:<22} sel={selected!r:<24} -> {sample_dir.name}", flush=True)
            except Exception as exc:  # keep running; one bad frame should not stop a co-op session
                print(f"analyze/save error: {exc}", flush=True)
                prev = sig
        else:
            if prev is None:
                prev = sig
        time.sleep(poll)

    write_status(stopped=True, last_screen=last_screen)
    counts: dict[str, int] = {}
    for e in entries:
        counts[e["screen"]] = counts.get(e["screen"], 0) + 1
    print(f"DONE saved={saved} seen={seen} skipped_same={skipped_same} elapsed={round(time.monotonic()-start,1)}s", flush=True)
    print("by_screen=" + json.dumps(counts, ensure_ascii=False), flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Human-in-the-loop capture-on-change Forza sampler (no input sent).")
    parser.add_argument("--title", default="Forza")
    parser.add_argument("--raw-root", default="datasets/forza_ui/raw")
    parser.add_argument("--report-dir", default="reports")
    parser.add_argument("--max-seconds", type=float, default=1200.0)
    parser.add_argument("--poll", type=float, default=0.5)
    parser.add_argument("--diff", dest="diff_threshold", type=float, default=6.0, help="Mean grayscale diff to count as a screen change.")
    parser.add_argument("--min-interval", type=float, default=1.0, help="Minimum seconds between saved samples.")
    parser.add_argument("--resave-cooldown", type=float, default=4.0, help="Do not re-save the same (screen, focused-item) within this many seconds.")
    parser.add_argument("--settle", type=float, default=0.35)
    parser.add_argument("--min-conf", type=float, default=0.42)
    parser.add_argument("--stop-flag", default="reports/coop_capture_stop.flag")
    args = parser.parse_args(argv)
    return run(
        title=args.title,
        raw_root=args.raw_root,
        report_dir=args.report_dir,
        max_seconds=args.max_seconds,
        poll=args.poll,
        diff_threshold=args.diff_threshold,
        min_interval=args.min_interval,
        resave_cooldown=args.resave_cooldown,
        settle=args.settle,
        min_conf=args.min_conf,
        stop_flag=args.stop_flag,
    )


if __name__ == "__main__":
    raise SystemExit(main())
