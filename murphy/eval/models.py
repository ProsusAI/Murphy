"""Pydantic models for persona fidelity evaluation results."""

from __future__ import annotations

from pydantic import BaseModel


class DimensionFidelity(BaseModel):
	"""Fidelity score for a single trait dimension."""

	trait_name: str
	murphy_score: float  # what Murphy scored (1–5)
	persona_score: float  # persona centroid = real-user average (1–5)
	delta: float  # murphy_score - persona_score (positive = Murphy scored higher)


class PersonaFidelityResult(BaseModel):
	"""Fidelity evaluation for one (test scenario, discovered persona) pair."""

	persona_id: int
	persona_name: str
	persona_slug: str
	test_scenario_name: str
	agent_history_path: str
	dimensions: list[DimensionFidelity]
	overall_fidelity_score: float  # 0–1, where 1 = perfect match to persona centroid
	scoring_reasoning: str  # LLM rationale from score_session()


class FidelityReport(BaseModel):
	"""Full fidelity report for a Murphy output directory."""

	personas_file: str
	output_dir: str
	timestamp: str
	results: list[PersonaFidelityResult]
