"""PostHog API client for ingesting events, persons, cohorts, and metadata.

Uses the HogQL Query API (POST /api/projects/:project_id/query/) for events
and persons. Uses the REST API for cohorts, event definitions, property
definitions, and session recordings. Returns raw JSON — no Pydantic
wrapping — so downstream consumers (e.g. trait mapping) decide their own schema.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any

import httpx

from murphy.config import (
	PERSONA_MIN_EVENTS_PER_SESSION,
	PERSONA_SAMPLE_SESSIONS,
	POSTHOG_API_KEY,
	POSTHOG_HOST,
	POSTHOG_PROJECT_ID,
)

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
		hogql = f'SELECT id, properties, created_at FROM persons{where} ORDER BY created_at DESC LIMIT {limit}'
		result = await self.query(hogql)
		return _rows_to_dicts(result)

	# ─── Session sampling ─────────────────────────────────────────────────────

	async def sample_user_sessions(
		self,
		*,
		num_sessions: int | None = None,
		min_events: int | None = None,
		after: str | datetime | None = None,
		before: str | datetime | None = None,
		offset: int = 0,
	) -> dict[str, list[dict[str, Any]]]:
		"""Sample random sessions that meet the event-count threshold.

		Parameters fall back to the values in ``murphy.config`` when not supplied:
		``PERSONA_SAMPLE_SESSIONS`` and ``PERSONA_MIN_EVENTS_PER_SESSION``.

		The ``offset`` parameter skips the first N qualifying sessions in the
		deterministic hash order, allowing callers to fetch distinct batches
		(e.g. offset=0 for discovery, offset=100 for scoring).

		Returns a dict keyed by ``distinct_id``, where each value is a list of
		session dicts. Each session dict has ``session_id``, ``session_start``,
		``session_end``, ``event_count``, and ``events`` (chronological list of
		event dicts). Only sessions with at least ``min_events`` events are
		included.
		"""
		num_sessions = num_sessions if num_sessions is not None else PERSONA_SAMPLE_SESSIONS
		min_events = min_events if min_events is not None else PERSONA_MIN_EVENTS_PER_SESSION

		time_filter = ''
		time_conditions: list[str] = []
		if after:
			time_conditions.append(f"timestamp > '{_to_iso(after)}'")
		if before:
			time_conditions.append(f"timestamp < '{_to_iso(before)}'")
		if time_conditions:
			time_filter = f' AND {" AND ".join(time_conditions)}'

		# 1. Pick random sessions above the event threshold
		offset_clause = f' OFFSET {offset}' if offset else ''
		sessions_q = (
			f'SELECT distinct_id, properties.$session_id as session_id,'
			f' min(timestamp) as session_start, max(timestamp) as session_end,'
			f' count() as event_count'
			f' FROM events'
			f' WHERE properties.$session_id IS NOT NULL{time_filter}'
			f' GROUP BY distinct_id, session_id'
			f' HAVING event_count >= {min_events}'
			f' ORDER BY cityHash64(session_id)'
			f' LIMIT {num_sessions}'
			f'{offset_clause}'
		)
		sessions_result = await self.query(sessions_q)
		sessions_rows = _rows_to_dicts(sessions_result)

		if not sessions_rows:
			logger.info('PostHog: no sessions found above threshold (%d events)', min_events)
			return {}

		all_session_ids = [s['session_id'] for s in sessions_rows]

		# 2. Fetch events for all selected sessions (batched to avoid PostHog timeouts)
		events_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
		batch_size = 50
		for i in range(0, len(all_session_ids), batch_size):
			batch_ids = all_session_ids[i : i + batch_size]
			escaped_sids = ', '.join(f"'{sid}'" for sid in batch_ids)
			events_q = (
				f'SELECT properties.$session_id as session_id, event, distinct_id, timestamp, properties'
				f' FROM events'
				f' WHERE properties.$session_id IN ({escaped_sids}){time_filter}'
				f' LIMIT 50000'
			)
			events_result = await self.query(events_q)
			for evt in _rows_to_dicts(events_result):
				events_by_session[evt['session_id']].append(evt)
			logger.debug(
				'PostHog: fetched events batch %d–%d of %d sessions',
				i + 1,
				min(i + batch_size, len(all_session_ids)),
				len(all_session_ids),
			)

		# Sort events within each session by timestamp (ORDER BY removed from query)
		for sid, evts in events_by_session.items():
			evts.sort(key=lambda e: e.get('timestamp', ''))

		# Group sessions by user
		result: dict[str, list[dict[str, Any]]] = defaultdict(list)
		total_events = 0
		for s in sessions_rows:
			sid = s['session_id']
			session_events = events_by_session.get(sid, [])
			result[s['distinct_id']].append(
				{
					'session_id': sid,
					'session_start': s['session_start'],
					'session_end': s['session_end'],
					'event_count': s['event_count'],
					'events': session_events,
				}
			)
			total_events += len(session_events)

		logger.info(
			'PostHog: sampled %d users, %d sessions, %d events',
			len(result),
			len(sessions_rows),
			total_events,
		)
		return dict(result)

	# ─── Event definitions (REST) ─────────────────────────────────────────────

	async def fetch_event_definitions(
		self,
		*,
		event_type: str | None = None,
		limit: int = 500,
	) -> list[dict[str, Any]]:
		"""List event definitions (name + description) via the REST API.

		``event_type`` can be ``'custom'`` to return only app-defined events or
		``'posthog'`` for PostHog built-in events. Omit to return all.

		Each result dict contains at minimum: ``name``, ``description``,
		``event_type`` (``'custom'`` | ``'posthog'``), ``volume_30_day``.
		"""
		params: dict[str, Any] = {'limit': min(limit, 500)}
		if event_type:
			params['event_type'] = event_type
		return await self._get_paginated(
			f'/api/projects/{self._project_id}/event_definitions/',
			params=params,
			max_results=limit,
		)

	# ─── Property definitions (REST) ──────────────────────────────────────────

	async def fetch_property_definitions(
		self,
		*,
		property_type: str = 'person',
		limit: int = 500,
	) -> list[dict[str, Any]]:
		"""List property definitions via the REST API.

		``property_type`` controls which property namespace is returned:
		``'person'`` (default) for person-level traits, ``'event'`` for
		event properties, ``'group'`` for group properties.

		Each result dict contains at minimum: ``name``, ``description``,
		``property_type`` (data type), ``is_numerical``.
		"""
		params: dict[str, Any] = {'type': property_type, 'limit': min(limit, 500)}
		return await self._get_paginated(
			f'/api/projects/{self._project_id}/property_definitions/',
			params=params,
			max_results=limit,
		)

	# ─── Session recordings (REST) ────────────────────────────────────────────

	async def fetch_session_recordings(
		self,
		*,
		after: str | datetime | None = None,
		before: str | datetime | None = None,
		limit: int = 100,
	) -> list[dict[str, Any]]:
		"""List session recording metadata via the REST API.

		Returns pre-computed engagement signals per session without re-aggregating
		from raw events. Each result dict contains: ``id`` (session_id),
		``distinct_id``, ``start_time``, ``end_time``, ``duration``,
		``active_seconds``, ``click_count``, ``keypress_count``,
		``mouse_activity_count``, ``recording_duration``.
		"""
		params: dict[str, Any] = {'limit': min(limit, 100)}
		if after:
			params['date_from'] = _to_iso(after)
		if before:
			params['date_to'] = _to_iso(before)
		return await self._get_paginated(
			f'/api/projects/{self._project_id}/session_recordings/',
			params=params,
			max_results=limit,
		)

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

	# ─── Pagination helper ────────────────────────────────────────────────────

	async def _get_paginated(
		self,
		path: str,
		*,
		params: dict[str, Any] | None = None,
		max_results: int = 500,
	) -> list[dict[str, Any]]:
		"""Follow PostHog ``next`` cursor links until ``max_results`` are collected."""
		client = self._ensure_client()
		results: list[dict[str, Any]] = []
		next_url: str | None = path
		req_params = dict(params or {})

		while next_url and len(results) < max_results:
			resp = await client.get(next_url, params=req_params)
			if resp.status_code >= 400:
				raise PostHogAPIError(resp.status_code, resp.text)
			data = resp.json()
			page = data.get('results', []) if isinstance(data, dict) else data
			results.extend(page)
			next_url = data.get('next') if isinstance(data, dict) else None
			req_params = {}  # params are encoded in the next URL already

		return results[:max_results]


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _to_iso(value: str | datetime) -> str:
	"""Format a datetime for use in HogQL string comparisons.

	HogQL expects ``YYYY-MM-DD HH:MM:SS`` (no microseconds, no tz offset).
	"""
	if isinstance(value, datetime):
		return value.strftime('%Y-%m-%d %H:%M:%S')
	return value


def _rows_to_dicts(result: dict[str, Any]) -> list[dict[str, Any]]:
	"""Convert HogQL columnar response (columns + results) into row dicts."""
	columns: list[str] = result.get('columns', [])
	rows: list[list[Any]] = result.get('results', [])
	return [dict(zip(columns, row)) for row in rows]
