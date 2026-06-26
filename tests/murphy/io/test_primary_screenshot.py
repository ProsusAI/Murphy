"""Tests for primary screenshot selection."""

from unittest.mock import MagicMock

from murphy.io.primary_screenshot import select_primary_screenshot_path


def _make_action(action_type: str) -> MagicMock:
	action = MagicMock()
	action.model_fields_set = {action_type, 'interacted_element'}
	return action


def _make_step(
	*,
	screenshot_path: str | None,
	actions: list[str] | None = None,
	error: str | None = None,
) -> MagicMock:
	step = MagicMock()
	step.state.screenshot_path = screenshot_path
	if actions:
		model_output = MagicMock()
		model_output.action = [_make_action(a) for a in actions]
		step.model_output = model_output
	else:
		step.model_output = None
	if error:
		result = MagicMock()
		result.error = error
		step.result = [result]
	else:
		step.result = []
	return step


def _make_history(steps: list[MagicMock]) -> MagicMock:
	history = MagicMock()
	history.history = steps
	history.screenshot_paths.return_value = [s.state.screenshot_path for s in steps if s.state.screenshot_path]
	return history


def test_select_primary_prefers_last_high_signal_step():
	steps = [
		_make_step(screenshot_path='/tmp/step_1.png', actions=['scroll']),
		_make_step(screenshot_path='/tmp/step_2.png', actions=['click']),
		_make_step(screenshot_path='/tmp/step_3.png', actions=['done']),
	]
	history = _make_history(steps)
	assert select_primary_screenshot_path(history) == '/tmp/step_3.png'


def test_select_primary_prefers_error_step_over_mid_signal():
	steps = [
		_make_step(screenshot_path='/tmp/step_1.png', actions=['click']),
		_make_step(screenshot_path='/tmp/step_2.png', actions=['scroll'], error='Element not found'),
		_make_step(screenshot_path='/tmp/step_3.png', actions=['scroll']),
	]
	history = _make_history(steps)
	# Last step (+10) beats error on step 2 (+4)
	assert select_primary_screenshot_path(history) == '/tmp/step_3.png'


def test_select_primary_falls_back_to_last_screenshot():
	steps = [
		_make_step(screenshot_path='/tmp/step_1.png', actions=['scroll']),
		_make_step(screenshot_path=None, actions=['scroll']),
		_make_step(screenshot_path='/tmp/step_3.png', actions=['scroll']),
	]
	history = _make_history(steps)
	assert select_primary_screenshot_path(history) == '/tmp/step_3.png'


def test_select_primary_empty_history_uses_screenshot_paths():
	history = MagicMock()
	history.history = []
	history.screenshot_paths.return_value = [None, '/tmp/step_2.png']
	assert select_primary_screenshot_path(history) == '/tmp/step_2.png'


def test_select_primary_no_screenshots_returns_none():
	history = MagicMock()
	history.history = []
	history.screenshot_paths.return_value = []
	assert select_primary_screenshot_path(history) is None
