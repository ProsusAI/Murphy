"""Murphy — test execution (Phase 3 of evaluation)."""

import asyncio
import json
import logging
import re
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from browser_use import Agent
from browser_use.agent.views import AgentHistoryList
from browser_use.browser.session import BrowserSession
from browser_use.llm import ChatOpenAI
from murphy.core.judge import murphy_judge
from murphy.core.summary import classify_failure
from murphy.models import (
	ScenarioExecutionVerdict,
	TestPlan,
	TestResult,
	TestScenario,
)
from murphy.prompts import build_execution_prompt

logger = logging.getLogger(__name__)

from murphy.config import MAX_PARALLEL_SESSIONS

# ─── Structured output parsing ────────────────────────────────────────────────


def _parse_structured_output(
	history: AgentHistoryList, model_cls: type[ScenarioExecutionVerdict]
) -> ScenarioExecutionVerdict | None:
	"""Safely parse structured output from agent history."""
	result = history.final_result()
	if not result:
		return None
	try:
		return model_cls.model_validate_json(result)
	except Exception:
		# Try parsing as dict
		try:
			data = json.loads(result)
			return model_cls.model_validate(data)
		except Exception:
			return None


def _extract_form_fills(actions: list[dict[str, Any]]) -> list[dict]:
	"""Extract form fill actions with field info and typed text."""
	fills: list[dict] = []
	for action in actions:
		for key, val in action.items():
			if key in ('input_text', 'input') and isinstance(val, dict):
				fill: dict[str, Any] = {
					'text': val.get('text', ''),
					'index': val.get('index'),
				}
				# Include interacted element info if available
				el = action.get('interacted_element')
				if el and isinstance(el, dict):
					fill['field_name'] = el.get('ax_name', '')
					fill['tag'] = el.get('tag_name', '')
					fill['placeholder'] = el.get('placeholder', '')
					# Additional attributes for better labeling
					attrs = el.get('attributes', {})
					if isinstance(attrs, dict):
						fill['name_attr'] = attrs.get('name', '')
						fill['aria_label'] = attrs.get('aria-label', '')
						fill['type_attr'] = attrs.get('type', '')
					fill['role'] = el.get('role', '')
				fills.append(fill)
	return fills


def _extract_pages_visited(actions: list[dict[str, Any]], start_url: str) -> list[str]:
	"""Extract unique pages visited from action history."""
	pages: list[str] = [start_url]
	for action in actions:
		for key, val in action.items():
			if key in ('navigate', 'go_to_url') and isinstance(val, dict):
				url = val.get('url', '')
				if url:
					pages.append(url)
	# Deduplicate preserving order
	seen: set[str] = set()
	unique: list[str] = []
	for p in pages:
		if p not in seen:
			seen.add(p)
			unique.append(p)
	return unique


_URL_RE = re.compile(r'https?://[^\s<>"\')\]]+')


def _extract_urls_from_texts(texts: list[str]) -> list[str]:
	"""Regex-based URL extraction from error messages / text blobs."""
	urls: list[str] = []
	for text in texts:
		if text:
			urls.extend(_URL_RE.findall(text))
	return urls


async def _collect_session_urls(browser_session: BrowserSession) -> list[str]:
	"""Collect current + historical tab URLs from browser session."""
	urls: list[str] = []
	try:
		tabs = await browser_session.get_tabs()
		for tab in tabs:
			tab_url = getattr(tab, 'url', '') or ''
			if tab_url and tab_url not in ('about:blank', ''):
				urls.append(tab_url)
	except Exception:
		pass
	return urls


# ─── Single-test execution helper ──────────────────────────────────────────────


