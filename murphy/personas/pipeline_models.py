"""Pydantic models for the persona discovery and scoring pipeline.

These models serve as structured output formats for LLM calls via
``ChatOpenAI.ainvoke(output_format=...)``, following the same pattern
used by ``JudgeVerdict``, ``ExecutiveSummary``, and ``TestPlan``.

Note: these models are sent to OpenAI as structured-output schemas.
Avoid ``extra='forbid'``, ``min_length`` on dicts, and ``dict[K, V]``
fields — the SchemaOptimizer strips ``additionalProperties`` which
breaks dynamic-key objects in OpenAI strict mode.
"""

from __future__ import annotations

from pydantic import BaseModel


class SessionObservation(BaseModel):
	"""Phase 1 per-session output: freeform trait observations."""

	session_id: str
	observed_traits: list[str]
	behavioral_summary: str


class TraitDimension(BaseModel):
	"""A single discovered behavioral dimension with scoring anchors."""

	name: str
	description: str
	low_description: str
	high_description: str


class TraitSchema(BaseModel):
	"""Phase 1 final output: the canonical trait schema discovered from session data."""

	dimensions: list[TraitDimension]
	rationale: str


class DimensionScore(BaseModel):
	"""A score for a single trait dimension."""

	trait_name: str
	score: int


class SessionScore(BaseModel):
	"""Phase 2 per-session output: structured scores against the trait schema."""

	session_id: str
	user_id: str
	scores: list[DimensionScore]
	reasoning: str

	def scores_as_dict(self) -> dict[str, int]:
		"""Convert scores list to a {trait_name: score} dict for convenience."""
		return {s.trait_name: s.score for s in self.scores}
