"""Murphy — test plan generation (Phase 2 of evaluation)."""

import logging
from typing import Any

from browser_use import Agent
from browser_use.browser.session import BrowserSession
from browser_use.llm import BaseChatModel, SystemMessage, UserMessage
from murphy.config import EXPLORE_MAX_STEPS, QUALITY_MAX_RETRIES
from murphy.core.quality import plan_quality_issues
from murphy.models import TestPlan
from murphy.personas.pipeline_models import PersonaResult, TraitSchema
from murphy.prompts import build_plan_synthesis_prompt, build_test_generation_prompt, build_test_generation_system_message

logger = logging.getLogger(__name__)


async def generate_tests(
	url: str,
	analysis: 'Any',
	llm: BaseChatModel,
	max_tests: int,
	goal: str | None = None,
	discovered_personas: tuple[PersonaResult, TraitSchema] | None = None,
	persona_slug: str | None = None,
) -> TestPlan:
	"""Feature-discovery test generation: analysis → test plan with quality checks."""
	logger.info('\n%s', '=' * 60)
	logger.info('Generating test scenarios')
	logger.info('%s\n', '=' * 60)

	prompt = build_test_generation_prompt(
		url, analysis, max_tests, goal, discovered_personas=discovered_personas, persona_slug=persona_slug
	)
	system_msg = SystemMessage(content=build_test_generation_system_message())

	# Build valid persona names set for quality checks
	valid_persona_names: set[str] | None = None
	if discovered_personas:
		from murphy.personas.bridge import get_discovered_persona_names

		valid_persona_names = set(get_discovered_persona_names(discovered_personas[0]))

	quality_task = goal or f'evaluate {url}'
	best_plan: TestPlan | None = None

	for attempt in range(QUALITY_MAX_RETRIES + 1):
		retry_hint = ''
		if attempt > 0 and best_plan is not None:
			quality_issues = plan_quality_issues(quality_task, best_plan, valid_persona_names=valid_persona_names)
			if quality_issues:
				retry_hint = (
					'\n\nPREVIOUS ATTEMPT HAD QUALITY ISSUES — fix these:\n'
					+ '\n'.join(f'- {issue}' for issue in quality_issues)
					+ '\n'
				)
			else:
				break  # No issues, accept the plan

		response = await llm.ainvoke(
			messages=[system_msg, UserMessage(content=prompt + retry_hint)],
			output_format=TestPlan,
		)

		plan = response.completion
		assert isinstance(plan, TestPlan), f'Expected TestPlan, got {type(plan)}'

		# If empty, retry with explicit instruction
		if not plan.scenarios and attempt < QUALITY_MAX_RETRIES:
			retry_hint = '\n\nYou returned an empty plan. Generate 5-8 scenarios with diverse personas.\n'
			continue

		best_plan = plan

		# Check quality on first attempt — retry if issues found
		if attempt == 0:
			quality_issues = plan_quality_issues(quality_task, plan, valid_persona_names=valid_persona_names)
			if not quality_issues:
				break
			logger.info('  Quality issues found (%d), regenerating...', len(quality_issues))
		else:
			break

	assert best_plan is not None and best_plan.scenarios, 'Failed to generate any test scenarios'

	_log_plan_summary(best_plan)
	return best_plan