async def _execute_single_test(
	url: str,
	scenario: TestScenario,
	llm: ChatOpenAI,
	browser_session: BrowserSession,
	goal: str | None,
	fixture_paths: list[Path] | None,
	max_steps: int,
	index: int,
	total: int,
	judge_llm: ChatOpenAI | None = None,
) -> TestResult:
	"""Execute one test scenario and return its TestResult.

	Shared by both sequential and parallel execution paths.
	"""
	from murphy.browser.actions import register_domain_access_action, register_refresh_dom_action
	from murphy.browser.session_utils import prepare_session_for_task

	logger.info('\n--- Test %d/%d: %s ---', index, total, scenario.name)

	try:
		# Stabilize session between tests
		await prepare_session_for_task(browser_session, url, force_navigate=True)

		file_paths_str = [str(p) for p in fixture_paths] if fixture_paths else []
		task_prompt = build_execution_prompt(
			goal or f'Evaluate {url}', scenario, url, available_file_paths=file_paths_str or None
		)

		agent_kwargs: dict[str, Any] = {
			'task': task_prompt,
			'llm': llm,
			'browser_session': browser_session,
			'use_judge': False,
			'max_actions_per_step': 3,
		}
		if file_paths_str:
			agent_kwargs['available_file_paths'] = file_paths_str

		# Use structured output for the verdict
		agent_kwargs['output_model_schema'] = ScenarioExecutionVerdict

		agent = Agent(**agent_kwargs)
		# Register custom actions
		register_domain_access_action(agent.tools, browser_session)
		register_refresh_dom_action(agent.tools, browser_session)

		history = await agent.run(max_steps=max_steps)

		# Parse structured verdict from agent
		verdict = _parse_structured_output(history, ScenarioExecutionVerdict)

		# Also run murphy judge for authoritative pass/fail
		judgement = await murphy_judge(history, scenario, llm, start_url=url, judge_llm=judge_llm)

		# Merge: use judge verdict as authoritative, but overlay agent's evaluations
		success = judgement.verdict
		status = 'PASS' if success else 'FAIL'
		logger.info('  Result: %s (%.1fs)', status, history.total_duration_seconds())

		# Log verdict disagreements for prompt debugging
		agent_verdict = verdict.success if verdict else None
		if agent_verdict is not None and agent_verdict != success:
			logger.warning(
				'  Verdict mismatch: agent=%s, judge=%s — scenario=%r',
				'PASS' if agent_verdict else 'FAIL',
				status,
				scenario.name,
			)

		# Prefer judge evaluations (third-party observer), fall back to agent's
		process_eval = judgement.process_evaluation or (verdict.process_evaluation if verdict else '')
		logical_eval = judgement.logical_evaluation or (verdict.logical_evaluation if verdict else '')
		usability_eval = judgement.usability_evaluation or (verdict.usability_evaluation if verdict else '')
		reason = judgement.failure_reason or (verdict.reason if verdict else '')
		validation_evidence = (verdict.validation_evidence if verdict else '') or ''

		all_actions = history.model_actions()
		errors = history.errors()

		# Collect pages from actions, session tabs, and error text URLs
		action_pages = _extract_pages_visited(all_actions, url)
		session_urls = await _collect_session_urls(browser_session)
		error_urls = _extract_urls_from_texts([e for e in errors if e])
		all_pages = action_pages + session_urls + error_urls
		# Deduplicate preserving order
		seen_urls: set[str] = set()
		unique_pages: list[str] = []
		for p in all_pages:
			if p not in seen_urls:
				seen_urls.add(p)
				unique_pages.append(p)

		test_result = TestResult(
			scenario=scenario,
			success=success,
			judgement=judgement,
			actions=all_actions,
			errors=errors,
			duration=history.total_duration_seconds(),
			pages_visited=unique_pages,
			screenshot_paths=[p for p in history.screenshot_paths() if p],
			form_fills=_extract_form_fills(all_actions),
			process_evaluation=process_eval,
			logical_evaluation=logical_eval,
			usability_evaluation=usability_eval,
			reason=reason,
			validation_evidence=validation_evidence,
			feedback_quality=judgement.feedback_quality,
			trait_evaluations=judgement.trait_evaluations,
			missing_signals=judgement.missing_signals,
		)
		test_result.failure_category = classify_failure(test_result)
	except Exception as exc:
		tb = traceback.format_exc()
		logger.error('  CRASH: %s: %s', type(exc).__name__, exc)
		test_result = TestResult(
			scenario=scenario,
			success=False,
			judgement=None,
			actions=[],
			errors=[f'{type(exc).__name__}: {exc}', tb],
			duration=0.0,
			reason=f'Test crashed: {type(exc).__name__}: {exc}',
		)
		test_result.failure_category = 'test_limitation'

	return test_result


