from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import time

from gamepad import Gamepad


def _write_status(path: Path, payload: dict) -> None:
    payload = dict(payload)
    payload["updated_at"] = datetime.now(timezone.utc).astimezone().isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_new_commands(queue_path: Path, offset: int) -> tuple[list[dict], int]:
    if not queue_path.exists():
        return [], offset
    with queue_path.open("r", encoding="utf-8") as handle:
        handle.seek(offset)
        lines = handle.readlines()
        offset = handle.tell()
    commands: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            commands.append(json.loads(line))
        except json.JSONDecodeError:
            commands.append({"error": "invalid-json", "raw": line})
    return commands, offset


def run_bridge(queue_path: Path, status_path: Path, poll: float) -> int:
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.touch(exist_ok=True)
    pad = Gamepad()
    pad.neutral()
    offset = queue_path.stat().st_size
    count = 0
    _write_status(status_path, {"running": True, "count": count, "last": "started"})
    try:
        while True:
            commands, offset = _read_new_commands(queue_path, offset)
            for command in commands:
                if command.get("error"):
                    _write_status(status_path, {"running": True, "count": count, "last": command})
                    continue
                if command.get("command") == "stop":
                    pad.neutral()
                    _write_status(status_path, {"running": False, "count": count, "last": "stopped"})
                    return 0
                button = str(command.get("button", "")).strip().lower()
                hold = float(command.get("hold", 0.15) or 0.15)
                after = float(command.get("after", 0.20) or 0.20)
                if button:
                    pad.tap(button, hold=hold)
                    time.sleep(after)
                    pad.neutral()
                    count += 1
                    _write_status(status_path, {"running": True, "count": count, "last": command})
            time.sleep(max(0.02, poll))
    finally:
        pad.neutral()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Keep one virtual Xbox gamepad alive and accept JSONL tap commands.")
    parser.add_argument("--queue", default="reports/gamepad_bridge_commands.jsonl")
    parser.add_argument("--status", default="reports/gamepad_bridge_status.json")
    parser.add_argument("--poll", type=float, default=0.05)
    args = parser.parse_args(argv)
    return run_bridge(Path(args.queue), Path(args.status), args.poll)


if __name__ == "__main__":
    raise SystemExit(main())
