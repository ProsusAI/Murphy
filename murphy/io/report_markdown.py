"""Report generation — Markdown output."""

from __future__ import annotations

from pathlib import Path

from murphy.io.report_helpers import (
	_compute_metrics,
	_form_field_label,
	_format_metrics_line,
	suggest_fix,
)
from murphy.models import EvaluationReport, TestResult


def _render_test_detail(r: TestResult, index: int, lines: list[str]) -> None:
	"""Append detailed info for a single test result (pass or fail)."""
	m = _compute_metrics(r)
	passed = r.success

	lines.append(f'**Result:** {"Passed" if passed else "Failed"} in {r.duration:.0f}s')
	lines.append('')
	lines.append(f'**Metrics:** {_format_metrics_line(m)}')
	lines.append('')
	# lines.append(f'{format_path(r)}')
	lines.append('')

	# ── Form fills ──
	if r.form_fills:
		lines += ['**Form data entered:**']
		for fill in r.form_fills:
			field_label = _form_field_label(fill)
			text = fill.get('text', '')
			preview = text[:80] + '...' if len(text) > 80 else text
			lines.append(f'- **{field_label}**: `{preview}`')
		lines.append('')

	# ── Screenshots ──
	if r.screenshot_paths:
		total = len(r.screenshot_paths)
		lines.append(f'**Screenshots:** {total} screenshot{"s" if total != 1 else ""} saved to `screenshots/` directory')
		lines.append('')

	# ── Validation evidence ──
	validation_evidence = getattr(r, 'validation_evidence', '') or ''
	if validation_evidence:
		lines += ['**Validation Performed:**', f'{validation_evidence}', '']
	else:
		lines += ['**Validation Performed:**', 'No explicit validation evidence recorded.', '']

	# ── Missing signals (shown on all tests — UX gaps even on passes) ──
	missing_signals = getattr(r, 'missing_signals', []) or []
	if missing_signals:
		lines += ['**Confirmation signals not observed (UX gaps):**']
		for s in missing_signals:
			lines.append(f'- {s}')
		lines.append('')

	# ── Evaluation dimensions ──
	if r.process_evaluation:
		lines += ['**Process evaluation:**', f'{r.process_evaluation}', '']
	if r.logical_evaluation:
		lines += ['**Logical evaluation:**', f'{r.logical_evaluation}', '']
	if r.usability_evaluation:
		lines += ['**Usability evaluation:**', f'{r.usability_evaluation}', '']

	# ── Trait evaluations ──
	if r.trait_evaluations:
		lines += ['**Trait evaluations:**']
		for trait_name, assessment in r.trait_evaluations.items():
			lines.append(f'- **{trait_name}**: {assessment}')
		lines.append('')

	# ── Pages visited ──
	if r.pages_visited:
		lines += ['**Pages visited:**']
		for page_url in r.pages_visited:
			lines.append(f'- {page_url}')
		lines.append('')

	if not passed:
		failure_reason = r.reason or ''
		if r.judgement:
			if not failure_reason:
				failure_reason = r.judgement.failure_reason

		if failure_reason:
			lines += [
				'**Why it failed:**',
				f'{failure_reason}',
				'',
			]

		suggestion = suggest_fix(r)
		if suggestion:
			lines += [
				'**Suggested fix:**',
				f'{suggestion}',
				'',
			]


