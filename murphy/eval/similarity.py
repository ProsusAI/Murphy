"""Compute persona similarity: how closely Murphy's behavior matches a discovered persona.

Core logic:
1. Format Murphy's agent_history as a behavioral timeline (history_adapter).
2. Score that timeline against the trait schema using the same score_session()
   function used on real PostHog sessions — this puts Murphy and real users in
   the same scoring space.
3. Compare Murphy's scores against the persona centroid (= real-user average
   for that cluster) to produce a per-dimension similarity score and an overall
   0–1 similarity score.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from browser_use.llm import BaseChatModel, SystemMessage, UserMessage
from murphy.eval.history_adapter import format_agent_history_as_timeline
from murphy.eval.models import DimensionSimilarity, PersonaSimilarityResult, SimilarityReport, TestRationale
from murphy.personas.bridge import slugify_persona_name
from murphy.personas.embedder import embed_texts
from murphy.personas.pipeline_models import Persona, TraitSchema
from murphy.personas.scoring import score_session

logger = logging.getLogger(__name__)


_RATIONALE_SYSTEM = """\
You are writing concise rationale lines for a persona similarity evaluation report.
Each explanation should be one clear, specific sentence grounded in the behavioral data.
Avoid generic statements — reference the specific trait and what the scores reveal about behavior."""

_RATIONALE_USER = """\
Persona: {persona_name}
{persona_description}
Distinguishing traits: {distinguishing_traits}

Test result:
- Best-matching trait: {best_trait}
  Murphy: {best_murphy:.1f}  |  Real users: {best_persona:.1f}  |  Delta: {best_delta}
- Biggest gap: {worst_trait}
  Murphy: {worst_murphy:.1f}  |  Real users: {worst_persona:.1f}  |  Delta: {worst_delta}
- Embedding similarity: {emb_str}  (0 = completely different behavioral timeline, 1 = identical)

Murphy's behavioral summary:
{murphy_behavioral_summary}

Behavioral context from scoring:
{scoring_reasoning}

Write three rationale fields:
- best_match: one sentence explaining why Murphy matched the best-matching trait well.
- biggest_gap: one sentence explaining what Murphy did differently on the biggest-gap trait and why it matters for persona fidelity.
- embedding: two sentences. Do NOT lead with or paraphrase the score number. Sentence 1: pick the single behavioral signal from Murphy's summary (e.g. a specific action count, deliberation steps, navigation style) that best aligns with one of this persona's distinguishing traits — name both explicitly. Sentence 2: pick the single behavioral signal that most diverges from another distinguishing trait — name both explicitly. End with one clause explaining whether the score is expected given this."""


def _delta_str(delta: float) -> str:
	return f'+{delta:.2f}' if delta >= 0 else f'{delta:.2f}'


async def generate_test_rationale(
	persona: Persona,
	best_dim: DimensionSimilarity,
	worst_dim: DimensionSimilarity,
	embedding_similarity: float | None,
	scoring_reasoning: str,
	murphy_behavioral_summary: str,
	llm: BaseChatModel,
) -> TestRationale | None:
	"""Generate one-line rationale for best match, biggest gap, and embedding similarity."""
	emb_str = f'{embedding_similarity:.3f}' if embedding_similarity is not None else 'not available'
	distinguishing_traits = ', '.join(persona.distinguishing_traits) if persona.distinguishing_traits else 'not specified'
	try:
		response = await llm.ainvoke(
			messages=[
				SystemMessage(content=_RATIONALE_SYSTEM),
				UserMessage(
					content=_RATIONALE_USER.format(
						persona_name=persona.name,
						persona_description=persona.description,
						distinguishing_traits=distinguishing_traits,
						best_trait=best_dim.trait_name,
						best_murphy=best_dim.murphy_score,
						best_persona=best_dim.persona_score,
						best_delta=_delta_str(best_dim.delta),
						worst_trait=worst_dim.trait_name,
						worst_murphy=worst_dim.murphy_score,
						worst_persona=worst_dim.persona_score,
						worst_delta=_delta_str(worst_dim.delta),
						emb_str=emb_str,
						murphy_behavioral_summary=murphy_behavioral_summary,
						scoring_reasoning=scoring_reasoning[:1200],
					)
				),
			],
			output_format=TestRationale,
		)
		return response.completion
	except Exception:
		logger.warning('Failed to generate test rationale for "%s"', persona.name, exc_info=True)
		return None


_TAKEAWAYS_SYSTEM = """\
You are analyzing a Murphy persona similarity report to extract product insights.
Murphy is an AI agent that simulates real user personas to test a product.
Write exactly 2 key takeaways about what this report reveals regarding Murphy's effectiveness and limitations as a product tester.
Each takeaway must be one to two sentences, specific and grounded in the data, and actionable for the product team."""

_TAKEAWAYS_USER = """\
Report summary across {num_results} test runs, {num_personas} personas:

{persona_summaries}

