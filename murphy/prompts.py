"""
Murphy — LLM prompt text for evaluation phases.

Extracted from evaluate.py for maintainability.
"""

from murphy.models import PERSONA_REGISTRY, TestPersona, TestScenario, TraitLevel, TraitVector, WebsiteAnalysis
from murphy.personas.pipeline_models import PersonaResult, TraitSchema

# Percentages for persona distribution in test generation
_PERSONA_DISTRIBUTION: dict[TestPersona, tuple[int, str]] = {
	'happy_path': (15, 'Standard user, expected flow. A skilled user who knows exactly what they want.'),
	'confused_novice': (
		12,
		"Simulate someone who doesn't read labels, clicks wrong buttons, submits empty forms, navigates backward repeatedly.",
	),
	'adversarial': (
		12,
		'Try to break things: XSS payloads, SQL injection, navigate to /admin, submit forms with whitespace, paste HTML tags.',
	),
	'edge_case': (
		10,
		'Empty submissions, extremely long inputs (500+ chars), special characters (emoji, RTL text, null bytes, unicode), double-clicking.',
	),
	'explorer': (
		8,
		'Unexpected navigation patterns — visit pages out of order, use features in unintended combinations, click decorative elements.',
	),
	'impatient_user': (
		10,
		'Click rapidly without waiting, skip required steps, submit forms immediately, navigate away mid-action, spam buttons.',
	),
	'angry_user': (
		8,
		'Rage-clicks buttons repeatedly, force-navigates by typing URLs, submits forms rapidly without waiting, abandons multi-step flows mid-way.',
	),
	'classic_ui': (
		9,
		'Evaluate from the perspective of a user who values readability and familiarity: font sizes must be readable, '
		'labels must be explicit text (not icon-only), layouts must follow familiar conventions '
		'(top nav, visible buttons), and contrast must be high enough for comfortable reading.',
	),
	'modern_ui': (
		8,
		'Evaluate from the perspective of a design-forward user: the site should feel current '
		'and visually engaging — bold colors, modern typography, dark mode vibes, smooth transitions, '
		'and expressive visual identity. Bland stock aesthetics or dated layouts are failures.',
	),
	'layout_auditor_ui': (
		8,
		'Evaluate spacing discipline: every margin, padding, and gutter must follow a consistent scale. '
		'Misaligned elements, cramped card layouts, inconsistent vertical rhythm, or irregular gaps '
		'between sibling components are failures.',
	),
}


def _build_persona_distribution_text() -> str:
	"""Generate persona distribution text from registry for the test generation prompt."""
	lines: list[str] = []
	for persona, (pct, description) in _PERSONA_DISTRIBUTION.items():
		entry = PERSONA_REGISTRY.get(persona)
		if entry:
			traits, test_type = entry
			trait_summary = (
				f'tech_lit={traits.technical_literacy.name}, '
				f'patience={traits.patience.name}, '
				f'intent={traits.intent}, '
				f'exploration={traits.exploration.name}, '
				f'reading={traits.reading_comprehension.name}'
			)
			if test_type == 'design':
				trait_summary += (
					f', density={traits.visual_density_preference.name}'
					f', era={traits.aesthetic_era}'
					f', strictness={traits.layout_strictness.name}'
				)
			lines.append(f'- {persona} (~{pct}%, {test_type}): {description} [Traits: {trait_summary}]')
		else:
			lines.append(f'- {persona} (~{pct}%): {description}')
	return '\n'.join(lines)


