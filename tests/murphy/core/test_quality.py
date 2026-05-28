"""Tests for test plan quality validation."""

from murphy.core.quality import plan_quality_issues, scenario_quality_issues
from murphy.models import TestPlan, TestScenario


def _make_scenario(**overrides) -> TestScenario:
	defaults = dict(
		name='Happy path login',
		description='Test login with valid credentials',
		priority='critical',
		feature_category='authentication',
		target_feature='Login form',
		test_persona='happy_path',
		steps_description='1. Navigate to login page\n2. Enter valid email\n3. Enter password\n4. Click submit',
		success_criteria='Login succeeds: user is redirected to dashboard and sees confirmation message',
	)
	defaults.update(overrides)
	return TestScenario.model_validate(defaults)


def _make_diverse_plan(n: int = 6) -> TestPlan:
	"""Create a plan that passes all quality checks."""
	scenarios = [
		_make_scenario(name='Happy path login', test_persona='happy_path', priority='critical'),
		_make_scenario(
			name='Confused novice tries login',
			test_persona='confused_novice',
			priority='medium',
			description='Novice submits empty login form',
			steps_description='1. Navigate to login page\n2. Click submit without filling fields',
		),
		_make_scenario(
			name='Adversarial XSS in login',
			test_persona='adversarial',
			priority='high',
			description='Inject XSS payload into login form',
			steps_description='1. Navigate to login page\n2. Type <script>alert(1)</script> in email',
		),
		_make_scenario(
			name='Edge case long input',
			test_persona='edge_case',
			priority='medium',
			description='Submit extremely long input in login field',
			steps_description='1. Navigate to login page\n2. Enter 500 chars in email field',
		),
		_make_scenario(
			name='Explorer unusual nav',
			test_persona='explorer',
			priority='low',
			description='Navigate to login via unusual path',
			steps_description='1. Navigate to footer links\n2. Find login link',
		),
		_make_scenario(
			name='Impatient rapid clicks',
			test_persona='impatient_user',
			priority='medium',
			description='Click login button rapidly',
			steps_description='1. Navigate to login page\n2. Click submit repeatedly',
		),
	]
	return TestPlan(scenarios=scenarios[:n])


# ─── scenario_quality_issues ──────────────────────────────────────────────────


def test_scenario_no_issues():
	s = _make_scenario()
	issues = scenario_quality_issues('test login', s)
	assert issues == []


def test_scenario_insufficient_steps():
	s = _make_scenario(steps_description='Do the thing')
	issues = scenario_quality_issues('test login', s)
	assert any('fewer than 2' in i for i in issues)


def test_scenario_missing_ui_signals():
	s = _make_scenario(success_criteria='It works correctly')
	issues = scenario_quality_issues('test login', s)
	assert any('observable UI signals' in i for i in issues)


def test_scenario_vague_phrasing_outside_novice():
	s = _make_scenario(
		test_persona='happy_path',
		steps_description='1. Click random element\n2. Check results',
	)
	issues = scenario_quality_issues('test login', s)
	assert any('vague' in i for i in issues)


def test_scenario_vague_phrasing_allowed_for_novice():
	s = _make_scenario(
		test_persona='confused_novice',
		steps_description='1. Click random element\n2. Check results',
	)
	issues = scenario_quality_issues('test login', s)
	assert not any('vague' in i for i in issues)


# ─── plan_quality_issues ──────────────────────────────────────────────────────


def test_plan_no_issues():
	plan = _make_diverse_plan()
	issues = plan_quality_issues('test login', plan)
	assert issues == []


def test_plan_too_few_scenarios():
	plan = TestPlan(scenarios=[_make_scenario()])
	issues = plan_quality_issues('test login', plan)
	assert any('minimum 5' in i for i in issues)


def test_plan_missing_critical_happy_path():
	scenarios = [_make_scenario(test_persona='happy_path', priority='medium')]
	plan = TestPlan(scenarios=scenarios)
	issues = plan_quality_issues('test login', plan)
	assert any('critical' in i for i in issues)


def test_plan_missing_trait_coverage():
	# All happy_path — missing low tech_lit, low patience, adversarial, high exploration
	scenarios = [_make_scenario() for _ in range(6)]
	plan = TestPlan(scenarios=scenarios)
	issues = plan_quality_issues('test login', plan)
	assert any('trait coverage' in i.lower() or 'Missing trait' in i for i in issues)


def test_plan_persona_dominance():
	# 5 out of 6 are happy_path — exceeds 40%
	scenarios = [_make_scenario(test_persona='happy_path') for _ in range(5)]
	scenarios.append(_make_scenario(test_persona='adversarial'))
	plan = TestPlan(scenarios=scenarios)
	issues = plan_quality_issues('test login', plan)
	assert any('dominates' in i for i in issues)


def test_plan_unrelated_scenarios():
	# Scenarios with no keyword overlap with task
	scenarios = [
		_make_scenario(
			name=f'Xyz scenario {i}',
			description='Something completely unrelated to task',
			test_persona='happy_path' if i == 0 else 'adversarial',
			priority='critical' if i == 0 else 'high',
		)
		for i in range(6)
	]
	plan = TestPlan(scenarios=scenarios)
	issues = plan_quality_issues('test login', plan)
	assert any('unrelated' in i for i in issues)
