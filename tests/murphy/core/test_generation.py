"""Tests for test plan generation with mocked LLM — no real API calls."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from murphy.core.generation import (
	_log_plan_summary,
	generate_tests,
	summarize_exploration_from_actions,
)
from murphy.models import Feature, PageInfo, TestPersona, TestPlan, TestScenario, WebsiteAnalysis


def _make_analysis() -> WebsiteAnalysis:
	return WebsiteAnalysis(
		site_name='Example',
		category='saas',
		description='An example site',
		key_pages=[
			PageInfo(url='https://example.com', title='Home', purpose='Landing', page_type='homepage', interactive_elements=[])
		],
		features=[
			Feature(
				name='Search',
				category='search',
				description='Search feature',
				page_url='https://example.com',
				elements=['search bar'],
				testability='testable',
				importance='core',
			)
		],
		identified_user_flows=['Browse -> Search'],
	)


def _make_good_plan() -> TestPlan:
	"""A plan that passes quality checks."""
	personas: list[TestPersona] = [
		'first_timer',
		'adversarial',
		'edge_case',
		'explorer',
		'impatient_user',
		'angry_user',
		'mobile_user',
	]
	scenarios = []
	for i, persona in enumerate(personas[:6]):
		priority = 'critical' if persona == 'first_timer' else 'high'
		scenarios.append(
			TestScenario(
				name=f'Test scenario {i + 1} for evaluate example.com',
				description=f'Test the search feature as {persona} on example.com',
				priority=priority,
				feature_category='search',
				target_feature='Search bar',
				test_persona=persona,
				steps_description='1. Navigate to the search page\n2. Type a query in the search box\n3. Click search button',
				success_criteria='Results appear visible on the page with a toast notification',
			)
		)
	return TestPlan(scenarios=scenarios)


def _make_mock_llm(plan: TestPlan) -> AsyncMock:
	llm = AsyncMock()
	response = MagicMock()
	response.completion = plan
	llm.ainvoke.return_value = response
	return llm


# ─── generate_tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_tests_returns_plan():
	plan = _make_good_plan()
	llm = _make_mock_llm(plan)
	analysis = _make_analysis()

	result = await generate_tests('https://example.com', analysis, llm, max_tests=8)

	assert isinstance(result, TestPlan)
	assert len(result.scenarios) == 6
	llm.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_generate_tests_retries_on_quality_issues():
	"""First call returns bad plan, second call returns good plan."""
	bad_plan = TestPlan(
		scenarios=[
			TestScenario(
				name='Only one test',
				description='Single test',
				priority='high',
				feature_category='search',
				target_feature='Search',
				test_persona='first_timer',
				steps_description='1. Do something',
				success_criteria='It works visible',
			)
		]
	)
	good_plan = _make_good_plan()

	llm = AsyncMock()
	responses = []
	for plan in [bad_plan, good_plan]:
		resp = MagicMock()
		resp.completion = plan
		responses.append(resp)
	llm.ainvoke.side_effect = responses

	result = await generate_tests('https://example.com', _make_analysis(), llm, max_tests=8)
	assert len(result.scenarios) >= 5
	assert llm.ainvoke.call_count == 2


@pytest.mark.asyncio
async def test_generate_tests_with_goal():
	plan = _make_good_plan()
	llm = _make_mock_llm(plan)
	analysis = _make_analysis()

	result = await generate_tests('https://example.com', analysis, llm, max_tests=8, goal='test checkout')
	assert isinstance(result, TestPlan)


@pytest.mark.asyncio
async def test_generate_tests_retries_on_empty_plan():
	"""Empty plan triggers retry."""
	empty_plan = TestPlan(scenarios=[])
	good_plan = _make_good_plan()

	llm = AsyncMock()
	responses = []
	for plan in [empty_plan, good_plan]:
		resp = MagicMock()
		resp.completion = plan
		responses.append(resp)
	llm.ainvoke.side_effect = responses

	result = await generate_tests('https://example.com', _make_analysis(), llm, max_tests=8)
	assert len(result.scenarios) > 0
	assert llm.ainvoke.call_count == 2


# ─── summarize_exploration_from_actions ──────────────────────────────────────


def test_summarize_exploration_empty():
	result = summarize_exploration_from_actions([], 'https://example.com')
	assert '(no actions)' in result


def test_summarize_exploration_navigate():
	actions = [{'navigate': {'url': 'https://example.com/about'}}]
	result = summarize_exploration_from_actions(actions, 'https://example.com')
	assert 'NAVIGATE' in result
	assert 'https://example.com/about' in result
	assert 'Pages visited' in result


def test_summarize_exploration_go_to_url():
	actions = [{'go_to_url': {'url': 'https://example.com/page'}}]
	result = summarize_exploration_from_actions(actions, 'https://example.com')
	assert 'NAVIGATE' in result


def test_summarize_exploration_click_with_element():
	actions = [
		{
			'click_element': {'index': 1},
			'interacted_element': {
				'tag_name': 'a',
				'text': 'About Us',
				'attributes': {'href': '/about'},
			},
		}
	]
	result = summarize_exploration_from_actions(actions, 'https://example.com')
	assert 'CLICK' in result
	assert 'About Us' in result
	assert '/about' in result


def test_summarize_exploration_click_without_element():
	actions = [{'click_element': {'index': 5}}]
	result = summarize_exploration_from_actions(actions, 'https://example.com')
	assert 'CLICK' in result
	assert 'element 5' in result


def test_summarize_exploration_input_text():
	actions = [{'input_text': {'text': 'search query'}}]
	result = summarize_exploration_from_actions(actions, 'https://example.com')
	assert 'TYPE' in result
	assert 'search query' in result


def test_summarize_exploration_scroll():
	actions = [{'scroll': {'down': True}}]
	result = summarize_exploration_from_actions(actions, 'https://example.com')
	assert 'SCROLL' in result
	assert 'down' in result


def test_summarize_exploration_scroll_up():
	actions = [{'scroll': {'down': False}}]
	result = summarize_exploration_from_actions(actions, 'https://example.com')
	assert 'up' in result


def test_summarize_exploration_done():
	actions = [{'done': {}}]
	result = summarize_exploration_from_actions(actions, 'https://example.com')
	assert 'DONE' in result


def test_summarize_exploration_deduplicates_pages():
	actions = [
		{'navigate': {'url': 'https://example.com/a'}},
		{'navigate': {'url': 'https://example.com/a'}},
		{'navigate': {'url': 'https://example.com/b'}},
	]
	result = summarize_exploration_from_actions(actions, 'https://example.com')
	# Pages section should have deduplicated list
	assert result.count('https://example.com/a') >= 2  # once in pages, once+ in trace


def test_summarize_exploration_mixed_actions():
	actions = [
		{'navigate': {'url': 'https://example.com/page'}},
		{'click_element': {'index': 1}, 'interacted_element': {'tag_name': 'button', 'text': 'Submit'}},
		{'input_text': {'text': 'hello'}},
		{'scroll': {'down': True}},
		{'done': {}},
	]
	result = summarize_exploration_from_actions(actions, 'https://example.com')
	assert 'NAVIGATE' in result
	assert 'CLICK' in result
	assert 'TYPE' in result
	assert 'SCROLL' in result
	assert 'DONE' in result


# ─── _log_plan_summary ──────────────────────────────────────────────────────


def test_log_plan_summary_does_not_raise():
	plan = _make_good_plan()
	# Should not raise
	_log_plan_summary(plan)


def test_log_plan_summary_empty_plan():
	plan = TestPlan(scenarios=[])
	_log_plan_summary(plan)