Write exactly 2 key takeaways. Each should name specific personas or traits, cite the data, and say what it means for product testing."""


def _build_persona_summaries(results: list[PersonaSimilarityResult]) -> str:
	from collections import defaultdict

	by_persona: dict[str, list[PersonaSimilarityResult]] = defaultdict(list)
	for r in results:
		by_persona[r.persona_name].append(r)

	lines: list[str] = []
	for persona_name, runs in sorted(by_persona.items()):
		avg_llm = sum(r.overall_similarity_score for r in runs) / len(runs)
		emb_scores = [r.embedding_similarity for r in runs if r.embedding_similarity is not None]
		avg_emb = f'{sum(emb_scores) / len(emb_scores):.2f}' if emb_scores else 'n/a'

		all_dims: dict[str, list[float]] = defaultdict(list)
		for r in runs:
			for d in r.dimensions:
				all_dims[d.trait_name].append(d.delta)
		avg_deltas = {t: sum(v) / len(v) for t, v in all_dims.items()}
		worst_trait = max(avg_deltas, key=lambda t: abs(avg_deltas[t]))
		delta_str = f'{avg_deltas[worst_trait]:+.2f}'

		trait_lines = '  '.join(f'{t}: {d:+.1f}' for t, d in sorted(avg_deltas.items(), key=lambda x: -abs(x[1])))
		lines.append(
			f'Persona: {persona_name} ({len(runs)} runs)\n'
			f'  Avg LLM match: {avg_llm:.2f} | Avg embedding: {avg_emb}\n'
			f'  Trait deltas (Murphy − real users): {trait_lines}\n'
			f'  Biggest gap: {worst_trait} {delta_str}'
		)
	return '\n\n'.join(lines)


async def generate_key_takeaways(report: SimilarityReport, llm: BaseChatModel) -> list[str]:
	"""Generate 2 key takeaways from the full similarity report."""
	from pydantic import BaseModel

	class _Takeaways(BaseModel):
		takeaway_1: str
		takeaway_2: str

	persona_summaries = _build_persona_summaries(report.results)
	num_personas = len({r.persona_name for r in report.results})
	try:
		response = await llm.ainvoke(
			messages=[
				SystemMessage(content=_TAKEAWAYS_SYSTEM),
				UserMessage(
					content=_TAKEAWAYS_USER.format(
						num_results=len(report.results),
						num_personas=num_personas,
						persona_summaries=persona_summaries,
					)
				),
			],
			output_format=_Takeaways,
		)
		t = response.completion
		return [t.takeaway_1, t.takeaway_2]
	except Exception:
		logger.warning('Failed to generate key takeaways', exc_info=True)
		return []


async def evaluate_similarity(
	persona: Persona,
	schema: TraitSchema,
	history_path: Path,
	scenario_name: str,
	scenario_steps: str,
	llm: BaseChatModel,
) -> PersonaSimilarityResult:
	"""Score Murphy's behavior against a persona's expected trait profile.

	Args:
	    persona:        The discovered persona Murphy was asked to imitate.
	    schema:         The trait schema used to score sessions (from personas.json).
	    history_path:   Path to the agent_history JSON file for this test run.
	    scenario_name:  Short name of the test scenario.
	    scenario_steps: Full steps_description from the test scenario.
	    llm:            LLM used for scoring (same as used in the pipeline).

	Returns:
	    PersonaSimilarityResult with per-dimension scores and an overall 0–1 similarity.
	"""
	timeline = format_agent_history_as_timeline(
		history_path,
		persona_name=persona.name,
		scenario_name=scenario_name,
		scenario_steps=scenario_steps,
	)

	session_score = await score_session(
		llm,
		schema,
		timeline,
		session_id=f'murphy_{scenario_name[:40]}',
		user_id='murphy',
	)

	centroid = {d.trait_name: d.score for d in persona.centroid}
	murphy_scores = session_score.scores_as_dict()

	dimensions: list[DimensionSimilarity] = []
	for trait_name, persona_score in centroid.items():
		murphy_score = float(murphy_scores.get(trait_name, 3.0))
		persona_score_f = float(persona_score)
		dimensions.append(
			DimensionSimilarity(
				trait_name=trait_name,
				murphy_score=murphy_score,
				persona_score=persona_score_f,
				delta=round(murphy_score - persona_score_f, 2),
			)
		)

	# Overall similarity: 1 - mean(|delta| / max_possible_delta)
	# Score range is 1–5, so max possible delta is 4.
	if dimensions:
		mean_normalized_delta = sum(abs(d.delta) / 4.0 for d in dimensions) / len(dimensions)
		overall = max(0.0, min(1.0, 1.0 - mean_normalized_delta))
	else:
		overall = 0.0

	# Embedding similarity: cosine distance between Murphy's timeline embedding
	# and the persona's centroid embedding (mean of its real-user session embeddings).
	# No LLM involved — purely text → vector → cosine similarity.
	emb_sim: float | None = None
	if persona.centroid_embedding:
		try:
			emb_matrix = await embed_texts([timeline])
			murphy_vec = emb_matrix[0]
			centroid_vec = np.array(persona.centroid_embedding, dtype=np.float64)
			norm = np.linalg.norm(murphy_vec) * np.linalg.norm(centroid_vec)
			if norm > 0:
				emb_sim = round(float(np.dot(murphy_vec, centroid_vec) / norm), 3)
		except Exception:
			logger.warning('Failed to compute embedding similarity for "%s"', scenario_name, exc_info=True)

	marker = '=== Action Timeline ==='
	cutoff = timeline.find(marker)
	murphy_behavioral_summary = timeline[:cutoff].strip() if cutoff != -1 else timeline[:800]

	best_dim = min(dimensions, key=lambda d: abs(d.delta)) if dimensions else None
	worst_dim = max(dimensions, key=lambda d: abs(d.delta)) if dimensions else None
	rationale: TestRationale | None = None
	if best_dim and worst_dim:
		rationale = await generate_test_rationale(
			persona, best_dim, worst_dim, emb_sim, session_score.reasoning, murphy_behavioral_summary, llm
		)

	return PersonaSimilarityResult(
		persona_id=persona.persona_id,
		persona_name=persona.name,
		persona_slug=slugify_persona_name(persona.name),
		test_scenario_name=scenario_name,
		agent_history_path=str(history_path),
		dimensions=dimensions,
		overall_similarity_score=round(overall, 3),
		scoring_reasoning=session_score.reasoning,
		embedding_similarity=emb_sim,
		rationale=rationale,
	)
