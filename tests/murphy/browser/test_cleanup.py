"""Tests for Murphy browser cleanup helpers."""

from __future__ import annotations

from types import SimpleNamespace

from murphy.browser import cleanup


def _patch_pid_paths(monkeypatch, tmp_path):
	pid_dir = tmp_path / 'murphy_browsers'
	legacy_pid_file = tmp_path / 'murphy_browser.pid'
	monkeypatch.setattr(cleanup, 'PID_DIR', pid_dir)
	monkeypatch.setattr(cleanup, 'PID_FILE', legacy_pid_file)
	return pid_dir, legacy_pid_file


def test_kill_stale_browser_detects_orphaned_murphy_processes(monkeypatch, tmp_path, caplog):
	"""Cleanup should scan for Murphy-owned browser helpers even without a PID file."""
	terminated: list[int] = []

	def fake_process_iter(_attrs):
		return [
			SimpleNamespace(
				pid=111,
				info={
					'pid': 111,
					'cmdline': [
						'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
						f'--user-data-dir={cleanup.PROJECT_BROWSER_PROFILE_DIR}',
						'--remote-debugging-port=65494',
					],
				},
			),
			SimpleNamespace(
				pid=222, info={'pid': 222, 'cmdline': ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome']}
			),
		]

	_patch_pid_paths(monkeypatch, tmp_path)
	monkeypatch.setattr(cleanup.psutil, 'process_iter', fake_process_iter)
	monkeypatch.setattr(cleanup, '_terminate_process_tree', lambda pid: terminated.append(pid) or {pid})

	cleanup.kill_stale_browser()

	assert terminated == [111]
	assert 'Killed stale Murphy browser processes: 111' in caplog.text


def test_kill_stale_browser_detects_browser_use_temp_profiles(monkeypatch, tmp_path):
	"""Startup cleanup should catch browser-use default temp profiles from failed launches."""
	terminated: list[int] = []

	def fake_process_iter(_attrs):
		return [
			SimpleNamespace(
				pid=333,
				info={
					'pid': 333,
					'cmdline': [
						'/usr/bin/chromium',
						'--user-data-dir=/tmp/browser-use-user-data-dir-a1b2c3',
						'--remote-debugging-port=65494',
					],
				},
			),
			SimpleNamespace(pid=444, info={'pid': 444, 'cmdline': ['/usr/bin/chromium']}),
		]

	_patch_pid_paths(monkeypatch, tmp_path)
	monkeypatch.setattr(cleanup.psutil, 'process_iter', fake_process_iter)
	monkeypatch.setattr(cleanup, '_terminate_process_tree', lambda pid: terminated.append(pid) or {pid})

	cleanup.kill_stale_browser()

	assert terminated == [333]


def test_record_and_clear_browser_pid_isolates_concurrent_sessions(monkeypatch, tmp_path):
	"""Clearing one tracked session must not remove another session's PID marker."""
	pid_dir, _legacy_pid_file = _patch_pid_paths(monkeypatch, tmp_path)
	monkeypatch.setattr(cleanup, '_register_atexit_cleanup', lambda: None)

	cleanup.record_browser_pid(111)
	cleanup.record_browser_pid(222)
	cleanup.clear_browser_pid(111)

	assert not (pid_dir / '111.pid').exists()
	assert (pid_dir / '222.pid').exists()


def test_kill_stale_browser_terminates_tracked_pids(monkeypatch, tmp_path):
	"""Startup cleanup should terminate every PID from the per-session tracking dir."""
	pid_dir, _legacy_pid_file = _patch_pid_paths(monkeypatch, tmp_path)
	pid_dir.mkdir()
	(pid_dir / '111.pid').write_text('111')
	(pid_dir / '222.pid').write_text('222')
	terminated: list[int] = []

	monkeypatch.setattr(cleanup.psutil, 'process_iter', lambda _attrs: [])
	monkeypatch.setattr(cleanup, '_terminate_process_tree', lambda pid: terminated.append(pid) or {pid})

	cleanup.kill_stale_browser()

	assert terminated == [111, 222]
	assert not list(pid_dir.glob('*.pid'))


def test_kill_stale_browser_migrates_legacy_pid_file(monkeypatch, tmp_path):
	"""Cleanup should still terminate the old single PID file after an upgrade."""
	_pid_dir, legacy_pid_file = _patch_pid_paths(monkeypatch, tmp_path)
	legacy_pid_file.write_text('333')
	terminated: list[int] = []

	monkeypatch.setattr(cleanup.psutil, 'process_iter', lambda _attrs: [])
	monkeypatch.setattr(cleanup, '_terminate_process_tree', lambda pid: terminated.append(pid) or {pid})

	cleanup.kill_stale_browser()

	assert terminated == [333]
	assert not legacy_pid_file.exists()


def test_atexit_cleanup_terminates_all_tracked_pids(monkeypatch, tmp_path):
	"""Last-resort cleanup should terminate every tracked browser session."""
	pid_dir, _legacy_pid_file = _patch_pid_paths(monkeypatch, tmp_path)
	pid_dir.mkdir()
	(pid_dir / '111.pid').write_text('111')
	(pid_dir / '222.pid').write_text('222')
	terminated: list[int] = []

	monkeypatch.setattr(cleanup, '_terminate_process_tree', lambda pid: terminated.append(pid) or {pid})

	cleanup._atexit_cleanup()

	assert terminated == [111, 222]
	assert not list(pid_dir.glob('*.pid'))
