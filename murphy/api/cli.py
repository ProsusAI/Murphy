"""Murphy CLI — single command entry point.

Usage:
    murphy --url https://example.com                              # full run: detect auth → analyze → edit features → generate tests → edit tests → execute
    murphy --url https://example.com --auth                     # skip detection, go straight to login wait
    murphy --url https://example.com --no-auth                    # skip auth detection, treat as public
    murphy --url https://example.com --features features.md     # skip analysis, load features from file
    murphy --url https://example.com --plan plan.yaml           # skip analysis + generation, load test plan
    murphy --url https://example.com --goal "test the checkout flow"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv

from browser_use.config import CONFIG

if TYPE_CHECKING:
	from murphy.api.server import ServerState
	from murphy.models import TestPlan, TestResult

load_dotenv()

logger = logging.getLogger(__name__)

# Persistent browser profile directory — stores cookies/session across runs so login is only needed once.
# In Docker, use a container-local path because mounted volumes (including /data) don't support
# Chrome's SingletonLock symlinks on macOS Docker Desktop (virtiofs).
BROWSER_PROFILE_DIR = (
	Path('/tmp/murphy_browser_profile') if CONFIG.IN_DOCKER else Path(__file__).parent.parent / 'browser_profile'
)


def main() -> int:
	parser = argparse.ArgumentParser(
		prog='murphy',
		description='Murphy — AI-driven website evaluation',
	)
	parser.add_argument('--url', required=True, help='Target URL to evaluate')
	parser.add_argument('--goal', help="Free-text goal to bias test generation (e.g. 'test the checkout flow')")
	parser.add_argument('--auth', action='store_true', help='Skip auto-detection and go straight to manual login wait')
	parser.add_argument('--no-auth', action='store_true', help='Skip auth detection entirely, treat site as public')
	parser.add_argument('--features', help='Path to existing features markdown (skips analysis, goes to test generation)')
	parser.add_argument('--plan', help='Path to existing YAML test plan (skips analysis + test generation)')
	parser.add_argument('--max-tests', type=int, default=8, help='Max test scenarios (default: 8)')
	parser.add_argument('--model', default='gpt-5-mini', help='OpenAI model for agent tasks (default: gpt-5-mini)')
	parser.add_argument('--judge-model', default='gpt-5-mini', help='OpenAI model for judging verdicts (default: gpt-5-mini)')
	parser.add_argument('--output-dir', default='./murphy/output', help='Output directory for reports')
	parser.add_argument('--category', help='Site category hint (ecommerce, saas, content, social)')
	parser.add_argument('--ui', action='store_true', help='Launch interactive web UI instead of running in terminal')
	parser.add_argument(
		'--no-highlights', action='store_true', help='Disable bounding boxes on interactive elements in the browser'
	)
	parser.add_argument('--max-steps', type=int, default=30, help='Max agent steps per exploration/execution phase (default: 30)')
	parser.add_argument(
		'--parallel',
		type=int,
		default=3,
		metavar='N',
		help='Number of tests to run concurrently (default: 3)',
	)
	args = parser.parse_args()

	try:
		asyncio.run(_async_main(args))
		return 0
	except KeyboardInterrupt:
		return 0
	except Exception as e:
		logger.error('ERROR: %s', e)
		return 1


async def _async_main(args: argparse.Namespace) -> None:
	from browser_use.browser.profile import BrowserProfile
	from browser_use.browser.session import BrowserSession
	from browser_use.llm import ChatOpenAI
	from murphy.api.auth import detect_auth_required, wait_for_manual_login
	from murphy.browser.patches import apply as apply_patches
	from murphy.core.analysis import analyze_website
	from murphy.core.execution import execute_tests_with_session
	from murphy.core.generation import explore_and_generate_plan, generate_tests
	from murphy.core.summary import build_summary, write_reports_and_print
	from murphy.io.features_io import read_features_markdown, write_features_markdown
	from murphy.io.fixtures import ensure_dummy_fixture_files
	from murphy.io.test_plan_io import load_test_plan, save_test_plan
	from murphy.models import WebsiteAnalysis

	# Apply patches early (idempotent)
	apply_patches()

	# Ensure dummy fixture files exist for upload testing
	fixture_paths = ensure_dummy_fixture_files()

	llm = ChatOpenAI(model=args.model)
	judge_llm = ChatOpenAI(model=args.judge_model) if args.judge_model != args.model else None
	output_dir = Path(args.output_dir)
	output_dir.mkdir(parents=True, exist_ok=True)

	browser_session: BrowserSession | None = None
	analysis: WebsiteAnalysis | None = None

	try:
		# ── Auth detection / login wait ──
		BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

		# Headless by default; show browser when --auth is used (user needs to interact).
		# Explicit BROWSER_USE_HEADLESS env var always takes precedence.
		if os.getenv('BROWSER_USE_HEADLESS') is not None:
			headless = os.getenv('BROWSER_USE_HEADLESS', 'true').lower()[:1] in 'ty1'
		elif CONFIG.IN_DOCKER:
			headless = True
		else:
			headless = not args.auth

		# CI mode: MURPHY_STORAGE_STATE env var provides auth cookies (no local profile needed).
		# Local mode: user_data_dir gives Chrome a persistent profile (cookies persist natively).
		env_storage_state = os.getenv('MURPHY_STORAGE_STATE')
		if env_storage_state:
			# CI: inject cookies from env var, no local profile
			env_storage_state = env_storage_state.strip()
			if env_storage_state.startswith('{'):
				storage_state = json.loads(env_storage_state)
			else:
				storage_state = Path(env_storage_state)
			user_data_dir = None
		else:
			# Local: Chrome profile handles cookie persistence
			storage_state = None
			user_data_dir = BROWSER_PROFILE_DIR

		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				user_data_dir=user_data_dir,
				storage_state=storage_state,
				keep_alive=True,
				headless=headless,
				dom_highlight_elements=not args.no_highlights,
			)
		)
		await browser_session.start()

		if args.auth:
			# --auth flag: skip detection, go straight to login wait
			await wait_for_manual_login(browser_session, llm, args.url)
			# Export decrypted cookies to storage_state.json for CI use
			storage_state_path = BROWSER_PROFILE_DIR / 'storage_state.json'
			await browser_session.export_storage_state(output_path=storage_state_path)
			logger.info('Saved storage state to %s — use as MURPHY_STORAGE_STATE in CI', storage_state_path)
			logger.info('Continuing with authenticated session...\n')
		elif not args.no_auth:
			# Auto-detect: navigate and let the LLM decide
			auth_required = await detect_auth_required(browser_session, llm, args.url)
			if auth_required:
				await wait_for_manual_login(browser_session, llm, args.url, already_navigated=True)
				# Export decrypted cookies to storage_state.json for CI use
				storage_state_path = BROWSER_PROFILE_DIR / 'storage_state.json'
				await browser_session.export_storage_state(output_path=storage_state_path)
				logger.info('Saved storage state to %s — use as MURPHY_STORAGE_STATE in CI', storage_state_path)
				logger.info('Continuing with authenticated session...\n')

		# ── Phase 1–2: Discover features & generate plan ──
		use_exploration_first = bool(args.goal and not args.features and not args.plan)

		if args.plan:
			# Skip both analysis and test generation
			plan_path = Path(args.plan)
			assert plan_path.exists(), f'Plan file not found: {plan_path}'
			url, test_plan = load_test_plan(plan_path)
			if url != args.url:
				logger.warning('Plan URL (%s) differs from --url (%s). Using --url.', url, args.url)
			logger.info('Loaded %d scenarios from %s', len(test_plan.scenarios), plan_path)
		elif use_exploration_first:
			# Exploration-first path: explore → summarize → synthesize plan
			test_plan = await explore_and_generate_plan(
				task=args.goal,
				url=args.url,
				llm=llm,
				session=browser_session,
				max_scenarios=args.max_tests,
				max_steps=args.max_steps,
			)

			# Save test plan to YAML
			plan_path = save_test_plan(args.url, test_plan, output_dir)
			logger.info('\n  Test plan saved: %s', plan_path)
			print('  Review and edit the file, then press Enter to continue.')
			print('  (Add, remove, or modify test scenarios as needed.)\n')

			loop = asyncio.get_event_loop()
			await loop.run_in_executor(None, lambda: input('  Press Enter to continue...  '))

			# Re-read in case user edited
			_, test_plan = load_test_plan(plan_path)
			logger.info('  Using %d test scenarios.\n', len(test_plan.scenarios))
		else:
			if args.features:
				# Load features from existing file
				features_path = Path(args.features)
				assert features_path.exists(), f'Features file not found: {features_path}'
				analysis = read_features_markdown(features_path)
				logger.info('Loaded %d features from %s', len(analysis.features), features_path)
			else:
				# Run analysis agent (feature-discovery path)
				analysis = await analyze_website(args.url, llm, goal=args.goal, browser_session=browser_session)

				# Save features markdown
				features_path = write_features_markdown(analysis, output_dir)
				logger.info('\n  Features saved: %s', features_path)
				print('  Review and edit the file, then press Enter to continue.')
				print('  (Add, remove, or modify features as needed.)\n')

				loop = asyncio.get_event_loop()
				await loop.run_in_executor(None, lambda: input('  Press Enter to continue...  '))

				# Re-read in case user edited
				analysis = read_features_markdown(features_path)
				logger.info('  Using %d features for test generation.\n', len(analysis.features))

			# ── Generate tests ──
			test_plan = await generate_tests(args.url, analysis, llm, args.max_tests, goal=args.goal)

			# Save test plan to YAML
			plan_path = save_test_plan(args.url, test_plan, output_dir)
			logger.info('\n  Test plan saved: %s', plan_path)
			print('  Review and edit the file, then press Enter to continue.')
			print('  (Add, remove, or modify test scenarios as needed.)\n')

			loop = asyncio.get_event_loop()
			await loop.run_in_executor(None, lambda: input('  Press Enter to continue...  '))

			# Re-read in case user edited
			_, test_plan = load_test_plan(plan_path)
			logger.info('  Using %d test scenarios.\n', len(test_plan.scenarios))

		# Ensure analysis exists for report writing (--goal and --plan paths skip feature discovery)
		if analysis is None:
			if args.goal:
				stub_description = f'Goal-directed evaluation: {args.goal}'
			elif args.plan:
				stub_description = f'Loaded from plan file: {args.plan}'
			else:
				stub_description = 'No feature discovery performed'
			analysis = WebsiteAnalysis(
				site_name=args.url,
				category='uncategorized',
				description=stub_description,
				key_pages=[],
				features=[],
				identified_user_flows=[],
			)

		# ── Phase 3: Execute ──
		def _on_test_complete(results: list[TestResult]) -> None:
			if analysis:
				write_reports_and_print(args.url, analysis, results, output_dir)

		if not args.ui:
			results = await execute_tests_with_session(
				args.url,
				test_plan,
				llm,
				browser_session,
				goal=args.goal,
				fixture_paths=fixture_paths,
				max_steps=args.max_steps,
				save_callback=_on_test_complete,
				max_concurrent=args.parallel,
				judge_llm=judge_llm,
			)
			if analysis:
				write_reports_and_print(args.url, analysis, results, output_dir)
			else:
				_log_results_summary(results)
			return

		# ── Server UI mode (--ui) ──
		from murphy.api.server import ServerState, start_server

		_browser_session = browser_session  # capture for closure

		async def _execute_fn(plan: TestPlan, state: ServerState) -> list[TestResult]:
			return await execute_tests_with_session(
				args.url,
				plan,
				llm,
				_browser_session,
				progress_state=state,
				goal=args.goal,
				fixture_paths=fixture_paths,
				max_steps=args.max_steps,
				save_callback=_on_test_complete,
				max_concurrent=args.parallel,
				judge_llm=judge_llm,
			)

		state = ServerState(
			url=args.url,
			analysis=analysis,
			test_plan=test_plan,
			execute_fn=_execute_fn,
		)
		state.build_summary_fn = build_summary

		runner, port = await start_server(state)

		logger.info('  Press Ctrl+C to stop the server.\n')
		try:
			while True:
				await asyncio.sleep(1)
				if state.done and state.results and not getattr(state, '_reports_written', False):
					if analysis:
						write_reports_and_print(args.url, analysis, state.results, output_dir)
					else:
						_log_results_summary(state.results)
					state._reports_written = True  # type: ignore[attr-defined]
		except KeyboardInterrupt:
			pass
		finally:
			await runner.cleanup()

	finally:
		if browser_session:
			await browser_session.kill()


def _log_results_summary(results: list[TestResult]) -> None:
	from murphy.core.summary import build_summary

	summary = build_summary(results)
	logger.info('\n%s', '=' * 60)
	logger.info('Evaluation Complete')
	logger.info('%s', '=' * 60)
	logger.info('\n  Pass rate: %s%% (%d/%d)', summary.pass_rate, summary.passed, summary.total)


if __name__ == '__main__':
	sys.exit(main())