# ─── Session pool for parallel execution ──────────────────────────────────────


async def _create_session_pool(
	pool_size: int,
	original_session: BrowserSession,
	highlight_elements: bool = True,
) -> list[BrowserSession]:
	"""Create N independent browser sessions for parallel test execution.

	Slot 0 = the original session (already started, already authenticated).
	Slots 1..N-1 = new BrowserSession instances with their own BrowserProfile.
	Auth cookies are transferred from the original session via CDP.
	"""
	from browser_use.browser.profile import BrowserProfile

	if pool_size <= 1:
		return [original_session]

	sessions: list[BrowserSession] = [original_session]

	# Extract cookies + web storage from original session for auth transfer
	cookies: list[Any] = []
	local_storage_entries: list[tuple[str, str]] = []
	session_storage_entries: list[tuple[str, str]] = []
	try:
		cdp_session = await original_session.get_or_create_cdp_session()
		result = await cdp_session.cdp_client.send.Network.getAllCookies(
			session_id=cdp_session.session_id,
		)
		cookies = (result or {}).get('cookies', [])
	except Exception as exc:
		logger.warning('Failed to extract cookies for auth transfer: %s', exc)

	# Extract localStorage and sessionStorage (token-based auth apps)
	try:
		cdp_session = await original_session.get_or_create_cdp_session()
		for storage_type, target_list in [('localStorage', local_storage_entries), ('sessionStorage', session_storage_entries)]:
			js = f'JSON.stringify(Object.keys({storage_type}).map(k => [k, {storage_type}.getItem(k)]))'
			result = await cdp_session.cdp_client.send.Runtime.evaluate(
				params={'expression': js, 'returnByValue': True},
				session_id=cdp_session.session_id,
			)
			raw = (result or {}).get('result', {}).get('value', '[]')
			target_list.extend(json.loads(raw) if isinstance(raw, str) else [])
	except Exception as exc:
		logger.warning('Failed to extract web storage for auth transfer: %s', exc)

	for _ in range(1, pool_size):
		profile = BrowserProfile(
			keep_alive=True,
			dom_highlight_elements=highlight_elements,
		)
		session = BrowserSession(browser_profile=profile)
		await session.start()

		# Inject auth cookies if available
		if cookies:
			try:
				cdp_session = await session.get_or_create_cdp_session()
				await cdp_session.cdp_client.send.Network.setCookies(
					params={'cookies': cookies},
					session_id=cdp_session.session_id,
				)
			except Exception as exc:
				logger.warning('Failed to inject cookies into pool session: %s', exc)

		# Transfer localStorage/sessionStorage for token-based auth
		if local_storage_entries or session_storage_entries:
			try:
				# Navigate to a page on the same origin so storage APIs are available
				current_url = await original_session.get_current_page_url()
				if current_url:
					await session.navigate_to(current_url)

				cdp_session = await session.get_or_create_cdp_session()
				for storage_type, entries in [
					('localStorage', local_storage_entries),
					('sessionStorage', session_storage_entries),
				]:
					for key, value in entries:
						escaped_key = json.dumps(key)
						escaped_value = json.dumps(value)
						await cdp_session.cdp_client.send.Runtime.evaluate(
							params={
								'expression': f'{storage_type}.setItem({escaped_key}, {escaped_value})',
								'returnByValue': True,
							},
							session_id=cdp_session.session_id,
						)
			except Exception as exc:
				logger.warning('Failed to transfer web storage to pool session: %s', exc)

		sessions.append(session)

	return sessions


async def _cleanup_session_pool(sessions: list[BrowserSession], original_session: BrowserSession) -> None:
	"""Kill all pool sessions except the original."""
	for session in sessions:
		if session is original_session:
			continue
		try:
			await session.kill()
		except Exception:
			pass


# ─── Execute & Report ─────────────────────────────────────────────────────────