def build_analysis_prompt(
	url: str,
	category: str | None = None,
	goal: str | None = None,
	is_authenticated: bool = False,
) -> str:
	"""Return the task prompt string for the analysis agent.

	When is_authenticated=False, starts with "Navigate to {url}..." and uses
	"unauthenticated headless browser" for testability.
	When is_authenticated=True, starts with "You are already logged in to {url}..."
	and uses "authenticated browser" for testability.
	"""
	category_hint = f'\nCategory hint: {category}' if category else ''

	goal_block = ''
	if goal:
		goal_block = (
			f'\nGOAL: Focus your exploration on: {goal}\n'
			f'- Still explore the full site, but pay extra attention to pages/features related to this goal.\n'
			f'- Mark features related to the goal as "core" importance.\n\n'
		)

	if is_authenticated:
		opener = f'You are already logged in to {url}. Discover what users can DO on this site.\n\n'
		browser_type = 'an authenticated browser'
		testability_blockers = 'third-party redirect, CAPTCHA, etc.'
	else:
		opener = f'Navigate to {url} and discover what users can DO on this site.{category_hint}\n\n'
		browser_type = 'an unauthenticated headless browser'
		testability_blockers = 'requires login, third-party redirect, CAPTCHA, etc.'

	return (
		f'{opener}'
		f'{goal_block}'
		f'EXPLORATION (this is the most important part — be thorough):\n'
		f'- Look at the sidebar/top navigation and click EVERY major nav item (e.g. Dashboard, Agents, Tasks, Connectors, Reports, Admin, Profile, Conversations, Settings — whatever exists)\n'
		f'- Do NOT stop after 1-2 pages. You must visit every distinct section in the navigation.\n'
		f'- On each page, note what actions a user can perform (not just what elements exist)\n'
		f'- If you see a list/table, click an item to see the detail view\n'
		f'- Check user profile/settings pages too — those often have important features\n'
		f'- IMPORTANT: This is READ-ONLY exploration. Do NOT click "Delete", "Place Order", or any button that would permanently destroy data or cost money. '
		f'You MAY click "Create", "Submit", "Send", "Save" to explore forms and creation flows — just don\'t confirm irreversible actions.\n'
		f'- IMPORTANT: Stay on the same domain as {url}. Do NOT follow links to external sites (e.g. social media, third-party docs, partner sites). If a link goes to a different domain, note the feature but do not navigate there.\n'
		f'- For each page, classify the page_type (homepage, landing, product, listing, detail, form, content, dashboard, auth, error, other)\n\n'
		f'FEATURE IDENTIFICATION:\n'
		f"- You should find at least 8-15 features for any non-trivial app. If you have fewer than 8, you haven't explored enough — go back and click more nav items.\n"
		f'- Name each feature as a user action: "Create AI agent", "Search tasks", "Upload document" — NOT "Navigation Links" or "Button group"\n'
		f"- A feature = one thing a user can accomplish. If it takes multiple steps, that's still one feature.\n"
		f'- For `elements`, write brief descriptions: "Create button on agents page", "Task name input" — NOT raw hrefs or DOM dumps\n'
		f'- For `page_url`, use the page where the feature is primarily accessed\n'
		f"- Skip generic navigation (header links, footer links, breadcrumbs) — those aren't features\n"
		f'- Skip auth-related elements (login/logout buttons)\n'
		f'- Category: navigation, search, forms, content_display, filtering_sorting, media, authentication, ecommerce, social, other\n'
		f'- Assess testability: can {browser_type} test this? (testable / partial / untestable). '
		f'If not fully testable, explain why ({testability_blockers})\n\n'
		f'IMPORTANCE:\n'
		f'- core: primary product functionality (the reason the site exists)\n'
		f'- secondary: useful but not the main purpose\n'
		f'- peripheral: only if truly notable (skip otherwise)\n\n'
		f'USER FLOWS:\n'
		f'- Identify 3-5 multi-step journeys: e.g. "Create agent → configure settings → deploy"\n'
		f'- Each flow should describe a complete user goal, not a single click\n'
	)


