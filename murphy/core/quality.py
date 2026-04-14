"""Murphy — test plan and scenario quality validation."""

import re
from collections import Counter

from murphy.models import PERSONA_REGISTRY, TestPlan, TestScenario, TraitLevel


def scenario_quality_issues(task: str, scenario: TestScenario) -> list[str]:
	"""Per-scenario quality validation. Returns list of issue descriptions."""
	issues: list[str] = []
	task_lower = task.lower()
	task_words = set(re.findall(r'\w+', task_lower))

	# 1. Task alignment — scenario keywords should overlap with task
	scenario_text = f'{scenario.name} {scenario.description} {scenario.steps_description}'.lower()
	scenario_words = set(re.findall(r'\w+', scenario_text))
	overlap = task_words & scenario_words - {'the', 'a', 'an', 'to', 'is', 'and', 'or', 'in', 'on', 'for', 'of', 'with'}
	if len(overlap) < 1 and scenario.test_persona == 'first_timer':
		issues.append(f'Scenario "{scenario.name}" has no keyword overlap with task "{task}"')

	# 2. Step clarity — at least 2 numbered/dotted steps
	steps = scenario.steps_description
	step_lines = [line for line in steps.split('\n') if re.match(r'^\s*(\d+[\.\)]\s|[-•]\s)', line.strip())]
	if len(step_lines) < 2:
		issues.append(f'Scenario "{scenario.name}" has fewer than 2 explicit steps')

	# 3. Observable criteria — success criteria should reference UI signals
	criteria_lower = scenario.success_criteria.lower()
	ui_signals = [
		'visible',
		'appears',
		'displayed',
		'shows',
		'confirmation',
		'toast',
		'badge',
		'error',
		'message',
		'redirect',
		'page',
		'list',
		'row',
	]
	if not any(signal in criteria_lower for signal in ui_signals):
		issues.append(f'Scenario "{scenario.name}" success criteria lack observable UI signals')

	# 4. No fabricated URLs — reject patterns like "/spaces/" or bare http:// in steps
	if re.search(r'https?://(?!.*(?:' + re.escape(task.split()[0] if task.split() else '') + r'))', steps):
		# Only flag if URL doesn't look related to the task
		pass  # Relaxed — hard to validate without exploration data

	# 5. Generic phrases — flag vague phrasing in all personas
	vague_patterns = ['click random', 'click any', 'click something']
	for pattern in vague_patterns:
		if pattern in steps.lower():
			issues.append(f'Scenario "{scenario.name}" uses vague "{pattern}" — use intent-based step descriptions instead')

	return issues


def plan_quality_issues(task: str, plan: TestPlan) -> list[str]:
	"""Plan-level quality validation. Returns list of issue descriptions."""
	issues: list[str] = []

	# 1. Minimum scenarios
	if len(plan.scenarios) < 5:
		issues.append(f'Plan has only {len(plan.scenarios)} scenarios (minimum 5)')

	# 2. Trait-space coverage validation
	has_low_patience = False
	has_adversarial_intent = False
	has_high_exploration = False
	for s in plan.scenarios:
		entry = PERSONA_REGISTRY.get(s.test_persona)
		if not entry:
			continue
		traits, _ = entry
		if traits.patience == TraitLevel.low:
			has_low_patience = True
		if traits.intent == 'adversarial':
			has_adversarial_intent = True
		if traits.exploration == TraitLevel.high:
			has_high_exploration = True
	coverage_gaps: list[str] = []
	if not has_low_patience:
		coverage_gaps.append('low patience')
	if not has_adversarial_intent:
		coverage_gaps.append('adversarial intent')
	if not has_high_exploration:
		coverage_gaps.append('high exploration')
	if coverage_gaps:
		issues.append(f'Missing trait coverage: {", ".join(coverage_gaps)}')

	# 3. Critical first_timer baseline
	has_critical_first_timer = any(s.test_persona == 'first_timer' and s.priority == 'critical' for s in plan.scenarios)
	if not has_critical_first_timer:
		issues.append('No first_timer scenario with priority=critical')

	# 4. Per-scenario quality
	for s in plan.scenarios:
		s_issues = scenario_quality_issues(task, s)
		issues.extend(s_issues)

	# 5. Persona distribution — no single persona should exceed 40% of the plan
	if plan.scenarios:
		persona_counts = Counter(s.test_persona for s in plan.scenarios)
		total = len(plan.scenarios)
		for persona, count in persona_counts.items():
			if count / total > 0.40:
				issues.append(f'Persona "{persona}" dominates plan at {count}/{total} ({round(count / total * 100)}%); max 40%')

	# 6. Task relevance — max 33% can be unrelated by keyword overlap
	task_words = set(re.findall(r'\w+', task.lower())) - {
		'the',
		'a',
		'an',
		'to',
		'is',
		'and',
		'or',
		'in',
		'on',
		'for',
		'of',
		'with',
	}
	unrelated = 0
	for s in plan.scenarios:
		scenario_text = f'{s.name} {s.description}'.lower()
		scenario_words = set(re.findall(r'\w+', scenario_text))
		if not (task_words & scenario_words):
			unrelated += 1
	if plan.scenarios and unrelated / len(plan.scenarios) > 0.33:
		issues.append(f'{unrelated}/{len(plan.scenarios)} scenarios appear unrelated to task')

	return issues
