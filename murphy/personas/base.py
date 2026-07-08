# Copyright © 2026 MIH AI B.V.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
		num_sessions: int,
		min_events: int,
		after: str | datetime | None = None,
		before: str | datetime | None = None,
	) -> list[AnalyticsSession]: ...
