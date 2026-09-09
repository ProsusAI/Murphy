"""Tests for summary building and failure classification."""

from murphy.core.summary import build_summary, classify_failure
from murphy.models import JudgeVerdict, LiteResult, TestResult, TestScenario


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


def _make_verdict(**overrides) -> JudgeVerdict:
	defaults = dict(
		reasoning='Done',
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
		duration=2.0,
	)
	defaults.update(overrides)
	return TestResult.model_validate(defaults)


# ─── classify_failure ─────────────────────────────────────────────────────────


def test_classify_failure_passed():
	r = _make_result(success=True)
	assert classify_failure(r) is None


def test_classify_failure_website_issue():
	v = _make_verdict(verdict=False, failure_category='website_issue')
	r = _make_result(success=False, judgement=v)
	assert classify_failure(r) == 'website_issue'


def test_classify_failure_test_limitation():
	v = _make_verdict(verdict=False, failure_category='test_limitation')
	r = _make_result(success=False, judgement=v)
	assert classify_failure(r) == 'test_limitation'


def test_classify_failure_crashed_no_judgement():
	r = _make_result(success=None, judgement=None)
	assert classify_failure(r) == 'test_limitation'


def test_classify_failure_failed_no_judgement():
	r = _make_result(success=False, judgement=None)
	assert classify_failure(r) == 'test_limitation'


def test_classify_failure_failed_lite_result_is_plain_failure():
	lite_result = LiteResult(
		grade=4,
		flaws=['The create flow is hard to find'],
		improvements=['Expose a clearer create action'],
		fixes=['Add a primary Create Agent button'],
		other_feedback=[],
	)
	r = _make_result(success=False, judgement=None, lite_result=lite_result)
	assert classify_failure(r) is None


def test_classify_failure_lite_browser_corruption_is_test_limitation():
	lite_result = LiteResult(grade=2, flaws=['The browser stopped responding.'])
	r = _make_result(
		success=False,
		judgement=None,
		lite_result=lite_result,
		errors=['Cannot execute click: browser session is corrupted (target_id=None).'],
	)

	assert classify_failure(r) == 'test_limitation'


# ─── build_summary ────────────────────────────────────────────────────────────


def test_build_summary_all_passed():
	results = [_make_result() for _ in range(3)]
	s = build_summary(results)
	assert s.total == 3
	assert s.passed == 3
	assert s.failed == 0
	assert s.pass_rate == 100.0


def test_build_summary_mixed():
	results = [
		_make_result(success=True, scenario=_make_scenario(priority='critical')),
		_make_result(success=False, scenario=_make_scenario(priority='high'), failure_category='website_issue'),
		_make_result(success=False, scenario=_make_scenario(priority='medium'), failure_category='test_limitation'),
	]
	s = build_summary(results)
	assert s.total == 3
	assert s.passed == 1
	assert s.failed == 2
	assert s.pass_rate == 33.3
	assert s.website_issues == 1
	assert s.test_limitations == 1


def test_build_summary_by_priority():
	results = [
		_make_result(success=True, scenario=_make_scenario(priority='critical')),
		_make_result(success=False, scenario=_make_scenario(priority='critical')),
		_make_result(success=True, scenario=_make_scenario(priority='low')),
	]
	s = build_summary(results)
	assert s.by_priority['critical'] == {'passed': 1, 'failed': 1}
	assert s.by_priority['low'] == {'passed': 1, 'failed': 0}


def test_build_summary_empty():
	s = build_summary([])
	assert s.total == 0
	assert s.passed == 0
	assert s.pass_rate == 0.0


def test_build_summary_crashed_counts_as_failed():
	results = [_make_result(success=None)]
	s = build_summary(results)
	assert s.passed == 0
	assert s.failed == 1