def build_test_generation_prompt(
	url: str,
	analysis: WebsiteAnalysis,
	max_tests: int,
	goal: str | None = None,
	discovered_personas: tuple[PersonaResult, TraitSchema] | None = None,
) -> str:
	"""Return the full test generation prompt for generating test scenarios from analysis."""
	features_by_testability: dict[str, list] = {'testable': [], 'partial': [], 'untestable': []}
	for f in analysis.features:
		features_by_testability[f.testability].append(f)

	testable_features = features_by_testability['testable'] + features_by_testability['partial']
	core_features = [f for f in testable_features if f.importance == 'core']
	secondary_features = [f for f in testable_features if f.importance == 'secondary']
	peripheral_features = [f for f in testable_features if f.importance == 'peripheral']

	goal_block = ''
	goal_criteria_rule = ''
	goal_steps_rule = ''
	if goal:
		goal_block = f'\nIMPORTANT GOAL: The user specifically wants to test: {goal}. Prioritize generating scenarios that address this goal.\n'
		goal_steps_rule = (
			"\n- GOAL PROGRESSION: Steps must progress through the stated goal's workflow, not just search for controls. "
			'At least one step MUST attempt to complete the core goal action (e.g., actually submitting the form, completing the purchase, or finishing the flow), not merely look for UI elements. '
			'BAD: "1) Look for a create button 2) If not found, note absence 3) Recommend adding a CTA" (only discovers controls, never attempts the goal). '
			'GOOD: "1) Navigate to the relevant section 2) Initiate the workflow 3) Fill in required fields and submit 4) Verify the outcome".'
		)
		goal_criteria_rule = (
			f'\n- GOAL COMPLETION AS SUCCESS CRITERION: The stated goal ("{goal}") being accomplished MUST be the primary success criterion for every scenario. '
			f'Success means the goal action was completed end-to-end (e.g., entity created, purchase confirmed, flow finished), not merely that the user could begin or find the entry point. '
			f'Persona-specific behavior criteria (e.g., visible feedback, graceful error handling) are still required, but they must be IN ADDITION TO verified goal completion. '
			f'BAD: "The site allows the user to begin the flow" (only evaluates the entry point, not completion). '
			f'BAD: "The site remains responsive and shows no errors" (only persona-driven, ignores goal). '
			f'GOOD: "The user completes the goal action end-to-end (outcome confirmed via list update, detail view, success message, OR redirect to result) AND the site provides visible feedback throughout the interaction".'
		)

	# Build persona distribution and criteria blocks — use discovered or predefined
	if discovered_personas:
		from murphy.personas.bridge import (
			build_discovered_persona_distribution_text,
			build_discovered_success_criteria_block,
			get_discovered_persona_names,
		)

		persona_result, trait_schema = discovered_personas
		persona_distribution_text = build_discovered_persona_distribution_text(persona_result, trait_schema)
		success_criteria_text = build_discovered_success_criteria_block(persona_result)
		persona_names_list = ', '.join(get_discovered_persona_names(persona_result))
		persona_names_instruction = f'- test_persona (one of: {persona_names_list})'
	else:
		persona_distribution_text = _build_persona_distribution_text()
		success_criteria_text = (
			'- happy_path (UX): "The agent completes the expected flow, receives clear confirmation feedback (toast, redirect, page update, success message), and arrives at the correct page/state"\n'
			'- confused_novice (UX): "The website provides VISIBLE FEEDBACK for the confused interaction — an error message, a tooltip on a disabled control, a redirect with explanation, or an inline hint. Silent rejection, disabled buttons with no explanation, or forms that do nothing on submit are FAILURES — the confused user must understand what to do next"\n'
			'- adversarial (Security): "The website does NOT execute injected scripts, does NOT expose debug info, shows an appropriate error or sanitizes the input"\n'
			'- edge_case (Security): "The website handles the edge case without crashing — shows a validation message, truncates gracefully, or ignores invalid input"\n'
			'- explorer (UX): "The website provides ORIENTATION AND FEEDBACK at every step — clear page titles, breadcrumbs, \'no results found\' messages, or redirect explanations. Dead ends with no feedback, blank pages, or silent failures are FAILURES"\n'
			'- impatient_user (UX): "The website provides VISIBLE STATE FEEDBACK during rapid interactions — loading indicators, \'please wait\' messages, queued-action confirmation, or duplicate-prevention messages. Silent deduplication with no user-facing signal is a FAILURE"\n'
			'- angry_user (Security): "The website absorbs the hostile interaction gracefully — no crash, no broken state from force-navigation, no infinite loops from rapid clicks"'
			'- classic_ui (Design): "Text is large and readable, labels are explicit (not icon-only), interactive controls are clearly labeled with familiar patterns (visible buttons, top nav), and contrast is high enough for comfortable reading. Novel hidden gestures or ambiguous icons without text labels are FAILURES"\n'
			'- modern_ui (Design): "The site feels visually current and engaging — bold palette, modern type, dark mode awareness, smooth transitions, expressive identity. Bland stock aesthetics, dated gradients, or zero visual personality are FAILURES"\n'
			'- layout_auditor_ui (Design): "Spacing follows a consistent scale — margins, padding, and gutters are uniform across sibling components. Misaligned elements, irregular vertical rhythm, cramped card layouts, or inconsistent gaps are FAILURES"'
		)
		persona_names_instruction = '- test_persona (one of: happy_path, confused_novice, adversarial, edge_case, explorer, impatient_user, angry_user, classic_ui, modern_ui, layout_auditor_ui)'

	return f"""Based on this website analysis, generate {max_tests} test scenarios that target the discovered features.
{goal_block}
Website: {url}
Analysis:
{analysis.model_dump_json(indent=2)}

FEATURE-DRIVEN TEST ALLOCATION:
- ONLY generate tests for features with testability "testable" or "partial". SKIP "untestable" features entirely.
- Each test MUST reference a target_feature (matching a Feature.name from the analysis) and use a feature_category matching that feature's category.
- Priority derives from feature importance:
  - core features → critical or high priority
  - secondary features → medium priority
  - peripheral features → low priority
- At least 50% of the test budget ({max_tests // 2} or more tests) MUST target core features.
- At most 1 test per peripheral feature.

TESTABLE FEATURES AVAILABLE:
- Core ({len(core_features)}): {', '.join(f.name for f in core_features) or 'none'}
- Secondary ({len(secondary_features)}): {', '.join(f.name for f in secondary_features) or 'none'}
- Peripheral ({len(peripheral_features)}): {', '.join(f.name for f in peripheral_features) or 'none'}
- Untestable (SKIP): {', '.join(f.name for f in features_by_testability['untestable']) or 'none'}

MANDATORY PERSONA DISTRIBUTION (for {max_tests} tests):
Each test MUST have a test_persona field. Distribute across these personas.
Each persona has a trait vector that explains WHY it tests different things:

{persona_distribution_text}

PERSONA-SPECIFIC SUCCESS CRITERIA GUIDANCE:
{success_criteria_text}

Each test should have:
- A clear name reflecting the persona behavior (e.g. "Novice submits empty search form" not "Test search functionality")
- What it verifies (description) — describe the REALISTIC USER BEHAVIOR being simulated
- Priority level (critical, high, medium, low)
- feature_category (navigation, search, forms, content_display, filtering_sorting, media, authentication, ecommerce, social, other)
- target_feature (the Feature.name this test exercises)
{persona_names_instruction}
- Step-by-step instructions (steps_description) — see STEP WRITING RULES below
- Concrete success criteria (success_criteria) — see SUCCESS CRITERIA RULES below

STEP WRITING RULES — steps_description must be INTENT-BASED with alternatives:
- Steps describe WHAT to accomplish, not exact elements to click.
- BAD: "Click the Cancel button"
- GOOD: "Attempt to abandon the form (via Cancel button, back navigation, or clicking another nav item)"
- BAD: "Click the Search icon in the top-right corner"
- GOOD: "Trigger a search (via search icon, search bar, or keyboard shortcut)"
- Each step MUST include at least one alternative approach in parentheses.
- Write steps AS IF the agent IS the persona. For confused novice, steps include wrong clicks and backtracking. For adversarial, steps include actual attack payloads.{goal_steps_rule}

SUCCESS CRITERIA RULES — must use BEHAVIORAL OUTCOME format:
- Describe the behavioral outcome, not specific UI text or elements.
- BAD: "'Please fill out this field' messages appear next to each required field"
- GOOD: "The site prevents empty form submission (button disabled, inline validation, browser-native prompts, toast error, or redirect — any prevention mechanism is a pass)"
- BAD: "An error toast appears saying 'Invalid input'"
- GOOD: "The site rejects or sanitizes the invalid input without crashing (error message, input cleared, silent rejection, or redirect — any graceful handling is a pass)"
- For non-happy-path criteria: list 3+ acceptable alternative outcomes separated by OR.
- NEVER reference specific error message text in quotes as the only acceptable outcome.
- Focus on what SHOULD NOT happen (crash, data leak, unhandled exception) as much as what should.
- "Silent handling" and "graceful degradation" are valid pass conditions ONLY for security-oriented personas (adversarial, edge_case, angry_user).
- For UX-oriented personas (happy_path, confused_novice, impatient_user, explorer), success criteria MUST include visible feedback requirements.
- The judge evaluates success by matching the action trace and browser URLs against these criteria.{goal_criteria_rule}

CRITICAL — Security-oriented persona criteria:
- For adversarial tests: if the site accepts the input without crashing, erroring, or exposing sensitive data, that IS a pass. Silent sanitization is valid and correct behavior.
- For edge_case tests: if the site handles unusual input without breaking, that IS a pass — even if no explicit validation message appears.
- For angry_user tests: if the site absorbs hostile interactions without crashing or exposing errors, that IS a pass.
- Do NOT assume the site has features it hasn't demonstrated (e.g., injection-specific error messages, input length validators).

CRITICAL — UX-oriented persona criteria:
- For happy_path tests: the user must receive visible confirmation that their action succeeded.
- For confused_novice tests: any silent handling (disabled button with no tooltip, form that does nothing, input silently ignored) is a FAIL — the novice needs visible guidance.
- For impatient_user tests: the user must see visible state feedback (loading, queued, duplicate-prevention). Silent deduplication is a FAIL.
- For explorer tests: the user must never hit a dead end with no feedback. Empty pages, silent redirects with no context, or features that do nothing are FAILS.

Make tests realistic — they should interact with the actual UI elements found in the analysis.
Do NOT generate tests that require authentication/login unless a login page was found.
"""


