"""Phase 2 — Scoring: score sessions against a fixed trait schema.

Each session is scored independently via an LLM call that receives the
trait schema and compressed timeline, outputting structured 1-5 scores.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from browser_use.llm import ChatOpenAI, SystemMessage, UserMessage
from murphy.personas.compressor import compress_session
from murphy.personas.models import AnalyticsSession
from murphy.personas.pipeline_models import SessionScore, TraitSchema

logger = logging.getLogger(__name__)

# ── Prompts ──────────────────────────────────────────────────────────────────

SCORE_SYSTEM = """\
You are a behavioral analyst scoring user sessions against a fixed set of
trait dimensions. For each dimension, assign an integer score from 1 to 5
based on the evidence in the session timeline.

Scoring guidelines:
- 1 = strongly matches the "low" description
- 3 = neutral / mixed signals
- 5 = strongly matches the "high" description
- Base your scores on observable evidence, not assumptions
- Provide brief reasoning that cites specific events from the timeline"""

SCORE_USER = """\
Score this session against the following trait dimensions.

=== Trait Schema ===
{schema_block}

=== Session Timeline ===
{timeline}"""


def _format_schema(schema: TraitSchema) -> str:
	lines: list[str] = []
	for dim in schema.dimensions:
		lines.append(f'**{dim.name}**: {dim.description}')
		lines.append(f'  Why this dimension: {dim.why_chosen}')
		lines.append(f'  1 (low) = {dim.low_description}')
		lines.append(f'  5 (high) = {dim.high_description}')
	return '\n'.join(lines)


# ── LLM call ─────────────────────────────────────────────────────────────────


async def score_session(
	llm: ChatOpenAI,
	schema: TraitSchema,
	timeline: str,
	session_id: str,
	user_id: str,
) -> SessionScore:
	"""Score one session against the fixed trait schema."""
	response = await llm.ainvoke(
		messages=[
			SystemMessage(content=SCORE_SYSTEM),
			UserMessage(
				content=SCORE_USER.format(
					schema_block=_format_schema(schema),
					timeline=timeline,
				)
			),
		],
		output_format=SessionScore,
	)
	score: SessionScore = response.completion
	if not score.session_id:
		score.session_id = session_id
	if not score.user_id:
		score.user_id = user_id
	return score


# ── Orchestrator ─────────────────────────────────────────────────────────────


async def run_scoring(
	llm: ChatOpenAI,
	schema: TraitSchema,
	sessions: list[AnalyticsSession],
	person_contexts: dict[str, dict[str, Any]],
	max_concurrent: int = 15,
) -> list[SessionScore]:
	"""Run the full Phase 2 scoring pipeline.

	1. Compress each session into a text timeline.
	2. Score each session against the trait schema (concurrently).
	"""
	sem = asyncio.Semaphore(max_concurrent)

	async def _score_one(session: AnalyticsSession) -> SessionScore | None:
		timeline = compress_session(session, person_contexts.get(session.user_id))
		async with sem:
			try:
				logger.info('Scoring session %s (user=%s)', session.session_id, session.user_id)
				return await score_session(
					llm,
					schema,
					timeline,
					session.session_id,
					session.user_id,
				)
			except Exception:
				logger.warning(
					'Failed to score session %s (user=%s, timeline_len=%d)',
					session.session_id,
					session.user_id,
					len(timeline),
					exc_info=True,
				)
				return None

	results = await asyncio.gather(*[_score_one(s) for s in sessions])
	scores = [r for r in results if r is not None]
	failed = len(results) - len(scores)
	if failed:
		logger.warning('Scoring completed with %d/%d failures', failed, len(results))
	logger.info('Scored %d sessions', len(scores))
	return scores
