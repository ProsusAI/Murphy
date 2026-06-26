"""Select the most informative screenshot path for a failed test."""

from __future__ import annotations

from browser_use.agent.views import AgentHistoryList

HIGH_SIGNAL_ACTIONS = frozenset(
	{
		'navigate',
		'input_text',
		'done',
		'select_dropdown_option',
		'upload_file',
		'evaluate',
	}
)

LOW_SIGNAL_ACTIONS = frozenset(
	{
		'scroll',
		'refresh_dom_state',
		'search_page',
		'find_elements',
		'switch_tab',
		'wait',
	}
)


def score_step(step: object, index: int, total_steps: int) -> int:
	"""Score how informative a step's screenshot is (shared with judge selection)."""
	score = 0

	if index == total_steps - 1:
		score += 10

	model_output = getattr(step, 'model_output', None)
	if model_output:
		for action in model_output.action:
			action_type = next((k for k in action.model_fields_set if k != 'interacted_element'), None)
			if action_type in HIGH_SIGNAL_ACTIONS:
				score += 3
			elif action_type not in LOW_SIGNAL_ACTIONS:
				score += 1

	for result in getattr(step, 'result', ()):
		if getattr(result, 'error', None):
			score += 4

	return score


def select_primary_screenshot_path(history: AgentHistoryList) -> str | None:
	"""Pick one filesystem screenshot path that best represents a failure."""
	steps = history.history
	if not isinstance(steps, list) or not steps:
		screenshots = history.screenshot_paths()
		valid = [p for p in screenshots if p]
		return valid[-1] if valid else None

	best_score, best_idx, best_path = -1, -1, None
	for i, step in enumerate(steps):
		path = step.state.screenshot_path
		if not path:
			continue
		step_score = score_step(step, i, len(steps))
		if step_score > best_score or (step_score == best_score and i > best_idx):
			best_score, best_idx, best_path = step_score, i, path

	if best_path:
		return best_path

	for step in reversed(steps):
		path = step.state.screenshot_path
		if path:
			return path

	return None