def write_markdown_report(report: EvaluationReport, output_dir: Path) -> Path:
	path = output_dir / 'evaluation_report.md'
	s = report.summary
	a = report.analysis

	lines = [
		f'# Evaluation Report: {a.site_name}',
		'',
		f'> **{a.description}**',
		'',
		'| | |',
		'|---|---|',
		f'| URL | {report.url} |',
		f'| Category | {a.category} |',
		f'| Date | {report.timestamp[:10]} |',
		f'| Pages Discovered | {", ".join(p.title for p in a.key_pages) or "None identified"} |',
		'',
		'---',
		'',
		'## Results at a Glance',
		'',
	]

	# Partition results
	website_issues = [r for r in report.results if r.failure_category == 'website_issue']
	test_limitations = [r for r in report.results if r.failure_category == 'test_limitation']
	passed_tests = [r for r in report.results if r.success]

	# Scorecard
	rate_str = f'{s.pass_rate}%'
	lines += [
		f'**{s.passed}/{s.total} tests passed ({rate_str})**',
		f'- Website Issues: {s.website_issues}',
		f'- Test Limitations: {s.test_limitations}',
		'',
		'| Test | Persona | Result | Category | Duration |',
		'|------|---------|--------|----------|----------|',
	]
	for r in report.results:
		persona_label = r.scenario.test_persona.replace('_', ' ').title()
		if r.success:
			emoji = '\u2705'
			result_str = 'Passed'
			category_str = ''
		elif r.failure_category == 'website_issue':
			emoji = '\U0001f534'
			result_str = 'Failed'
			category_str = 'Website Issue'
		else:
			emoji = '\u26a0\ufe0f'
			result_str = 'Failed'
			category_str = 'Test Limitation'
		lines.append(f'| {emoji} {r.scenario.name} | {persona_label} | {result_str} | {category_str} | {r.duration:.0f}s |')

	# ── Feedback Quality Index ────────────────────────────────────────────────
	fq_results = [r for r in report.results if r.feedback_quality]
	if fq_results:
		lines += [
			'',
			'### Feedback Quality Index',
			'',
			'| Test | Persona | Present | Timely | Clear | Actionable | Type | Score |',
			'|------|---------|---------|--------|-------|------------|------|-------|',
		]
		for r in fq_results:
			fq = r.feedback_quality
			assert fq is not None
			score = sum([fq.response_present, fq.response_timely, fq.response_clear, fq.response_actionable])

			def yes_no(b):
				return 'Yes' if b else 'No'

			persona_label = r.scenario.test_persona.replace('_', ' ').title()
			lines.append(
				f'| {r.scenario.name[:40]} | {persona_label} | {yes_no(fq.response_present)} | {yes_no(fq.response_timely)} | '
				f'{yes_no(fq.response_clear)} | {yes_no(fq.response_actionable)} | {fq.feedback_type} | {score}/4 |'
			)

	lines += ['', '---', '']

	# ── Executive Summary ─────────────────────────────────────────────────────
	if report.executive_summary:
		es = report.executive_summary
		lines += [
			'## Executive Summary',
			'',
			f'{es.overall_assessment}',
			'',
			'### Key Findings',
			'',
		]
		for i, finding in enumerate(es.key_findings, 1):
			lines.append(f'{i}. {finding}')
		lines += [
			'',
			'### Recommended Actions',
			'',
		]
		for i, action in enumerate(es.recommended_actions, 1):
			lines.append(f'{i}. {action}')
		lines += ['', '---', '']

	# ── Website Issues section ────────────────────────────────────────────────
	if website_issues:
		lines += ['## Website Issues', '']
		for i, r in enumerate(website_issues, 1):
			persona_label = r.scenario.test_persona.replace('_', ' ').title()
			summary_text = f'\U0001f534 {i}. {r.scenario.name} — {persona_label}'
			detail_lines: list[str] = [
				f'**Persona:** {persona_label}',
				'',
				f'**What was tested:** {r.scenario.description}',
				'',
			]
			_render_test_detail(r, i, detail_lines)
			lines += ['<details>', f'<summary>{summary_text}</summary>', ''] + detail_lines + ['</details>', '']

	# ── Test Limitations section ──────────────────────────────────────────────
	if test_limitations:
		lines += ['## Test Limitations', '']
		for i, r in enumerate(test_limitations, 1):
			persona_label = r.scenario.test_persona.replace('_', ' ').title()
			summary_text = f'\u26a0\ufe0f {i}. {r.scenario.name} — {persona_label}'
			detail_lines = [
				f'**Persona:** {persona_label}',
				'',
				f'**What was tested:** {r.scenario.description}',
				'',
			]
			_render_test_detail(r, i, detail_lines)
			lines += ['<details>', f'<summary>{summary_text}</summary>', ''] + detail_lines + ['</details>', '']

	# ── Passed Tests section ──────────────────────────────────────────────────
	if passed_tests:
		lines += ['## Passed Tests', '']
		for i, r in enumerate(passed_tests, 1):
			persona_label = r.scenario.test_persona.replace('_', ' ').title()
			summary_text = f'\u2705 {i}. {r.scenario.name} — {persona_label}'
			detail_lines = [
				f'**Persona:** {persona_label}',
				'',
				f'**What was tested:** {r.scenario.description}',
				'',
			]
			_render_test_detail(r, i, detail_lines)
			lines += ['<details>', f'<summary>{summary_text}</summary>', ''] + detail_lines + ['</details>', '']

	# Features discovered
	if a.features:
		lines += [
			'## Features Discovered',
			'',
			'| Feature | Category | Importance | Testability | Reason |',
			'|---------|----------|------------|-------------|--------|',
		]
		for f in a.features:
			testability_icon = {'testable': '\u2705', 'partial': '\u26a0\ufe0f', 'untestable': '\u26d4'}[f.testability]
			reason = f.testability_reason or ''
			lines.append(f'| {f.name} | {f.category} | {f.importance} | {testability_icon} {f.testability} | {reason} |')
		lines.append('')

	# User flows discovered (context)
	if a.identified_user_flows:
		lines += [
			'## User Flows Discovered',
			'',
			'These are the user journeys identified on the website:',
			'',
		]
		for flow in a.identified_user_flows:
			lines.append(f'- {flow}')
		lines.append('')

	path.write_text('\n'.join(lines))
	return path
