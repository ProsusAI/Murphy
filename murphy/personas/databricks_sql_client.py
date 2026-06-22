"""Databricks SQL client for reading murphy_evals_data from Unity Catalog."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from murphy.config import (
	DATABRICKS_CONFIG_PROFILE,
	DATABRICKS_HOST,
	DATABRICKS_TOKEN,
	DATABRICKS_WAREHOUSE_ID,
)

logger = logging.getLogger(__name__)


class DatabricksSqlError(Exception):
	"""Raised when a Databricks SQL query fails."""


def _normalize_host(host: str) -> str:
	return host.replace('https://', '').replace('http://', '').rstrip('/')


def _host_with_scheme(host: str) -> str:
	if host.startswith('http://') or host.startswith('https://'):
		return host
	return f'https://{host}'


def _parse_cell(value: Any) -> Any:
	if value is None:
		return None
	if hasattr(value, 'asDict'):
		return {k: _parse_cell(v) for k, v in value.asDict().items()}
	if isinstance(value, dict):
		return {k: _parse_cell(v) for k, v in value.items()}
	if isinstance(value, (list, tuple)):
		return [_parse_cell(v) for v in value]
	if isinstance(value, str):
		stripped = value.strip()
		if stripped.startswith(('[', '{')):
			try:
				return _parse_cell(json.loads(stripped))
			except json.JSONDecodeError:
				return value
		return value
	if isinstance(value, (int, float, bool)):
		return value
	return str(value)


class DatabricksSqlClient:
	"""Thin async wrapper around the sync databricks-sql-connector.

	Authentication (first match wins):

	1. Explicit ``token`` / ``DATABRICKS_TOKEN`` — static PAT or copied OAuth token.
	2. Databricks CLI profile via ``profile`` / ``DATABRICKS_CONFIG_PROFILE`` (or the
	   CLI ``DEFAULT`` profile when unset). Uses OAuth tokens from ``~/.databrickscfg``.
	"""

	def __init__(
		self,
		*,
		host: str | None = None,
		token: str | None = None,
		profile: str | None = None,
		warehouse_id: str | None = None,
	) -> None:
		self._host = _normalize_host(host or DATABRICKS_HOST)
		self._token = token if token is not None else DATABRICKS_TOKEN
		self._profile = profile if profile is not None else (DATABRICKS_CONFIG_PROFILE or None)
		self._warehouse_id = warehouse_id or DATABRICKS_WAREHOUSE_ID
		if not self._warehouse_id:
			raise ValueError('Databricks warehouse ID is required (set DATABRICKS_WAREHOUSE_ID)')

	async def query(self, sql: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
		return await asyncio.to_thread(self._query_sync, sql, parameters or {})

	def _connect(self, dbsql: Any) -> Any:
		http_path = f'/sql/1.0/warehouses/{self._warehouse_id}'
		logger.debug('Databricks SQL query (warehouse=%s)', self._warehouse_id)

		if self._token:
			if not self._host:
				raise ValueError('Databricks host is required when using DATABRICKS_TOKEN (set DATABRICKS_HOST)')
			return dbsql.connect(
				server_hostname=self._host,
				http_path=http_path,
				access_token=self._token,
			)

		try:
			from databricks.sdk.core import Config
		except ImportError as exc:
			raise ImportError(
				'databricks-sdk is required for Databricks CLI profile auth. Install with: uv sync --extra databricks'
			) from exc

		cfg_kwargs: dict[str, Any] = {}
		if self._profile:
			cfg_kwargs['profile'] = self._profile
		if self._host:
			cfg_kwargs['host'] = _host_with_scheme(self._host)

		cfg = Config(**cfg_kwargs)
		host = self._host or _normalize_host(cfg.host or '')
		if not host:
			raise ValueError(
				'Databricks host is required (set DATABRICKS_HOST or authenticate a CLI profile with databricks auth login)'
			)
		auth_label = self._profile or 'DEFAULT'
		logger.debug('Databricks SQL using CLI profile auth (profile=%s)', auth_label)
		return dbsql.connect(
			server_hostname=host,
			http_path=http_path,
			credentials_provider=lambda: cfg.authenticate,
		)

	def _query_sync(self, sql: str, parameters: dict[str, Any]) -> list[dict[str, Any]]:
		try:
			from databricks import sql as dbsql
		except ImportError as exc:
			raise ImportError(
				'databricks-sql-connector is required for the Databricks persona pipeline. '
				'Install with: uv sync --extra databricks'
			) from exc

		with self._connect(dbsql) as connection:
			with connection.cursor() as cursor:
				cursor.execute(sql, parameters)
				if cursor.description is None:
					return []
				columns = [col[0] for col in cursor.description]
				rows = cursor.fetchall()
				return [{col: _parse_cell(val) for col, val in zip(columns, row)} for row in rows]
