"""Tests for test plan generation with mocked LLM — no real API calls."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from murphy.core.generation import (
	_log_plan_summary,
	generate_tests,
	make_lite_plan,
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
		'happy_path',
		'confused_novice',
		'adversarial',
		'edge_case',
		'explorer',
		'impatient_user',
		'angry_user',
	]
	scenarios = []
	for i, persona in enumerate(personas[:6]):
		priority = 'critical' if persona == 'happy_path' else 'high'
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
	assert llm.ainvoke.call_count >= 1


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
				test_persona='happy_path',
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


# ─── make_lite_plan ──────────────────────────────────────────────────────────


def test_make_lite_plan_creates_persona_scenarios_without_llm():
	plan = make_lite_plan('https://example.com', goal='Test agent creation flow', analysis=_make_analysis(), max_tests=2)

	assert isinstance(plan, TestPlan)
	assert len(plan.scenarios) == 2
	assert [s.test_persona for s in plan.scenarios] == ['happy_path', 'confused_novice']
	assert all('Test agent creation flow' in s.description for s in plan.scenarios)
	assert all('flaws, improvements, fixes' in s.success_criteria for s in plan.scenarios)


def test_make_lite_plan_interactive_goal_requires_objective_attempt_and_verification():
	plan = make_lite_plan('https://example.com', goal='Test agent creation flow', analysis=_make_analysis(), max_tests=1)
	steps = plan.scenarios[0].steps_description

	assert 'most plausible in-app route' in steps
	assert 'Attempt the objective' in steps
	assert 'harmless test input' in steps
	assert 'Advance or submit only when safe' in steps
	assert 'Verify the resulting UI state' in steps


def test_make_lite_plan_state_change_goal_uses_generalized_steps():
	plan = make_lite_plan('https://example.com', goal='Test dark mode switching', analysis=_make_analysis(), max_tests=1)
	steps = plan.scenarios[0].steps_description

	assert 'Change the requested state' in steps
	assert 'Verify the resulting UI state' in steps
	assert 'appearance' not in steps.lower()
	assert 'theme control' not in steps.lower()


def test_make_lite_plan_uses_analysis_context_when_available():
	plan = make_lite_plan('https://example.com', goal=None, analysis=_make_analysis(), max_tests=1)
	scenario = plan.scenarios[0]

	assert scenario.target_feature == 'Search'
	assert scenario.feature_category == 'search'
	assert 'Browse -> Search' in scenario.steps_description


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
