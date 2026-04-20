"""Convert Murphy agent_history JSON files to behavioral text timelines.

The output format mirrors the compressed PostHog session format used by
compressor.py so that score_session() from scoring.py can score Murphy's
behavior on the same trait dimensions as real users.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# ── Action formatting ─────────────────────────────────────────────────────────


def _element_label(interacted_elements: list[Any], action_index: int) -> str | None:
	"""Return a human-readable label for the element at action_index, or None."""
	if not interacted_elements or action_index >= len(interacted_elements):
		return None
	el = interacted_elements[action_index]
	if not isinstance(el, dict):
		return None
	# ax_name is the most reliable accessibility label
	ax_name = (el.get('ax_name') or '').strip()
	if ax_name:
		return ax_name
	# Fall back to aria-label attribute
	attrs = el.get('attributes', {})
	if isinstance(attrs, dict):
		aria = (attrs.get('aria-label') or '').strip()
		if aria:
			return aria
	return None


def _action_label(action_dict: dict[str, Any], interacted_elements: list[Any] | None = None, action_index: int = 0) -> str:
	"""Return a human-readable label for a single agent action dict."""
	if not action_dict:
		return 'unknown'
	atype = next(iter(action_dict))
	params = action_dict[atype]
	if not isinstance(params, dict):
		return atype

	if atype == 'click':
		label = _element_label(interacted_elements or [], action_index)
		node_type = None
		if interacted_elements and action_index < len(interacted_elements):
			el = interacted_elements[action_index]
			if isinstance(el, dict):
				node_type = el.get('node_name', '').lower() or None
		if label:
			tag_hint = f' ({node_type})' if node_type else ''
			return f'Clicked "{label}"{tag_hint}'
		return f'click [#{params.get("index", "?")}]'

	if atype == 'input_text':
		text = str(params.get('text', ''))
		if len(text) > 40:
			text = text[:37] + '...'
		return f"type '{text}'"

	if atype in ('navigate_to', 'navigate'):
		url = params.get('url', params.get('url', '?'))
		return f'navigate to {url}'

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

	if atype == 'upload_file':
		path = params.get('path', '')
		filename = os.path.basename(path) if path else '?'
		return f'upload file: {filename}'

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


def _fmt_duration(seconds: float) -> str:
	if seconds < 0:
		seconds = 0
	m, s = divmod(int(seconds), 60)
	h, m = divmod(m, 60)
	if h:
		return f'{h}h {m}m {s}s'
	return f'{m}m {s}s'


def _timestamp_label(unix_ts: float) -> str:
	dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
	return dt.strftime('%H:%M:%S')


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


def _has_deliberation(text: str) -> bool:
	t = text.lower()
	return any(kw in t for kw in _DELIBERATION_KEYWORDS)


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
	  2. Cognitive signals summary
	  3. Navigation summary
	  4. Action timeline with timing, element labels, errors, memory, and verdict

	Args:
	    history_path:    Path to a test_XX_*.json agent history file.
	    persona_name:    Human-readable persona name (e.g. "Steady Tasker").
	    scenario_name:   Short test scenario name.
	    scenario_steps:  Full steps_description from the test scenario.
	"""
	data = json.loads(history_path.read_text(encoding='utf-8'))
	history: list[dict[str, Any]] = data.get('history', [])

	# ── Pre-pass: collect URLs, timings, and action type stats ───────────────
	urls: list[str] = []
	titles: list[str] = []
	step_durations: list[float] = []
	session_start: float | None = None
	session_end: float | None = None
	action_type_counts: Counter[str] = Counter()
	error_count = 0
	deliberation_count = 0
	max_tabs_seen = 1

	for step in history:
		state = step.get('state', {})
		tabs = state.get('tabs', [])
		if tabs and isinstance(tabs[0], dict):
			url = tabs[0].get('url', '')
			if url:
				urls.append(url)
			title = tabs[0].get('title', '')
			if title:
				titles.append(title)
		elif state.get('url'):
			urls.append(state['url'])

		if len(tabs) > max_tabs_seen:
			max_tabs_seen = len(tabs)

		meta = step.get('metadata', {})
		t_start = meta.get('step_start_time')
		t_end = meta.get('step_end_time')
		if t_start and t_end:
			dur = t_end - t_start
			step_durations.append(dur)
			if session_start is None or t_start < session_start:
				session_start = t_start
			if session_end is None or t_end > session_end:
				session_end = t_end
		else:
			step_durations.append(0.0)

		mo = step.get('model_output', {})
		for action in mo.get('action', []) or []:
			if isinstance(action, dict):
				atype = next(iter(action), None)
				if atype:
					action_type_counts[atype] += 1

		for r in step.get('result', []):
			if isinstance(r, dict) and r.get('error'):
				error_count += 1

		thinking = mo.get('thinking', '') or ''
		if thinking and _has_deliberation(thinking):
			deliberation_count += 1

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

	# Dwell time: time between consecutive URL changes
	url_change_times: list[tuple[str, float]] = []
	for i, step in enumerate(history):
		tabs = step.get('state', {}).get('tabs', [])
		url = ''
		if tabs and isinstance(tabs[0], dict):
			url = tabs[0].get('url', '')
		elif step.get('state', {}).get('url'):
			url = step['state']['url']
		meta = step.get('metadata', {})
		t = meta.get('step_start_time')
		if url and t:
			url_change_times.append((_pathname(url), t))

	dwells: list[float] = []
	for i in range(len(url_change_times) - 1):
		p_cur, t_cur = url_change_times[i]
		p_next, t_next = url_change_times[i + 1]
		if p_cur != p_next and t_next > t_cur:
			dwells.append(t_next - t_cur)

	# ── Assemble sections ─────────────────────────────────────────────────────
	lines: list[str] = []

	# 1. Metadata header
	total_duration = (session_end - session_start) if session_start and session_end else None
	lines.append('=== Murphy Agent Session ===')
	lines.append(f'Persona: {persona_name}')
	lines.append(f'Task: {scenario_name}')
	lines.append(f'Task description: {_truncate(scenario_steps, 200)}')
	lines.append(f'Total steps: {len(history)}  |  Distinct pages: {len(unique_pages)}')
	if total_duration is not None:
		lines.append(f'Session duration: {_fmt_duration(total_duration)}')
	if session_start:
		lines.append(f'Session start (UTC): {_timestamp_label(session_start)}')
	lines.append('')

	# 2. Cognitive signals (equivalent to compressor's second section)
	cog_lines = ['=== Cognitive & Behavioral Signals ===']
	if action_type_counts:
		dist = ', '.join(f'{k} ×{v}' for k, v in action_type_counts.most_common())
		cog_lines.append(f'Action distribution: {dist}')
	if error_count:
		cog_lines.append(f'Errors encountered: {error_count}')
	if deliberation_count:
		cog_lines.append(f'Deliberation steps: {deliberation_count}')
	if backtracks:
		cog_lines.append(f'Navigation backtracks: {backtracks}')
	if max_tabs_seen > 1:
		cog_lines.append(f'Multi-tab: opened up to {max_tabs_seen} tabs')
	if len(cog_lines) > 1:
		lines.extend(cog_lines)
		lines.append('')

	# 3. Navigation summary
	lines.append('=== Navigation Summary ===')
	pages_str = ', '.join(unique_pages[:10])
	lines.append(f'Pages visited: {len(unique_pages)} unique ({pages_str})')
	lines.append(f'Navigation style: {nav_style} ({backtracks} backtracks in {transitions} transitions)')
	if dwells:
		longest_dwell = max(dwells)
		lines.append(f'Avg page dwell: {_fmt_duration(sum(dwells) / len(dwells))}')
		lines.append(f'Longest dwell: {_fmt_duration(longest_dwell)}')
	if max_tabs_seen > 1:
		lines.append(f'Multi-tab: up to {max_tabs_seen} tabs open simultaneously')
	lines.append('')

	# 4. Action timeline
	lines.append('=== Action Timeline ===')
	prev_plan_update: list[str] | None = None

	for i, step in enumerate(history, start=1):
		model_output: dict[str, Any] = step.get('model_output', {})
		results: list[dict[str, Any]] = step.get('result', [])
		state: dict[str, Any] = step.get('state', {})
		meta: dict[str, Any] = step.get('metadata', {})

		goal = model_output.get('next_goal', '').strip()
		eval_prev = model_output.get('evaluation_previous_goal', '').strip()
		thinking = (model_output.get('thinking', '') or '').strip()
		memory = (model_output.get('memory', '') or '').strip()
		actions: list[dict[str, Any]] = model_output.get('action', []) or []
		plan_update: list[str] | None = model_output.get('plan_update')
		current_plan_item: int | None = model_output.get('current_plan_item')

		# Interacted elements aligned with actions by position
		interacted_elements: list[Any] = state.get('interacted_element', []) or []

		# Step timing
		t_start = meta.get('step_start_time')
		t_end = meta.get('step_end_time')
		dur_str = ''
		ts_str = ''
		if t_start and t_end:
			dur = t_end - t_start
			dur_str = f' ({dur:.1f}s)'
			ts_str = f'[{_timestamp_label(t_start)}] '

		# Page title for context
		page_title = state.get('title', '')
		title_hint = f' — {page_title}' if page_title else ''

		action_labels = [_action_label(a, interacted_elements, idx) for idx, a in enumerate(actions) if isinstance(a, dict)]
		action_str = ' + '.join(action_labels) if action_labels else 'no action'

		# Collect all result contents (not just first)
		result_parts: list[str] = []
		errors: list[str] = []
		is_done = False
		done_data: dict[str, Any] | None = None

		for r in results:
			if not isinstance(r, dict):
				continue
			content = r.get('extracted_content', '')
			if content:
				result_parts.append(_truncate(str(content), 120))
			err = r.get('error')
			if err:
				errors.append(_truncate(str(err), 120))
			if r.get('is_done'):
				is_done = True

		# Extract done verdict data from the done action if present
		for action in actions:
			if isinstance(action, dict) and 'done' in action:
				done_params = action['done']
				if isinstance(done_params, dict):
					inner = done_params.get('data', done_params)
					if isinstance(inner, dict) and any(
						k in inner for k in ('reason', 'process_evaluation', 'usability_evaluation')
					):
						done_data = inner

		lines.append(f'{ts_str}[Step {i}]{title_hint}{dur_str} Goal: {_truncate(goal, 120)}')
		lines.append(f'  Action: {action_str}')

		# All result contents
		for part in result_parts:
			lines.append(f'  Result: {part}')

		# Errors
		for err in errors:
			lines.append(f'  Error: {err}')

		# Self-assessment (always include, not only on uncertainty keywords)
		if eval_prev and i > 1 and eval_prev.lower() != 'start':
			lines.append(f'  Assessment: {_truncate(eval_prev, 120)}')

		# Working memory snapshot (only when it changes meaningfully)
		if memory:
			lines.append(f'  Memory: {_truncate(memory, 160)}')

		# Deliberation excerpt
		if thinking and (_has_deliberation(thinking) or len(actions) > 1):
			lines.append(f'  Deliberation: {_truncate(thinking, 150)}')

		# Plan tracking — emit only when plan changes
		if plan_update is not None and plan_update != prev_plan_update:
			if current_plan_item is not None and current_plan_item < len(plan_update):
				current_step_label = plan_update[current_plan_item]
				lines.append(f'  Plan step {current_plan_item + 1}/{len(plan_update)}: {_truncate(current_step_label, 80)}')
			prev_plan_update = plan_update

		# Done verdict fields
		if done_data:
			for field in ('reason', 'process_evaluation', 'logical_evaluation', 'usability_evaluation', 'validation_evidence'):
				val = done_data.get(field, '')
				if val:
					label = field.replace('_', ' ').capitalize()
					lines.append(f'  Verdict {label}: {_truncate(str(val), 200)}')

		if is_done:
			lines.append('  [Task ended]')

	return '\n'.join(lines)
