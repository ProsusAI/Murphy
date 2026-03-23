"""Phase 1 — Discovery: observe sessions and aggregate into a trait schema.

Two LLM steps:
1. Per-session observation (concurrent, semaphore-limited).
2. Cross-session aggregation into a canonical TraitSchema.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from browser_use.llm import ChatOpenAI, SystemMessage, UserMessage
from murphy.personas.compressor import compress_session
from murphy.personas.models import AnalyticsSession
from murphy.personas.pipeline_models import SessionObservation, TraitSchema

logger = logging.getLogger(__name__)

# ── Prompts ──────────────────────────────────────────────────────────────────

OBSERVE_SYSTEM = """\
You are a behavioral analyst studying user sessions on a web application.
You will receive a compressed timeline of a single user session including
metadata, navigation patterns, cognitive signals, and a sequence of events.

Your job is to identify and describe behavioral traits you observe.
Focus on patterns like:
- Engagement depth (shallow browsing vs. deep interaction)
- Navigation style (linear, exploratory, oscillating)
- Feature usage (which parts of the product they use)
- Frustration signals (rage clicks, errors, repeated actions)
- Communication patterns (conversation length, feedback habits)
- Adoption indicators (new user exploration vs. power-user efficiency)
- Cognitive investment (memory/knowledge management, learning preferences)
- Prompt sophistication (creating/reusing saved prompts vs. ad-hoc input)
- Feedback depth (binary thumbs up/down vs. detailed written feedback)
- Model awareness (sticking with defaults vs. deliberately switching models)

When cognitive signal data is present, use it to assess the user's
metacognitive engagement — are they building persistent context, engineering
their prompts, critically evaluating outputs, or deliberately selecting
models? When absent, do not assume low engagement; treat it as no signal.

Be specific and grounded in the data. Do not speculate beyond what the
timeline shows."""

OBSERVE_USER = """\
Analyze this session timeline and identify the behavioral traits you observe.

{timeline}"""

AGGREGATE_SYSTEM = """\
You are a behavioral scientist designing a trait taxonomy for user personas.

You will receive behavioral observations from multiple user sessions, plus
optional aggregate navigation flow data showing the most common paths users
take through the application.

Your job is to synthesize these observations into a canonical set of 5-8
orthogonal behavioral dimensions. Each dimension should:
- Capture a distinct behavioral axis (not redundant with others)
- Be observable from session event data (not speculative)
- Have clear low (1) and high (5) anchors
- Be useful for distinguishing different user personas
- Include a "why_chosen" field: 1-3 sentences explaining why you included this
  dimension, grounded in specific patterns from the observations (e.g. which
  traits recurred, how users differed, or what navigation flows suggested the axis)

Aim for dimensions that separate user archetypes meaningfully."""

AGGREGATE_USER = """\
Below are behavioral observations from {num_sessions} user sessions.
Synthesize them into a canonical trait schema of 5-8 orthogonal dimensions.
For every dimension, explain in why_chosen how the observations (and population
flows, if present) motivated that axis.

{observations_block}
{paths_block}"""


# ── LLM calls ────────────────────────────────────────────────────────────────


async def observe_session(llm: ChatOpenAI, timeline: str, session_id: str) -> SessionObservation:
	"""Ask the LLM to freely describe behavioral traits observed in one session."""
	response = await llm.ainvoke(
		messages=[
			SystemMessage(content=OBSERVE_SYSTEM),
			UserMessage(content=OBSERVE_USER.format(timeline=timeline)),
		],
		output_format=SessionObservation,
	)
	observation: SessionObservation = response.completion
	if not observation.session_id:
		observation.session_id = session_id
	return observation


async def aggregate_trait_schema(
	llm: ChatOpenAI,
	observations: list[SessionObservation],
	population_paths: str | None = None,
) -> TraitSchema:
	"""Synthesize all per-session observations into a canonical trait schema."""
	obs_lines: list[str] = []
	for i, obs in enumerate(observations, 1):
		traits = ', '.join(obs.observed_traits)
		obs_lines.append(f'Session {i}: {obs.behavioral_summary} [Traits: {traits}]')
	observations_block = '\n'.join(obs_lines)

	if population_paths:
		paths_block = f'\n=== Aggregate Navigation Flows (population-level) ===\n{population_paths}'
	else:
		paths_block = ''

	response = await llm.ainvoke(
		messages=[
			SystemMessage(content=AGGREGATE_SYSTEM),
			UserMessage(
				content=AGGREGATE_USER.format(
					num_sessions=len(observations),
					observations_block=observations_block,
					paths_block=paths_block,
				)
			),
		],
		output_format=TraitSchema,
	)
	return response.completion


# ── Orchestrator ─────────────────────────────────────────────────────────────


async def run_discovery(
	llm: ChatOpenAI,
	sessions: list[AnalyticsSession],
	person_contexts: dict[str, dict[str, Any]],
	population_paths: str | None = None,
	max_concurrent: int = 15,
) -> TraitSchema:
	"""Run the full Phase 1 discovery pipeline.

	1. Compress each session into a text timeline.
	2. Run per-session observation LLM calls (concurrently).
	3. Aggregate observations into a TraitSchema.
	"""
	sem = asyncio.Semaphore(max_concurrent)

	async def _observe_one(session: AnalyticsSession) -> SessionObservation | None:
		timeline = compress_session(session, person_contexts.get(session.user_id))
		async with sem:
			try:
				logger.info('Observing session %s (user=%s)', session.session_id, session.user_id)
				return await observe_session(llm, timeline, session.session_id)
			except Exception:
				logger.warning(
					'Failed to observe session %s (user=%s, timeline_len=%d)',
					session.session_id,
					session.user_id,
					len(timeline),
					exc_info=True,
				)
				return None

	results = await asyncio.gather(*[_observe_one(s) for s in sessions])
	observations = [r for r in results if r is not None]
	failed = len(results) - len(observations)
	if failed:
		logger.warning('Discovery completed with %d/%d failures', failed, len(results))
	logger.info('Completed %d session observations, aggregating trait schema', len(observations))

	schema = await aggregate_trait_schema(llm, list(observations), population_paths)
	logger.info(
		'Discovered %d trait dimensions: %s',
		len(schema.dimensions),
		[d.name for d in schema.dimensions],
	)
	return schema
