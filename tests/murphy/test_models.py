"""Tests for murphy pydantic models."""

import pytest
from pydantic import ValidationError

from murphy.models import (
	PERSONA_REGISTRY,
	EvaluationReport,
	ExecutiveSummary,
	Feature,
	FeedbackQualityScore,
	InteractiveElement,
	JudgeVerdict,
	PageInfo,
	ReportSummary,
	ScenarioExecutionVerdict,
	TestPlan,
	TestResult,
	TestScenario,
	TraitLevel,
	TraitVector,
	WebsiteAnalysis,
)

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_scenario(**overrides) -> TestScenario:
	defaults = dict(
		name='Login flow',
		description='Test the login flow end-to-end',
		priority='high',
		feature_category='authentication',
		target_feature='Login form',
		test_persona='first_timer',
		steps_description='1. Open login page\n2. Enter credentials\n3. Click submit',
		success_criteria='User is logged in',
	)
	defaults.update(overrides)
	return TestScenario.model_validate(defaults)


def _make_verdict(**overrides) -> JudgeVerdict:
	defaults = dict(
		reasoning='All steps completed',
		verdict=True,
		failure_reason='',
		impossible_task=False,
		reached_captcha=False,
		failure_category=None,
	)
	defaults.update(overrides)
	return JudgeVerdict.model_validate(defaults)


def _make_result(**overrides) -> TestResult:
	defaults = dict(
		scenario=_make_scenario(),
		success=True,
		judgement=_make_verdict(),
		actions=[],
		errors=[],
		duration=1.5,
	)
	defaults.update(overrides)
	return TestResult.model_validate(defaults)


def _make_analysis(**overrides) -> WebsiteAnalysis:
	defaults = dict(
		site_name='Test Site',
		category='saas',
		description='A test site',
		key_pages=[
			PageInfo(
				url='https://example.com',
				title='Home',
				purpose='Landing page',
				page_type='homepage',
				interactive_elements=[],
			)
		],
		features=[
			Feature(
				name='Search',
				category='search',
				description='Search the site',
				page_url='https://example.com/search',
				elements=['search bar'],
				testability='testable',
				importance='core',
			)
		],
		identified_user_flows=['Browse → Search → View details'],
	)
	defaults.update(overrides)
	return WebsiteAnalysis.model_validate(defaults)


# ─── TraitVector ──────────────────────────────────────────────────────────────


def test_trait_vector_defaults():
	tv = TraitVector()
	assert tv.technical_literacy == TraitLevel.medium
	assert tv.patience == TraitLevel.medium
	assert tv.intent == 'benign'


def test_trait_vector_frozen():
	tv = TraitVector()
	with pytest.raises(ValidationError):
		tv.technical_literacy = TraitLevel.high


def test_trait_vector_extra_forbidden():
	with pytest.raises(ValidationError):
		TraitVector(speed='fast')  # type: ignore[call-arg]


# ─── PERSONA_REGISTRY ────────────────────────────────────────────────────────


def test_persona_registry_completeness():
	expected_personas = {'first_timer', 'adversarial', 'edge_case', 'explorer', 'impatient_user', 'angry_user', 'boomer_ui', 'genz_ui', 'whitespace_police_ui', 'mobile_user'}
	assert set(PERSONA_REGISTRY.keys()) == expected_personas


def test_persona_registry_values_are_trait_vector_and_test_type():
	for persona, (traits, test_type) in PERSONA_REGISTRY.items():
		assert isinstance(traits, TraitVector), f'{persona} traits not TraitVector'
		assert test_type in ('ux', 'security', 'boundary', 'design'), f'{persona} test_type invalid: {test_type}'


# ─── ScenarioExecutionVerdict ─────────────────────────────────────────────────


def test_scenario_execution_verdict_defaults():
	v = ScenarioExecutionVerdict(success=True)
	assert v.success is True
	assert v.reason == ''
	assert v.process_evaluation == ''
	assert v.logical_evaluation == ''
	assert v.usability_evaluation == ''
	assert v.validation_evidence == ''


def test_scenario_execution_verdict_with_fields():
	v = ScenarioExecutionVerdict(
		success=False,
		reason='Button not clickable',
		process_evaluation='Steps followed correctly',
		logical_evaluation='UI logic broken',
		usability_evaluation='Poor affordance on submit button',
	)
	assert v.success is False
	assert 'Button' in v.reason


# ─── TestScenario ─────────────────────────────────────────────────────────────


def test_test_scenario_name_truncation():
	long_name = 'A' * 150
	s = _make_scenario(name=long_name)
	assert len(s.name) == 100


def test_test_scenario_rejects_empty_description():
	with pytest.raises(ValidationError):
		_make_scenario(description='')


def test_test_scenario_rejects_empty_steps():
	with pytest.raises(ValidationError):
		_make_scenario(steps_description='')


def test_test_scenario_rejects_empty_criteria():
	with pytest.raises(ValidationError):
		_make_scenario(success_criteria='')


def test_test_scenario_rejects_invalid_priority():
	with pytest.raises(ValidationError):
		_make_scenario(priority='urgent')


def test_test_scenario_rejects_invalid_persona():
	with pytest.raises(ValidationError):
		_make_scenario(test_persona='robot')


def test_test_scenario_rejects_invalid_category():
	with pytest.raises(ValidationError):
		_make_scenario(feature_category='blockchain')


# ─── TestPlan ─────────────────────────────────────────────────────────────────


