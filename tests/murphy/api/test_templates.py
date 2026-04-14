"""Tests for HTML template rendering."""

from murphy.api.templates import (
	_PERSONA_LABELS,
	_e,
	_format_action_html,
	_render_features_summary_html,
	render_plan_html,
	render_results_html,
)
from murphy.models import (
	Feature,
	JudgeVerdict,
	PageInfo,
	TestPlan,
	TestResult,
	TestScenario,
	WebsiteAnalysis,
)


def _make_analysis(**overrides) -> WebsiteAnalysis:
	defaults = dict(
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
	defaults.update(overrides)
	return WebsiteAnalysis.model_validate(defaults)


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


def _make_result(**overrides) -> TestResult:
	defaults = dict(
		scenario=_make_scenario(),
		success=True,
		judgement=None,
		actions=[],
		errors=[],
		duration=5.0,
	)
	defaults.update(overrides)
	return TestResult.model_validate(defaults)


# ─── _e (HTML escape) ────────────────────────────────────────────────────────


def test_html_escape():
	assert _e('<script>alert("xss")</script>') == '&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;'


def test_html_escape_ampersand():
	assert _e('a & b') == 'a &amp; b'


# ─── _format_action_html ─────────────────────────────────────────────────────


def test_format_action_html_navigate():
	html = _format_action_html({'navigate': {'url': 'https://example.com'}})
	assert 'navigate' in html
	assert 'https://example.com' in html


def test_format_action_html_click_with_element():
	html = _format_action_html(
		{
			'click': {'index': 1},
			'interacted_element': {'tag_name': 'button', 'ax_name': 'Submit'},
		}
	)
	assert 'click' in html
	assert 'Submit' in html
	assert 'button' in html


def test_format_action_html_non_dict():
	html = _format_action_html('plain string')
	assert 'plain string' in html


def test_format_action_html_long_value_truncated():
	html = _format_action_html({'input_text': {'text': 'x' * 200}})
	assert 'show more' in html


def test_format_action_html_escapes_xss():
	html = _format_action_html({'navigate': {'url': '<script>alert(1)</script>'}})
	assert '<script>' not in html
	assert '&lt;script&gt;' in html


# ─── _render_features_summary_html ───────────────────────────────────────────


def test_render_features_summary_empty():
	analysis = _make_analysis(features=[])
	assert _render_features_summary_html(analysis) == ''


def test_render_features_summary_has_content():
	analysis = _make_analysis()
	html = _render_features_summary_html(analysis)
	assert 'Features Discovered' in html
	assert 'Search' in html
	assert 'testable' in html


# ─── render_plan_html ────────────────────────────────────────────────────────


def test_render_plan_html_basic():
	analysis = _make_analysis()
	plan = TestPlan(scenarios=[_make_scenario()])
	html = render_plan_html('https://example.com', analysis, plan)
	assert '<!DOCTYPE html>' in html
	assert 'Test Plan Review' in html
	assert 'Test search' in html
	assert 'Run Tests' in html


def test_render_plan_html_groups_by_persona():
	analysis = _make_analysis()
	plan = TestPlan(
		scenarios=[
			_make_scenario(name='Test A', test_persona='first_timer'),
			_make_scenario(name='Test B', test_persona='adversarial'),
		]
	)
	html = render_plan_html('https://example.com', analysis, plan)
	assert 'First Timer' in html
	assert 'Adversarial' in html


# ─── render_results_html ─────────────────────────────────────────────────────


def test_render_results_html_basic():
	analysis = _make_analysis()
	results = [_make_result()]
	html = render_results_html('https://example.com', analysis, results, None)
	assert '<!DOCTYPE html>' in html
	assert 'Murphy — Results' in html
	assert 'PASS' in html


def test_render_results_html_with_failure():
	analysis = _make_analysis()
	verdict = JudgeVerdict(
		reasoning='Failed',
		verdict=False,
		failure_reason='Search broke',
		impossible_task=False,
		reached_captcha=False,
		failure_category='website_issue',
	)
	results = [_make_result(success=False, judgement=verdict, failure_category='website_issue')]
	html = render_results_html('https://example.com', analysis, results, None)
	assert 'WEBSITE ISSUE' in html
	assert 'Website Issue' in html


def test_render_results_html_escapes_xss():
	analysis = _make_analysis(site_name='<script>alert(1)</script>')
	results = [_make_result()]
	html = render_results_html('https://example.com', analysis, results, None)
	assert '<script>alert(1)</script>' not in html
	assert '&lt;script&gt;' in html


def test_render_results_html_persona_stats():
	analysis = _make_analysis()
	results = [
		_make_result(scenario=_make_scenario(test_persona='first_timer'), success=True),
		_make_result(scenario=_make_scenario(test_persona='adversarial'), success=False, failure_category='website_issue'),
	]
	html = render_results_html('https://example.com', analysis, results, None)
	assert 'By Persona' in html


# ─── _PERSONA_LABELS ─────────────────────────────────────────────────────────


def test_persona_labels_completeness():
	expected = ['first_timer', 'adversarial', 'edge_case', 'explorer', 'impatient_user', 'angry_user', 'mobile_user']
	for persona in expected:
		assert persona in _PERSONA_LABELS
