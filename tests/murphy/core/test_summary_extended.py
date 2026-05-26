"""Extended tests for summary — generate_executive_summary and write_reports_and_print with mocks."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from murphy.core.summary import generate_executive_summary, write_reports_and_print
from murphy.models import (
	ExecutiveSummary,
	Feature,
	JudgeVerdict,
	LiteResult,
	PageInfo,
	ReportSummary,
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


# ─── generate_executive_summary ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_executive_summary():
	exec_summary = ExecutiveSummary(
		overall_assessment='Good site overall.',
		key_findings=['Search works well', 'Login is smooth'],
		recommended_actions=['Improve error messages'],
	)
	llm = AsyncMock()
	response = MagicMock()
	response.completion = exec_summary
	llm.ainvoke.return_value = response

	analysis = _make_analysis()
	results = [_make_result()]
	summary = ReportSummary(total=1, passed=1, failed=0, pass_rate=100.0, by_priority={'high': {'passed': 1, 'failed': 0}})

	result = await generate_executive_summary('https://example.com', analysis, results, summary, llm)

	assert isinstance(result, ExecutiveSummary)
	assert result.overall_assessment == 'Good site overall.'
	assert len(result.key_findings) == 2
	llm.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_generate_executive_summary_with_failures():
	exec_summary = ExecutiveSummary(
		overall_assessment='Some issues found.',
		key_findings=['Search broken'],
		recommended_actions=['Fix search'],
	)
	llm = AsyncMock()
	response = MagicMock()
	response.completion = exec_summary
	llm.ainvoke.return_value = response

	analysis = _make_analysis()
	failed_verdict = _make_verdict(verdict=False, failure_category='website_issue', failure_reason='Search broken')
	results = [
		_make_result(),
		_make_result(success=False, judgement=failed_verdict, failure_category='website_issue', reason='Search broken'),
	]
	summary = ReportSummary(
		total=2,
		passed=1,
		failed=1,
		pass_rate=50.0,
		website_issues=1,
		by_priority={'high': {'passed': 1, 'failed': 1}},
	)

	result = await generate_executive_summary('https://example.com', analysis, results, summary, llm)
	assert isinstance(result, ExecutiveSummary)


@pytest.mark.asyncio
async def test_generate_executive_summary_with_trait_and_feedback():
	"""Trait evaluations and feedback quality are included in the prompt."""
	from murphy.models import FeedbackQualityScore

	exec_summary = ExecutiveSummary(
		overall_assessment='Feedback quality varies.',
		key_findings=['Some tests lack actionable feedback'],
		recommended_actions=['Add toast notifications'],
	)
	llm = AsyncMock()
	response = MagicMock()
	response.completion = exec_summary
	llm.ainvoke.return_value = response

	fq = FeedbackQualityScore(
		response_present=True,
		response_timely=False,
		response_clear=True,
		response_actionable=False,
		feedback_type='inline_message',
	)
	results = [
		_make_result(
			feedback_quality=fq,
			trait_evaluations={'technical_literacy': 'pass'},
		)
	]
	analysis = _make_analysis()
	summary = ReportSummary(total=1, passed=1, failed=0, pass_rate=100.0, by_priority={})

	result = await generate_executive_summary('https://example.com', analysis, results, summary, llm)
	assert isinstance(result, ExecutiveSummary)

	# Verify prompt included feedback and trait info
	call_args = llm.ainvoke.call_args
	messages = call_args.kwargs.get('messages') or call_args[0][0]
	prompt_text = messages[1].content
	assert 'Feedback' in prompt_text
	assert 'Trait evals' in prompt_text


# ─── write_reports_and_print ─────────────────────────────────────────────────


def test_write_reports_and_print():
	analysis = _make_analysis()
	results = [_make_result()]

	with tempfile.TemporaryDirectory() as tmpdir:
		output_dir = Path(tmpdir)
		write_reports_and_print('https://example.com', analysis, results, output_dir)

		json_path = output_dir / 'evaluation_report.json'
		md_path = output_dir / 'evaluation_report.md'
		assert json_path.exists()
		assert md_path.exists()


def test_write_reports_and_print_preserves_lite_result_details():
	analysis = _make_analysis()
	lite_result = LiteResult(
		grade=6,
		flaws=['Unclear first step'],
		improvements=['Clarify the first step'],
		fixes=['Add helper text beside the first field'],
		other_feedback=['The rest of the flow is understandable'],
	)
	results = [
		_make_result(
			judgement=None,
			lite_result=lite_result,
			reason='Lite mode grade: 6',
		)
	]

	with tempfile.TemporaryDirectory() as tmpdir:
		output_dir = Path(tmpdir)
		write_reports_and_print('https://example.com', analysis, results, output_dir)

		json_path = output_dir / 'evaluation_report.json'
		md_path = output_dir / 'evaluation_report.md'
		assert json_path.exists()
		assert md_path.exists()

		json_content = json.loads(json_path.read_text())
		assert json_content['results'][0]['lite_result']['grade'] == 6
		md_content = md_path.read_text()
		assert '**Grade:** 6/10' in md_content
		assert '- Unclear first step' in md_content
		assert '- Clarify the first step' in md_content
		assert '- Add helper text beside the first field' in md_content


def test_write_reports_and_print_with_executive_summary():
	analysis = _make_analysis()
	results = [_make_result()]
	es = ExecutiveSummary(
		overall_assessment='Good.',
		key_findings=['All tests passed'],
		recommended_actions=['Keep it up'],
	)

	with tempfile.TemporaryDirectory() as tmpdir:
		output_dir = Path(tmpdir)
		write_reports_and_print('https://example.com', analysis, results, output_dir, executive_summary=es)

		md_content = (output_dir / 'evaluation_report.md').read_text()
		assert 'Executive Summary' in md_content
