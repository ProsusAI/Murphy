"""Tests for Murphy browser cleanup helpers."""

from __future__ import annotations

from types import SimpleNamespace

from murphy.browser import cleanup


def test_kill_stale_browser_detects_orphaned_murphy_processes(monkeypatch, caplog):
	"""Cleanup should scan for Murphy-owned browser helpers even without a PID file."""
	terminated: list[int] = []

	def fake_process_iter(_attrs):
		return [
			SimpleNamespace(
				info={
					'pid': 111,
					'cmdline': [
						'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
						f'--user-data-dir={cleanup.PROJECT_BROWSER_PROFILE_DIR}',
						'--remote-debugging-port=65494',
					],
				}
			),
			SimpleNamespace(info={'pid': 222, 'cmdline': ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome']}),
		]

	monkeypatch.setattr(cleanup, 'PID_FILE', cleanup.PID_FILE.with_name('test-murphy-browser.pid'))
	monkeypatch.setattr(cleanup.psutil, 'process_iter', fake_process_iter)
	monkeypatch.setattr(cleanup, '_terminate_process_tree', lambda pid: terminated.append(pid) or {pid})

	cleanup.kill_stale_browser()

	assert terminated == [111]
	assert 'Killed stale Murphy browser processes: 111' in caplog.text
