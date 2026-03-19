"""PostHog API client for ingesting events, persons, and cohorts.

Uses the HogQL Query API (POST /api/projects/:project_id/query/) for events
and persons, and the REST API for cohorts. Returns raw JSON — no Pydantic
wrapping — so downstream consumers (e.g. trait mapping) decide their own schema.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any

import httpx

from murphy.config import POSTHOG_API_KEY, POSTHOG_HOST, POSTHOG_PROJECT_ID

logger = logging.getLogger(__name__)


class PostHogAPIError(Exception):
	"""Raised when the PostHog API returns a non-2xx response."""

	def __init__(self, status_code: int, detail: str) -> None:
		self.status_code = status_code
		self.detail = detail
		super().__init__(f'PostHog API error {status_code}: {detail}')


class PostHogClient:
	"""Async client for reading data from PostHog.

	Usage::

		async with PostHogClient() as client:
			events = await client.fetch_events(after='2025-01-01')
	"""

	def __init__(
		self,
		api_key: str = '',
		project_id: str = '',
		host: str = '',
	) -> None:
		self._api_key = api_key or POSTHOG_API_KEY
		self._project_id = project_id or POSTHOG_PROJECT_ID
		self._host = (host or POSTHOG_HOST).rstrip('/')
		if not self._api_key:
			raise ValueError('PostHog API key is required (set POSTHOG_API_KEY or pass api_key)')
		if not self._project_id:
			raise ValueError('PostHog project ID is required (set POSTHOG_PROJECT_ID or pass project_id)')
		self._client: httpx.AsyncClient | None = None

	async def __aenter__(self) -> PostHogClient:
		self._client = httpx.AsyncClient(
			base_url=self._host,
			headers={'Authorization': f'Bearer {self._api_key}'},
			timeout=30.0,
		)
		return self

	async def __aexit__(self, *exc: Any) -> None:
		if self._client:
			await self._client.aclose()
			self._client = None

	def _ensure_client(self) -> httpx.AsyncClient:
		if self._client is None:
			raise RuntimeError('PostHogClient must be used as an async context manager')
		return self._client

	# ─── Core query method ────────────────────────────────────────────────────

	async def query(self, hogql: str) -> dict[str, Any]:
		"""Execute a raw HogQL query and return the full response.

		Returns a dict with keys: ``columns``, ``results``, ``hasMore``, etc.
		Use a LIMIT clause in your HogQL string to control result size.
		"""
		client = self._ensure_client()
		resp = await client.post(
			f'/api/projects/{self._project_id}/query/',
			json={
				'query': {
					'kind': 'HogQLQuery',
					'query': hogql,
				},
			},
		)
		if resp.status_code >= 400:
			raise PostHogAPIError(resp.status_code, resp.text)
		return resp.json()

	# ─── Events ───────────────────────────────────────────────────────────────

	async def fetch_events(
		self,
		*,
		event_types: list[str] | None = None,
		after: str | datetime | None = None,
		before: str | datetime | None = None,
		distinct_id: str | None = None,
		limit: int = 1000,
	) -> list[dict[str, Any]]:
		"""Fetch events via HogQL. Returns a list of event dicts."""
		conditions: list[str] = []
		if event_types:
			escaped = ', '.join(f"'{e}'" for e in event_types)
			conditions.append(f'event IN ({escaped})')
		if after:
			conditions.append(f"timestamp > '{_to_iso(after)}'")
		if before:
			conditions.append(f"timestamp < '{_to_iso(before)}'")
		if distinct_id:
			conditions.append(f"distinct_id = '{distinct_id}'")

		where = f' WHERE {" AND ".join(conditions)}' if conditions else ''
		hogql = (
			f'SELECT uuid, event, distinct_id, properties.$session_id as session_id, timestamp, properties'
			f' FROM events{where}'
			f' ORDER BY timestamp DESC'
			f' LIMIT {limit}'
		)
		result = await self.query(hogql)
		return _rows_to_dicts(result)

	# ─── Persons ──────────────────────────────────────────────────────────────

	async def fetch_persons(
		self,
		*,
		limit: int = 1000,
		properties_filter: str | None = None,
	) -> list[dict[str, Any]]:
		"""Fetch persons via HogQL. Returns a list of person dicts.

		``properties_filter`` is an optional raw HogQL WHERE clause fragment
		applied to person properties, e.g. ``"properties.email IS NOT NULL"``.
		"""
		where = f' WHERE {properties_filter}' if properties_filter else ''
		hogql = (
			f'SELECT id, properties, created_at'
			f' FROM persons{where}'
			f' ORDER BY created_at DESC'
			f' LIMIT {limit}'
		)
		result = await self.query(hogql)
		return _rows_to_dicts(result)

	# ─── User session sampling ────────────────────────────────────────────────

	async def sample_user_sessions(
		self,
		*,
		num_users: int = 10,
		sessions_per_user: int = 3,
		after: str | datetime | None = None,
		before: str | datetime | None = None,
	) -> dict[str, list[dict[str, Any]]]:
		"""Sample random users and return their most recent sessions with events.

		Returns a dict keyed by ``distinct_id``, where each value is a list of
		session dicts (most recent first, up to ``sessions_per_user``). Each
		session dict has ``session_id``, ``session_start``, ``session_end``,
		``event_count``, and ``events`` (chronological list of event dicts).
		"""
		time_filter = ''
		time_conditions: list[str] = []
		if after:
			time_conditions.append(f"timestamp > '{_to_iso(after)}'")
		if before:
			time_conditions.append(f"timestamp < '{_to_iso(before)}'")
		if time_conditions:
			time_filter = f' AND {" AND ".join(time_conditions)}'

		# 1. Pick random users that have session data
		users_q = (
			f'SELECT DISTINCT distinct_id FROM events'
			f" WHERE properties.$session_id IS NOT NULL{time_filter}"
			f' ORDER BY cityHash64(distinct_id) LIMIT {num_users}'
		)
		users_result = await self.query(users_q)
		user_ids = [row[0] for row in users_result.get('results', [])]
		if not user_ids:
			logger.info('PostHog: no users found with session data')
			return {}

		# 2. Get sessions for these users (most recent first)
		escaped_ids = ', '.join(f"'{uid}'" for uid in user_ids)
		max_sessions = num_users * sessions_per_user
		sessions_q = (
			f'SELECT distinct_id, properties.$session_id as session_id,'
			f' min(timestamp) as session_start, max(timestamp) as session_end,'
			f' count() as event_count'
			f' FROM events'
			f' WHERE distinct_id IN ({escaped_ids})'
			f" AND properties.$session_id IS NOT NULL{time_filter}"
			f' GROUP BY distinct_id, session_id'
			f' ORDER BY distinct_id, session_start DESC'
			f' LIMIT {max_sessions}'
		)
		sessions_result = await self.query(sessions_q)
		sessions_rows = _rows_to_dicts(sessions_result)

		# Keep only the N most recent sessions per user
		user_sessions: dict[str, list[dict[str, Any]]] = defaultdict(list)
		for row in sessions_rows:
			uid = row['distinct_id']
			if len(user_sessions[uid]) < sessions_per_user:
				user_sessions[uid].append(row)

		all_session_ids = [s['session_id'] for slist in user_sessions.values() for s in slist]
		if not all_session_ids:
			logger.info('PostHog: no sessions found for sampled users')
			return {}

		# 3. Fetch events for all selected sessions
		escaped_sids = ', '.join(f"'{sid}'" for sid in all_session_ids)
		events_q = (
			f'SELECT properties.$session_id as session_id, event, distinct_id, timestamp, properties'
			f' FROM events'
			f' WHERE properties.$session_id IN ({escaped_sids})'
			f' ORDER BY timestamp ASC'
			f' LIMIT 50000'
		)
		events_result = await self.query(events_q)
		event_rows = _rows_to_dicts(events_result)

		# Group events by session
		events_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
		for evt in event_rows:
			events_by_session[evt['session_id']].append(evt)

		# Assemble final structure
		result: dict[str, list[dict[str, Any]]] = {}
		total_sessions = 0
		total_events = 0
		for uid, sessions in user_sessions.items():
			result[uid] = []
			for s in sessions:
				sid = s['session_id']
				session_events = events_by_session.get(sid, [])
				result[uid].append({
					'session_id': sid,
					'session_start': s['session_start'],
					'session_end': s['session_end'],
					'event_count': s['event_count'],
					'events': session_events,
				})
				total_sessions += 1
				total_events += len(session_events)

		logger.info(
			'PostHog: sampled %d users, %d sessions, %d events',
			len(result), total_sessions, total_events,
		)
		return result

	# ─── Cohorts (REST) ───────────────────────────────────────────────────────

	async def fetch_cohorts(self) -> list[dict[str, Any]]:
		"""List all cohorts via the REST API."""
		client = self._ensure_client()
		resp = await client.get(f'/api/projects/{self._project_id}/cohorts/')
		if resp.status_code >= 400:
			raise PostHogAPIError(resp.status_code, resp.text)
		data = resp.json()
		return data.get('results', data) if isinstance(data, dict) else data

	async def fetch_cohort_persons(
		self,
		cohort_id: int | str,
		*,
		limit: int = 1000,
	) -> list[dict[str, Any]]:
		"""List persons belonging to a specific cohort."""
		client = self._ensure_client()
		resp = await client.get(
			f'/api/projects/{self._project_id}/cohorts/{cohort_id}/persons/',
			params={'limit': limit},
		)
		if resp.status_code >= 400:
			raise PostHogAPIError(resp.status_code, resp.text)
		data = resp.json()
		return data.get('results', data) if isinstance(data, dict) else data


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _to_iso(value: str | datetime) -> str:
	if isinstance(value, datetime):
		return value.isoformat()
	return value


def _rows_to_dicts(result: dict[str, Any]) -> list[dict[str, Any]]:
	"""Convert HogQL columnar response (columns + results) into row dicts."""
	columns: list[str] = result.get('columns', [])
	rows: list[list[Any]] = result.get('results', [])
	return [dict(zip(columns, row)) for row in rows]
