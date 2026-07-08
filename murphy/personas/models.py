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

"""Canonical analytics models shared across all vendor integrations."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AnalyticsEvent(BaseModel):
	"""A single analytics event, normalized from any vendor."""

	model_config = ConfigDict(extra='forbid')

	event_id: str
	event_name: str
	user_id: str
	session_id: str | None = None
	timestamp: datetime
	properties: dict[str, Any] = Field(default_factory=dict)
	elements_chain: str = ''
	source: str = ''
	raw: dict[str, Any] | None = None


class AnalyticsSession(BaseModel):
	"""A user session containing chronologically ordered events."""

	model_config = ConfigDict(extra='forbid')

	session_id: str
	user_id: str
	started_at: datetime
	ended_at: datetime
	event_count: int
	events: list[AnalyticsEvent] = Field(default_factory=list)
	source: str = ''
