"""Murphy — shared pipeline orchestration.

Lifecycle-managed helpers that encapsulate the common pattern of:
apply patches → create LLM → create browser session → run → cleanup.

Used by the REST API. The CLI has its own orchestration due to interactive
prompts, auth flow, and UI mode.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from murphy.browser.patches import apply as apply_patches
from murphy.evaluate import (
	analyze_website,
	build_summary,
	execute_tests_with_session,
	explore_and_generate_plan,
	generate_tests,
)
from murphy.io.fixtures import ensure_dummy_fixture_files
from murphy.llm import create_llm
from murphy.models import DEFAULT_MAX_TESTS, ReportSummary, TestPlan, TestResult, WebsiteAnalysis
from murphy.process.model import NavigationModel


async def run_analyze(
	url: str,
	model: str,
	provider: str = 'openai',
	goal: str | None = None,
	browser_session: BrowserSession | None = None,
) -> WebsiteAnalysis:
	"""Run website analysis (feature discovery)."""
	apply_patches()
	llm = create_llm(model, provider=provider)
	own_session = browser_session is None
	if own_session:
		browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True, keep_alive=False))
		await browser_session.start()
	try:
		return await analyze_website(url, llm, browser_session=browser_session, goal=goal)
	finally:
		if own_session:
			await browser_session.kill()


async def run_generate_plan(
	url: str,
	analysis: WebsiteAnalysis,
	model: str,
	provider: str = 'openai',
	max_tests: int = DEFAULT_MAX_TESTS,
	goal: str | None = None,
) -> TestPlan:
	"""Generate test plan from analysis."""
	apply_patches()
	llm = create_llm(model, provider=provider)
	return await generate_tests(url, analysis, llm, max_tests, goal=goal)


async def run_execute(
	url: str,
	test_plan: TestPlan,
	model: str,
	provider: str = 'openai',
	judge_model: str | None = None,
	judge_provider: str | None = None,
	goal: str | None = None,
	max_steps: int = 15,
	max_concurrent: int = 3,
	browser_session: BrowserSession | None = None,
	fixture_paths: list[Path] | None = None,
	save_callback: Any = None,
	progress_state: Any = None,
	output_dir: Path | None = None,
) -> tuple[list[TestResult], ReportSummary]:
	"""Execute tests and return results + summary."""
	apply_patches()
	if fixture_paths is None:
		fixture_paths = ensure_dummy_fixture_files()
	llm = create_llm(model, provider=provider)
	jp = judge_provider or provider
	jm = judge_model or model
	judge_llm = create_llm(jm, provider=jp) if (jm != model or jp != provider) else None
	own_session = browser_session is None
	if own_session:
		browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True, keep_alive=False))
		await browser_session.start()
	try:
		nav_model_path = (output_dir or Path('./murphy/output')) / 'navigation_model.json'
		navigation_model = NavigationModel(nav_model_path)
		results = await execute_tests_with_session(
			url,
			test_plan,
			llm,
			browser_session,
			goal=goal,
			fixture_paths=fixture_paths,
			max_steps=max_steps,
			max_concurrent=max_concurrent,
			judge_llm=judge_llm,
			output_dir=output_dir,
			navigation_model=navigation_model,
		)
		summary = build_summary(results)
		return results, summary
	finally:
		if own_session:
			await browser_session.kill()


async def run_evaluate(
	url: str,
	model: str,
	provider: str = 'openai',
	max_tests: int = DEFAULT_MAX_TESTS,
	goal: str | None = None,
	browser_session: BrowserSession | None = None,
) -> TestPlan:
	"""Exploration-first: explore site then generate test plan."""
	apply_patches()
	task = goal or f'Evaluate the website at {url}'
	llm = create_llm(model, provider=provider)
	own_session = browser_session is None
	if own_session:
		browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True, keep_alive=False))
		await browser_session.start()
	try:
		return await explore_and_generate_plan(
			task=task,
			url=url,
			llm=llm,
			session=browser_session,
			max_scenarios=max_tests,
		)
	finally:
		if own_session:
			await browser_session.kill()
