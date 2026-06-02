"""Tests for execution helper functions (no browser/LLM calls)."""

from types import SimpleNamespace
from typing import Any, cast

import pytest

from browser_use.browser.session import BrowserSession
from browser_use.llm import BaseChatModel
from murphy.core.execution import (
	_cleanup_session_pool,
	_create_session_pool,
	_execute_single_test,
	_extract_form_fills,
	_extract_urls_from_texts,
	execute_tests_with_session,
)
from murphy.models import TestPlan as MurphyTestPlan
from murphy.models import TestResult as MurphyTestResult
from murphy.models import TestScenario as MurphyTestScenario


def _make_scenario(name: str = 'Test scenario') -> MurphyTestScenario:
	return MurphyTestScenario(
		name=name,
		description='Exercise a feature',
		priority='high',
		feature_category='navigation',
		target_feature='Navigation',
		test_persona='happy_path',
		steps_description='Navigate through the site',
		success_criteria='The page loads successfully',
	)


def _make_result(scenario: MurphyTestScenario) -> MurphyTestResult:
	return MurphyTestResult(
		scenario=scenario,
		success=True,
		judgement=None,
		actions=[],
		errors=[],
		duration=0.0,
	)


class _OriginalSession:
	browser_profile = None


class _FakeFreshSession:
	instances: list['_FakeFreshSession'] = []

	def __init__(self, browser_profile: Any):
		self.browser_profile = browser_profile
		self.started = False
		self.killed = False
		self.pid = 1000 + len(_FakeFreshSession.instances)
		_FakeFreshSession.instances.append(self)

	async def start(self) -> None:
		self.started = True

	async def kill(self) -> None:
		self.killed = True


class _FakeKillFailSession(_FakeFreshSession):
	async def kill(self) -> None:
		self.killed = True
		raise RuntimeError('kill failed')


class _UnhealthySession:
	is_cdp_connected = False
	cdp_url = None
	session_manager = None
	agent_focus_target_id = None

	def __init__(self):
		self.event_bus = type('EventBus', (), {'handlers': {}})()


# ─── Sequential BrowserSession isolation ─────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_tests_with_session_uses_fresh_session_per_sequential_test(monkeypatch):
	_FakeFreshSession.instances.clear()
	scenarios = [_make_scenario('First'), _make_scenario('Second')]
	seen_sessions: list[_FakeFreshSession] = []

	async def fake_execute_single_test(**kwargs):
		session = kwargs['browser_session']
		seen_sessions.append(session)
		return _make_result(kwargs['scenario'])

	monkeypatch.setattr('murphy.core.execution.BrowserSession', _FakeFreshSession)
	monkeypatch.setattr('murphy.core.execution._execute_single_test', fake_execute_single_test)

	results = await execute_tests_with_session(
		url='https://example.com',
		test_plan=MurphyTestPlan(scenarios=scenarios),
		llm=cast(BaseChatModel, object()),
		browser_session=cast(BrowserSession, _OriginalSession()),
		max_concurrent=1,
	)

	assert len(results) == 2
	assert len(_FakeFreshSession.instances) == 2
	assert seen_sessions == _FakeFreshSession.instances
	assert all(session.started for session in _FakeFreshSession.instances)
	assert all(session.killed for session in _FakeFreshSession.instances)
	assert len({id(session) for session in seen_sessions}) == 2


@pytest.mark.asyncio
async def test_execute_tests_with_session_tracks_fresh_sequential_session_pids(monkeypatch):
	_FakeFreshSession.instances.clear()
	scenarios = [_make_scenario('First'), _make_scenario('Second')]
	events: list[tuple[str, int]] = []

	async def fake_execute_single_test(**kwargs):
		return _make_result(kwargs['scenario'])

	monkeypatch.setattr('murphy.core.execution.BrowserSession', _FakeFreshSession)
	monkeypatch.setattr('murphy.core.execution._execute_single_test', fake_execute_single_test)
	monkeypatch.setattr('murphy.core.execution.get_browser_pid_from_session', lambda session: session.pid, raising=False)
	monkeypatch.setattr('murphy.core.execution.record_browser_pid', lambda pid: events.append(('record', pid)), raising=False)
	monkeypatch.setattr('murphy.core.execution.clear_browser_pid', lambda pid: events.append(('clear', pid)), raising=False)

	await execute_tests_with_session(
		url='https://example.com',
		test_plan=MurphyTestPlan(scenarios=scenarios),
		llm=cast(BaseChatModel, object()),
		browser_session=cast(BrowserSession, _OriginalSession()),
		max_concurrent=1,
	)

	assert events == [
		('record', 1000),
		('clear', 1000),
		('record', 1001),
		('clear', 1001),
	]