def build_test_generation_system_message() -> str:
	"""Return the system message string for test generation."""
	return (
		'You are a senior QA strategist who designs test suites that find real problems. '
		'Your job is NOT to verify happy paths — any junior can do that. '
		'Your job is to think like real users: confused, impatient, angry, adversarial, and exploratory. '
		'Each test should simulate a REALISTIC human behavior, not a robotic verification step. '
		'Real users misclick, rage-type, paste garbage, get lost, and do things nobody planned for.'
	)


def build_exploration_prompt(task: str, url: str) -> str:
	"""Discovery prompt for the explore agent."""
	return (
		f'You are exploring {url} to understand its UI for a specific task.\n\n'
		f'TASK: {task}\n\n'
		f'YOUR JOB:\n'
		f'1. Start from the home page.\n'
		f'2. Discover TWO candidate navigation routes to the page/feature relevant to the task.\n'
		f'3. Validate both routes — pick the most reliable one.\n'
		f'4. Execute the core happy-path flow ONCE end-to-end.\n'
		f'5. Capture concrete page URLs, control labels, and element types you interact with.\n\n'
		f'RULES:\n'
		f'- This is READ-ONLY exploration. Do NOT click "Delete" or confirm irreversible actions.\n'
		f'- Stay on the same domain as {url}.\n'
		f'- STOP once the core flow is confirmed — do not re-check or explore further.\n'
		f'- Note any alternative routes, form fields, buttons, dropdowns, and validation messages.\n'
		f'- If UI appears empty, call refresh_dom_state first. Only if still empty, do at most one reload.\n'
		f'- If a navigation attempt fails or yields a non-interactive/ambiguous page state, do NOT navigate to that same destination again until you call refresh_dom_state and re-check.\n'
		f'- Never perform back-to-back navigate actions to the same destination without an intervening refresh_dom_state check.\n'
		f'- Never perform repeated reload loops; prefer refresh_dom_state and wait checks.\n'
		f'- Never reload the same URL repeatedly.\n'
	)


