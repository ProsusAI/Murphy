"""Murphy — test plan generation (Phase 2 of evaluation)."""

import logging
from typing import Any

from browser_use import Agent
from browser_use.browser.session import BrowserSession
from browser_use.llm import BaseChatModel, SystemMessage, UserMessage
from murphy.browser.actions import register_domain_access_action, register_refresh_dom_action
from murphy.browser.session_utils import prepare_session_for_task
from murphy.config import EXPLORE_MAX_STEPS, QUALITY_MAX_RETRIES
from murphy.core.quality import plan_quality_issues
from murphy.models import PERSONA_REGISTRY, TestPlan, TestScenario, WebsiteAnalysis
from murphy.personas.bridge import get_discovered_persona_names
from murphy.personas.pipeline_models import PersonaResult, TraitSchema
from murphy.prompts import (
	build_exploration_prompt,
	build_plan_synthesis_prompt,
	build_test_generation_prompt,
	build_test_generation_system_message,
)

logger = logging.getLogger(__name__)


_INTERACTIVE_GOAL_KEYWORDS = (
	'add',
	'book',
	'buy',
	'change',
	'checkout',
	'complete',
	'configure',
	'create',
	'delete',
	'disable',
	'download',
	'edit',
	'enable',
	'filter',
	'login',
	'order',
	'purchase',
	'save',
	'search',
	'select',
	'send',
	'set up',
	'setup',
	'sign in',
	'sign up',
	'submit',
	'switch',
	'test',
	'toggle',
	'try',
	'update',
	'upload',
	'use',
)

_STATE_CHANGE_GOAL_KEYWORDS = (
	'change',
	'disable',
	'enable',
	'mode',
	'preference',
	'setting',
	'switch',
	'toggle',
	'turn off',
	'turn on',
)

_CREATION_OR_SUBMISSION_GOAL_KEYWORDS = (
	'add',
	'book',
	'buy',
	'checkout',
	'complete',
	'configure',
	'create',
	'creation',
	'new',
	'order',
	'purchase',
	'save',
	'send',
	'set up',
	'setup',
	'sign up',
	'submit',
	'upload',
)


def _matches_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
	"""Return True if any objective keyword appears in text."""
	normalized = text.lower()
	return any(keyword in normalized for keyword in keywords)


def _lite_goal_requires_interaction(task: str) -> bool:
	"""Whether a lite objective should require at least one in-app interaction."""
	return _matches_any_keyword(task, _INTERACTIVE_GOAL_KEYWORDS)


def _lite_goal_is_state_change(task: str) -> bool:
	"""Whether a lite objective is primarily about changing UI or app state."""
	return _matches_any_keyword(task, _STATE_CHANGE_GOAL_KEYWORDS)


def _lite_goal_is_creation_or_submission(task: str) -> bool:
	"""Whether a lite objective likely needs safe test input and advancement."""
	return _matches_any_keyword(task, _CREATION_OR_SUBMISSION_GOAL_KEYWORDS)


def _build_lite_objective_steps(url: str, task: str) -> str:
	"""Build generalized objective-driven steps for lite mode."""
	steps = [
		f'Complete this objective on {url}: {task}.',
		'Minimum required path:',
		'1. Locate the most plausible in-app route for the objective. If a control is ambiguous but plausibly relevant, try it and report the ambiguity afterward.',
	]

	if _lite_goal_is_creation_or_submission(task):
		steps.extend(
			[
				'2. Attempt the objective by initiating the route, providing harmless test input only for fields required to continue, and advancing one step at a time.',
				'3. Advance or submit only when safe; stop before destructive, payment, external-domain, or support/contact/feedback actions unless the objective explicitly requires reporting that blocker.',
			]
		)
	elif _lite_goal_is_state_change(task):
		steps.extend(
			[
				'2. Change the requested state using the most plausible in-app control or setting.',
				'3. Check whether the requested state is reflected in the visible UI or remains in effect after a simple in-app navigation or refresh when safe.',
			]
		)
	elif _lite_goal_requires_interaction(task):
		steps.extend(
			[
				'2. Attempt the objective through the most plausible in-app interaction rather than stopping at observation.',
				'3. Continue until the objective is completed, blocked, or objectively unavailable.',
			]
		)
	else:
		steps.extend(
			[
				'2. Inspect the experience through the persona lens and interact with any clearly relevant in-app controls if they are needed to evaluate the objective.',
				'3. Stop when you have concrete observed evidence for the objective.',
			]
		)

	steps.extend(
		[
			'4. Verify the resulting UI state using visible evidence such as confirmation, validation, changed state, blocked state, persisted state, or clear absence of a plausible route.',
			'5. Return concise lite output with flaws, improvements, fixes, and other observations grounded in what you attempted and observed.',
		]
	)
	return '\n'.join(steps)


