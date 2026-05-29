from __future__ import annotations

"""Drive V4 mode-three for N rounds with one shared virtual pad.

Each round = V1 buy/skill phase -> V3-guided EventLab navigation -> vision farm
-> exit_after_farm. Uses a single V4Mode3Runner (one pad, one recognizer) so the
virtual controller is not churned between rounds. Stalls longer than the
watchdog window are stopped automatically per phase.
"""

import logging
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from v4.mode3_runner import V4Mode3Runner

ROUNDS = 2
FARM_SECONDS = 180.0   # 3 minutes of farming per round
WATCHDOG = 180.0       # stall longer than 3 minutes -> stop that phase

runner = V4Mode3Runner(title="Forza", watchdog_seconds=WATCHDOG, on_log=print)
runner._farm_mode = "vision"

summary = []
for rnd in range(1, ROUNDS + 1):
    print(f"################ ROUND {rnd}/{ROUNDS} START (buy + skill points + farm) ################", flush=True)
    ok = runner.run_once(
        startup_delay=0.0,
        farm_seconds=FARM_SECONDS,
        run_buy=True,
        run_farm=True,
        exit_after_farm=True,
        auto_focus=True,
        require_foreground=True,
    )
    reason = runner.report.stopped_reason
    laps = getattr(runner.vision_farm_runner, "laps", "?")
    hud = getattr(runner.vision_farm_runner, "race_hud_seen", "?")
    print(
        f"################ ROUND {rnd}/{ROUNDS} DONE ok={ok} reason={reason} "
        f"farm_laps={laps} race_hud_frames={hud} ################",
        flush=True,
    )
    summary.append({"round": rnd, "ok": ok, "reason": reason, "laps": laps, "race_hud_frames": hud})
    if rnd < ROUNDS:
        time.sleep(3.0)

print("################ ALL ROUNDS SUMMARY:", summary, flush=True)
