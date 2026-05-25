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

from pydantic import BaseModel, Field


class SessionObservation(BaseModel):
	"""Phase 1 per-session output: freeform trait observations."""

	session_id: str
	observed_traits: list[str]
	behavioral_summary: str


class TraitDimension(BaseModel):
	"""A single discovered behavioral dimension with scoring anchors."""

	name: str
	description: str
	why_chosen: str = Field(
		description=(
			'Why this dimension was included: cite patterns from the session observations '
			'(recurring traits, contrasts between users, or population flows) that motivated this axis.'
		),
	)
	low_description: str
	high_description: str


class TraitSchema(BaseModel):
	"""Phase 1 final output: the canonical trait schema discovered from session data."""

	dimensions: list[TraitDimension]
	rationale: str


class DimensionScore(BaseModel):
	"""A score for a single trait dimension."""

	trait_name: str
	score: int | float


class SessionScore(BaseModel):
	"""Phase 2 per-session output: structured scores against the trait schema."""

	session_id: str
	user_id: str
	scores: list[DimensionScore]
	reasoning: str

	def scores_as_dict(self) -> dict[str, int | float]:
		"""Convert scores list to a {trait_name: score} dict for convenience."""
		return {s.trait_name: s.score for s in self.scores}


# ── Phase 3: Clustering & Persona Labeling ───────────────────────────────────


class PersonaDescription(BaseModel):
	"""LLM-generated label for a single persona cluster.

	Used as structured output from the labeling LLM call.
	"""

	persona_id: int
	name: str
	description: str
	distinguishing_traits: list[str]
	test_orientation: str = Field(
		description="'ux' or 'resilience' — whether testing this persona focuses on UX clarity or resilience to unexpected behavior",
	)
	success_criteria_guidance: str = Field(
		description='What "success" looks like when testing as this persona (1-2 sentences)',
	)
	execution_hints: list[str] = Field(
		description='2-4 behavioral instructions for the agent acting as this persona',
	)
	judge_questions: list[str] = Field(
		description='2-4 evaluation questions for the judge to assess whether the site handled this persona well',
	)
	suggestion_instruction: str = Field(
		description=(
			"Instruction for generating feature suggestions from this persona's perspective. "
			'Format: "As a <role>, suggest 1-3 <category> improvements (e.g. <2-3 concrete examples>)."'
		),
	)


class PersonaLabels(BaseModel):
	"""LLM output: labels for all persona clusters in one call."""

	personas: list[PersonaDescription]


class SessionPersonaAssignment(BaseModel):
	"""Maps a scored session to its assigned persona cluster."""

	session_id: str
	user_id: str
	persona_id: int


class Persona(BaseModel):
	"""A fully described persona: algorithmic centroid merged with LLM labels."""

	persona_id: int
	name: str
	description: str
	centroid: list[DimensionScore]
	distinguishing_traits: list[str]
	size: int
	test_orientation: str = ''
	success_criteria_guidance: str = ''
	execution_hints: list[str] = Field(default_factory=list)
	judge_questions: list[str] = Field(default_factory=list)
	centroid_embedding: list[float] | None = None
	suggestion_instruction: str = ''
	llm_ceiling: float | None = None
	embedding_ceiling: float | None = None
	ceiling_n_sessions: int = 0


class PersonaResult(BaseModel):
	"""Complete output of Phase 3: personas, assignments, and quality metrics."""

	personas: list[Persona]
	num_clusters: int
	silhouette_score: float
	assignments: list[SessionPersonaAssignment]
