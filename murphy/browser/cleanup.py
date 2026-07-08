# Copyright © 2026 MIH AI B.V.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Browser process cleanup for Murphy.

Ensures orphan Chromium processes from crashed runs are cleaned up,
and records the current browser PID so the next run can kill it if needed.
"""

from __future__ import annotations

import atexit
import logging
from pathlib import Path

import psutil

logger = logging.getLogger(__name__)

PID_FILE = Path('/tmp/murphy_browser.pid')
PROJECT_BROWSER_PROFILE_DIR = Path(__file__).resolve().parent.parent / 'browser_profile'
DOCKER_BROWSER_PROFILE_DIR = Path('/tmp/murphy_browser_profile')
TEMP_PROFILE_MARKER = 'browseruse-tmp-'

_atexit_registered = False


def kill_stale_browser() -> None:
	"""Kill a leftover Chromium process from a previous crashed run.

	Reads the PID file written by a prior Murphy session and also scans for
	orphaned Chrome helper processes still attached to Murphy-managed profiles.
	"""
	killed_pids: set[int] = set()

	try:
		if PID_FILE.exists():
			pid = int(PID_FILE.read_text().strip())
			killed_pids.update(_terminate_process_tree(pid))
		orphan_pids = [pid for pid in _find_stale_browser_pids() if pid not in killed_pids]
		for pid in orphan_pids:
			killed_pids.update(_terminate_process_tree(pid))

		if killed_pids:
			logger.info('Killed stale Murphy browser processes: %s', ', '.join(str(pid) for pid in sorted(killed_pids)))
		else:
			logger.info('No stale browser process found')
	except ValueError:
		logger.warning('Ignoring invalid Murphy browser PID file: %s', PID_FILE)
	except psutil.Error as exc:
		logger.warning('Failed to clean stale Murphy browser processes: %s', exc)
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
		killed_pids = _terminate_process_tree(pid)
		if killed_pids:
			logger.info(
				'atexit: killed Murphy browser processes: %s',
				', '.join(str(killed_pid) for killed_pid in sorted(killed_pids)),
			)
	except (ValueError, psutil.Error):
		logger.debug('atexit: Murphy browser cleanup did not complete cleanly', exc_info=True)
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
	watchdog = getattr(browser_session, '_local_browser_watchdog', None)
	if watchdog is None:
		return None
	return getattr(watchdog, 'browser_pid', None)


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
	profile_markers = (str(PROJECT_BROWSER_PROFILE_DIR), str(DOCKER_BROWSER_PROFILE_DIR), TEMP_PROFILE_MARKER)
	browser_markers = ('Chrome', 'Chromium')

	for proc in psutil.process_iter(['pid', 'cmdline']):
		try:
			cmdline = ' '.join(proc.info.get('cmdline') or [])
		except (psutil.NoSuchProcess, psutil.AccessDenied):
			continue
		if not cmdline:
			continue
		if any(marker in cmdline for marker in profile_markers) and any(marker in cmdline for marker in browser_markers):
			pids.add(proc.pid)

	return sorted(pids)
