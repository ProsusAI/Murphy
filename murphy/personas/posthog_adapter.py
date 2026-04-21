"""PostHog adapter — maps PostHogClient output to canonical analytics models."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from murphy.personas.models import AnalyticsEvent, AnalyticsSession
from murphy.personas.posthog_client import PostHogClient

SOURCE = 'posthog'


def _parse_timestamp(value: Any) -> datetime:
	if isinstance(value, datetime):
		return value
	return datetime.fromisoformat(str(value))


def _parse_properties(value: Any) -> dict[str, Any]:
	if isinstance(value, dict):
		return value
	if isinstance(value, str):
		try:
			parsed = json.loads(value)
			if isinstance(parsed, dict):
				return parsed
		except (json.JSONDecodeError, TypeError):
			pass
	return {}


def _event_from_dict(row: dict[str, Any], *, has_uuid: bool = True) -> AnalyticsEvent:
	return AnalyticsEvent(
		event_id=row['uuid'] if has_uuid else uuid.uuid4().hex,
		event_name=row['event'],
		user_id=row['distinct_id'],
		session_id=row.get('session_id'),
		timestamp=_parse_timestamp(row['timestamp']),
		properties=_parse_properties(row.get('properties')),
		elements_chain=row.get('elements_chain') or '',
		source=SOURCE,
		raw=row,
	)


class PostHogAdapter:
	"""Wraps :class:`PostHogClient` and exposes the :class:`AnalyticsConnector` interface."""

	def __init__(self, client: PostHogClient) -> None:
		self._client = client

	async def get_events(
		self,
		*,
		after: str | datetime | None = None,
		before: str | datetime | None = None,
		limit: int = 1000,
	) -> list[AnalyticsEvent]:
		rows = await self._client.fetch_events(after=after, before=before, limit=limit)
		return [_event_from_dict(r, has_uuid=True) for r in rows]

	async def get_sessions(
		self,
		*,
		num_sessions: int | None = None,
		min_events: int | None = None,
		after: str | datetime | None = None,
		before: str | datetime | None = None,
		offset: int = 0,
		tenants: list[str] | None = None,
	) -> list[AnalyticsSession]:
		raw = await self._client.sample_user_sessions(
			num_sessions=num_sessions,
			min_events=min_events,
			after=after,
			before=before,
			offset=offset,
			tenants=tenants,
		)
		sessions: list[AnalyticsSession] = []
		for uid, user_sessions in raw.items():
			for s in user_sessions:
				events = [_event_from_dict(e, has_uuid=False) for e in s.get('events', [])]
				sessions.append(
					AnalyticsSession(
						session_id=s['session_id'],
						user_id=uid,
						started_at=_parse_timestamp(s['session_start']),
						ended_at=_parse_timestamp(s['session_end']),
						event_count=s['event_count'],
						events=events,
						source=SOURCE,
					)
				)
		return sessions
