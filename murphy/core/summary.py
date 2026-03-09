"""Murphy — results classification, summary building, and report writing."""

import logging
from pathlib import Path
from typing import Literal

from browser_use.llm import ChatOpenAI, SystemMessage, UserMessage
from browser_use.utils import sanitize_surrogates
from murphy.io.report import write_full_report
from murphy.models import (
	ExecutiveSummary,
	ReportSummary,
	TestResult,
	WebsiteAnalysis,
)

logger = logging.getLogger(__name__)


def classify_failure(result: TestResult) -> Literal['website_issue', 'test_limitation'] | None:
	"""Classify a failed test as a website issue or a test limitation.

	Delegates to the judge LLM's failure_category field, which has full context
	about the agent's actions and the website's behavior.

	Crashed tests (success=None, no judgement) are automatically classified as
	test_limitation — the test infrastructure failed, not the website.
	"""
	if result.success is True:
		return None
	# Crashed tests: success=None with no judgement → test infrastructure failure
	if result.success is None:
		return 'test_limitation'
	if result.judgement is None:
		return 'test_limitation'
	return result.judgement.failure_category


def build_summary(results: list[TestResult]) -> ReportSummary:
	"""Build a summary of test results by priority and failure category."""
	passed = sum(1 for r in results if r.success is True)
	failed = sum(1 for r in results if r.success is not True)
	total = len(results)

	by_priority: dict[str, dict[str, int]] = {}
	for r in results:
		p = r.scenario.priority
		if p not in by_priority:
			by_priority[p] = {'passed': 0, 'failed': 0}
		if r.success is True:
			by_priority[p]['passed'] += 1
		else:
			by_priority[p]['failed'] += 1

	website_issues = sum(1 for r in results if r.failure_category == 'website_issue')
	test_limitations = sum(1 for r in results if r.failure_category == 'test_limitation')

	return ReportSummary(
		total=total,
		passed=passed,
		failed=failed,
		pass_rate=round(passed / total * 100, 1) if total > 0 else 0.0,
		website_issues=website_issues,
		test_limitations=test_limitations,
		by_priority=by_priority,
	)


async def generate_executive_summary(
	url: str,
	analysis: WebsiteAnalysis,
	results: list[TestResult],
	summary: ReportSummary,
	llm: ChatOpenAI,
) -> ExecutiveSummary:
	"""Generate an LLM-powered executive summary of the evaluation results."""
	results_summary_parts: list[str] = []
	for i, r in enumerate(results, 1):
		status = 'PASSED' if r.success else 'FAILED'
		persona = r.scenario.test_persona.replace('_', ' ')
		reason = ''
		if not r.success:
			reason = r.reason or (r.judgement.failure_reason if r.judgement else '')
			category = r.failure_category or 'unknown'
			reason = f' | Category: {category} | Reason: {reason}'
		# Include trait evaluations if available
		trait_note = ''
		if r.trait_evaluations:
			trait_parts = [f'{k}: {v}' for k, v in r.trait_evaluations.items()]
			trait_note = f' | Trait evals: {"; ".join(trait_parts)}'
		# Include feedback quality if available
		fq_note = ''
		if r.feedback_quality:
			fq = r.feedback_quality
			score = sum([fq.response_present, fq.response_timely, fq.response_clear, fq.response_actionable])
			fq_note = f' | Feedback: {score}/4 ({fq.feedback_type})'
		results_summary_parts.append(
			f'{i}. [{status}] {r.scenario.name} (persona: {persona}, priority: {r.scenario.priority}){reason}{fq_note}{trait_note}'
		)

	prompt = f"""Analyze these website evaluation results and produce an executive summary.

Website: {url}
Site: {analysis.site_name} ({analysis.category})
Description: {analysis.description}

Results: {summary.passed}/{summary.total} tests passed ({summary.pass_rate}%)
- Website Issues: {summary.website_issues}
- Test Limitations: {summary.test_limitations}

Individual results:
{chr(10).join(results_summary_parts)}

Provide:
1. overall_assessment: 1-2 sentences on the site's overall quality based on test results
2. key_findings: 3-5 specific UX findings ranked by severity (most severe first). Each finding should reference specific test results. When trait evaluations are available, reference the specific trait dimension that failed (e.g., "Users with low reading comprehension will miss the error message because it's plain body text"). When feedback quality scores are available, reference specific gaps (e.g., "3 of 8 tests had no actionable feedback").
3. recommended_actions: Top 3 concrete actions the site team should take to improve UX

Be specific and actionable. Reference actual test names and outcomes. Do NOT use generic statements."""
	prompt = sanitize_surrogates(prompt)

	response = await llm.ainvoke(
		messages=[
			SystemMessage(
				content='You are a senior UX analyst writing an executive summary of automated website testing results. Be concise, specific, and actionable.'
			),
			UserMessage(content=prompt),
		],
		output_format=ExecutiveSummary,
	)

	result = response.completion
	assert isinstance(result, ExecutiveSummary), f'Expected ExecutiveSummary, got {type(result)}'
	return result


def write_reports_and_print(
	url: str,
	analysis: WebsiteAnalysis,
	results: list[TestResult],
	output_dir: Path,
	executive_summary: ExecutiveSummary | None = None,
) -> None:
	"""Write JSON + markdown reports and log summary to console."""
	json_path, md_path = write_full_report(url, analysis, results, output_dir, executive_summary=executive_summary)
	summary = build_summary(results)

	logger.info('\n%s', '=' * 60)
	logger.info('Evaluation Complete')
	logger.info('%s', '=' * 60)
	logger.info('\n  Pass rate: %s%% (%d/%d)', summary.pass_rate, summary.passed, summary.total)
	logger.info('  JSON report: %s', json_path)
	logger.info('  Markdown report: %s', md_path)
