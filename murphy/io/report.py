"""Report generation — orchestration and re-exports.

Sub-modules:
  report_helpers  — shared utilities (ActionMetrics, format_path, suggest_fix)
  report_json     — JSON output and screenshot management
  report_markdown — Markdown output
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from murphy.io.report_helpers import (
	ActionMetrics,
	_compute_metrics,
	_form_field_label,
	_format_metrics_line,
	_slugify,
	format_path,
	suggest_fix,
)
from murphy.io.report_json import copy_screenshots_to_output, write_json_report
from murphy.io.report_markdown import _render_test_detail, write_markdown_report
from murphy.models import EvaluationReport, ExecutiveSummary, TestResult, TokenUsage, WebsiteAnalysis

# Re-export everything for backward compatibility
__all__ = [
	'ActionMetrics',
	'_compute_metrics',
	'_form_field_label',
	'_format_metrics_line',
	'_render_test_detail',
	'_slugify',
	'copy_screenshots_to_output',
	'format_path',
	'suggest_fix',
	'write_full_report',
	'write_json_report',
	'write_markdown_report',
]


def write_full_report(
	url: str,
	analysis: WebsiteAnalysis,
	results: list[TestResult],
	output_dir: Path,
	executive_summary: ExecutiveSummary | None = None,
	persona_discovery_tokens: TokenUsage | None = None,
	murphy_tokens: TokenUsage | None = None,
) -> tuple[Path, Path]:
	"""Copy screenshots + write JSON + write Markdown. Returns (json_path, md_path)."""
	from murphy.evaluate import build_summary

	summary = build_summary(results)
	report = EvaluationReport(
		url=url,
		timestamp=datetime.now(timezone.utc).isoformat(),
		analysis=analysis,
		results=results,
		summary=summary,
		executive_summary=executive_summary,
		persona_discovery_tokens=persona_discovery_tokens,
		murphy_tokens=murphy_tokens,
	)

	copy_screenshots_to_output(report, output_dir)
	json_path = write_json_report(report, output_dir)
	md_path = write_markdown_report(report, output_dir)
	return json_path, md_path
