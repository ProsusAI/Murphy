"""Databricks adapter — maps murphy_evals_data rows to canonical analytics models."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from murphy.config import DATABRICKS_EVALS_TABLE, DATABRICKS_EVENT_DATE_FROM
from murphy.personas.databricks_normalize import databricks_row_to_session
from murphy.personas.databricks_sql_client import DatabricksSqlClient
from murphy.personas.models import AnalyticsEvent, AnalyticsSession

logger = logging.getLogger(__name__)

SOURCE = 'databricks'


class DatabricksAdapter:
	"""Reads session-grain rows from Unity Catalog murphy_evals_data."""

	def __init__(self, client: DatabricksSqlClient | None = None, *, table: str | None = None) -> None:
		self._client = client or DatabricksSqlClient()
		self._table = table or DATABRICKS_EVALS_TABLE
		self.last_session_contexts: dict[str, dict[str, Any]] = {}
		self.last_person_contexts: dict[str, dict[str, Any]] = {}

	async def get_events(
		self,
		*,
		after: str | datetime | None = None,
		before: str | datetime | None = None,
		limit: int = 1000,
	) -> list[AnalyticsEvent]:
		sessions = await self.get_sessions(num_sessions=limit, min_events=1, after=after, before=before)
		events: list[AnalyticsEvent] = []
		for session in sessions:
			events.extend(session.events)
		events.sort(key=lambda e: e.timestamp)
		return events[:limit]

	async def get_sessions(
		self,
		*,
		num_sessions: int | None = None,
		min_events: int | None = None,
		after: str | datetime | None = None,
		before: str | datetime | None = None,
		offset: int = 0,
		event_date_from: str | None = None,
	) -> list[AnalyticsSession]:
		min_ev = min_events if min_events is not None else 1
		limit = num_sessions if num_sessions is not None else 100
		date_from = event_date_from or after or DATABRICKS_EVENT_DATE_FROM
		if isinstance(date_from, datetime):
			date_from = date_from.strftime('%Y-%m-%d')

		sql = f"""
SELECT
  conversation_id,
  session_id,
  user_email,
  session_start,
  session_end,
  event_count,
  origin_title,
  space_id,
  message_count,
  to_json(events) AS events,
  to_json(interactions) AS interactions
FROM {self._table}
WHERE event_count >= :min_events
  AND session_start >= :event_date_from
ORDER BY hash(conversation_id, session_id)
LIMIT :limit OFFSET :offset
"""
		params: dict[str, Any] = {
			'min_events': min_ev,
			'event_date_from': date_from,
			'limit': limit,
			'offset': offset,
		}
		if before is not None:
			before_val = before.strftime('%Y-%m-%d %H:%M:%S') if isinstance(before, datetime) else str(before)
			sql = sql.replace(
				'ORDER BY hash',
				'  AND session_end <= :before\nORDER BY hash',
			)
			params['before'] = before_val

		rows = await self._client.query(sql, params)
		sessions: list[AnalyticsSession] = []
		session_contexts: dict[str, dict[str, Any]] = {}
		person_contexts: dict[str, dict[str, Any]] = {}

		for row in rows:
			session, session_context, person_context = databricks_row_to_session(row)
			sessions.append(session)
			session_contexts[session.session_id] = session_context
			if person_context:
				person_contexts[session.user_id] = person_context

		self.last_session_contexts = session_contexts
		self.last_person_contexts = person_contexts
		logger.info(
			'Databricks: fetched %d sessions (min_events=%d, offset=%d, date_from=%s)',
			len(sessions),
			min_ev,
			offset,
			date_from,
		)
		return sessions

	async def fetch_population_paths(self, event_date_from: str | None = None) -> str:
		"""Aggregate top pathnames from nested events arrays."""
		date_from = event_date_from or DATABRICKS_EVENT_DATE_FROM
		sql = f"""
SELECT e.pathname AS page, count(*) AS visits
FROM {self._table}
LATERAL VIEW explode(events) ev AS e
WHERE session_start >= :event_date_from
  AND e.event_name = '$pageview'
  AND e.pathname IS NOT NULL
  AND trim(e.pathname) != ''
GROUP BY e.pathname
ORDER BY visits DESC
LIMIT 30
"""
		try:
			rows = await self._client.query(sql, {'event_date_from': date_from})
			if not rows:
				return 'No aggregate flow data available.'
			lines = ['Top pages by visit count:']
			for row in rows:
				lines.append(f'  {row.get("page", "?")} — {row.get("visits", 0)} visits')
			return '\n'.join(lines)
		except Exception:
			logger.warning('Failed to fetch Databricks population paths', exc_info=True)
			return 'Aggregate flow data unavailable.'
