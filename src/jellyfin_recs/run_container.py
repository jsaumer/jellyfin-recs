"""
Container entrypoint runner.

Runs BOTH long-running parts of the app in a single container:
  - the Flask dashboard (foreground-ish, in a thread)
  - the periodic refresh scheduler (in a thread)

Using threads (not subprocesses) keeps one PID as the container's main process,
so Docker's health/stop signals behave predictably. If either thread dies, we
log it; the dashboard thread is the one that keeps the container alive.

A one-time history seed runs at startup if seed files are present and seeding
hasn't been done yet (tracked by a marker file in DATA_DIR).
"""

import os
import sys
import threading
import time
import signal

from . import config


_stop = threading.Event()


def _seed_once():
    """Run history seeding a single time (idempotent via a marker file)."""
    marker = os.path.join(config.DATA_DIR, ".seeded")
    if os.path.exists(marker):
        return
    try:
        from . import seed_history
        result = seed_history.seed(verbose=True)
        os.makedirs(config.DATA_DIR, exist_ok=True)
        with open(marker, "w") as f:
            f.write(str(result))
        print(f"[entrypoint] History seed complete: {result}")
    except Exception as e:
        print(f"[entrypoint] History seed skipped/failed: {e}", file=sys.stderr)


def _run_scheduler():
    from . import pipeline
    from . import settings
    print(f"[scheduler] started; interval "
          f"{settings.get('refresh_interval_hours')}h")
    # Small startup delay so the dashboard is up first and we don't hammer
    # Jellyfin/Claude the instant the container starts.
    if _stop.wait(timeout=15):
        return
    while not _stop.is_set():
        started = time.time()
        try:
            pipeline.run_refresh(verbose=False)
            print("[scheduler] refresh complete")
        except Exception as e:
            print(f"[scheduler] refresh failed: {e}", file=sys.stderr)
        # Re-read each loop so a Settings-page change to the interval applies
        # without a redeploy.
        interval = settings.get("refresh_interval_hours") * 3600
        elapsed = time.time() - started
        # Interruptible sleep so SIGTERM stops us promptly.
        if _stop.wait(timeout=max(60, interval - elapsed)):
            break
    print("[scheduler] stopped")


def _run_dashboard():
    # Import here so any import error surfaces in this thread's logs.
    from .dashboard import app
    print(f"[dashboard] serving on {config.DASHBOARD_HOST}:{config.DASHBOARD_PORT}")
    # threaded=True lets the dashboard handle requests while the scheduler runs.
    app.run(host=config.DASHBOARD_HOST, port=config.DASHBOARD_PORT,
            debug=False, threaded=True, use_reloader=False)


def _handle_signal(signum, frame):
    print(f"[entrypoint] received signal {signum}, shutting down ...")
    _stop.set()
    # Flask's dev server doesn't stop cleanly from a signal handler in a thread;
    # exiting the process is acceptable here since state is persisted to disk.
    os._exit(0)


def main():
    # Signal handlers can only be registered from the main thread. In normal
    # container use this IS the main thread; guard so importing/running under a
    # test harness or WSGI worker thread doesn't crash.
    try:
        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)
    except ValueError:
        print("[entrypoint] not main thread — skipping signal handlers")

    os.makedirs(config.DATA_DIR, exist_ok=True)
    _seed_once()

    # Scheduler in a background thread; dashboard on the main thread.
    if config.ANTHROPIC_API_KEY:
        threading.Thread(target=_run_scheduler, daemon=True).start()
    else:
        print("[entrypoint] ANTHROPIC_API_KEY not set — scheduler disabled, "
              "dashboard will run but refreshes will fail until it's provided.")

    _run_dashboard()


if __name__ == "__main__":
    main()
