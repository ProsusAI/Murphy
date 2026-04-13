"""Convert Murphy agent_history JSON files to behavioral text timelines.

The output format mirrors the compressed PostHog session format used by
compressor.py so that score_session() from scoring.py can score Murphy's
behavior on the same trait dimensions as real users.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# ── Action formatting ─────────────────────────────────────────────────────────


def _action_label(action_dict: dict[str, Any]) -> str:
	"""Return a human-readable label for a single agent action dict."""
	if not action_dict:
		return 'unknown'
	atype = next(iter(action_dict))
	params = action_dict[atype]
	if not isinstance(params, dict):
		return atype

	if atype == 'click':
		return f'click [#{params.get("index", "?")}]'
	if atype == 'input_text':
		text = str(params.get('text', ''))
		if len(text) > 40:
			text = text[:37] + '...'
		return f"type '{text}'"
	if atype == 'navigate_to':
		return f'navigate to {params.get("url", "?")}'
	if atype == 'done':
		data = params.get('data', params)
		if isinstance(data, dict):
			success = data.get('success', '?')
		else:
			success = '?'
		return f'finish (success={success})'
	if atype == 'go_back':
		return 'navigate back'
	if atype == 'scroll':
		direction = params.get('direction', '')
		return f'scroll {direction}'.strip()
	if atype == 'wait':
		return 'wait'
	if atype == 'extract_page_content':
		return 'read page content'
	if atype == 'get_dropdown_options':
		return 'inspect dropdown'
	if atype == 'select_dropdown_option':
		text = str(params.get('text', ''))
		return f'select "{text[:40]}"'
	return atype


# ── Navigation helpers ────────────────────────────────────────────────────────


def _pathname(url: str) -> str:
	if url.startswith('http'):
		return urlparse(url).path or '/'
	return url or '/'


def _truncate(s: str, max_len: int) -> str:
	s = s.strip()
	if len(s) <= max_len:
		return s
	return s[: max_len - 1] + '…'


# ── Deliberation signal detection ─────────────────────────────────────────────

_DELIBERATION_KEYWORDS = (
	'not sure',
	'uncertain',
	'unclear',
	'alternatively',
	'however',
	'verify',
	'check',
	'confirm',
	'make sure',
	'wait',
	'careful',
	'if this fails',
	'instead',
	're-read',
	'try',
	'attempt',
	'double',
	'revisit',
	'reconsider',
)

_UNCERTAINTY_KEYWORDS = (
	'fail',
	'wrong',
	'incorrect',
	'not found',
	'unclear',
	'unexpected',
	'error',
	'did not',
	"wasn't",
	'cannot',
)


def _has_deliberation(text: str) -> bool:
	t = text.lower()
	return any(kw in t for kw in _DELIBERATION_KEYWORDS)


def _has_uncertainty(text: str) -> bool:
	t = text.lower()
	return any(kw in t for kw in _UNCERTAINTY_KEYWORDS)


# ── Public API ────────────────────────────────────────────────────────────────


def format_agent_history_as_timeline(
	history_path: Path,
	persona_name: str,
	scenario_name: str,
	scenario_steps: str,
) -> str:
	"""Convert an agent_history JSON file to a behavioral text timeline.

	The returned string is compatible with score_session() — it follows the
	same section structure as compress_session() output:
	  1. Session metadata header
	  2. Navigation summary
	  3. Action timeline with deliberation signals

	Args:
	    history_path:    Path to a test_XX_*.json agent history file.
	    persona_name:    Human-readable persona name (e.g. "Steady Tasker").
	    scenario_name:   Short test scenario name.
	    scenario_steps:  Full steps_description from the test scenario.
	"""
	data = json.loads(history_path.read_text(encoding='utf-8'))
	history: list[dict[str, Any]] = data.get('history', [])

	# ── Collect URLs across steps ─────────────────────────────────────────────
	urls: list[str] = []
	for step in history:
		tabs = step.get('state', {}).get('tabs', [])
		if tabs and isinstance(tabs[0], dict):
			url = tabs[0].get('url', '')
			if url:
				urls.append(url)

	# ── Navigation analysis ───────────────────────────────────────────────────
	pathnames = [_pathname(u) for u in urls]
	unique_pages = list(dict.fromkeys(pathnames))

	backtracks = 0
	visited: set[str] = set()
	for i, p in enumerate(pathnames):
		if i > 0 and p in visited:
			backtracks += 1
		visited.add(p)

	transitions = max(len(pathnames) - 1, 1)
	backtrack_ratio = backtracks / transitions
	if backtrack_ratio > 0.3:
		nav_style = 'oscillating'
	elif backtrack_ratio < 0.1:
		nav_style = 'linear'
	else:
		nav_style = 'moderate'

	# ── Assemble sections ─────────────────────────────────────────────────────
	lines: list[str] = []

	# Header
	lines.append('=== Murphy Agent Session ===')
	lines.append(f'Persona: {persona_name}')
	lines.append(f'Task: {scenario_name}')
	lines.append(f'Task description: {_truncate(scenario_steps, 200)}')
	lines.append(f'Total steps: {len(history)}  |  Distinct pages: {len(unique_pages)}')
	lines.append('')

	# Navigation summary
	lines.append('=== Navigation Summary ===')
	pages_str = ', '.join(unique_pages[:10])
	lines.append(f'Pages visited: {len(unique_pages)} unique ({pages_str})')
	lines.append(f'Navigation style: {nav_style} ({backtracks} backtracks in {transitions} transitions)')
	lines.append('')

	# Action timeline
	lines.append('=== Action Timeline ===')
	for i, step in enumerate(history, start=1):
		model_output: dict[str, Any] = step.get('model_output', {})
		results: list[dict[str, Any]] = step.get('result', [])

		goal = model_output.get('next_goal', '').strip()
		eval_prev = model_output.get('evaluation_previous_goal', '').strip()
		thinking = model_output.get('thinking', '').strip()
		actions: list[dict[str, Any]] = model_output.get('action', []) or []

		action_labels = [_action_label(a) for a in actions if isinstance(a, dict)]
		action_str = ' + '.join(action_labels) if action_labels else 'no action'

		extracted = ''
		is_done = False
		for r in results:
			if not isinstance(r, dict):
				continue
			content = r.get('extracted_content', '')
			if content and not extracted:
				extracted = _truncate(str(content), 120)
			if r.get('is_done'):
				is_done = True

		lines.append(f'[Step {i}] Goal: {_truncate(goal, 120)}')
		lines.append(f'  Action: {action_str}')
		if extracted:
			lines.append(f'  Result: {extracted}')

		# Include deliberation excerpt when it signals caution or hesitation
		if thinking and (_has_deliberation(thinking) or len(actions) > 1):
			lines.append(f'  Deliberation: {_truncate(thinking, 150)}')

		# Include self-assessment when it reveals uncertainty about the previous step
		if eval_prev and i > 1 and _has_uncertainty(eval_prev):
			lines.append(f'  Previous step assessment: {_truncate(eval_prev, 120)}')

		if is_done:
			lines.append('  [Task ended]')

	return '\n'.join(lines)
