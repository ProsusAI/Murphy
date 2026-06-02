"""Tests for pipeline browser cleanup lifecycle."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from murphy.core import pipeline
from murphy.models import ReportSummary
from murphy.models import TestPlan as MurphyTestPlan


@pytest.fixture
def browser_lifecycle(monkeypatch):
	events: list[object] = []

	class FakeBrowserSession:
		def __init__(self, browser_profile=None):
			self.browser_profile = browser_profile
			self._local_browser_watchdog = SimpleNamespace(browser_pid=123)

		async def start(self):
			events.append('start')

		async def kill(self):
			events.append('kill')

	monkeypatch.setattr(pipeline, 'BrowserSession', FakeBrowserSession)
	monkeypatch.setattr(pipeline, 'BrowserProfile', lambda **kwargs: SimpleNamespace(kwargs=kwargs))
	monkeypatch.setattr(pipeline, 'apply_patches', lambda: events.append('patches'))
	monkeypatch.setattr(pipeline, 'kill_stale_browser', lambda: events.append('kill_stale_browser'), raising=False)
	monkeypatch.setattr(pipeline, 'record_browser_pid', lambda pid: events.append(('record', pid)))
	monkeypatch.setattr(pipeline, 'clear_browser_pid', lambda pid: events.append(('clear', pid)))
	monkeypatch.setattr(pipeline, 'create_llm', lambda *args, **kwargs: object())
	return events


async def test_run_analyze_does_not_run_startup_cleanup_and_clears_own_pid(monkeypatch, browser_lifecycle):
	async def fake_analyze_website(*args, **kwargs):
		return 'analysis'

	monkeypatch.setattr(pipeline, 'analyze_website', fake_analyze_website)

	result = await pipeline.run_analyze('https://example.com', 'gpt-test')

	assert result == 'analysis'
	assert 'kill_stale_browser' not in browser_lifecycle
	assert ('record', 123) in browser_lifecycle
	assert ('clear', 123) in browser_lifecycle


async def test_run_execute_does_not_run_startup_cleanup_and_clears_own_pid(monkeypatch, browser_lifecycle):
	async def fake_execute_tests_with_session(*args, **kwargs):
		return []

	monkeypatch.setattr(pipeline, 'ensure_dummy_fixture_files', lambda: [])
	monkeypatch.setattr(pipeline, 'execute_tests_with_session', fake_execute_tests_with_session)
	monkeypatch.setattr(
		pipeline,
		'build_summary',
		lambda _results: ReportSummary(total=0, passed=0, failed=0, pass_rate=0.0, by_priority={}),
	)

	results, summary = await pipeline.run_execute('https://example.com', MurphyTestPlan(scenarios=[]), 'gpt-test')

	assert results == []
	assert summary.total == 0
	assert 'kill_stale_browser' not in browser_lifecycle
	assert ('record', 123) in browser_lifecycle
	assert ('clear', 123) in browser_lifecycle


async def test_run_evaluate_does_not_run_startup_cleanup_and_clears_own_pid(monkeypatch, browser_lifecycle):
	async def fake_explore_and_generate_plan(*args, **kwargs):
		return MurphyTestPlan(scenarios=[])

	monkeypatch.setattr(pipeline, 'explore_and_generate_plan', fake_explore_and_generate_plan)

	result = await pipeline.run_evaluate('https://example.com', 'gpt-test')

	assert result == MurphyTestPlan(scenarios=[])
	assert 'kill_stale_browser' not in browser_lifecycle
	assert ('record', 123) in browser_lifecycle
	assert ('clear', 123) in browser_lifecycle
