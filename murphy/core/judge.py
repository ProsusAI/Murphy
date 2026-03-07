"""
Murphy's own judge — evaluates agent success based on action trace, not self-report.

The key difference from browser_use's built-in judge: this treats the action trace
(navigations, clicks, form submissions, URLs visited) as primary evidence of task
completion, rather than demanding the agent explicitly report what it did.

Pre-processes raw action data into clean, human-readable evidence so the LLM judge
can't miss navigation proof buried in nested JSON.
"""

from browser_use.agent.views import AgentHistoryList
from browser_use.llm import ChatOpenAI, SystemMessage, UserMessage
from browser_use.llm.messages import ContentPartImageParam, ContentPartTextParam, ImageURL
from browser_use.utils import sanitize_surrogates
from murphy.models import (
	PERSONA_REGISTRY,
	JudgeVerdict,
	TestScenario,
	TestType,
	TraitLevel,
	TraitVector,
)

TRAIT_JUDGE_QUESTIONS: dict[str, dict[TraitLevel, str]] = {
	'technical_literacy': {
		TraitLevel.low: 'Would a user unfamiliar with UI conventions understand what happened? Labels, icons, affordances must be self-explanatory without domain knowledge. This user needs explicit text, not just icons or color cues.',
		TraitLevel.medium: 'Were standard UI patterns followed? Would a typical web user understand the interaction?',
		TraitLevel.high: 'Were expert-level controls available and efficient?',
	},
	'patience': {
		TraitLevel.low: 'Did the site communicate state IMMEDIATELY? Loading indicators, progress bars, "please wait" messages? This user interprets 2+ seconds of silence as broken. Silent deduplication with no feedback = FAIL.',
		TraitLevel.medium: 'Did the site provide timely feedback within reasonable expectations?',
		TraitLevel.high: 'Did the site complete the task correctly, regardless of timing?',
	},
	'reading_comprehension': {
		TraitLevel.low: 'Was critical information conveyed through visual hierarchy: bold labels, color coding, icons, position-based cues? Error messages in body text are invisible to this user.',
		TraitLevel.medium: 'Were important messages prominent and scannable?',
		TraitLevel.high: 'Was detailed information available for thorough readers?',
	},
	'exploration': {
		TraitLevel.high: 'Did the site provide ORIENTATION at every step? Breadcrumbs, page titles, "no results" messages? Dead ends with no feedback = FAIL.',
		TraitLevel.medium: 'Did the site handle minor path deviations gracefully?',
		TraitLevel.low: 'Did the expected path work without requiring exploration?',
	},
}

TEST_TYPE_RULES: dict[TestType, str] = {
	'ux': 'Silent handling with no visible feedback is a FAIL. The user must understand what happened.',
	'security': 'Silent sanitization is CORRECT behavior. Only fail on crash, data leak, or code execution.',
	'boundary': 'Graceful degradation (even silent) is a PASS. Only fail on unhandled exception or corrupted state.',
}


def build_judge_trait_context(persona: str, traits: TraitVector, test_type: TestType) -> str:
	"""Assemble per-trait evaluation questions from the trait vector + test_type."""
	lines: list[str] = []
	lines.append(f'## Persona: {persona}')
	lines.append(f'## Test type: {test_type}')
	lines.append(f'## Test type rule: {TEST_TYPE_RULES[test_type]}')
	lines.append('')
	lines.append('## Per-trait evaluation questions (evaluate each independently):')
	lines.append('')

	trait_fields = {
		'technical_literacy': traits.technical_literacy,
		'patience': traits.patience,
		'reading_comprehension': traits.reading_comprehension,
		'exploration': traits.exploration,
	}
	for trait_name, level in trait_fields.items():
		assert isinstance(level, TraitLevel)
		question = TRAIT_JUDGE_QUESTIONS[trait_name][level]
		lines.append(f'- **{trait_name}** ({level.name}): {question}')

	# Intent doesn't use TraitLevel — add it directly
	intent = traits.intent
	if intent == 'adversarial':
		lines.append(
			f'- **intent** ({intent}): Is the site RESISTING the attack? Input sanitized or rejected = PASS. Script executed, debug info leaked, raw SQL error = FAIL.'
		)
	elif intent == 'exploratory':
		lines.append(
			f'- **intent** ({intent}): Does the site handle unexpected usage gracefully? Non-crash non-leak behavior = PASS.'
		)
	else:
		lines.append(f'- **intent** ({intent}): Did the site complete the intended task successfully?')

	lines.append('')
	return '\n'.join(lines)


