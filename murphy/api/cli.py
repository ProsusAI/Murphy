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
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv

from browser_use.config import CONFIG
from browser_use.tokens.service import TokenCost

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
	parser.add_argument('--url', help='Target URL to evaluate (required unless --open)')
	parser.add_argument('--goal', help="Free-text goal to bias test generation (e.g. 'test the checkout flow')")
	parser.add_argument('--auth', action='store_true', help='Skip auto-detection and go straight to manual login wait')
	parser.add_argument('--no-auth', action='store_true', help='Skip auth detection entirely, treat site as public')
	parser.add_argument('--features', help='Path to existing features markdown (skips analysis, goes to test generation)')
	parser.add_argument('--plan', help='Path to existing YAML test plan (skips analysis + test generation)')
	parser.add_argument('--max-tests', type=int, default=8, help='Max test scenarios (default: 8)')
	parser.add_argument(
		'--provider', default='openai', help='LLM provider (default: openai). e.g. google, anthropic, azure, mistral'
	)
	parser.add_argument(
		'--model', default='gpt-5-mini', help='LLM model name as it appears in the provider docs (default: gpt-5-mini)'
	)
	parser.add_argument('--judge-provider', default=None, help='LLM provider for judging (defaults to --provider)')
	parser.add_argument('--judge-model', default=None, help='LLM model for judging (defaults to --model)')
	parser.add_argument('--output-dir', default='./murphy/output', help='Output directory for reports')
	parser.add_argument(
		'--open',
		action='store_true',
		help='Open existing results from --output-dir without running tests',
	)
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
	parser.add_argument(
		'--discover-personas',
		action='store_true',
		help='Run persona discovery pipeline first, then use discovered personas for testing',
	)
	parser.add_argument(
		'--personas',
		nargs='?',
		const=True,
		default=None,
		metavar='PATH',
		help='Use discovered personas (default: {output_dir}/personas.json, or specify a path)',
	)
	args = parser.parse_args()

	if not args.open and not args.url:
		parser.error('--url is required unless using --open')

	try:
		asyncio.run(_async_main(args))
		return 0
	except KeyboardInterrupt:
		return 0
	except Exception as e:
		logger.error('ERROR: %s', e)
		return 1


