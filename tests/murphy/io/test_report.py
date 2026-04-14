"""Tests for report generation — markdown output, action metrics, and screenshot copying."""

import tempfile
from pathlib import Path

from murphy.io.report import (
	ActionMetrics,
	_compute_metrics,
	_form_field_label,
	_format_metrics_line,
	_slugify,
	copy_screenshots_to_output,
	format_path,
	suggest_fix,
	write_json_report,
	write_markdown_report,
)
from murphy.models import (
	EvaluationReport,
	Feature,
	FeedbackQualityScore,
	JudgeVerdict,
	PageInfo,
	ReportSummary,
	TestResult,
	TestScenario,
	WebsiteAnalysis,
)

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_scenario(**overrides) -> TestScenario:
	defaults = dict(
		name='Test search',
		description='Test the search feature',
		priority='high',
		feature_category='search',
		target_feature='Search bar',
		test_persona='first_timer',
		steps_description='1. Click search\n2. Type query\n3. Check results',
		success_criteria='Results appear',
	)
	defaults.update(overrides)
	return TestScenario.model_validate(defaults)


def _make_verdict(**overrides) -> JudgeVerdict:
	defaults = dict(
		reasoning='Steps completed',
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
		duration=5.0,
	)
	defaults.update(overrides)
	return TestResult.model_validate(defaults)


def _make_report(**overrides) -> EvaluationReport:
	defaults = dict(
		url='https://example.com',
		timestamp='2025-01-01T00:00:00Z',
		analysis=WebsiteAnalysis(
			site_name='Example',
			category='saas',
			description='An example site',
			key_pages=[
				PageInfo(
					url='https://example.com', title='Home', purpose='Landing', page_type='homepage', interactive_elements=[]
				)
			],
			features=[
				Feature(
					name='Search',
					category='search',
					description='Search',
					page_url='https://example.com',
					elements=['search bar'],
					testability='testable',
					importance='core',
				)
			],
			identified_user_flows=['Browse -> Search'],
		),
		results=[_make_result()],
		summary=ReportSummary(total=1, passed=1, failed=0, pass_rate=100.0, by_priority={'high': {'passed': 1, 'failed': 0}}),
	)
	defaults.update(overrides)
	return EvaluationReport.model_validate(defaults)


# ─── _slugify ─────────────────────────────────────────────────────────────────


def test_slugify_basic():
	assert _slugify('Hello World') == 'hello_world'


def test_slugify_truncates_long_names():
	result = _slugify('A' * 100)
	assert len(result) <= 50


def test_slugify_removes_apostrophes():
	assert _slugify("Don't click") == 'dont_click'


# ─── _compute_metrics ─────────────────────────────────────────────────────────


def test_compute_metrics_empty():
	r = _make_result(actions=[])
	m = _compute_metrics(r)
	assert m.total_actions == 0
	assert m.clicks == 0


def test_compute_metrics_mixed_actions():
	actions = [
		{'click': {'index': 1}},
		{'navigate': {'url': 'https://example.com/page1'}},
		{'input_text': {'text': 'hello'}},
		{'scroll': {'direction': 'down'}},
		{'go_to_url': {'url': 'https://example.com/page2'}},
	]
	r = _make_result(actions=actions)
	m = _compute_metrics(r)
	assert m.clicks == 1
	assert m.navigations == 2
	assert m.text_inputs == 1
	assert m.scrolls == 1
	assert m.total_actions == 5
	assert m.unique_pages == 2


def test_compute_metrics_unrecognized_action_type():
	"""Actions that are dicts but have no recognized action key still count as total."""
	r = _make_result(actions=[{'unknown_action': {}}])
	m = _compute_metrics(r)
	assert m.total_actions == 1
	assert m.clicks == 0


# ─── _format_metrics_line ─────────────────────────────────────────────────────


def test_format_metrics_line_empty():
	m = ActionMetrics()
	assert _format_metrics_line(m) == 'No actions recorded'


def test_format_metrics_line_singular():
	m = ActionMetrics(clicks=1)
	assert '1 click' in _format_metrics_line(m)
	assert 'clicks' not in _format_metrics_line(m)


def test_format_metrics_line_plural():
	m = ActionMetrics(clicks=3, navigations=2)
	line = _format_metrics_line(m)
	assert '3 clicks' in line
	assert '2 navigations' in line


# ─── format_path ─────────────────────────────────────────────────────────────


def test_format_path_no_actions():
	r = _make_result(actions=[])
	assert format_path(r) == 'No path recorded'


def test_format_path_navigate():
	r = _make_result(actions=[{'navigate': {'url': 'https://example.com/about'}}])
	path = format_path(r)
	assert 'about' in path


def test_format_path_click_with_name():
	r = _make_result(actions=[{'click': {}, 'interacted_element': {'ax_name': 'About Us'}}])
	path = format_path(r)
	assert 'About Us' in path


def test_format_path_input_text():
	r = _make_result(actions=[{'input_text': {'text': 'hello world'}}])
	path = format_path(r)
	assert 'hello world' in path


def test_format_path_scroll():
	r = _make_result(actions=[{'scroll': {'direction': 'down'}}])
	assert 'scroll down' in format_path(r)


# ─── _form_field_label ────────────────────────────────────────────────────────


def test_form_field_label_field_name():
	assert _form_field_label({'field_name': 'Email'}) == 'Email'


def test_form_field_label_aria_label():
	assert _form_field_label({'aria_label': 'Search input'}) == 'Search input'


def test_form_field_label_placeholder():
	assert _form_field_label({'placeholder': 'Enter text'}) == 'Enter text'


def test_form_field_label_tag_and_type():
	assert _form_field_label({'tag': 'input', 'type_attr': 'email'}) == '<input type="email">'