def make_lite_plan(
	url: str,
	goal: str | None = None,
	analysis: WebsiteAnalysis | None = None,
	max_tests: int | None = None,
	discovered_personas: tuple[PersonaResult, TraitSchema] | None = None,
) -> TestPlan:
	"""Create a compact lite-mode plan without an LLM generation call."""
	if discovered_personas:
		personas = get_discovered_persona_names(discovered_personas[0])
	else:
		personas = list(PERSONA_REGISTRY.keys())
	if max_tests is not None:
		personas = personas[:max_tests]

	core_features = [f for f in (analysis.features if analysis else []) if f.importance == 'core']
	testable_features = [f for f in (analysis.features if analysis else []) if f.testability in ('testable', 'partial')]
	primary_feature = (core_features or testable_features)[0] if (core_features or testable_features) else None
	target_feature = primary_feature.name if primary_feature else (goal or 'overall site experience')
	feature_category = primary_feature.category if primary_feature else 'other'
	site_name = analysis.site_name if analysis else url
	task = goal or f'Evaluate {site_name}'

	steps_parts = [_build_lite_objective_steps(url, task)]
	if analysis and analysis.identified_user_flows:
		steps_parts.append('Relevant user flows:\n' + '\n'.join(f'- {flow}' for flow in analysis.identified_user_flows))
	if core_features:
		steps_parts.append('Core features:\n' + '\n'.join(f'- {feature.name}' for feature in core_features))
	steps_description = '\n\n'.join(steps_parts)

	scenarios: list[TestScenario] = []
	for index, persona in enumerate(personas):
		priority = 'critical' if index == 0 else 'high'
		scenarios.append(
			TestScenario(
				name=f'Lite {persona.replace("_", " ")} review'[:100],
				description=f'{task} as {persona} on {site_name}.',
				priority=priority,  # type: ignore[arg-type]
				feature_category=feature_category,
				target_feature=target_feature,
				test_persona=persona,
				steps_description=steps_description,
				success_criteria='Return structured flaws, improvements, fixes, and other observations for this goal.',
			)
		)

	logger.info('\n%s', '=' * 60)
	logger.info('Built %d lite scenarios without LLM test generation', len(scenarios))
	logger.info('%s\n', '=' * 60)
	return TestPlan(scenarios=scenarios)


async def generate_tests(
	url: str,
	analysis: 'Any',
	llm: BaseChatModel,
	max_tests: int | None = None,
	goal: str | None = None,
	discovered_personas: tuple[PersonaResult, TraitSchema] | None = None,
) -> TestPlan:
	"""Feature-discovery test generation: analysis → test plan with quality checks.

	``max_tests`` defaults to the number of discovered personas when available,
	falling back to ``DEFAULT_MAX_TESTS`` when no personas are provided.
	"""
	if max_tests is None:
		max_tests = len(discovered_personas[0].personas) if discovered_personas else len(PERSONA_REGISTRY)
	logger.info('\n%s', '=' * 60)
	logger.info('Generating test scenarios')
	logger.info('%s\n', '=' * 60)

	prompt = build_test_generation_prompt(url, analysis, max_tests, goal, discovered_personas=discovered_personas)
	system_msg = SystemMessage(content=build_test_generation_system_message())

	# Build valid persona names set for quality checks
	valid_persona_names: set[str] | None = None
	if discovered_personas:
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
	max_scenarios: int | None = None,
	max_steps: int = 30,
	discovered_personas: tuple[PersonaResult, TraitSchema] | None = None,
) -> TestPlan:
	"""Exploration-first plan generation: explore → summarize → synthesize with quality checks.

	``max_scenarios`` defaults to the number of discovered personas when available,
	falling back to ``DEFAULT_MAX_TESTS`` when no personas are provided.
	"""
	if max_scenarios is None:
		max_scenarios = len(discovered_personas[0].personas) if discovered_personas else len(PERSONA_REGISTRY)
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
		task, url, exploration_context, max_scenarios, discovered_personas=discovered_personas
	)

	# Build valid persona names set for quality checks
	valid_persona_names: set[str] | None = None
	if discovered_personas:
		valid_persona_names = set(get_discovered_persona_names(discovered_personas[0]))

	best_plan: TestPlan | None = None

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

		# If empty, retry with explicit instruction
		if not plan.scenarios and attempt < QUALITY_MAX_RETRIES:
			retry_hint = '\n\nYou returned an empty plan. Generate 5-8 scenarios with diverse personas.\n'
			continue

		best_plan = plan

		# Check quality on first attempt — retry if issues found
		if attempt == 0:
			quality_issues = plan_quality_issues(task, plan, valid_persona_names=valid_persona_names)
			if not quality_issues:
				break
			logger.info('  Quality issues found (%d), regenerating...', len(quality_issues))
		else:
			break

	assert best_plan is not None and best_plan.scenarios, 'Failed to generate any test scenarios'

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
