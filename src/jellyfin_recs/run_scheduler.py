"""
Simple built-in scheduler for periodic recommendation refreshes.

Runs a refresh immediately, then every REFRESH_INTERVAL_HOURS. Keep it running
as a background service (systemd, docker, tmux, etc.).

    python3 run_scheduler.py

If you'd rather use your OS scheduler instead of leaving this running, skip it
and add a cron entry that calls pipeline.py — example in the README.
"""

import time
import sys

from . import pipeline
from . import settings


def main():
    print(f"Scheduler started. Refreshing now, then every "
          f"{settings.get('refresh_interval_hours')}h.")
    while True:
        started = time.time()
        try:
            pipeline.run_refresh(verbose=True)
        except Exception as e:
            print(f"Refresh failed: {e}", file=sys.stderr)
        # Re-read each loop so a Settings-page change applies without a restart.
        interval = settings.get("refresh_interval_hours") * 3600
        elapsed = time.time() - started
        sleep_for = max(60, interval - elapsed)
        nxt = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() + sleep_for))
        print(f"Next refresh at ~{nxt}. Sleeping ...")
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()
