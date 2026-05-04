"""Pydantic models for persona similarity evaluation results."""

from __future__ import annotations

from pydantic import BaseModel


class DimensionSimilarity(BaseModel):
	"""Similarity score for a single trait dimension."""

	trait_name: str
	murphy_score: float  # what Murphy scored (1–5)
	persona_score: float  # persona centroid = real-user average (1–5)
	delta: float  # murphy_score - persona_score (positive = Murphy scored higher)


class TestRationale(BaseModel):
	"""LLM-generated one-line explanations for the three key signals in a similarity result."""

	best_match: str  # why Murphy matched the best-matching trait
	biggest_gap: str  # what Murphy did differently on the worst-matching trait
	embedding: str  # what the embedding similarity score reveals beyond trait scores


class PersonaSimilarityResult(BaseModel):
	"""Similarity evaluation for one (test scenario, discovered persona) pair."""

	persona_id: int
	persona_name: str
	persona_slug: str
	test_scenario_name: str
	agent_history_path: str
	dimensions: list[DimensionSimilarity]
	overall_similarity_score: float  # 0–1, where 1 = perfect match to persona centroid
	scoring_reasoning: str  # LLM rationale from score_session()
	embedding_similarity: float | None = None  # 0–1 cosine sim of timeline embeddings; None if centroid_embedding not available
	rationale: TestRationale | None = None  # structured LLM rationale for best match, biggest gap, embedding


class SimilarityReport(BaseModel):
	"""Full similarity report for a Murphy output directory."""

	personas_file: str
	output_dir: str
	timestamp: str
	results: list[PersonaSimilarityResult]
