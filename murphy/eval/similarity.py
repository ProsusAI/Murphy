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

from browser_use.llm import BaseChatModel
from murphy.eval.history_adapter import format_agent_history_as_timeline
from murphy.eval.models import DimensionSimilarity, PersonaSimilarityResult
from murphy.personas.bridge import slugify_persona_name
from murphy.personas.pipeline_models import Persona, TraitSchema
from murphy.personas.scoring import score_session

logger = logging.getLogger(__name__)


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

	return PersonaSimilarityResult(
		persona_id=persona.persona_id,
		persona_name=persona.name,
		persona_slug=slugify_persona_name(persona.name),
		test_scenario_name=scenario_name,
		agent_history_path=str(history_path),
		dimensions=dimensions,
		overall_similarity_score=round(overall, 3),
		scoring_reasoning=session_score.reasoning,
	)