JUDGE_SYSTEM_PROMPT = """\
You are a QA judge evaluating whether a browser automation agent successfully completed a test scenario.

You judge success based on OBSERVABLE ACTIONS, not on what the agent said or reported.

## How to read the evidence

You will receive four evidence sections:

1. **Navigation Evidence** — a pre-extracted summary of every click, navigation, and form interaction the agent performed, plus the actual browser URLs reached. This is your PRIMARY evidence.
2. **Screenshots** — the last few browser screenshots taken during test execution. Use these to verify VISUAL feedback: toasts, error messages, state changes, loading indicators, disabled controls, inline validation. Screenshots are critical for judging UX feedback quality — the action trace alone cannot tell you whether a toast appeared or a button was visually disabled.
3. **Full Step Trace** — the complete step-by-step action log with results and errors.
4. **Agent's Final Response** — what the agent said at the end. This is supplementary only.

## Evaluation rules

- The action trace IS the verification. A click on a link with href="/about-us" followed by the browser URL changing to that path IS proof of successful navigation. No further "verification" is needed.
- If the Navigation Evidence shows the agent clicked the right elements and the browser reached the right URLs, that IS success.
- Real errors in the trace (timeouts, element not found, HTTP errors) weigh against success.
- An agent completing all required interactions with zero errors is strong evidence of success.
- The verdict should be TRUE if the actions and URLs match the success criteria, regardless of what the agent said or did not say in its final response.
- NEVER require the agent to "verify", "confirm", "report", or "provide evidence of" anything. The action trace is the evidence.

## Trait-based evaluation

Each test has a **persona** with a **trait vector** (5 dimensions) and a **test type** (ux/security/boundary). The user prompt includes per-trait evaluation questions and test-type rules assembled from the persona's traits. Use those to structure your evaluation.

Evaluate each trait dimension independently, then synthesize into a verdict. A test can fail on one trait dimension but pass on others — report all of them in `trait_evaluations`.

## Feedback quality assessment

For EVERY test, evaluate the website's feedback quality:
- **response_present**: Did the site produce ANY response to the user's action? (visual change, message, redirect, state update)
- **response_timely**: Did feedback appear within a reasonable time? (< 2s for UI actions)
- **response_clear**: Was the feedback understandable for THIS persona's trait levels? (relative to technical_literacy and reading_comprehension)
- **response_actionable**: Could the user determine what to do next based on the feedback?
- **feedback_type**: Classify the response mechanism (none, silent_handling, visual_state_change, inline_message, toast_notification, modal_dialog, page_redirect, error_page)

## Success criteria interpretation

Success criteria describe the EXPECTED BEHAVIORAL OUTCOME, not the only acceptable implementation. Apply these rules:

- **Flexible mechanism matching**: If the criteria say "the site prevents empty form submission" and the site uses a disabled submit button instead of an error toast, that IS a pass — the behavior (prevention) was achieved through a different mechanism.
- **Quoted text is illustrative, not literal**: Any quoted UI text in criteria (e.g., "'Please fill out this field'") is ONE example of acceptable behavior, not the only acceptable response. A site showing "Required" instead of "Please fill out this field" achieves the same outcome.
- **Alternative outcomes**: When criteria list alternatives separated by OR, ANY one of them is sufficient for a pass.- **Non-happy-path default**: For security-oriented personas (adversarial, edge_case, angry_user), any mechanism that prevents the bad outcome (crash, data leak, unhandled exception, corrupted state) is a PASS. Only FAIL on demonstrable mishandling.
- **Silent handling is valid for security-oriented personas (adversarial, edge_case, angry_user)**: If the site silently sanitizes input, ignores invalid data, or gracefully degrades without any visible feedback, that IS correct behavior for security personas — not a failure. For UX-oriented personas (happy_path, confused_novice, impatient_user, explorer), the site MUST provide visible feedback — a disabled button with no explanation, a silently ignored input, or a form that does nothing on submit is a FAIL.
- **Disabled controls ARE prevention for security-oriented personas**: If a submit/publish/next button is disabled when fields are empty or invalid, that IS the site preventing submission for security personas. For UX-oriented personas, a disabled control MUST be accompanied by visible explanation (tooltip, inline text, grayed-out label explaining why) to count as a PASS.
- **Focus on harm, not form** (security personas): Ask "did the site handle this situation without harm?" not "did the site handle it exactly as described?"
- **Focus on clarity, not just harm** (UX personas): Ask "did the site help the user understand what happened?" not just "did it avoid crashing?" A site that silently swallows user input with no feedback is harmful to UX even if nothing technically broke.

## Missing signals (always report, never fail on)

Even when verdict=true, populate `missing_signals` with any expected confirmation signals that were NOT observed. These are UX observations that do not affect the verdict:
- Ephemeral signals not captured: e.g. "success toast not observed" or "error flash message not seen"
- Status indicators absent: e.g. "'Active' badge not visible on the list entry"
- Secondary confirmations missing: e.g. "confirmation dialog not shown before delete"

If verdict=true and all expected signals were observed, leave `missing_signals` as an empty list.


## Failure classification

If verdict is FALSE, you MUST also classify the failure:
- **website_issue**: The agent executed the test (or got far enough) and observed the website behaving badly — empty page, broken UI, unhandled input, crash, error, missing validation, data corruption.
- **test_limitation**: The agent could NOT complete the test itself — couldn't find an element, ran out of steps, navigated to wrong page, test steps were ambiguous or impossible.
- If the first URL in "Pages Reached" does not match or relate to the "Intended Starting URL", and the agent never navigated to the correct area, classify as **test_limitation** — the test infrastructure failed to place the agent on the right page.

If verdict is TRUE, set failure_category to null.

## Evaluation dimensions

In addition to the verdict, provide three brief evaluation assessments:

1. **process_evaluation**: Assess the step-by-step process quality. Was the flow smooth or did the user encounter friction (extra clicks, unclear navigation, redundant confirmations)? Note any unnecessary steps or confusing transitions.
2. **logical_evaluation**: Assess UI/system logic consistency. Did the application behave logically? Were state changes consistent? Did buttons do what labels promised? Were error messages accurate?
3. **usability_evaluation**: Assess clarity, affordances, and user-friendliness. Were controls discoverable? Was feedback timely? Were labels clear? Would a real user understand what to do next at each step?

Keep each evaluation to 1-3 sentences grounded in the observed action trace.
"""

