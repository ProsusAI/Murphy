"""Browser process cleanup for Murphy.

Ensures orphan Chromium processes from crashed runs are cleaned up,
and records current browser PIDs so process-exit cleanup can kill them if needed.
"""

from __future__ import annotations

import atexit
import logging
from pathlib import Path

import psutil

logger = logging.getLogger(__name__)

# Legacy single-slot file kept so an upgrade can clean a browser from the old layout.
PID_FILE = Path('/tmp/murphy_browser.pid')
PID_DIR = Path('/tmp/murphy_browsers')
PROJECT_BROWSER_PROFILE_DIR = Path(__file__).resolve().parent.parent / 'browser_profile'
DOCKER_BROWSER_PROFILE_DIR = Path('/tmp/murphy_browser_profile')
TEMP_PROFILE_MARKER = 'browseruse-tmp-'
BROWSER_USE_TEMP_PROFILE_MARKER = 'browser-use-user-data-dir-'

_atexit_registered = False


def kill_stale_browser() -> None:
	"""Kill leftover Chromium processes from a previous crashed process.

	Reads tracked PID files written by prior Murphy sessions and also scans for
	orphaned Chrome helper processes still attached to Murphy-managed profiles.
	This is intended for process startup, before any current jobs are running.
	"""
	killed_pids: set[int] = set()

	try:
		tracked_pids = _iter_tracked_pids()
		logger.info('Stale browser cleanup started: tracked_pids=%s', tracked_pids)
		for pid in tracked_pids:
			killed_pids.update(_terminate_process_tree(pid))
		orphan_pids = [pid for pid in _find_stale_browser_pids() if pid not in killed_pids]
		logger.info('Stale browser cleanup scan complete: orphan_pids=%s already_killed=%s', orphan_pids, sorted(killed_pids))
		for pid in orphan_pids:
			killed_pids.update(_terminate_process_tree(pid))

		if killed_pids:
			logger.info('Killed stale Murphy browser processes: %s', ', '.join(str(pid) for pid in sorted(killed_pids)))
		else:
			logger.info('No stale browser process found')
	except psutil.Error as exc:
		logger.warning('Failed to clean stale Murphy browser processes: %s', exc)
	finally:
		_clear_tracking_files()


def record_browser_pid(pid: int) -> None:
	"""Track a browser PID so it can be cleaned up after a crash."""
	PID_DIR.mkdir(parents=True, exist_ok=True)
	(PID_DIR / f'{pid}.pid').write_text(str(pid))
	_register_atexit_cleanup()


def clear_browser_pid(pid: int) -> None:
	"""Stop tracking one gracefully closed browser PID."""
	(PID_DIR / f'{pid}.pid').unlink(missing_ok=True)


def _atexit_cleanup() -> None:
	"""Last-resort cleanup when the Python process exits."""
	if not PID_FILE.exists() and not PID_DIR.exists():
		return
	killed_pids: set[int] = set()
	try:
		for pid in _iter_tracked_pids():
			killed_pids.update(_terminate_process_tree(pid))
		if killed_pids:
			logger.info(
				'atexit: killed Murphy browser processes: %s',
				', '.join(str(killed_pid) for killed_pid in sorted(killed_pids)),
			)
	except psutil.Error:
		logger.debug('atexit: Murphy browser cleanup did not complete cleanly', exc_info=True)
	finally:
		_clear_tracking_files()


def _register_atexit_cleanup() -> None:
	"""Register the atexit handler exactly once."""
	global _atexit_registered
	if not _atexit_registered:
		atexit.register(_atexit_cleanup)
		_atexit_registered = True


def get_browser_pid_from_session(browser_session: object) -> int | None:
	"""Extract the Chromium PID from a BrowserSession, if available."""
	watchdog = getattr(browser_session, '_local_browser_watchdog', None)
	if watchdog is None:
		return None
	return getattr(watchdog, 'browser_pid', None)


def _iter_tracked_pids() -> list[int]:
	"""Return tracked browser PIDs from the current directory layout plus legacy file."""
	pids: list[int] = []
	if PID_DIR.exists():
		for path in sorted(PID_DIR.glob('*.pid')):
			pid = _read_pid_file(path)
			if pid is not None:
				pids.append(pid)

	pid = _read_pid_file(PID_FILE)
	if pid is not None:
		pids.append(pid)

	return pids


def _read_pid_file(path: Path) -> int | None:
	if not path.exists():
		return None
	try:
		return int(path.read_text().strip())
	except ValueError:
		logger.warning('Ignoring invalid Murphy browser PID file: %s', path)
		return None


def _clear_tracking_files() -> None:
	if PID_DIR.exists():
		for path in PID_DIR.glob('*.pid'):
			path.unlink(missing_ok=True)
	PID_FILE.unlink(missing_ok=True)


def _terminate_process_tree(pid: int) -> set[int]:
	"""Terminate a process and its descendants, returning all targeted PIDs."""
	try:
		root = psutil.Process(pid)
	except psutil.Error:
		return set()

	processes = [root, *root.children(recursive=True)]
	targeted_pids = {proc.pid for proc in processes}

	for proc in reversed(processes):
		try:
			proc.terminate()
		except psutil.NoSuchProcess:
			continue
		except psutil.Error:
			logger.debug('Failed to terminate stale process %s', proc.pid, exc_info=True)

	_, alive = psutil.wait_procs(processes, timeout=3)
	for proc in alive:
		try:
			proc.kill()
		except psutil.NoSuchProcess:
			continue
		except psutil.Error:
			logger.debug('Failed to force-kill stale process %s', proc.pid, exc_info=True)
	psutil.wait_procs(alive, timeout=3)

	return targeted_pids


def _find_stale_browser_pids() -> list[int]:
	"""Find Murphy-owned browser processes even when the root PID is gone."""
	pids: set[int] = set()
	profile_markers = (
		str(PROJECT_BROWSER_PROFILE_DIR),
		str(DOCKER_BROWSER_PROFILE_DIR),
		TEMP_PROFILE_MARKER,
		BROWSER_USE_TEMP_PROFILE_MARKER,
	)
	profile_markers = tuple(marker.lower() for marker in profile_markers)
	browser_markers = ('chrome', 'chromium')

	for proc in psutil.process_iter(['pid', 'cmdline']):
		try:
			cmdline = ' '.join(proc.info.get('cmdline') or [])
		except (psutil.NoSuchProcess, psutil.AccessDenied):
			continue
		if not cmdline:
			continue
		cmdline_lower = cmdline.lower()
		if any(marker in cmdline_lower for marker in profile_markers) and any(marker in cmdline_lower for marker in browser_markers):
			pids.add(proc.pid)

	return sorted(pids)