def build_plan_synthesis_prompt(
	task: str,
	url: str,
	exploration_context: str,
	max_scenarios: int,
	discovered_personas: tuple[PersonaResult, TraitSchema] | None = None,
) -> str:
	"""Synthesis prompt with persona requirements for generating a plan from exploration data."""
	if discovered_personas:
		from murphy.personas.bridge import (
			build_discovered_persona_distribution_text,
			build_discovered_success_criteria_block,
			get_discovered_persona_names,
		)

		persona_result, trait_schema = discovered_personas
		names = get_discovered_persona_names(persona_result)
		persona_req = f'- Must include a diverse mix of these personas: {", ".join(names)}.\n'
		names[0] if names else 'happy_path'
		critical_req = '- At least one scenario must have priority=critical.\n'
		distribution_block = (
			f'PERSONA DISTRIBUTION:\n'
			f'{build_discovered_persona_distribution_text(persona_result, trait_schema)}\n\n'
			f'PERSONA-SPECIFIC SUCCESS CRITERIA GUIDANCE:\n'
			f'{build_discovered_success_criteria_block(persona_result)}\n'
		)
	else:
		persona_req = '- Must include these personas: happy_path, confused_novice, adversarial, edge_case, explorer, classic_ui, modern_ui, layout_auditor_ui.\n'
		critical_req = '- At least one scenario must be happy_path with priority=critical.\n'
		distribution_block = (
			'PERSONA DISTRIBUTION:\n'
			'- happy_path (~15%): Standard user completing the expected flow. Success requires visible confirmation feedback.\n'
			'- confused_novice (~12%): Misclicks, wrong inputs, backtracking. Success requires visible guidance — error messages, tooltips, inline hints. Silent rejection is a FAIL.\n'
			'- adversarial (~12%): XSS payloads, SQL injection, probing /admin. Silent sanitization is a valid PASS.\n'
			'- edge_case (~10%): Empty inputs, special chars, long strings. Graceful degradation (even silent) is a PASS.\n'
			'- explorer (~8%): Unusual navigation, unexpected feature combos. Success requires orientation feedback — page titles, breadcrumbs, "no results" messages. Dead ends with no feedback are FAILS.\n'
			'- impatient_user (~10%): Rapid clicks, skipping steps. Success requires visible state feedback — loading indicators, "please wait" messages. Silent deduplication is a FAIL.\n'
			'- angry_user (~8%): Rage-clicks, force-navigation, rapid form submissions, abandoning flows. Absorbing hostility without crash is a PASS.\n'
			'- classic_ui (~9%): Evaluate readability and familiarity — large fonts, explicit labels, high contrast, conventional layouts. Icon-only controls or hidden gestures are FAILS.\n'
			'- modern_ui (~8%): Evaluate visual currency — bold colors, modern type, dark mode, transitions, visual personality. Dated or bland aesthetics are FAILS.\n'
			'- layout_auditor_ui (~8%): Evaluate spacing discipline — consistent margins, padding, gutters, vertical rhythm, grid alignment. Misaligned or cramped layouts are FAILS.\n'
		)

	return (
		f'Based on the following exploration of {url}, generate {max_scenarios} test scenarios.\n\n'
		f'TASK: {task}\n\n'
		f'EXPLORATION CONTEXT (observed UI evidence):\n{exploration_context}\n\n'
		f'REQUIREMENTS:\n'
		f'- Generate exactly {max_scenarios} scenarios (minimum 5 if max allows).\n'
		f'{persona_req}'
		f'{critical_req}'
		f'- The first happy-path/primary scenario must describe the chosen route AND mention alternatives considered.\n'
		f'- steps_description must be INTENT-BASED: describe WHAT to accomplish, not exact elements. Each step must include at least one alternative approach in parentheses. BAD: "Click the Submit button". GOOD: "Submit the form (via Submit button, Enter key, or any submit control)".\n'
		f"- GOAL PROGRESSION: Steps must progress through the stated TASK's workflow, not just search for controls. "
		f'At least one step MUST attempt to complete the core goal action (e.g., actually submitting the form, completing the purchase, or finishing the flow), not merely look for UI elements. '
		f'BAD: "1) Look for a create button 2) If not found, note absence 3) Recommend adding a CTA" (only discovers controls, never attempts the goal). '
		f'GOOD: "1) Navigate to the relevant section 2) Initiate the workflow 3) Fill in required fields and submit 4) Verify the outcome".\n'
		f'- success_criteria must use BEHAVIORAL OUTCOME format: describe the expected behavior, not specific UI text. List 3+ acceptable alternative outcomes separated by OR. BAD: "Error toast says Invalid". GOOD: "The site rejects invalid input without crashing (error message, input cleared, silent rejection, or redirect)". Never quote specific error message text as the only acceptable outcome.\n'
		f'- GOAL COMPLETION AS SUCCESS CRITERION: The stated TASK ("{task}") being accomplished MUST be the primary success criterion for every scenario. '
		f'Success means the goal action was completed end-to-end (e.g., entity created, purchase confirmed, flow finished), not merely that the user could begin or find the entry point. '
		f'Persona-specific behavior criteria (e.g., visible feedback, graceful error handling) are still required, but they must be IN ADDITION TO verified goal completion. '
		f'BAD: "The site allows the user to begin the flow" (only evaluates the entry point, not completion). '
		f'BAD: "The site remains responsive and shows no errors" (only persona-driven, ignores the task goal). '
		f'GOOD: "The user completes the goal action end-to-end (outcome confirmed via list update, detail view, success message, OR redirect to result) AND the site provides visible feedback throughout the interaction".\n'
		f'- Do NOT fabricate URLs — only reference pages/paths observed in the exploration context.\n'
		f'- Do NOT assume UI elements exist that were not observed during exploration (e.g., do not assume a search bar, filter, or input field exists unless one was seen). If a persona needs to interact with an input field but none was observed, write the scenario to: (a) look for the expected element, (b) note its absence, (c) use whatever elements ARE present to achieve the task intent, and (d) recommend the missing element as a UX improvement in the final assessment.\n'
		f'- For security/resilience-oriented personas: evaluate how the website HANDLES unexpected behavior. Any graceful handling (including silent sanitization) is a pass; only crash/leak/corruption is a fail.\n'
		f'- For UX-oriented personas: the site MUST provide visible feedback. Silent handling, disabled buttons with no explanation, or forms that do nothing are FAILURES.\n\n'
		f'{distribution_block}'
	)