def test_test_plan_empty_scenarios():
	plan = TestPlan(scenarios=[])
	assert plan.scenarios == []


def test_test_plan_with_scenarios():
	plan = TestPlan(scenarios=[_make_scenario(), _make_scenario(name='Second test')])
	assert len(plan.scenarios) == 2


# ─── JudgeVerdict ─────────────────────────────────────────────────────────────


def test_judge_verdict_failure_categories():
	v = _make_verdict(verdict=False, failure_category='website_issue')
	assert v.failure_category == 'website_issue'

	v2 = _make_verdict(verdict=False, failure_category='test_limitation')
	assert v2.failure_category == 'test_limitation'


def test_judge_verdict_with_feedback_quality():
	fq = FeedbackQualityScore(
		response_present=True,
		response_timely=True,
		response_clear=False,
		response_actionable=False,
		feedback_type='toast_notification',
	)
	v = _make_verdict(feedback_quality=fq)
	assert v.feedback_quality is not None
	assert v.feedback_quality.feedback_type == 'toast_notification'


def test_judge_verdict_with_trait_evaluations():
	v = _make_verdict(trait_evaluations={'patience': 'Good', 'exploration': 'Poor'})
	assert v.trait_evaluations is not None
	assert len(v.trait_evaluations) == 2


# ─── TestResult ───────────────────────────────────────────────────────────────


def test_test_result_has_evaluation_fields():
	r = _make_result(
		reason='All steps completed',
		process_evaluation='Clean execution',
		logical_evaluation='Logic sound',
		usability_evaluation='Good UX',
		pages_visited=['https://example.com', 'https://example.com/login'],
	)
	assert r.success is True
	assert r.reason == 'All steps completed'
	assert len(r.pages_visited) == 2
	assert r.judgement is not None
	assert r.judgement.verdict is True


def test_test_result_defaults():
	r = _make_result()
	assert r.failure_category is None
	assert r.pages_visited == []
	assert r.screenshot_paths == []
	assert r.form_fills == []
	assert r.process_evaluation == ''
	assert r.feedback_quality is None


def test_test_result_nullable_success():
	"""success=None represents a crashed test."""
	r = _make_result(success=None, judgement=None)
	assert r.success is None


# ─── WebsiteAnalysis ─────────────────────────────────────────────────────────


def test_website_analysis_normalizes_unknown_category():
	a = _make_analysis(category='unknown')
	assert a.category == 'uncategorized'


def test_website_analysis_normalizes_na_category():
	a = _make_analysis(category='n/a')
	assert a.category == 'uncategorized'


def test_website_analysis_keeps_valid_category():
	a = _make_analysis(category='ecommerce')
	assert a.category == 'ecommerce'


def test_website_analysis_rejects_empty_category():
	with pytest.raises(ValidationError):
		_make_analysis(category='')


# ─── InteractiveElement ──────────────────────────────────────────────────────


def test_interactive_element_valid():
	el = InteractiveElement(element_type='button', label='Submit')
	assert el.element_type == 'button'
	assert el.destination is None


def test_interactive_element_rejects_invalid_type():
	with pytest.raises(ValidationError):
		InteractiveElement(element_type='widget', label='Submit')  # type: ignore[arg-type]


# ─── FeedbackQualityScore ────────────────────────────────────────────────────


def test_feedback_quality_score_valid_types():
	valid_types = [
		'none',
		'silent_handling',
		'visual_state_change',
		'inline_message',
		'toast_notification',
		'modal_dialog',
		'page_redirect',
		'error_page',
	]
	for ft in valid_types:
		fq = FeedbackQualityScore(
			response_present=True,
			response_timely=True,
			response_clear=True,
			response_actionable=True,
			feedback_type=ft,  # type: ignore[arg-type]
		)
		assert fq.feedback_type == ft


def test_feedback_quality_score_rejects_invalid_type():
	with pytest.raises(ValidationError):
		FeedbackQualityScore(
			response_present=True,
			response_timely=True,
			response_clear=True,
			response_actionable=True,
			feedback_type='popup',  # type: ignore[arg-type]
		)


# ─── ReportSummary ───────────────────────────────────────────────────────────


def test_report_summary():
	s = ReportSummary(
		total=10,
		passed=7,
		failed=3,
		pass_rate=70.0,
		website_issues=2,
		test_limitations=1,
		by_priority={'high': {'passed': 5, 'failed': 1}, 'medium': {'passed': 2, 'failed': 2}},
	)
	assert s.total == 10
	assert s.pass_rate == 70.0


# ─── ExecutiveSummary ────────────────────────────────────────────────────────


def test_executive_summary():
	es = ExecutiveSummary(
		overall_assessment='Site has good core functionality.',
		key_findings=['Login works', 'Search is broken'],
		recommended_actions=['Fix search', 'Add error handling'],
	)
	assert len(es.key_findings) == 2
	assert len(es.recommended_actions) == 2


# ─── EvaluationReport ────────────────────────────────────────────────────────


def test_evaluation_report_construction():
	report = EvaluationReport(
		url='https://example.com',
		timestamp='2025-01-01T00:00:00Z',
		analysis=_make_analysis(),
		results=[_make_result()],
		summary=ReportSummary(
			total=1,
			passed=1,
			failed=0,
			pass_rate=100.0,
			by_priority={'high': {'passed': 1, 'failed': 0}},
		),
	)
	assert report.url == 'https://example.com'
	assert len(report.results) == 1
	assert report.executive_summary is None
