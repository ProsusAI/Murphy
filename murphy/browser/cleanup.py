"""Browser process cleanup for Murphy.

Ensures orphan Chromium processes from crashed runs are cleaned up,
and records the current browser PID so the next run can kill it if needed.
"""

from __future__ import annotations

import atexit
import logging
import os
import signal
from pathlib import Path

logger = logging.getLogger(__name__)

PID_FILE = Path("/tmp/murphy_browser.pid")

_atexit_registered = False


def kill_stale_browser() -> None:
    """Kill a leftover Chromium process from a previous crashed run.

    Reads the PID file written by a prior Murphy session and sends SIGTERM.
    Safe to call even if no stale process exists.
    """
    if not PID_FILE.exists():
        logger.info("No stale browser process found")
        return
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        logger.info("Killed stale browser process (pid=%d) from previous run", pid)
    except (ProcessLookupError, PermissionError):
        pass
    except (ValueError, OSError):
        pass
    finally:
        PID_FILE.unlink(missing_ok=True)


def record_browser_pid(pid: int) -> None:
    """Write the browser PID to disk so it can be cleaned up after a crash."""
    PID_FILE.write_text(str(pid))
    _register_atexit_cleanup()


def clear_browser_pid() -> None:
    """Remove the PID file (called on graceful shutdown)."""
    PID_FILE.unlink(missing_ok=True)


def _atexit_cleanup() -> None:
    """Last-resort cleanup when the Python process exits."""
    if not PID_FILE.exists():
        return
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        logger.debug("atexit: killed browser process (pid=%d)", pid)
    except (ProcessLookupError, PermissionError, ValueError, OSError):
        pass
    finally:
        PID_FILE.unlink(missing_ok=True)


def _register_atexit_cleanup() -> None:
    """Register the atexit handler exactly once."""
    global _atexit_registered
    if not _atexit_registered:
        atexit.register(_atexit_cleanup)
        _atexit_registered = True


def get_browser_pid_from_session(browser_session: object) -> int | None:
    """Extract the Chromium PID from a BrowserSession, if available."""
    watchdog = getattr(browser_session, "_local_browser_watchdog", None)
    if watchdog is None:
        return None
    return getattr(watchdog, "browser_pid", None)