JUDGE_USER_TEMPLATE = """\
## Test Scenario
**Name:** {name}
**Test Persona:** {persona}
**Description:** {description}
**Steps:** {steps}
**Success Criteria:** {criteria}

{trait_context}

## Intended Starting URL
{start_url}

## Navigation Evidence (pre-extracted)
{navigation_evidence}

## Pages Reached (actual browser URLs, in order)
{pages_reached}

## Full Step Trace
{step_trace}

## Errors
{errors}

## Agent's Final Response
{final_result}

---

## Validation rules
- Validate outcome state before returning a verdict (no inference from partial signals).
- Use visible UI signals only: toasts, badges, list rows, detail cards, confirmation messages.
- For create flows: confirm new entity appears with a recognizable identifier.
- For delete flows: confirm entity is absent from list/search.
- For edit flows: reopen and confirm updates persist.
- If evidence is ambiguous, return verdict=false.

## Signal gaps (for `missing_signals` — never affects verdict)

After determining the verdict, check which expected confirmation signals were NOT observed and list each one in `missing_signals`. Examples:
- "Ephemeral success toast not captured in screenshots or step trace"
- "'Active' status badge not visible on the agent list entry"
- "Confirmation dialog not shown before the destructive action"

These are UX observations only. A non-empty `missing_signals` on a passing test means the site's feedback could be improved — it does NOT change the verdict.

Based on the Navigation Evidence and Pages Reached, did the agent successfully complete this test?
Evaluate each trait dimension independently and report per-trait assessments in trait_evaluations.
Also assess feedback quality (response_present, response_timely, response_clear, response_actionable, feedback_type).
"""


def _extract_navigation_evidence(history: AgentHistoryList) -> str:
	"""Extract a clean, human-readable summary of navigation actions from the raw action trace.

	Pulls out clicked links (with hrefs), navigate actions, form submissions, typing,
	and other interactions — structured so the LLM judge can directly match against
	success criteria without parsing nested JSON.
	"""
	evidence_lines: list[str] = []
	actions = history.model_actions()

	for i, action in enumerate(actions, 1):
		# Each action dict has the action type as first key, plus 'interacted_element'
		interacted = action.get('interacted_element')

		# Extract action type (first key that isn't 'interacted_element')
		action_type = None
		action_params = None
		for key, val in action.items():
			if key != 'interacted_element':
				action_type = key
				action_params = val
				break

		if not action_type:
			continue

		if action_type == 'click_element':
			# Build description from interacted element
			if interacted and isinstance(interacted, dict):
				tag = interacted.get('tag_name', '?')
				text = interacted.get('text', '')
				href = interacted.get('attributes', {}).get('href', '') if isinstance(interacted.get('attributes'), dict) else ''

				if href:
					evidence_lines.append(f'{i}. CLICK: <{tag}> "{text}" → href="{href}"')
				elif text:
					evidence_lines.append(f'{i}. CLICK: <{tag}> "{text}"')
				else:
					index = action_params.get('index', '?') if isinstance(action_params, dict) else '?'
					evidence_lines.append(f'{i}. CLICK: <{tag}> (element {index})')
			else:
				index = action_params.get('index', '?') if isinstance(action_params, dict) else '?'
				evidence_lines.append(f'{i}. CLICK: element {index}')

		elif action_type == 'navigate':
			url = action_params.get('url', '?') if isinstance(action_params, dict) else '?'
			evidence_lines.append(f'{i}. NAVIGATE: → {url}')

		elif action_type == 'input_text':
			if isinstance(action_params, dict):
				text = action_params.get('text', '')
				evidence_lines.append(f'{i}. TYPE: "{text}"')

		elif action_type == 'search':
			if isinstance(action_params, dict):
				query = action_params.get('query', '')
				evidence_lines.append(f'{i}. SEARCH: "{query}"')

		elif action_type == 'scroll':
			direction = 'down' if (isinstance(action_params, dict) and action_params.get('down', True)) else 'up'
			evidence_lines.append(f'{i}. SCROLL: {direction}')

		elif action_type == 'done':
			text = action_params.get('text', '') if isinstance(action_params, dict) else ''
			success = action_params.get('success', True) if isinstance(action_params, dict) else True
			evidence_lines.append(f'{i}. DONE: success={success}')

		elif action_type in ('select_dropdown_option', 'get_dropdown_options'):
			if isinstance(action_params, dict):
				text = action_params.get('text', '')
				evidence_lines.append(f'{i}. {action_type.upper()}: "{text}"')

		elif action_type == 'switch_tab':
			evidence_lines.append(f'{i}. SWITCH TAB')

		else:
			evidence_lines.append(f'{i}. {action_type.upper()}')

	return '\n'.join(evidence_lines) if evidence_lines else '(no actions recorded)'