def test_form_field_label_role_fallback():
	assert _form_field_label({'role': 'textbox'}) == 'textbox'


def test_form_field_label_index_fallback():
	assert _form_field_label({'index': 5}) == 'element #5'


# ─── suggest_fix ─────────────────────────────────────────────────────────────


def test_suggest_fix_captcha():
	v = _make_verdict(verdict=False, reached_captcha=True)
	r = _make_result(success=False, judgement=v)
	fix = suggest_fix(r)
	assert 'CAPTCHA' in fix


def test_suggest_fix_impossible():
	v = _make_verdict(verdict=False, impossible_task=True)
	r = _make_result(success=False, judgement=v)
	fix = suggest_fix(r)
	assert 'not be possible' in fix


def test_suggest_fix_timeout():
	v = _make_verdict(verdict=False, failure_reason='Request timeout after 30s')
	r = _make_result(success=False, judgement=v)
	fix = suggest_fix(r)
	assert 'too long' in fix.lower() or 'timeout' in fix.lower()


def test_suggest_fix_element_not_found():
	v = _make_verdict(verdict=False, failure_reason='Element not found on page')
	r = _make_result(success=False, judgement=v)
	fix = suggest_fix(r)
	assert 'element' in fix.lower()


def test_suggest_fix_navigation_failure():
	v = _make_verdict(verdict=False, failure_reason='Could not navigate to URL')
	r = _make_result(success=False, judgement=v)
	fix = suggest_fix(r)
	assert 'navigate' in fix.lower() or 'load' in fix.lower() or 'page' in fix.lower()


def test_suggest_fix_passed_returns_empty():
	r = _make_result(success=True)
	fix = suggest_fix(r)
	assert fix == ''


# ─── write_json_report ────────────────────────────────────────────────────────


def test_write_json_report():
	report = _make_report()
	with tempfile.TemporaryDirectory() as tmpdir:
		path = write_json_report(report, Path(tmpdir))
		assert path.exists()
		assert path.name == 'evaluation_report.json'
		content = path.read_text()
		assert 'example.com' in content


# ─── write_markdown_report ────────────────────────────────────────────────────


def test_write_markdown_report_basic():
	report = _make_report()
	with tempfile.TemporaryDirectory() as tmpdir:
		path = write_markdown_report(report, Path(tmpdir))
		assert path.exists()
		content = path.read_text()
		assert '# Evaluation Report' in content
		assert 'Results at a Glance' in content
		assert 'Test search' in content


def test_write_markdown_report_includes_passed_section():
	report = _make_report()
	with tempfile.TemporaryDirectory() as tmpdir:
		content = write_markdown_report(report, Path(tmpdir)).read_text()
		assert 'Passed Tests' in content


def test_write_markdown_report_includes_failure_sections():
	failed_result = _make_result(
		success=False,
		judgement=_make_verdict(verdict=False, failure_reason='Search returned no results', failure_category='website_issue'),
		failure_category='website_issue',
	)
	report = _make_report(
		results=[failed_result],
		summary=ReportSummary(
			total=1,
			passed=0,
			failed=1,
			pass_rate=0.0,
			website_issues=1,
			by_priority={'high': {'passed': 0, 'failed': 1}},
		),
	)
	with tempfile.TemporaryDirectory() as tmpdir:
		content = write_markdown_report(report, Path(tmpdir)).read_text()
		assert 'Website Issues' in content


def test_write_markdown_report_includes_features_discovered():
	report = _make_report()
	with tempfile.TemporaryDirectory() as tmpdir:
		content = write_markdown_report(report, Path(tmpdir)).read_text()
		assert 'Features Discovered' in content
		assert 'Search' in content


def test_write_markdown_report_includes_executive_summary():
	from murphy.models import ExecutiveSummary

	es = ExecutiveSummary(
		overall_assessment='Good site overall.',
		key_findings=['Search works', 'Login broken'],
		recommended_actions=['Fix login'],
	)
	report = _make_report(executive_summary=es)
	with tempfile.TemporaryDirectory() as tmpdir:
		content = write_markdown_report(report, Path(tmpdir)).read_text()
		assert 'Executive Summary' in content
		assert 'Good site overall' in content


def test_write_markdown_report_feedback_quality_index():
	fq = FeedbackQualityScore(
		response_present=True,
		response_timely=False,
		response_clear=True,
		response_actionable=False,
		feedback_type='inline_message',
	)
	result = _make_result(feedback_quality=fq)
	report = _make_report(results=[result])
	with tempfile.TemporaryDirectory() as tmpdir:
		content = write_markdown_report(report, Path(tmpdir)).read_text()
		assert 'Feedback Quality Index' in content


# ─── copy_screenshots_to_output ──────────────────────────────────────────────


def test_copy_screenshots_creates_dir():
	with tempfile.TemporaryDirectory() as tmpdir:
		tmpdir = Path(tmpdir)
		src = tmpdir / 'src_screenshot.png'
		src.write_bytes(b'fake png data')

		result = _make_result(screenshot_paths=[str(src)])
		report = _make_report(results=[result])

		output_dir = tmpdir / 'output'
		output_dir.mkdir()
		copy_screenshots_to_output(report, output_dir)

		screenshots_dir = output_dir / 'screenshots'
		assert screenshots_dir.exists()


def test_copy_screenshots_skips_none_paths():
	result = _make_result(screenshot_paths=[None, None])
	report = _make_report(results=[result])

	with tempfile.TemporaryDirectory() as tmpdir:
		output_dir = Path(tmpdir) / 'output'
		output_dir.mkdir()
		copy_screenshots_to_output(report, output_dir)
