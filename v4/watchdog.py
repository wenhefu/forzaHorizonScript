from __future__ import annotations

from dataclasses import dataclass
import time


@dataclass
class WatchdogState:
    token: str = ""
    phase: str = ""
    changed_at: float = 0.0
    recovery_count: int = 0


class ProgressWatchdog:
    """Tracks semantic progress and detects route stalls."""

    def __init__(self, timeout_seconds: float = 120.0, max_recoveries: int = 3):
        self.timeout_seconds = float(timeout_seconds)
        self.max_recoveries = int(max_recoveries)
        self.state = WatchdogState(changed_at=time.monotonic())

    def observe(self, phase: str, token: str) -> bool:
        now = time.monotonic()
        changed = phase != self.state.phase or token != self.state.token
        if changed:
            self.state.phase = phase
            self.state.token = token
            self.state.changed_at = now
            self.state.recovery_count = 0
        return changed

    def elapsed_without_progress(self) -> float:
        return max(0.0, time.monotonic() - self.state.changed_at)

    def stalled(self) -> bool:
        return self.elapsed_without_progress() >= self.timeout_seconds

    def can_recover(self) -> bool:
        return self.state.recovery_count < self.max_recoveries

    def note_recovery(self) -> int:
        self.state.recovery_count += 1
        self.state.changed_at = time.monotonic()
        return self.state.recovery_count

    def reset(self, phase: str = "", token: str = "") -> None:
        self.state = WatchdogState(phase=phase, token=token, changed_at=time.monotonic())