async def execute_tests(
	url: str,
	test_plan: TestPlan,
	llm: ChatOpenAI,
	progress_state: Any = None,
	save_callback: Callable[[list[TestResult]], None] | None = None,
	judge_llm: ChatOpenAI | None = None,
) -> list[TestResult]:
	"""Execute tests without a pre-existing session (creates its own)."""
	from browser_use.browser.profile import BrowserProfile

	browser_session = BrowserSession(browser_profile=BrowserProfile(keep_alive=True))
	await browser_session.start()

	try:
		return await execute_tests_with_session(
			url=url,
			test_plan=test_plan,
			llm=llm,
			browser_session=browser_session,
			progress_state=progress_state,
			save_callback=save_callback,
			max_concurrent=1,
			judge_llm=judge_llm,
		)
	finally:
		await browser_session.kill()


async def execute_tests_with_session(
	url: str,
	test_plan: TestPlan,
	llm: ChatOpenAI,
	browser_session: BrowserSession,
	progress_state: Any = None,
	goal: str | None = None,
	fixture_paths: list[Path] | None = None,
	max_steps: int = 15,
	save_callback: Callable[[list[TestResult]], None] | None = None,
	max_concurrent: int = 3,
	judge_llm: ChatOpenAI | None = None,
) -> list[TestResult]:
	"""Phase 3 execution reusing an existing browser session.

	Uses BOTH structured agent verdict (ScenarioExecutionVerdict) AND murphy judge.
	When max_concurrent > 1, runs tests in parallel using a session pool.
	"""
	total = len(test_plan.scenarios)
	mode = 'parallel' if max_concurrent > 1 else 'sequential'
	logger.info('\n%s', '=' * 60)
	logger.info('Executing %d tests (%s, max_concurrent=%d)', total, mode, max_concurrent)
	logger.info('%s\n', '=' * 60)

	if max_concurrent <= 1:
		# ── Sequential path (unchanged behavior) ──
		results: list[TestResult] = []
		for i, scenario in enumerate(test_plan.scenarios, 1):
			if progress_state is not None:
				progress_state.current_test = i

			test_result = await _execute_single_test(
				url=url,
				scenario=scenario,
				llm=llm,
				browser_session=browser_session,
				goal=goal,
				fixture_paths=fixture_paths,
				max_steps=max_steps,
				index=i,
				total=total,
				judge_llm=judge_llm,
			)
			results.append(test_result)

			if save_callback:
				try:
					save_callback(results)
				except Exception as e:
					logger.warning('  save_callback failed: %s', e)

		return results

	# ── Parallel path ──
	# Clamp: no more sessions than scenarios, and enforce hard cap
	effective_concurrent = min(max_concurrent, total, MAX_PARALLEL_SESSIONS)

	highlight = browser_session.browser_profile.dom_highlight_elements if browser_session.browser_profile else True
	sessions = await _create_session_pool(
		pool_size=effective_concurrent,
		original_session=browser_session,
		highlight_elements=highlight,
	)

	try:
		results_slots: list[TestResult | None] = [None] * total
		report_lock = asyncio.Lock()
		# Use a queue so each concurrent test gets an exclusive session
		session_queue: asyncio.Queue[BrowserSession] = asyncio.Queue()
		for s in sessions:
			session_queue.put_nowait(s)

		async def _run_one(index_0: int, scenario: TestScenario) -> None:
			session = await session_queue.get()
			try:
				if progress_state is not None:
					progress_state.current_test = index_0 + 1

				result = await _execute_single_test(
					url=url,
					scenario=scenario,
					llm=llm,
					browser_session=session,
					goal=goal,
					fixture_paths=fixture_paths,
					max_steps=max_steps,
					index=index_0 + 1,
					total=total,
					judge_llm=judge_llm,
				)
				results_slots[index_0] = result

				if save_callback:
					async with report_lock:
						completed = [r for r in results_slots if r is not None]
						try:
							save_callback(completed)
						except Exception as e:
							logger.warning('  save_callback failed: %s', e)
			finally:
				session_queue.put_nowait(session)

		async with asyncio.TaskGroup() as tg:
			for i, scenario in enumerate(test_plan.scenarios):
				tg.create_task(_run_one(i, scenario))

		# Return results in plan order
		return [r for r in results_slots if r is not None]

	finally:
		await _cleanup_session_pool(sessions, browser_session)
