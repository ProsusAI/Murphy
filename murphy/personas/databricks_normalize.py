"""Map flat Databricks murphy_evals_data rows to canonical AnalyticsEvent models."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from murphy.personas.models import AnalyticsEvent, AnalyticsSession

SOURCE = 'databricks'


def _coerce_struct(value: Any) -> dict[str, Any]:
	"""Convert SQL connector structs (dict, Row, JSON string) to a plain dict."""
	if isinstance(value, dict):
		return value
	if hasattr(value, 'asDict'):
		return value.asDict(recursive=True)
	if isinstance(value, str):
		stripped = value.strip()
		if stripped.startswith('Row(') and stripped.endswith(')'):
			return _parse_row_literal(stripped)
		try:
			parsed = json.loads(stripped)
		except json.JSONDecodeError:
			parsed = None
		if isinstance(parsed, dict):
			return parsed
	raise TypeError(f'Expected struct-like event/interaction, got {type(value).__name__}')


def _parse_row_literal(value: str) -> dict[str, Any]:
	"""Parse ``Row(k='v', flag=True, tab=None)`` strings from the SQL connector."""
	inner = value.strip()[4:-1]
	fields: dict[str, Any] = {}
	i = 0
	length = len(inner)

	def skip_ws() -> None:
		nonlocal i
		while i < length and inner[i] in ' \t':
			i += 1

	def parse_value() -> Any:
		nonlocal i
		skip_ws()
		if i >= length:
			raise ValueError('Unexpected end of Row literal')
		if inner.startswith('None', i):
			i += 4
			return None
		if inner.startswith('True', i):
			i += 4
			return True
		if inner.startswith('False', i):
			i += 5
			return False
		if inner[i] in '"\'':
			quote = inner[i]
			i += 1
			start = i
			while i < length and inner[i] != quote:
				if inner[i] == '\\' and i + 1 < length:
					i += 2
					continue
				i += 1
			val = inner[start:i]
			i += 1
			return val
		start = i
		while i < length and inner[i] not in ',)':
			i += 1
		raw = inner[start:i].strip()
		if not raw:
			raise ValueError('Empty Row field value')
		try:
			if '.' in raw:
				return float(raw)
			return int(raw)
		except ValueError:
			return raw

	while i < length:
		skip_ws()
		key_start = i
		while i < length and (inner[i].isalnum() or inner[i] == '_'):
			i += 1
		key = inner[key_start:i]
		skip_ws()
		if i >= length or inner[i] != '=':
			raise ValueError(f'Invalid Row literal near index {i}')
		i += 1
		fields[key] = parse_value()
		skip_ws()
		if i < length:
			if inner[i] != ',':
				raise ValueError(f'Expected comma in Row literal near index {i}')
			i += 1

	return fields


def _coerce_struct_list(values: Any) -> list[dict[str, Any]]:
	if not values:
		return []
	if isinstance(values, str):
		parsed = json.loads(values)
		if not isinstance(parsed, list):
			raise TypeError(f'Expected JSON array of structs, got {type(parsed).__name__}')
		return [_coerce_struct(v) for v in parsed]
	return [_coerce_struct(v) for v in values]


def _parse_timestamp(value: Any) -> datetime:
	if isinstance(value, datetime):
		return value
	return datetime.fromisoformat(str(value).replace('Z', '+00:00'))


def _composite_session_id(conversation_id: str, session_id: str) -> str:
	return f'{conversation_id}:{session_id}'


def databricks_event_to_analytics_event(
	row: dict[str, Any],
	*,
	user_id: str,
	composite_session_id: str,
) -> AnalyticsEvent:
	"""Convert one flat event struct from murphy_evals_data.events[] to AnalyticsEvent."""
	props: dict[str, Any] = {}
	pathname = row.get('pathname')
	if pathname:
		props['$pathname'] = pathname
	tab = row.get('tab')
	if tab:
		props['tab'] = tab
	surface = row.get('surface')
	if surface:
		props['surface'] = surface
	feedback = row.get('feedback')
	if feedback is not None and str(feedback).strip():
		props['feedback'] = feedback
	conv_id = row.get('conversation_id')
	if conv_id:
		props['conversation_id'] = conv_id
	if row.get('ph_event_has_conversation_id') is not None:
		props['ph_event_has_conversation_id'] = row['ph_event_has_conversation_id']
	if row.get('distinct_id'):
		props['distinct_id'] = row['distinct_id']
	if row.get('email_source'):
		props['email_source'] = row['email_source']

	# Merge the full PostHog `properties` map when present (enriched murphy_evals_data_props
	# table). It arrives as a JSON string (VARIANT serialized via to_json in SQL). Keys are
	# PostHog-native, so they already match what the compressor consumes. Curated scalars above
	# win on key conflicts (they derive from the same source columns, so values agree). Absent
	# on the baseline table -> no-op, keeping behavior unchanged.
	raw_props = row.get('properties')
	if isinstance(raw_props, str):
		try:
			raw_props = json.loads(raw_props)
		except json.JSONDecodeError:
			raw_props = None
	if isinstance(raw_props, dict):
		props = {**raw_props, **props}

	elements_chain = row.get('elements_chain') or ''
	if not elements_chain and isinstance(raw_props, dict):
		elements_chain = raw_props.get('elements_chain') or raw_props.get('$elements_chain') or ''

	event_id = row.get('event_id') or row.get('event_name', 'unknown')
	return AnalyticsEvent(
		event_id=str(event_id),
		event_name=str(row.get('event_name', 'unknown')),
		user_id=user_id,
		session_id=composite_session_id,
		timestamp=_parse_timestamp(row['event_timestamp']),
		properties=props,
		elements_chain=str(elements_chain),
		source=SOURCE,
		raw=row,
	)


def databricks_row_to_session(
	row: dict[str, Any],
) -> tuple[AnalyticsSession, dict[str, Any], dict[str, Any]]:
	"""Convert one murphy_evals_data table row to AnalyticsSession, session_context, person_context."""
	conversation_id = str(row['conversation_id'])
	session_id = str(row['session_id'])
	composite_id = _composite_session_id(conversation_id, session_id)

	user_email = (row.get('user_email') or '').strip()
	events_raw = _coerce_struct_list(row.get('events'))
	user_id = user_email
	if not user_id and events_raw:
		first_distinct = events_raw[0].get('distinct_id')
		user_id = str(first_distinct or composite_id)
	if not user_id:
		user_id = composite_id

	events = [
		databricks_event_to_analytics_event(
			e,
			user_id=user_id,
			composite_session_id=composite_id,
		)
		for e in events_raw
	]
	events.sort(key=lambda e: e.timestamp)

	interactions = _coerce_struct_list(row.get('interactions'))

	first_model: str | None = None
	for ix in interactions:
		if isinstance(ix, dict) and ix.get('model_name'):
			first_model = str(ix['model_name'])
			break

	for event in events:
		if event.event_name == 'conversation_started' and first_model and 'model' not in event.properties:
			event.properties['model'] = first_model
		if event.event_name == 'conversation_started' and row.get('space_id') is not None:
			event.properties.setdefault('withinSpace', bool(row.get('space_id')))

	session_context: dict[str, Any] = {
		'conversation_id': conversation_id,
		'origin_title': row.get('origin_title'),
		'space_id': row.get('space_id'),
		'message_count': row.get('message_count', 0),
		'interactions': interactions,
		'user_email': user_email or None,
	}

	person_context: dict[str, Any] = {}
	if user_email:
		person_context['user_email'] = user_email
	if row.get('origin_title'):
		person_context['origin_title'] = row['origin_title']
	if row.get('space_id'):
		person_context['space_id'] = row['space_id']

	session = AnalyticsSession(
		session_id=composite_id,
		user_id=user_id,
		started_at=_parse_timestamp(row['session_start']),
		ended_at=_parse_timestamp(row['session_end']),
		event_count=int(row.get('event_count') or len(events)),
		events=events,
		source=SOURCE,
	)

	return session, session_context, person_context