async def _async_main(args: argparse.Namespace) -> None:
	if args.open:
		await _open_mode(Path(args.output_dir))
		return

	from browser_use.browser.profile import BrowserProfile
	from browser_use.browser.session import BrowserSession
	from murphy.api.auth import detect_auth_required, wait_for_manual_login
	from murphy.browser.cleanup import clear_browser_pid, get_browser_pid_from_session, kill_stale_browser, record_browser_pid
	from murphy.browser.patches import apply as apply_patches
	from murphy.core.analysis import analyze_website
	from murphy.core.execution import execute_tests_with_session
	from murphy.core.generation import explore_and_generate_plan, generate_tests
	from murphy.core.summary import build_summary, write_reports_and_print
	from murphy.io.features_io import read_features_markdown, write_features_markdown
	from murphy.io.fixtures import ensure_dummy_fixture_files
	from murphy.io.test_plan_io import load_test_plan, save_test_plan
	from murphy.llm import create_llm
	from murphy.models import TokenUsage, WebsiteAnalysis

	# Kill any orphan browser from a previous crashed run
	kill_stale_browser()

	# Apply patches early (idempotent)
	apply_patches()

	# Ensure dummy fixture files exist for upload testing
	fixture_paths = ensure_dummy_fixture_files()

	llm = create_llm(args.model, provider=args.provider)
	judge_provider = args.judge_provider or args.provider
	judge_model = args.judge_model or args.model
	judge_llm = (
		create_llm(judge_model, provider=judge_provider)
		if (judge_model != args.model or judge_provider != args.provider)
		else None
	)
	output_dir = Path(args.output_dir)
	output_dir.mkdir(parents=True, exist_ok=True)

	# ── Token tracking for Murphy execution ──
	murphy_token_cost = TokenCost()
	murphy_token_cost.register_llm(llm)
	if judge_llm is not None:
		murphy_token_cost.register_llm(judge_llm)

	persona_discovery_tokens: TokenUsage | None = None

	# ── Resolve discovered personas ──
	discovered_personas: tuple[PersonaResult, TraitSchema] | None = None

	if args.discover_personas:
		from murphy.personas.pipeline import run_persona_pipeline

		logger.info('Running persona discovery pipeline...')
		schema, _scores, persona_result, _sample, persona_discovery_tokens = await run_persona_pipeline(
			model=args.model,
			discovery_sessions=100,
			scoring_sessions=200,
			num_clusters=8,
		)
		save_personas(schema, persona_result, output_dir)
		discovered_personas = (persona_result, schema)
		logger.info('Discovered %d personas, saved to %s', len(persona_result.personas), output_dir / 'personas.json')
	elif args.personas is not None:
		if args.personas is True:
			personas_path = output_dir / 'personas.json'
		else:
			personas_path = Path(args.personas)
		assert personas_path.exists(), f'Personas file not found: {personas_path}'
		schema, persona_result = load_personas(personas_path)
		discovered_personas = (persona_result, schema)

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

		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				user_data_dir=BROWSER_PROFILE_DIR,
				keep_alive=True,
				headless=headless,
				dom_highlight_elements=not args.no_highlights,
			)
		)
		await browser_session.start()

		browser_pid = get_browser_pid_from_session(browser_session)
		if browser_pid:
			record_browser_pid(browser_pid)

		if args.auth:
			# --auth flag: skip detection, go straight to login wait
			await wait_for_manual_login(browser_session, llm, args.url)
			logger.info('Continuing with authenticated session...\n')
		elif not args.no_auth:
			# Auto-detect: navigate and let the LLM decide
			auth_required = await detect_auth_required(browser_session, llm, args.url)
			if auth_required:
				await wait_for_manual_login(browser_session, llm, args.url, already_navigated=True)
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
				discovered_personas=discovered_personas,
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
			test_plan = await generate_tests(
				args.url, analysis, llm, args.max_tests, goal=args.goal, discovered_personas=discovered_personas
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
		def _get_murphy_tokens() -> TokenUsage:
			usage = murphy_token_cost.get_usage_tokens_for_model(args.model)
			total_input = usage.prompt_tokens
			total_output = usage.completion_tokens
			if judge_llm is not None:
				judge_usage = murphy_token_cost.get_usage_tokens_for_model(args.judge_model)
				total_input += judge_usage.prompt_tokens
				total_output += judge_usage.completion_tokens
			return TokenUsage(input_tokens=total_input, output_tokens=total_output)

		def _on_test_complete(results: list[TestResult]) -> None:
			if analysis:
				write_reports_and_print(
					args.url,
					analysis,
					results,
					output_dir,
					persona_discovery_tokens=persona_discovery_tokens,
					murphy_tokens=_get_murphy_tokens(),
				)

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
				output_dir=output_dir,
				discovered_personas=discovered_personas,
			)
			if analysis:
				write_reports_and_print(
					args.url,
					analysis,
					results,
					output_dir,
					persona_discovery_tokens=persona_discovery_tokens,
					murphy_tokens=_get_murphy_tokens(),
				)
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
				output_dir=output_dir,
				discovered_personas=discovered_personas,
			)

		state = ServerState(
			url=args.url,
			analysis=analysis,
			test_plan=test_plan,
			execute_fn=_execute_fn,
			output_dir=output_dir,
		)
		state.build_summary_fn = build_summary

		runner, port = await start_server(state)

		logger.info('  Press Ctrl+C to stop the server.\n')
		try:
			while True:
				await asyncio.sleep(1)
				if state.done and state.results and not getattr(state, '_reports_written', False):
					if analysis:
						write_reports_and_print(
							args.url,
							analysis,
							state.results,
							output_dir,
							persona_discovery_tokens=persona_discovery_tokens,
							murphy_tokens=_get_murphy_tokens(),
						)
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
		clear_browser_pid()


async def _open_mode(output_dir: Path) -> None:
	"""Start the results server from existing evaluation_report.json (no browser/LLM)."""
	from murphy.api.server import ServerState, start_server
	from murphy.models import EvaluationReport

	report_path = output_dir / 'evaluation_report.json'
	if not report_path.exists():
		raise FileNotFoundError(f'No report found at {report_path}')

	report = EvaluationReport.model_validate_json(report_path.read_text())
	state = ServerState(
		url=report.url,
		analysis=report.analysis,
		test_plan=None,
		execute_fn=None,
		output_dir=output_dir,
	)
	state.results = report.results
	state.summary = report.summary
	state.done = True

	runner, _ = await start_server(state)
	logger.info('  Press Ctrl+C to stop.\n')
	stop_event = asyncio.Event()
	try:
		await stop_event.wait()
	except KeyboardInterrupt:
		pass
	finally:
		await runner.cleanup()


def _log_results_summary(results: list[TestResult]) -> None:
	from murphy.core.summary import build_summary

	summary = build_summary(results)
	logger.info('\n%s', '=' * 60)
	logger.info('Evaluation Complete')
	logger.info('%s', '=' * 60)
	logger.info('\n  Pass rate: %s%% (%d/%d)', summary.pass_rate, summary.passed, summary.total)


if __name__ == '__main__':
	sys.exit(main())
