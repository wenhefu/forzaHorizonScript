"""Runtime settings captured from the GUI at start time."""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RuntimeSettings:
    """Immutable per-run options.

    The GUI owns text boxes and checkboxes. Runners should receive a snapshot so
    hidden/debug controls cannot keep mutating a live run accidentally.
    """

    mode_id: str
    startup_delay: float
    drive_seconds: float
    total_minutes: float
    keep_active: bool
    auto_focus: bool
    no_activate: bool
    require_foreground: bool
    resume_after_focus: bool
    source: str = "button"

    @property
    def total_seconds(self) -> Optional[float]:
        if self.total_minutes <= 0:
            return None
        return self.total_minutes * 60

    @property
    def resume_button(self) -> Optional[str]:
        return "a" if self.resume_after_focus else None