def _render_trait_vector(traits: TraitVector) -> str:
	"""Render a trait vector as a compact structured block."""
	return (
		f'  technical_literacy: {traits.technical_literacy.name}\n'
		f'  patience: {traits.patience.name}\n'
		f'  intent: {traits.intent}\n'
		f'  exploration: {traits.exploration.name}\n'
		f'  reading_comprehension: {traits.reading_comprehension.name}\n'
		f'  visual_density_preference: {traits.visual_density_preference.name}\n'
		f'  aesthetic_era: {traits.aesthetic_era}\n'
		f'  layout_strictness: {traits.layout_strictness.name}'
	)


# Character descriptions for vivid role-playing
_PERSONA_DESCRIPTIONS: dict[TestPersona, str] = {
	'happy_path': 'A skilled, patient user who knows exactly what they want. Follows the expected flow directly and efficiently.',
	'confused_novice': "A first-time user who doesn't read labels carefully, clicks wrong buttons, submits forms without filling them, and navigates backward repeatedly. Needs the site to actively guide them.",
	'adversarial': 'A security tester probing for vulnerabilities. Types XSS payloads, SQL injection fragments, navigates to /admin, and tries to bypass validation.',
	'edge_case': 'A methodical tester exercising boundary conditions: empty fields, max-length strings, special characters (emoji, RTL text, null bytes), double-clicks.',
	'explorer': 'A curious user who takes unexpected paths: visits pages out of order, uses features in unintended combinations, clicks decorative elements.',
	'impatient_user': 'A rushed user who clicks rapidly without waiting, skips required steps, submits forms immediately, navigates away mid-action.',
	'angry_user': 'A frustrated user who rage-clicks buttons repeatedly, force-navigates by typing URLs, submits forms rapidly without waiting, and abandons multi-step flows mid-way.',
	'classic_ui': 'A user who values readability and familiarity above all else. Needs large, legible fonts, high-contrast text, explicitly labeled buttons (not icon-only), and conventional layouts (top nav bar, visible sidebar links). Anything that requires guessing — hidden hamburger menus, swipe gestures, unlabeled icon buttons — is a problem. Does not test functionality — focuses purely on whether the design is comfortable, clear, and follows well-established conventions.',
	'modern_ui': 'A design-forward user immersed in current visual trends and modern SaaS apps. Expects bold color palettes, expressive typography, dark mode support, smooth micro-interactions, and a distinct visual identity. Bland corporate aesthetics, dated skeuomorphic patterns, or stale layouts are failures. Does not test functionality — focuses purely on whether the design feels current, engaging, and visually appealing.',
	'layout_auditor_ui': 'A meticulous spacing perfectionist who evaluates every margin, padding, and gutter. Checks that sibling components share identical spacing, vertical rhythm is consistent across sections, card grids align to an implicit baseline grid, and no element feels cramped or adrift. Misaligned buttons, irregular gaps between list items, or inconsistent padding inside cards are immediate red flags. Does not test functionality — focuses purely on spatial consistency and breathing room.',
}


def _render_persona_for_execution(persona: str) -> str:
	"""Produce both character description and trait breakdown for the execution prompt."""
	entry = PERSONA_REGISTRY.get(persona)  # type: ignore[arg-type]
	description = _PERSONA_DESCRIPTIONS.get(persona, '')  # type: ignore[arg-type]

	lines = [f'Your persona: **{persona}**']
	if description:
		lines.append(f'Character: {description}')
	if entry:
		traits, test_type = entry
		lines.append(f'Test type: {test_type}')
		lines.append('Trait profile:')
		lines.append(_render_trait_vector(traits))
		# Add trait-specific behavioral instructions
		if traits.technical_literacy == traits.technical_literacy.low:
			lines.append('→ You are unfamiliar with UI conventions. Do not assume icons or color cues are self-explanatory.')
		if traits.patience == traits.patience.low:
			lines.append('→ You have zero patience. If something takes more than 2 seconds with no feedback, treat it as broken.')
		if traits.reading_comprehension == traits.reading_comprehension.low:
			lines.append('→ You do not read body text. Only bold labels, color coding, icons, and position-based cues register.')
		if traits.exploration == traits.exploration.high:
			lines.append('→ You actively wander off the expected path. Try unexpected navigation, unusual feature combinations.')
		if traits.intent == 'adversarial':
			lines.append('→ You are actively trying to break things. Use XSS payloads, SQL fragments, probe hidden endpoints.')
		if test_type == 'design':
			if traits.aesthetic_era == 'classic':
				lines.append(
					'→ You value readability and familiar patterns. Judge font size, label clarity, contrast for aging eyes, and whether controls use explicit text labels instead of icon-only affordances.'
				)
			elif traits.aesthetic_era == 'experimental':
				lines.append(
					'→ You expect modern, visually engaging design. Judge bold color choices, expressive typography, dark mode awareness, smooth transitions, and overall visual personality. Bland or dated aesthetics are failures.'
				)
			else:
				lines.append(
					'→ You expect clean, contemporary design. Judge type scale, systematic spacing, polished details, and visual consistency across pages.'
				)
			if traits.layout_strictness == TraitLevel.high:
				lines.append(
					'→ You are a spacing perfectionist. Every margin, padding, and gutter must follow a consistent scale. Flag misaligned elements, irregular gaps, and inconsistent padding between sibling components.'
				)
			if traits.visual_density_preference == TraitLevel.low:
				lines.append(
					'→ You prefer spacious layouts with generous whitespace. Cramped or information-dense screens feel overwhelming — flag them.'
				)
			elif traits.visual_density_preference == TraitLevel.high:
				lines.append(
					'→ You prefer information-dense layouts. Wasted space and overly sparse screens feel empty — flag them.'
				)
	return '\n'.join(lines)