def _format_pages_reached(history: AgentHistoryList) -> str:
	"""Deduplicate and format the actual browser URLs visited, in order."""
	urls = history.urls()
	# Deduplicate while preserving order
	seen: set[str] = set()
	unique_urls: list[str] = []
	for url in urls:
		if url and url not in seen:
			seen.add(url)
			unique_urls.append(url)

	if not unique_urls:
		return '(no URLs recorded)'

	lines = [f'  {i}. {url}' for i, url in enumerate(unique_urls, 1)]
	return '\n'.join(lines)


async def murphy_judge(
	history: AgentHistoryList,
	scenario: TestScenario,
	llm: ChatOpenAI,
	start_url: str = '',
	*,
	judge_llm: ChatOpenAI | None = None,
) -> JudgeVerdict:
	"""Evaluate agent success based on action trace, not self-report.

	When judge_llm is provided, it is used for the verdict call instead of llm.
	This allows using a more capable model for judging while using a cheaper model elsewhere.
	"""
	judge = judge_llm or llm
	# Pre-processed evidence
	navigation_evidence = _extract_navigation_evidence(history)
	pages_reached = _format_pages_reached(history)

	# Full step trace from agent_steps() — already formatted for judge evaluation
	agent_steps = history.agent_steps()
	step_trace = '\n'.join(agent_steps) if agent_steps else '(no steps recorded)'

	# Errors
	errors = history.errors()
	errors_text = '\n'.join(f'  - Step {i + 1}: {e}' for i, e in enumerate(errors) if e) if any(errors) else '(none)'

	# Final result
	final_result = history.final_result() or '(no final response)'

	# Build trait context for this persona
	trait_context = ''
	persona_entry = PERSONA_REGISTRY.get(scenario.test_persona)
	if persona_entry:
		traits, test_type = persona_entry
		trait_context = build_judge_trait_context(scenario.test_persona, traits, test_type)

	user_prompt = JUDGE_USER_TEMPLATE.format(
		name=scenario.name,
		persona=scenario.test_persona,
		description=scenario.description,
		steps=scenario.steps_description,
		criteria=scenario.success_criteria,
		trait_context=trait_context,
		start_url=start_url or '(not provided)',
		navigation_evidence=navigation_evidence,
		pages_reached=pages_reached,
		step_trace=step_trace,
		errors=errors_text,
		final_result=final_result,
	)
	user_prompt = sanitize_surrogates(user_prompt)

	# Build multimodal user message with screenshots for visual verification
	user_content: list[ContentPartTextParam | ContentPartImageParam] = [
		ContentPartTextParam(text=user_prompt),
	]

	# Attach last N screenshots (base64) — these let the judge verify visual feedback
	screenshots = history.screenshots(n_last=3)
	for i, screenshot_b64 in enumerate(screenshots):
		if screenshot_b64:
			user_content.append(ContentPartTextParam(text=f'\n## Screenshot {i + 1} of {len(screenshots)}'))
			user_content.append(
				ContentPartImageParam(
					image_url=ImageURL(url=f'data:image/png;base64,{screenshot_b64}', detail='low'),
				)
			)

	response = await judge.ainvoke(
		messages=[
			SystemMessage(content=JUDGE_SYSTEM_PROMPT),
			UserMessage(content=user_content),
		],
		output_format=JudgeVerdict,
	)

	verdict = response.completion
	assert isinstance(verdict, JudgeVerdict), f'Expected JudgeVerdict, got {type(verdict)}'

	return verdict
