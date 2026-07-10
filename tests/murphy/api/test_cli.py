"""Tests for Murphy CLI report-writing helpers."""

from pathlib import Path
from unittest.mock import patch

from murphy.api.cli import _write_reports_and_log_results
from murphy.models import TestResult, TestScenario, TokenUsage, WebsiteAnalysis


def _make_analysis() -> WebsiteAnalysis:
	return WebsiteAnalysis(
		site_name='Example',
		category='saas',
		description='An example site',
		key_pages=[],
		features=[],
		identified_user_flows=[],
	)


def _make_result() -> TestResult:
	return TestResult(
		scenario=TestScenario(
			name='Lite agent creation',
			description='Assess the agent creation flow',
			priority='high',
			feature_category='forms',
			target_feature='Agent creation',
			test_persona='confused_novice',
			steps_description='Try to create an agent',
			success_criteria='Return lightweight UX feedback',
		),
		success=True,
		judgement=None,
		actions=[],
		errors=[],
		duration=2.0,
		reason='Lite mode grade: 6',
	)


def test_write_reports_and_log_results_writes_lite_report_and_logs_summary():
	analysis = _make_analysis()
	results = [_make_result()]
	output_dir = Path('/tmp/murphy-test-output')
	tokens = TokenUsage(input_tokens=10, output_tokens=5)

	with (
		patch('murphy.core.summary.write_reports_and_print') as write_reports,
		patch('murphy.api.cli._log_lite_summary') as log_lite_summary,
	):
		_write_reports_and_log_results(
			url='https://example.com',
			analysis=analysis,
			results=results,
			output_dir=output_dir,
			use_lite=True,
			persona_discovery_tokens=None,
			murphy_tokens=tokens,
		)

	write_reports.assert_called_once_with(
		'https://example.com',
		analysis,
		results,
		output_dir,
		persona_discovery_tokens=None,
		murphy_tokens=tokens,
	)
	log_lite_summary.assert_called_once_with(results)