@pytest.mark.asyncio
async def test_execute_tests_with_session_keeps_sequential_pid_marker_when_kill_fails(monkeypatch):
	_FakeFreshSession.instances.clear()
	events: list[tuple[str, int]] = []

	async def fake_execute_single_test(**kwargs):
		return _make_result(kwargs['scenario'])

	monkeypatch.setattr('murphy.core.execution.BrowserSession', _FakeKillFailSession)
	monkeypatch.setattr('murphy.core.execution._execute_single_test', fake_execute_single_test)
	monkeypatch.setattr('murphy.core.execution.get_browser_pid_from_session', lambda session: session.pid, raising=False)
	monkeypatch.setattr('murphy.core.execution.record_browser_pid', lambda pid: events.append(('record', pid)), raising=False)
	monkeypatch.setattr('murphy.core.execution.clear_browser_pid', lambda pid: events.append(('clear', pid)), raising=False)

	await execute_tests_with_session(
		url='https://example.com',
		test_plan=MurphyTestPlan(scenarios=[_make_scenario()]),
		llm=cast(BaseChatModel, object()),
		browser_session=cast(BrowserSession, _OriginalSession()),
		max_concurrent=1,
	)

	assert events == [('record', 1000)]


@pytest.mark.asyncio
async def test_create_session_pool_records_extra_session_pids(monkeypatch):
	_FakeFreshSession.instances.clear()
	events: list[tuple[str, int]] = []

	class FakeSend:
		class Network:
			@staticmethod
			async def getAllCookies(**kwargs):
				return {'cookies': []}

		class Runtime:
			@staticmethod
			async def evaluate(**kwargs):
				return {'result': {'value': '[]'}}

	class OriginalSession:
		browser_profile = None

		async def get_or_create_cdp_session(self):
			return SimpleNamespace(session_id='original', cdp_client=SimpleNamespace(send=FakeSend))

	monkeypatch.setattr('murphy.core.execution.BrowserSession', _FakeFreshSession)
	monkeypatch.setattr('browser_use.browser.profile.BrowserProfile', lambda **kwargs: SimpleNamespace(kwargs=kwargs))
	monkeypatch.setattr('murphy.core.execution.get_browser_pid_from_session', lambda session: session.pid, raising=False)
	monkeypatch.setattr('murphy.core.execution.record_browser_pid', lambda pid: events.append(('record', pid)), raising=False)

	sessions = await _create_session_pool(
		pool_size=3,
		original_session=cast(BrowserSession, OriginalSession()),
	)

	assert len(sessions) == 3
	assert events == [('record', 1000), ('record', 1001)]


@pytest.mark.asyncio
async def test_cleanup_session_pool_clears_extra_session_pids_but_not_original(monkeypatch):
	events: list[tuple[str, int]] = []
	original = _OriginalSession()
	extra_one = _FakeFreshSession(browser_profile=None)
	extra_two = _FakeFreshSession(browser_profile=None)

	monkeypatch.setattr('murphy.core.execution.get_browser_pid_from_session', lambda session: session.pid, raising=False)
	monkeypatch.setattr('murphy.core.execution.clear_browser_pid', lambda pid: events.append(('clear', pid)), raising=False)

	await _cleanup_session_pool(
		[
			cast(BrowserSession, original),
			cast(BrowserSession, extra_one),
			cast(BrowserSession, extra_two),
		],
		cast(BrowserSession, original),
	)

	assert extra_one.killed is True
	assert extra_two.killed is True
	assert events == [('clear', extra_one.pid), ('clear', extra_two.pid)]


@pytest.mark.asyncio
async def test_cleanup_session_pool_keeps_pid_marker_when_kill_fails(monkeypatch):
	events: list[tuple[str, int]] = []
	original = _OriginalSession()
	extra = _FakeKillFailSession(browser_profile=None)

	monkeypatch.setattr('murphy.core.execution.get_browser_pid_from_session', lambda session: session.pid, raising=False)
	monkeypatch.setattr('murphy.core.execution.clear_browser_pid', lambda pid: events.append(('clear', pid)), raising=False)

	await _cleanup_session_pool(
		[
			cast(BrowserSession, original),
			cast(BrowserSession, extra),
		],
		cast(BrowserSession, original),
	)

	assert extra.killed is True
	assert events == []


# ─── Pre-agent browser session health checks ─────────────────────────────────


