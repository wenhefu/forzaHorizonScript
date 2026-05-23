"""Command-line farm runner (no GUI). Run: python farm.py   (stop: Ctrl+C)"""
import time

import config
from runner import Runner
from sequences import farm_sequence


def main():
    runner = Runner(on_log=print)
    total = None if not config.TOTAL_MINUTES else config.TOTAL_MINUTES * 60
    runner.start(farm_sequence(), startup_delay=config.STARTUP_DELAY, total_seconds=total)
    try:
        while runner.is_running():
            time.sleep(0.2)
    except KeyboardInterrupt:
        runner.stop()
        while runner.is_running():
            time.sleep(0.1)


if __name__ == "__main__":
    main()
