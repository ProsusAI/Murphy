"""Tests for prompt construction functions."""

from murphy.models import Feature, PageInfo, TestScenario, WebsiteAnalysis
from murphy.prompts import (
	_build_persona_distribution_text,
	_render_persona_for_execution,
	build_analysis_prompt,
	build_execution_prompt,
	build_exploration_prompt,
	build_lite_prompt,
	build_plan_synthesis_prompt,
	build_test_generation_prompt,
	build_test_generation_system_message,
)


def _make_analysis() -> WebsiteAnalysis:
	return WebsiteAnalysis(
		site_name='Acme',
		category='saas',
		description='A SaaS tool',
		key_pages=[
			PageInfo(url='https://acme.com', title='Home', purpose='Landing', page_type='homepage', interactive_elements=[])
		],
		features=[
			Feature(
				name='Search',
				category='search',
				description='Search',
				page_url='https://acme.com',
				elements=['search bar'],
				testability='testable',
				importance='core',
			),
			Feature(
				name='Export',
				category='media',
				description='Export',
				page_url='https://acme.com',
				elements=['button'],
				testability='untestable',
				importance='peripheral',
			),
		],
		identified_user_flows=['Search -> View'],
	)


def _make_scenario(**overrides) -> TestScenario:
	defaults = dict(
		name='Test search',
		description='Test the search feature',
		priority='high',
		feature_category='search',
		target_feature='Search bar',
		test_persona='happy_path',
		steps_description='1. Click search\n2. Type query',
		success_criteria='Results appear',
	)
	defaults.update(overrides)
	return TestScenario.model_validate(defaults)


# ─── build_analysis_prompt ────────────────────────────────────────────────────


def test_analysis_prompt_unauthenticated():
	prompt = build_analysis_prompt('https://example.com')
	assert 'Navigate to https://example.com' in prompt
	assert 'unauthenticated' in prompt


def test_analysis_prompt_authenticated():
	prompt = build_analysis_prompt('https://example.com', is_authenticated=True)
	assert 'already logged in' in prompt
	assert 'authenticated browser' in prompt


def test_analysis_prompt_with_category():
	prompt = build_analysis_prompt('https://example.com', category='ecommerce')
	assert 'ecommerce' in prompt


def test_analysis_prompt_with_goal():
	prompt = build_analysis_prompt('https://example.com', goal='check login')
	assert 'check login' in prompt
	assert 'GOAL' in prompt


# ─── build_test_generation_prompt ─────────────────────────────────────────────


def test_test_generation_prompt_includes_analysis():
	analysis = _make_analysis()
	prompt = build_test_generation_prompt('https://acme.com', analysis, max_tests=8)
	assert 'Search' in prompt
	assert 'SKIP "untestable"' in prompt


def test_test_generation_prompt_with_goal():
	analysis = _make_analysis()
	prompt = build_test_generation_prompt('https://acme.com', analysis, max_tests=8, goal='test search')
	assert 'test search' in prompt
	assert 'GOAL' in prompt


def test_test_generation_prompt_feature_counts():
	analysis = _make_analysis()
	prompt = build_test_generation_prompt('https://acme.com', analysis, max_tests=8)
	assert 'Core (1)' in prompt
	assert 'Untestable (SKIP): Export' in prompt


# ─── build_test_generation_system_message ─────────────────────────────────────


def test_system_message_is_nonempty():
	msg = build_test_generation_system_message()
	assert len(msg) > 50
	assert 'QA' in msg


# ─── build_exploration_prompt ─────────────────────────────────────────────────


def test_exploration_prompt():
	prompt = build_exploration_prompt('check login', 'https://example.com')
	assert 'check login' in prompt
	assert 'https://example.com' in prompt
	assert 'READ-ONLY' in prompt


# ─── build_plan_synthesis_prompt ──────────────────────────────────────────────


def test_plan_synthesis_prompt():
	prompt = build_plan_synthesis_prompt('test login', 'https://example.com', 'Explored 3 pages', max_scenarios=8)
	assert 'test login' in prompt
	assert 'Explored 3 pages' in prompt
	assert '8' in prompt


# ─── build_execution_prompt ───────────────────────────────────────────────────


def test_execution_prompt_basic():
	scenario = _make_scenario()
	prompt = build_execution_prompt('evaluate site', scenario, 'https://example.com')
	assert 'Test search' in prompt
	assert 'happy_path' in prompt
	assert 'VALIDATION RULES' in prompt


def test_execution_prompt_with_files():
	scenario = _make_scenario()
	prompt = build_execution_prompt('evaluate site', scenario, 'https://example.com', available_file_paths=['/tmp/dummy.pdf'])
	assert 'FILE UPLOAD' in prompt
	assert '/tmp/dummy.pdf' in prompt


def test_execution_prompt_without_files():
	scenario = _make_scenario()
	prompt = build_execution_prompt('evaluate site', scenario, 'https://example.com')
	assert 'FILE UPLOAD' not in prompt


def test_execution_prompt_adversarial_persona():
	scenario = _make_scenario(test_persona='adversarial')
	prompt = build_execution_prompt('evaluate site', scenario, 'https://example.com')
	assert 'adversarial' in prompt
	assert 'XSS' in prompt


def test_execution_prompt_confused_novice_persona():
	scenario = _make_scenario(test_persona='confused_novice')
	prompt = build_execution_prompt('evaluate site', scenario, 'https://example.com')
	assert 'confused_novice' in prompt


# ─── build_lite_prompt ───────────────────────────────────────────────────────


def test_lite_prompt_requests_structured_lite_fields():
	scenario = _make_scenario(test_persona='happy_path')
	prompt = build_lite_prompt(scenario, 'https://example.com', analysis=_make_analysis())

	assert 'LiteResult' in prompt
	assert 'flaws' in prompt
	assert 'improvements' in prompt
	assert 'fixes' in prompt
	assert 'other_feedback' in prompt
	assert 'SKIP' not in prompt


def test_lite_prompt_reuses_persona_context():
	scenario = _make_scenario(test_persona='confused_novice')
	prompt = build_lite_prompt(scenario, 'https://example.com')

	assert 'confused_novice' in prompt
	assert 'first-time user' in prompt
	assert 'Stay on the same domain' in prompt


# ─── _build_persona_distribution_text ─────────────────────────────────────────


def test_persona_distribution_text_all_personas():
	text = _build_persona_distribution_text()
	for persona in ['happy_path', 'confused_novice', 'adversarial', 'edge_case', 'explorer', 'impatient_user', 'angry_user']:
		assert persona in text


def test_persona_distribution_text_includes_traits():
	text = _build_persona_distribution_text()
	assert 'tech_lit=' in text
	assert 'patience=' in text


# ─── _render_persona_for_execution ────────────────────────────────────────────


def test_render_all_personas():
	for persona in ['happy_path', 'confused_novice', 'adversarial', 'edge_case', 'explorer', 'impatient_user', 'angry_user']:
		rendered = _render_persona_for_execution(persona)  # type: ignore[arg-type]
		assert persona in rendered
		assert 'Trait profile' in rendered
