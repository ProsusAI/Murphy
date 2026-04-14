"""Tests for write_full_report orchestration."""

import tempfile
from pathlib import Path

from murphy.io.report import write_full_report
from murphy.models import (
	ExecutiveSummary,
	Feature,
	JudgeVerdict,
	PageInfo,
	TestResult,
	TestScenario,
	WebsiteAnalysis,
)


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


# ─── write_full_report ────────────────────────────────────────────────────────


def test_write_full_report_creates_both_files():
	analysis = _make_analysis()
	results = [_make_result()]

	with tempfile.TemporaryDirectory() as tmpdir:
		json_path, md_path = write_full_report('https://example.com', analysis, results, Path(tmpdir))
		assert json_path.exists()
		assert md_path.exists()
		assert json_path.name == 'evaluation_report.json'
		assert md_path.name == 'evaluation_report.md'


def test_write_full_report_with_executive_summary():
	analysis = _make_analysis()
	results = [_make_result()]
	es = ExecutiveSummary(
		overall_assessment='Good site.',
		key_findings=['Search works'],
		recommended_actions=['Keep it up'],
	)

	with tempfile.TemporaryDirectory() as tmpdir:
		json_path, md_path = write_full_report('https://example.com', analysis, results, Path(tmpdir), executive_summary=es)
		md_content = md_path.read_text()
		assert 'Executive Summary' in md_content
		assert 'Good site' in md_content


def test_write_full_report_computes_summary():
	"""Summary is auto-computed from results."""
	analysis = _make_analysis()
	results = [
		_make_result(success=True),
		_make_result(
			success=False,
			judgement=_make_verdict(verdict=False, failure_category='website_issue'),
			failure_category='website_issue',
		),
	]

	with tempfile.TemporaryDirectory() as tmpdir:
		json_path, _ = write_full_report('https://example.com', analysis, results, Path(tmpdir))
		import json

		report_data = json.loads(json_path.read_text())
		assert report_data['summary']['total'] == 2
		assert report_data['summary']['passed'] == 1
		assert report_data['summary']['failed'] == 1


def test_write_full_report_multiple_results():
	analysis = _make_analysis()
	results = [_make_result() for _ in range(5)]

	with tempfile.TemporaryDirectory() as tmpdir:
		json_path, md_path = write_full_report('https://example.com', analysis, results, Path(tmpdir))
		md_content = md_path.read_text()
		assert '100.0%' in md_content  # 5/5 passed
