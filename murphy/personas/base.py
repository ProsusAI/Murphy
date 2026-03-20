"""Abstract connector protocol for analytics integrations."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from murphy.personas.models import AnalyticsEvent, AnalyticsSession


@runtime_checkable
class AnalyticsConnector(Protocol):
	"""Contract that every analytics adapter must satisfy.

	Downstream code depends on this protocol — never on a concrete vendor client.
	"""

	async def get_events(
		self,
		*,
		after: str | datetime | None = None,
		before: str | datetime | None = None,
		limit: int = 1000,
	) -> list[AnalyticsEvent]: ...

	async def get_sessions(
		self,
		*,
		num_sessions: int | None = None,
		min_events: int | None = None,
		after: str | datetime | None = None,
		before: str | datetime | None = None,
	) -> list[AnalyticsSession]: ...