_PERSONA_SUGGESTION_INSTRUCTIONS: dict[str, str] = {
	'happy_path': (
		'As a standard user completing the expected flow, suggest 1-3 features that would make '
		'the happy path smoother (e.g. clearer confirmation feedback, streamlined form flows, '
		'better success states, progress indicators for multi-step processes).'
	),
	'confused_novice': (
		'As a confused first-time user, suggest 1-3 features that would help you orient yourself '
		'(e.g. onboarding checklists, guided tours, empty-state guidance, clearer CTAs, '
		'contextual help tooltips, "what is this?" hints).'
	),
	'adversarial': (
		'As a security tester, suggest 1-3 security UX improvements based on what you observed '
		'(e.g. 2FA prompts, rate-limit feedback, error messaging that does not leak internals, '
		'CAPTCHA on sensitive actions, input sanitization indicators).'
	),
	'edge_case': (
		'As a boundary-condition tester, suggest 1-3 error-recovery features based on what you observed '
		'(e.g. auto-save, progress persistence, undo/redo, clear recovery paths after errors, '
		'input length indicators, character limit warnings).'
	),
	'explorer': (
		'As an exploratory user taking unexpected paths, suggest 1-3 discoverability improvements '
		'(e.g. global search, keyboard shortcuts, breadcrumb navigation, contextual related-feature links, '
		'site map, "you might also like" suggestions).'
	),
	'impatient_user': (
		'As an impatient user who wants instant feedback, suggest 1-3 speed or responsiveness improvements '
		'(e.g. skeleton loaders, optimistic UI updates, progress bars, reduced click-depth, '
		'prefetching on hover, instant search).'
	),
	'angry_user': (
		'As a frustrated user, suggest 1-3 error-recovery features that would reduce frustration '
		'(e.g. auto-save on form abandonment, undo for destructive actions, clear "start over" paths, '
		'graceful handling of rapid interactions, queue/debounce feedback).'
	),
	'classic_ui': (
		'As a user who values readability and familiarity, suggest 1-3 accessibility or legibility '
		'improvements (e.g. font-size control, high-contrast mode, larger buttons with text labels, '
		'persistent visible navigation, reduced reliance on icons without text).'
	),
	'modern_ui': (
		'As a design-forward user, suggest 1-3 improvements to make the design feel more current '
		'and engaging (e.g. dark mode toggle, micro-interactions, expressive typography, gamification elements, '
		'branded illustrations, smooth transitions).'
	),
	'layout_auditor_ui': (
		'As a spacing perfectionist, suggest 1-3 design-system improvements to resolve spacing issues '
		'(e.g. a spacing scale with 4/8/16/24/32px tokens, a consistent grid system, '
		'component-level padding standards, vertical rhythm baseline).'
	),
}


def _build_suggestion_instruction(
	persona: str,
	discovered_personas: tuple[PersonaResult, TraitSchema] | None = None,
) -> str:
	"""Return the feature suggestion instruction block for a persona."""
	instruction = _PERSONA_SUGGESTION_INSTRUCTIONS.get(persona)
	if instruction is None and discovered_personas:
		from murphy.personas.bridge import get_discovered_suggestion_instruction

		instruction = get_discovered_suggestion_instruction(persona, discovered_personas[0]) or None
	if instruction is None:
		instruction = (
			'Based on your persona perspective, suggest 1-3 concrete feature or UX improvements '
			'that would enhance the experience for users like you.'
		)
	return (
		f'FEATURE SUGGESTIONS:\n'
		f'In your ScenarioExecutionVerdict, populate the feature_suggestions field with 1-3 concrete, '
		f'actionable improvement suggestions based on what you observed during testing.\n'
		f'{instruction}\n'
		f'Each suggestion should be a single sentence describing a specific, implementable improvement.\n'
	)


