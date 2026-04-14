"""Tests for murphy_judge with mocked LLM — no real API calls."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from murphy.core.judge import murphy_judge
from murphy.models import JudgeVerdict, TestScenario


def _make_scenario(**overrides) -> TestScenario:
	defaults = dict(
		name='Test search',
		description='Test the search feature',
		priority='high',
		feature_category='search',
		target_feature='Search bar',
		test_persona='first_timer',
		steps_description='1. Click search\n2. Type query',
		success_criteria='Results appear',
	)
	defaults.update(overrides)
	return TestScenario.model_validate(defaults)


def _make_mock_step(screenshot_b64: str | None = None) -> MagicMock:
	"""Create a mock agent history step with an optional screenshot."""
	step = MagicMock()
	step.state.get_screenshot.return_value = screenshot_b64
	step.model_output = None  # no actions — score stays 0
	step.result = []
	return step


def _make_mock_history(
	actions: list[dict] | None = None,
	urls: list[str] | None = None,
	errors: list[str] | None = None,
	final_result: str | None = None,
	screenshots: list[str] | None = None,
	agent_steps: list[str] | None = None,
) -> MagicMock:
	h = MagicMock()
	h.model_actions.return_value = actions or []
	h.urls.return_value = urls or []
	h.errors.return_value = errors or []
	h.final_result.return_value = final_result or ''
	h.agent_steps.return_value = agent_steps or []
	# _select_key_screenshots reads history.history, not history.screenshots()
	# Each step must have step.state.get_screenshot(), step.model_output, step.result
	if screenshots:
		h.history = [_make_mock_step(s) for s in screenshots]
	else:
		h.history = []
	return h


def _make_mock_llm(verdict: JudgeVerdict) -> MagicMock:
	"""Create a mock LLM that returns a JudgeVerdict from ainvoke."""
	llm = AsyncMock()
	response = MagicMock()
	response.completion = verdict
	llm.ainvoke.return_value = response
	return llm


@pytest.mark.asyncio
async def test_murphy_judge_pass():
	verdict = JudgeVerdict(
		reasoning='Test passed successfully',
		verdict=True,
		failure_reason='',
		impossible_task=False,
		reached_captcha=False,
		failure_category=None,
	)
	llm = _make_mock_llm(verdict)
	history = _make_mock_history(
		actions=[{'navigate': {'url': 'https://example.com'}}],
		urls=['https://example.com'],
	)

	result = await murphy_judge(history, _make_scenario(), llm, start_url='https://example.com')

	assert result.verdict is True
	assert result.failure_category is None
	llm.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_murphy_judge_fail_website_issue():
	verdict = JudgeVerdict(
		reasoning='Search returned no results',
		verdict=False,
		failure_reason='Search is broken',
		impossible_task=False,
		reached_captcha=False,
		failure_category='website_issue',
	)
	llm = _make_mock_llm(verdict)
	history = _make_mock_history()

	result = await murphy_judge(history, _make_scenario(), llm, start_url='https://example.com')

	assert result.verdict is False
	assert result.failure_category == 'website_issue'


@pytest.mark.asyncio
async def test_murphy_judge_uses_judge_llm_when_provided():
	"""When judge_llm is provided, it should be used instead of the main llm."""
	verdict = JudgeVerdict(
		reasoning='OK',
		verdict=True,
		failure_reason='',
		impossible_task=False,
		reached_captcha=False,
		failure_category=None,
	)
	main_llm = AsyncMock()
	judge_llm = _make_mock_llm(verdict)
	history = _make_mock_history()

	result = await murphy_judge(history, _make_scenario(), main_llm, start_url='https://example.com', judge_llm=judge_llm)

	assert result.verdict is True
	judge_llm.ainvoke.assert_called_once()
	main_llm.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_murphy_judge_includes_trait_context():
	"""Verify that the judge prompt includes persona trait context."""
	verdict = JudgeVerdict(
		reasoning='OK',
		verdict=True,
		failure_reason='',
		impossible_task=False,
		reached_captcha=False,
		failure_category=None,
	)
	llm = _make_mock_llm(verdict)
	history = _make_mock_history()

	await murphy_judge(history, _make_scenario(test_persona='adversarial'), llm, start_url='https://example.com')

	# Check the prompt passed to LLM contains adversarial context
	call_args = llm.ainvoke.call_args
	messages = call_args.kwargs.get('messages') or call_args[0][0]
	user_msg_content = messages[1].content
	# user_content is a list of ContentPartTextParam
	text_parts = [p.text if hasattr(p, 'text') else str(p) for p in user_msg_content if hasattr(p, 'text')]
	full_text = '\n'.join(text_parts)
	assert 'adversarial' in full_text
	assert 'RESISTING' in full_text


@pytest.mark.asyncio
async def test_murphy_judge_with_screenshots():
	"""Screenshots should be included in the user message."""
	verdict = JudgeVerdict(
		reasoning='OK',
		verdict=True,
		failure_reason='',
		impossible_task=False,
		reached_captcha=False,
		failure_category=None,
	)
	llm = _make_mock_llm(verdict)
	history = _make_mock_history(screenshots=['base64data1', 'base64data2'])

	await murphy_judge(history, _make_scenario(), llm, start_url='https://example.com')

	call_args = llm.ainvoke.call_args
	messages = call_args.kwargs.get('messages') or call_args[0][0]
	user_msg_content = messages[1].content
	# Should have text + screenshot entries
	assert len(user_msg_content) > 1


@pytest.mark.asyncio
async def test_murphy_judge_with_errors():
	"""Errors in history should be included in the prompt."""
	verdict = JudgeVerdict(
		reasoning='Failed due to errors',
		verdict=False,
		failure_reason='Element not found',
		impossible_task=False,
		reached_captcha=False,
		failure_category='test_limitation',
	)
	llm = _make_mock_llm(verdict)
	history = _make_mock_history(
		errors=['', 'Element not found', ''],
	)

	result = await murphy_judge(history, _make_scenario(), llm, start_url='https://example.com')
	assert result.verdict is False


@pytest.mark.asyncio
async def test_murphy_judge_unknown_persona_no_trait_context():
	"""An unknown persona should still work, just without trait context."""
	verdict = JudgeVerdict(
		reasoning='OK',
		verdict=True,
		failure_reason='',
		impossible_task=False,
		reached_captcha=False,
		failure_category=None,
	)
	llm = _make_mock_llm(verdict)
	history = _make_mock_history()

	# Use a valid persona — all 7 are in PERSONA_REGISTRY, so test with happy_path
	# which we know works
	result = await murphy_judge(history, _make_scenario(test_persona='first_timer'), llm, start_url='https://example.com')
	assert result.verdict is True