async def explore_and_generate_plan(
	task: str,
	url: str,
	llm: BaseChatModel,
	session: BrowserSession,
	max_scenarios: int = 8,
	max_steps: int = 30,
	discovered_personas: tuple[PersonaResult, TraitSchema] | None = None,
	persona_slug: str | None = None,
) -> TestPlan:
	"""Exploration-first plan generation: explore → summarize → synthesize with quality checks."""
	from murphy.browser.actions import register_domain_access_action, register_refresh_dom_action
	from murphy.browser.session_utils import prepare_session_for_task
	from murphy.prompts import build_exploration_prompt

	logger.info('\n%s', '=' * 60)
	logger.info('Exploration-first plan generation')
	logger.info('  Task: %s', task)
	logger.info('  URL: %s', url)
	logger.info('%s\n', '=' * 60)

	# Step 1: Prepare session
	await prepare_session_for_task(session, url, force_navigate=False)

	# Step 2: Run exploration agent
	logger.info('Exploring UI...')
	explore_agent = Agent(
		task=build_exploration_prompt(task, url),
		llm=llm,
		browser_session=session,
		use_judge=False,
		max_actions_per_step=3,
	)
	# Register custom actions on the explore agent's tools
	register_domain_access_action(explore_agent.tools, session)
	register_refresh_dom_action(explore_agent.tools, session)

	explore_steps = min(max_steps, EXPLORE_MAX_STEPS)
	explore_history = await explore_agent.run(max_steps=explore_steps)

	# Step 3: Synthesize discovered context
	exploration_context = summarize_exploration_from_actions(
		explore_history.model_actions(),
		url,
	)
	logger.info('\n  Exploration complete. Summarized %d actions.\n', len(explore_history.model_actions()))

	# Step 4: Generate plan with quality checks
	logger.info('Synthesizing test plan...')
	synthesis_prompt = build_plan_synthesis_prompt(
		task,
		url,
		exploration_context,
		max_scenarios,
		discovered_personas=discovered_personas,
		persona_slug=persona_slug,
	)

	# Build valid persona names set for quality checks
	valid_persona_names: set[str] | None = None
	if discovered_personas:
		from murphy.personas.bridge import get_discovered_persona_names

		valid_persona_names = set(get_discovered_persona_names(discovered_personas[0]))

	best_plan: TestPlan | None = None

	last_exc: Exception | None = None

	for attempt in range(QUALITY_MAX_RETRIES + 1):
		retry_hint = ''
		if attempt > 0 and best_plan is not None:
			quality_issues = plan_quality_issues(task, best_plan, valid_persona_names=valid_persona_names)
			if quality_issues:
				retry_hint = (
					'\n\nPREVIOUS ATTEMPT HAD QUALITY ISSUES — fix these:\n'
					+ '\n'.join(f'- {issue}' for issue in quality_issues)
					+ '\n'
				)
			else:
				break  # No issues, accept the plan

		if attempt > 0:
			logger.info('  Synthesis attempt %d/%d...', attempt + 1, QUALITY_MAX_RETRIES + 1)

		try:
			response = await llm.ainvoke(
				messages=[
					SystemMessage(
						content=(
							'You are a QA strategist. Produce valid structured test plans from observed UI evidence. '
							'Every scenario must reference concrete UI elements observed during exploration.'
						)
					),
					UserMessage(content=synthesis_prompt + retry_hint),
				],
				output_format=TestPlan,
			)
			plan = response.completion
			assert isinstance(plan, TestPlan), f'Expected TestPlan, got {type(plan)}'
		except Exception as exc:
			last_exc = exc
			logger.warning('  Synthesis attempt %d failed (%s), retrying...', attempt + 1, exc)
			if attempt < QUALITY_MAX_RETRIES:
				continue
			break

		# If empty, retry with explicit instruction
		if not plan.scenarios and attempt < QUALITY_MAX_RETRIES:
			retry_hint = '\n\nYou returned an empty plan. Generate 5-8 scenarios with diverse personas.\n'
			continue

		best_plan = plan
		last_exc = None

		# Check quality on first attempt — retry if issues found
		if attempt == 0:
			quality_issues = plan_quality_issues(task, plan, valid_persona_names=valid_persona_names)
			if not quality_issues:
				break
			logger.info('  Quality issues found (%d), regenerating...', len(quality_issues))
		else:
			break

	if best_plan is None or not best_plan.scenarios:
		if last_exc is not None:
			raise RuntimeError(
				f'Plan synthesis failed after {QUALITY_MAX_RETRIES + 1} attempts. Last error: {last_exc}'
			) from last_exc
		raise AssertionError('Failed to generate any test scenarios')

	_log_plan_summary(best_plan)
	return best_plan


def summarize_exploration_from_actions(actions: list[dict[str, Any]], url: str) -> str:
	"""Extract pages visited, clicks, and inputs from action history into a text summary."""
	lines: list[str] = []
	pages_seen: list[str] = []

	for i, action in enumerate(actions, 1):
		interacted = action.get('interacted_element')
		for key, val in action.items():
			if key == 'interacted_element':
				continue

			if key in ('navigate', 'go_to_url'):
				nav_url = val.get('url', '?') if isinstance(val, dict) else '?'
				lines.append(f'{i}. NAVIGATE → {nav_url}')
				if isinstance(val, dict) and val.get('url'):
					pages_seen.append(val['url'])

			elif key == 'click_element':
				el_desc = ''
				if interacted and isinstance(interacted, dict):
					tag = interacted.get('tag_name', '?')
					text = interacted.get('text', '')
					href = (
						interacted.get('attributes', {}).get('href', '') if isinstance(interacted.get('attributes'), dict) else ''
					)
					el_desc = f'<{tag}> "{text}"'
					if href:
						el_desc += f' → href="{href}"'
				else:
					idx = val.get('index', '?') if isinstance(val, dict) else '?'
					el_desc = f'element {idx}'
				lines.append(f'{i}. CLICK {el_desc}')

			elif key == 'input_text':
				text = val.get('text', '') if isinstance(val, dict) else ''
				lines.append(f'{i}. TYPE "{text[:50]}"')

			elif key == 'scroll':
				direction = 'down' if (isinstance(val, dict) and val.get('down', True)) else 'up'
				lines.append(f'{i}. SCROLL {direction}')

			elif key == 'done':
				lines.append(f'{i}. DONE')

	# Deduplicate pages
	unique_pages = list(dict.fromkeys(pages_seen))
	summary_parts = []
	if unique_pages:
		summary_parts.append('Pages visited:\n' + '\n'.join(f'  - {p}' for p in unique_pages))
	summary_parts.append('\nAction trace:\n' + '\n'.join(lines) if lines else '(no actions)')
	return '\n'.join(summary_parts)


def _log_plan_summary(plan: TestPlan) -> None:
	"""Log generated plan summary."""
	logger.info('Generated %d test scenarios:', len(plan.scenarios))
	for i, s in enumerate(plan.scenarios, 1):
		logger.info('  %d. [%s] [%s] %s (%s)', i, s.priority.upper(), s.test_persona, s.name, s.feature_category)