@pytest.mark.asyncio
async def test_execute_single_test_returns_test_limitation_when_browser_session_unhealthy(monkeypatch):
	agent_was_called = False

	async def fake_prepare_session_for_task(*args, **kwargs):
		return False

	class FakeAgent:
		def __init__(self, **kwargs):
			nonlocal agent_was_called
			agent_was_called = True
			raise AssertionError('Agent should not run with unhealthy browser session')

	monkeypatch.setattr('murphy.browser.session_utils.prepare_session_for_task', fake_prepare_session_for_task)
	monkeypatch.setattr('murphy.core.execution.Agent', FakeAgent)

	result = await _execute_single_test(
		url='https://example.com',
		scenario=_make_scenario(),
		llm=cast(BaseChatModel, object()),
		browser_session=cast(BrowserSession, _UnhealthySession()),
		goal=None,
		fixture_paths=None,
		max_steps=1,
		index=1,
		total=1,
	)

	assert agent_was_called is False
	assert result.success is False
	assert result.failure_category == 'test_limitation'
	assert result.errors
	first_error = result.errors[0]
	assert first_error is not None
	assert 'Browser session' in first_error


# ─── _extract_form_fills ─────────────────────────────────────────────────────


def test_extract_form_fills_empty():
	assert _extract_form_fills([]) == []


def test_extract_form_fills_no_input_actions():
	actions = [{'click': {'index': 1}}, {'navigate': {'url': 'https://example.com'}}]
	assert _extract_form_fills(actions) == []


def test_extract_form_fills_input_text():
	actions = [
		{
			'input_text': {'text': 'hello', 'index': 3},
			'interacted_element': {
				'ax_name': 'Email',
				'tag_name': 'input',
				'placeholder': 'Enter email',
				'attributes': {'name': 'email', 'aria-label': 'Email field', 'type': 'email'},
				'role': 'textbox',
			},
		}
	]
	fills = _extract_form_fills(actions)
	assert len(fills) == 1
	assert fills[0]['text'] == 'hello'
	assert fills[0]['index'] == 3
	assert fills[0]['field_name'] == 'Email'
	assert fills[0]['tag'] == 'input'
	assert fills[0]['placeholder'] == 'Enter email'
	assert fills[0]['name_attr'] == 'email'
	assert fills[0]['aria_label'] == 'Email field'
	assert fills[0]['type_attr'] == 'email'
	assert fills[0]['role'] == 'textbox'


def test_extract_form_fills_input_key():
	"""The 'input' key is also recognized (not just 'input_text')."""
	actions = [{'input': {'text': 'world', 'index': 5}}]
	fills = _extract_form_fills(actions)
	assert len(fills) == 1
	assert fills[0]['text'] == 'world'


def test_extract_form_fills_without_interacted_element():
	actions = [{'input_text': {'text': 'test', 'index': 1}}]
	fills = _extract_form_fills(actions)
	assert len(fills) == 1
	assert fills[0]['text'] == 'test'
	assert 'field_name' not in fills[0]


def test_extract_form_fills_multiple():
	actions = [
		{'input_text': {'text': 'alice', 'index': 1}},
		{'click': {'index': 2}},
		{'input_text': {'text': 'password123', 'index': 3}},
	]
	fills = _extract_form_fills(actions)
	assert len(fills) == 2
	assert fills[0]['text'] == 'alice'
	assert fills[1]['text'] == 'password123'


def test_extract_form_fills_non_dict_val_ignored():
	"""Non-dict values for input_text are skipped."""
	actions = [{'input_text': 'not a dict'}]
	assert _extract_form_fills(actions) == []


def test_extract_form_fills_attributes_non_dict():
	"""If interacted_element.attributes is not a dict, don't crash."""
	actions = [
		{
			'input_text': {'text': 'x'},
			'interacted_element': {'ax_name': 'Field', 'tag_name': 'input', 'attributes': 'bad'},
		}
	]
	fills = _extract_form_fills(actions)
	assert len(fills) == 1
	assert fills[0]['field_name'] == 'Field'


# ─── _extract_urls_from_texts ────────────────────────────────────────────────


def test_extract_urls_from_texts_empty():
	assert _extract_urls_from_texts([]) == []


def test_extract_urls_from_texts_no_urls():
	assert _extract_urls_from_texts(['no urls here', 'just plain text']) == []


def test_extract_urls_from_texts_single():
	result = _extract_urls_from_texts(['Error at https://example.com/page'])
	assert result == ['https://example.com/page']


def test_extract_urls_from_texts_multiple():
	result = _extract_urls_from_texts(
		[
			'Failed on https://a.com and http://b.com/path',
			'Also https://c.com',
		]
	)
	assert len(result) == 3


def test_extract_urls_from_texts_skips_none():
	result = _extract_urls_from_texts(['', 'https://ok.com'])
	assert result == ['https://ok.com']
