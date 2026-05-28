"""Tests for execution helper functions (no browser/LLM calls)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from murphy.core.execution import (
	_execute_single_test,
	_extract_form_fills,
	_extract_urls_from_texts,
)
from murphy.models import LiteResult, TestScenario

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


# ─── Lite execution ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_single_test_lite_mode_skips_judge_and_returns_lite_result():
	scenario = TestScenario(
		name='Lite agent creation',
		description='Assess the agent creation flow',
		priority='critical',
		feature_category='forms',
		target_feature='Agent creation',
		test_persona='happy_path',
		steps_description='Try to create an agent',
		success_criteria='Return structured flaws, improvements, fixes, and other observations.',
	)
	lite_result = LiteResult(
		grade=7,
		flaws=['Creation has unclear required fields'],
		improvements=['Show progress while creating the agent'],
		fixes=['Label the create button clearly'],
		other_feedback=['The main navigation is understandable'],
	)
	history = MagicMock()
	history.final_result.return_value = json.dumps(lite_result.model_dump())
	history.model_actions.return_value = [{'click': {'index': 1}}]
	history.errors.return_value = []
	history.total_duration_seconds.return_value = 3.5
	history.urls.return_value = ['https://example.com/agents']
	history.screenshot_paths.return_value = []

	agent = MagicMock()
	agent.tools = MagicMock()
	agent.run = AsyncMock(return_value=history)

	with (
		patch('murphy.core.execution.Agent', return_value=agent) as agent_cls,
		patch('murphy.core.execution.murphy_judge', new_callable=AsyncMock) as judge,
		patch('murphy.browser.session_utils.prepare_session_for_task', new_callable=AsyncMock),
		patch('murphy.browser.actions.register_domain_access_action'),
		patch('murphy.browser.actions.register_refresh_dom_action'),
	):
		result = await _execute_single_test(
			url='https://example.com',
			scenario=scenario,
			llm=MagicMock(),
			browser_session=MagicMock(),
			goal='Test agent creation flow',
			fixture_paths=None,
			max_steps=5,
			index=1,
			total=1,
			use_lite=True,
		)

	agent_cls.assert_called_once()
	assert agent_cls.call_args.kwargs['output_model_schema'] is LiteResult
	judge.assert_not_awaited()
	assert result.success is True
	assert result.judgement is None
	assert result.lite_result == lite_result
	assert result.reason == 'Lite mode grade: 7'


@pytest.mark.asyncio
async def test_execute_single_test_lite_mode_low_grade_is_plain_failed_test():
	scenario = TestScenario(
		name='Lite confused user',
		description='Assess the agent creation flow for confusion',
		priority='high',
		feature_category='forms',
		target_feature='Agent creation',
		test_persona='confused_novice',
		steps_description='Try to create an agent',
		success_criteria='Return structured flaws, improvements, fixes, and other observations.',
	)
	lite_result = LiteResult(
		grade=4,
		flaws=['The create flow is hard to find'],
		improvements=['Expose a clearer create action'],
		fixes=['Add a primary Create Agent button'],
		other_feedback=[],
	)
	history = MagicMock()
	history.final_result.return_value = json.dumps(lite_result.model_dump())
	history.model_actions.return_value = [{'click': {'index': 1}}]
	history.errors.return_value = []
	history.total_duration_seconds.return_value = 2.0
	history.urls.return_value = ['https://example.com']
	history.screenshot_paths.return_value = []

	agent = MagicMock()
	agent.tools = MagicMock()
	agent.run = AsyncMock(return_value=history)

	with (
		patch('murphy.core.execution.Agent', return_value=agent),
		patch('murphy.core.execution.murphy_judge', new_callable=AsyncMock) as judge,
		patch('murphy.browser.session_utils.prepare_session_for_task', new_callable=AsyncMock),
		patch('murphy.browser.actions.register_domain_access_action'),
		patch('murphy.browser.actions.register_refresh_dom_action'),
	):
		result = await _execute_single_test(
			url='https://example.com',
			scenario=scenario,
			llm=MagicMock(),
			browser_session=MagicMock(),
			goal='Test agent creation flow',
			fixture_paths=None,
			max_steps=5,
			index=1,
			total=1,
			use_lite=True,
		)

	judge.assert_not_awaited()
	assert result.success is False
	assert result.judgement is None
	assert result.failure_category is None
	assert result.lite_result == lite_result
	assert result.reason == 'Lite mode grade: 4'
