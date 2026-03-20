"""Session compressor — converts AnalyticsSession into a token-efficient text timeline.

Produces three sections: metadata header, navigation summary, and compressed
event timeline.  Designed for LLM consumption in the persona discovery and
scoring pipeline.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from murphy.personas.models import AnalyticsEvent, AnalyticsSession

NOISE_EVENTS = frozenset(
	{
		'$web_vitals',
		'$set',
		'$identify',
		'$feature_flag_called',
		'build_outdated',
		'$pageleave',
	}
)

NOISE_PREFIXES = ('pusher_',)


def _is_noise(event_name: str) -> bool:
	if event_name in NOISE_EVENTS:
		return True
	return any(event_name.startswith(p) for p in NOISE_PREFIXES)


def _fmt_duration(seconds: float) -> str:
	if seconds < 0:
		seconds = 0
	m, s = divmod(int(seconds), 60)
	h, m = divmod(m, 60)
	if h:
		return f'{h}h {m}m {s}s'
	return f'{m}m {s}s'


def _extract_pathname(url_or_path: str) -> str:
	if url_or_path.startswith('http'):
		return urlparse(url_or_path).path or '/'
	return url_or_path or '/'


def _feature_section(pathname: str) -> str:
	"""Map a pathname to its top-level feature section."""
	parts = [p for p in pathname.strip('/').split('/') if p]
	if not parts:
		return 'home'
	return parts[0]


def _timestamp_label(ts: datetime) -> str:
	return ts.strftime('%H:%M:%S')


def _compress_event_label(event: AnalyticsEvent) -> str:
	"""Return a human-readable one-line label for an event."""
	name = event.event_name
	props = event.properties

	if name == '$pageview':
		pathname = props.get('$pathname') or props.get('$current_url', '')
		return f'Navigated to {_extract_pathname(pathname)}'

	if name == '$autocapture':
		el_text = props.get('$el_text', '').strip()
		if el_text:
			return f'Clicked "{el_text[:60]}"'
		return 'Interacted with element'

	if name == 'conversation_started':
		model = props.get('model', '?')
		space = props.get('withinSpace', False)
		return f'Started conversation (model={model}, space={space})'

	if name == 'conversation_continued':
		return 'Sent follow-up message'

	if name in ('file_uploaded', 'file_pasted', 'file_dropped'):
		return 'Uploaded file'

	if name == 'message_feedback':
		feedback = props.get('feedback', '?')
		return f'Gave {feedback} feedback'

	if name == '$rageclick':
		return 'Rage-clicked'

	if name == '$exception':
		return 'Error encountered'

	if name == 'scroll_down_clicked':
		return 'Scrolled down'

	# ── Knowledge management ──────────────────────────────────────────────
	if name == 'memory_added':
		return 'Added a memory'
	if name == 'memory_updated':
		return 'Updated a memory'
	if name == 'memory_deleted':
		return 'Deleted a memory'
	if name == 'all_memories_deleted':
		return 'Deleted all memories'
	if name == 'memory_preferences_updated':
		return 'Updated memory preferences'
	if name == 'learning_preferences_updated':
		return 'Updated learning preferences'
	if name == 'knowledge_added':
		return 'Added knowledge'
	if name == 'knowledge_deleted':
		return 'Deleted knowledge'

	# ── Prompt engineering ────────────────────────────────────────────────
	if name == 'prompt_created':
		return 'Created a saved prompt'
	if name == 'prompt_selected':
		return 'Selected a saved prompt'
	if name == 'stored_prompt_used':
		source = props.get('source', '')
		suffix = f' (from {source})' if source else ''
		return f'Used a stored prompt{suffix}'
	if name == 'prompts_library_opened':
		return 'Opened prompts library'
	if name == 'prompts_library_loaded':
		return 'Browsed prompts library'

	# ── Feedback depth ────────────────────────────────────────────────────
	if name == 'additional_feedback_started':
		return 'Started writing detailed feedback'
	if name == 'additional_feedback_sent':
		return 'Submitted detailed feedback'
	if name == 'additional_feedback_cancelled':
		return 'Cancelled detailed feedback'

	# ── Model selection ───────────────────────────────────────────────────
	if name == 'model_select_changed':
		model_id = props.get('model_id', '?')
		return f'Switched model to {model_id}'

	return name.replace('_', ' ')


# ── Metadata header ──────────────────────────────────────────────────────────


def _build_metadata_header(
	session: AnalyticsSession,
	person_context: dict[str, Any] | None,
) -> str:
	lines = ['=== Session Metadata ===']
	lines.append(f'User: {session.user_id}')

	if person_context:
		created_at = person_context.get('created_at')
		if created_at:
			if isinstance(created_at, str):
				try:
					created_at = datetime.fromisoformat(created_at)
				except ValueError:
					created_at = None
			if created_at:
				age_days = (datetime.now(tz=timezone.utc) - created_at.replace(tzinfo=timezone.utc)).days
				lines.append(f'Account age: {age_days} days')
		initial_ref = person_context.get('initial_referring_domain') or person_context.get('initial_ref')
		if initial_ref:
			lines.append(f'Initial acquisition: {initial_ref}')

	duration = (session.ended_at - session.started_at).total_seconds()
	lines.append(f'Session duration: {_fmt_duration(duration)}')
	lines.append(f'Total events: {session.event_count}')

	if session.events:
		first_props = session.events[0].properties
		entry_path = first_props.get('$session_entry_pathname', '')
		if entry_path:
			lines.append(f'Entry page: {entry_path}')
		entry_ref = first_props.get('$session_entry_referring_domain') or first_props.get('$session_entry_referrer', '')
		if entry_ref:
			lines.append(f'Entry referrer: {entry_ref}')

		browser = first_props.get('$browser', '')
		os_name = first_props.get('$os', '')
		device = first_props.get('$device_type', '')
		if browser or os_name or device:
			parts = [p for p in [device, browser, os_name] if p]
			lines.append(f'Device: {", ".join(parts)}')

		city = first_props.get('$geoip_city_name', '')
		country = first_props.get('$geoip_country_name', '')
		if city or country:
			loc_parts = [p for p in [city, country] if p]
			lines.append(f'Location: {", ".join(loc_parts)}')

		lang = first_props.get('$browser_language', '')
		if lang:
			lines.append(f'Language: {lang}')

	rageclick_count = sum(1 for e in session.events if e.event_name == '$rageclick')
	if rageclick_count:
		lines.append(f'Rage clicks: {rageclick_count}')

	lcp = _extract_lcp(session.events)
	if lcp is not None:
		lines.append(f'Page load (LCP): {lcp:.1f}s')

	return '\n'.join(lines)


def _extract_lcp(events: list[AnalyticsEvent]) -> float | None:
	"""Extract LCP value from the first $web_vitals event, if present."""
	for e in events:
		if e.event_name == '$web_vitals':
			lcp_val = e.properties.get('$web_vitals_LCP_value')
			if lcp_val is not None:
				try:
					return float(lcp_val) / 1000.0
				except (ValueError, TypeError):
					pass
	return None


# ── Cognitive signals summary ────────────────────────────────────────────

_KNOWLEDGE_MGMT_EVENTS = frozenset(
	{
		'memory_added',
		'memory_updated',
		'memory_deleted',
		'all_memories_deleted',
		'memory_preferences_updated',
		'learning_preferences_updated',
		'knowledge_added',
		'knowledge_deleted',
	}
)

_PROMPT_ENGINEERING_EVENTS = frozenset(
	{
		'prompt_created',
		'prompt_selected',
		'stored_prompt_used',
		'prompts_library_opened',
		'prompts_library_loaded',
	}
)

_FEEDBACK_DEPTH_EVENTS = frozenset(
	{
		'additional_feedback_started',
		'additional_feedback_sent',
		'additional_feedback_cancelled',
	}
)


def _build_cognitive_signals(events: list[AnalyticsEvent]) -> str | None:
	"""Summarise knowledge-management, prompt-engineering, feedback-depth,
	and model-selection activity. Returns ``None`` when no signals are present."""
	km_counts: Counter[str] = Counter()
	pe_counts: Counter[str] = Counter()
	fb_counts: Counter[str] = Counter()
	model_switches: list[str] = []
	feedback_polarities: Counter[str] = Counter()

	for e in events:
		name = e.event_name
		if name in _KNOWLEDGE_MGMT_EVENTS:
			km_counts[name] += 1
		elif name in _PROMPT_ENGINEERING_EVENTS:
			pe_counts[name] += 1
		elif name in _FEEDBACK_DEPTH_EVENTS:
			fb_counts[name] += 1
		elif name == 'model_select_changed':
			model_id = e.properties.get('model_id', '?')
			model_switches.append(model_id)
		elif name == 'message_feedback':
			polarity = e.properties.get('feedback', 'unknown')
			feedback_polarities[polarity] += 1

	if not (km_counts or pe_counts or fb_counts or model_switches):
		return None

	lines = ['=== Cognitive & Communication Signals ===']

	if km_counts:
		total = sum(km_counts.values())
		detail = ', '.join(f'{k.replace("_", " ")}: {v}' for k, v in km_counts.most_common())
		lines.append(f'Knowledge management actions: {total} ({detail})')

	if pe_counts:
		total = sum(pe_counts.values())
		detail = ', '.join(f'{k.replace("_", " ")}: {v}' for k, v in pe_counts.most_common())
		lines.append(f'Prompt engineering actions: {total} ({detail})')

	if feedback_polarities:
		detail = ', '.join(f'{k}: {v}' for k, v in feedback_polarities.most_common())
		lines.append(f'Feedback given: {detail}')

	if fb_counts:
		started = fb_counts.get('additional_feedback_started', 0)
		sent = fb_counts.get('additional_feedback_sent', 0)
		cancelled = fb_counts.get('additional_feedback_cancelled', 0)
		lines.append(f'Detailed feedback: {sent} sent, {cancelled} cancelled (of {started} started)')

	if model_switches:
		unique_models = list(dict.fromkeys(model_switches))
		lines.append(f'Model switches: {len(model_switches)} (models used: {", ".join(unique_models)})')

	return '\n'.join(lines)


# ── Navigation summary ───────────────────────────────────────────────────────


def _build_navigation_summary(events: list[AnalyticsEvent]) -> str:
	pageviews = [e for e in events if e.event_name == '$pageview']
	if not pageviews:
		return '=== Navigation Summary ===\nNo pageviews recorded.'

	pathnames: list[str] = []
	for pv in pageviews:
		pathname = pv.properties.get('$pathname') or pv.properties.get('$current_url', '/')
		pathnames.append(_extract_pathname(pathname))

	unique_pages = list(dict.fromkeys(pathnames))
	sections = list(dict.fromkeys(_feature_section(p) for p in pathnames))

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

	custom_events = [e for e in events if not e.event_name.startswith('$') and not _is_noise(e.event_name)]
	if custom_events and pageviews:
		ttfa = (custom_events[0].timestamp - pageviews[0].timestamp).total_seconds()
	else:
		ttfa = None

	dwells: list[float] = []
	for i in range(len(pageviews) - 1):
		gap = (pageviews[i + 1].timestamp - pageviews[i].timestamp).total_seconds()
		if gap > 0:
			dwells.append(gap)

	lines = ['=== Navigation Summary ===']
	lines.append(f'Pages visited: {len(unique_pages)} unique ({", ".join(unique_pages[:8])})')
	lines.append(f'Feature sections: {len(sections)} ({", ".join(sections[:8])})')
	lines.append(f'Navigation style: {nav_style} ({backtracks} backtracks in {transitions} transitions)')
	if ttfa is not None:
		lines.append(f'Time to first action: {_fmt_duration(ttfa)}')
	if dwells:
		longest_idx = dwells.index(max(dwells))
		longest_page = pathnames[longest_idx] if longest_idx < len(pathnames) else '?'
		lines.append(f'Longest dwell: {longest_page} ({_fmt_duration(max(dwells))})')
		lines.append(f'Avg page dwell: {_fmt_duration(sum(dwells) / len(dwells))}')

	return '\n'.join(lines)


# ── Event timeline ───────────────────────────────────────────────────────────


def _build_event_timeline(events: list[AnalyticsEvent]) -> str:
	filtered = [e for e in events if not _is_noise(e.event_name)]
	if not filtered:
		return '=== Event Timeline ===\n(no events after filtering)'

	lines = ['=== Event Timeline ===']
	prev_label: str | None = None
	repeat_count = 0

	def _flush_repeats() -> None:
		nonlocal prev_label, repeat_count
		if prev_label and repeat_count > 1:
			lines[-1] = lines[-1] + f' (x{repeat_count})'
		prev_label = None
		repeat_count = 0

	for event in filtered:
		label = _compress_event_label(event)
		if label == prev_label:
			repeat_count += 1
			continue

		_flush_repeats()
		ts = _timestamp_label(event.timestamp)
		lines.append(f'[{ts}] {label}')
		prev_label = label
		repeat_count = 1

	_flush_repeats()
	return '\n'.join(lines)


# ── Sanitisation ─────────────────────────────────────────────────────────────

_CONTROL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


def _sanitize(text: str) -> str:
	"""Strip characters that break JSON serialisation for the OpenAI API.

	Applies two passes:
	1. Remove ASCII control characters (NUL, backspace, etc.) except
	   tab (\\x09), newline (\\x0a), and carriage return (\\x0d).
	2. Re-encode through UTF-8 with surrogate and error replacement to
	   drop any lone surrogates or invalid sequences.
	"""
	text = _CONTROL_CHARS.sub('', text)
	return text.encode('utf-8', errors='replace').decode('utf-8', errors='replace')


# ── Public API ───────────────────────────────────────────────────────────────


def compress_session(
	session: AnalyticsSession,
	person_context: dict[str, Any] | None = None,
) -> str:
	"""Convert an AnalyticsSession into a compact text timeline for LLM consumption.

	Returns a string with sections: metadata header, cognitive signals summary
	(when present), navigation summary, and compressed event timeline.
	"""
	header = _build_metadata_header(session, person_context)
	cognitive = _build_cognitive_signals(session.events)
	nav = _build_navigation_summary(session.events)
	timeline = _build_event_timeline(session.events)

	sections = [header]
	if cognitive:
		sections.append(cognitive)
	sections.append(nav)
	sections.append(timeline)
	return _sanitize('\n\n'.join(sections))