def build_execution_prompt(
	global_task: str,
	scenario: TestScenario,
	start_url: str,
	available_file_paths: list[str] | None = None,
	discovered_personas: tuple[PersonaResult, TraitSchema] | None = None,
) -> str:
	"""Build execution prompt with validation rules."""
	# Resolve persona behavior block — use discovered if persona not in predefined registry
	if discovered_personas and scenario.test_persona not in PERSONA_REGISTRY:
		from murphy.personas.bridge import render_discovered_persona_for_execution

		persona_result, trait_schema = discovered_personas
		persona_block = render_discovered_persona_for_execution(scenario.test_persona, persona_result, trait_schema)
	else:
		persona_block = _render_persona_for_execution(scenario.test_persona)

	return (
		f'Test: {scenario.name}\n\n'
		f'Global task context: {global_task}\n\n'
		f'Description: {scenario.description}\n\n'
		f'Steps:\n{scenario.steps_description}\n\n'
		f'Success criteria: {scenario.success_criteria}\n\n'
		f'IMPORTANT: You are already logged in. Be direct and efficient. '
		f'Complete the test as fast as possible with minimal steps.\n\n'
		f'ADAPTATION RULES:\n'
		f'- INTENT, NOT ELEMENTS: Steps describe intent, not exact UI elements. If "Click the Cancel button" fails, try any mechanism that achieves the same intent (back navigation, clicking another nav item, pressing Escape, etc.).\n'
		f'- NEVER REPEAT A FAILED ACTION: If an action fails, try a DIFFERENT approach immediately. Never retry the same click, search, or navigation.\n'
		f'- FALLBACK LADDER: On failure, follow this sequence: (1) try an alternative element or interaction, (2) try a completely different route to the same goal, (3) call refresh_dom_state and reassess, (4) after 3 total failed attempts at the same intent, STOP and call done(success=false) explaining what was tried.\n'
		f'- EARLY ABORT: If you cannot reach the target page or find the target feature after 5 steps, call done() immediately with your verdict. Also call done() as soon as you have confirmed the target is missing AND identified alternative support/contact paths (e.g. one search found a contact/support link, Slack, or "Get Started") — do not spend further steps re-gathering the same evidence.\n'
		f'- LOOP DETECTION: If you perform the same action type (e.g., click, scroll, search) on the same target more than twice, STOP immediately and call done(success=false). Report the loop.\n'
		f'- EVIDENCE COLLECTION ONCE: When documenting missing UI elements and fallback paths, run search_page (or similar) at most once per page to gather support/contact evidence. Once you have enough to cite (e.g. fallback links or text found), call done() with the ScenarioExecutionVerdict in the very next step. Do NOT run multiple steps that only "collect evidence" or "capture context" for the same findings — that is a loop.\n'
		f'- DISABLED ELEMENTS: If a button is disabled, do NOT retry it. Analyze why (missing required fields, prerequisite step) and address the root cause, or skip and report.\n'
		f'- EMPTY RESULTS: If search returns 0 results, the content does not exist. Do NOT repeat the search or scroll hoping it appears. Try alternative terms or navigation.\n'
		f'- MISSING EXPECTED ELEMENT: If the scenario expects a specific UI element (e.g., search bar, filter, input field) but it does not exist on the page, do NOT give up or fabricate interactions with elements that are not there. Instead:\n'
		f'  (1) Log which element was expected and that it was not found.\n'
		f'  (2) Identify what elements ARE present on the page that can achieve the same task intent (e.g. docs, support links, contact form).\n'
		f'  (3) Use those present elements to complete the test scenario as best as possible.\n'
		f'  (4) Run at most one search_page (or equivalent) to confirm fallback paths (e.g. support, contact, "Get Started"). Once you have that result, do NOT run another step only to "collect evidence" or "capture context" — produce the verdict immediately.\n'
		f'  (5) In your final done() response, include a "Missing UI elements" section noting: what was expected, that it was absent, what you used instead, and a recommendation that the missing element should ideally be present for better user clarity.\n\n'
		f'PERSONA BEHAVIOR:\n'
		f'{persona_block}\n\n'
		f'{_build_suggestion_instruction(scenario.test_persona, discovered_personas)}\n'
		f'EDGE CASE / ADVERSARIAL TESTING:\n'
		f'- For edge_case or adversarial tests: ATTEMPT the action even if controls appear disabled. Click the submit/publish button, try form submission — observe what happens.\n'
		f'- Do NOT just search for error messages or describe what you see. Actually interact with the form: leave fields empty, then click submit. Report the observed behavior (disabled button, inline validation, error toast, silent rejection, etc.).\n'
		f"- The goal is to test the site's handling mechanism, not to find error messages.\n\n"
		f'VALIDATION RULES:\n'
		f'- Validate outcome state before returning success (no inference from partial signals).\n'
		f'- Use visible UI signals only: toasts, badges, list rows, detail cards, confirmation messages.\n'
		f'- For create flows: confirm new entity appears with a recognizable identifier.\n'
		f'- For delete flows: confirm entity is absent from list/search.\n'
		f'- For edit flows: reopen and confirm updates persist.\n'
		f'- If evidence is ambiguous, return success=false.\n'
		f'- If the primary completion signal/action is blocked, disabled, or inconclusive, perform one alternate in-app verification route before deciding verdict.\n'
		f'- Alternate verification must be within the app (e.g., list/detail/search/status views) and should check for objective outcome evidence.\n'
		f'- During alternate verification, do not re-run the full primary workflow; verify existing outcome state only.\n'
		f'- If evidence is ambiguous, contradictory, or missing, return success=false and explain what could not be verified.\n'
		f'- Verify scenario success_criteria explicitly and cite which UI signal satisfied each required condition.\n\n'
		f'DOM STATE RULES:\n'
		f'- If UI appears empty, call refresh_dom_state before any reload. Do not repeatedly reload the same URL.\n'
		f'- If navigation to a destination fails or page state is non-interactive/ambiguous afterward, call refresh_dom_state before any second navigation attempt.\n'
		f'- Do not issue consecutive navigate actions to the same destination unless refresh_dom_state has been called in between.\n\n'
		f'VALIDATION FALLBACK:\n'
		f'- Validation-only fallback mode: once the primary outcome action has been attempted (e.g., create/delete/update submit), do NOT restart the full primary workflow.\n'
		f'- In validation-only fallback mode, only perform evidence checks (list/detail/search/status/confirmation views) to verify whether outcome exists or not.\n'
		f'- If fallback verification cannot confirm outcome, return success=false with explicit missing evidence; do not create/delete/update again as a workaround.\n'
		+ (
			f'\nFILE UPLOAD:\n'
			f'- If the scenario requires file upload, use the provided available file paths with upload_file.\n'
			f'- Available files: {", ".join(available_file_paths)}\n'
			if available_file_paths
			else ''
		)
	)
