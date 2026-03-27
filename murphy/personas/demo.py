"""Demo: run the persona discovery and scoring pipeline and display results.

Usage::

    python -m murphy.personas.demo [--discovery N] [--scoring N] [--min-events N] [--months-back N] [--model MODEL] [--examples N] [--context-max-chars N] [--no-context]

Defaults to 10 discovery sessions and 20 scoring sessions for a quick demo run.
After the run, prints a sample of the compressed session text inserted as {timeline} in the
per-session discovery user message (OBSERVE_USER in murphy.personas.discovery).
Set higher values (100/200) for production-quality results.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from murphy.personas.discovery import OBSERVE_USER
from murphy.personas.pipeline import run_persona_pipeline
from murphy.personas.pipeline_models import PersonaResult, SessionScore, TraitSchema
from murphy.personas.storage import save_personas


def _print_discovery_session_context(timeline: str | None, max_chars: int) -> None:
	"""Show what one discovery session looks like after :func:`compress_session` (LLM user body)."""
	print('\n' + '=' * 80)
	print('  DISCOVERY LLM — SESSION CONTEXT (sample)')
	print('=' * 80)
	print(
		'\nPhase 1 calls the model once per discovery session. The system prompt is '
		'OBSERVE_SYSTEM (behavioral analyst instructions); the user message is '
		'OBSERVE_USER: a short instruction plus the compressed session timeline below '
		'(from compress_session in murphy.personas.compressor).\n'
	)
	print('--- User message prefix (fixed) ---')
	prefix, _, _ = OBSERVE_USER.partition('{timeline}')
	print(prefix.rstrip())
	print('\n--- {timeline} sample (first discovery session) ---')
	if timeline is None:
		print('(No discovery sessions were returned; nothing to show.)')
		print()
		return
	if max_chars > 0 and len(timeline) > max_chars:
		shown = timeline[:max_chars]
		print(shown)
		print(f'\n... [{len(timeline) - max_chars} more characters truncated; use --context-max-chars 0 for full text]')
	else:
		print(timeline)
	print()


def _print_schema(schema: TraitSchema) -> None:
	print('\n' + '=' * 80)
	print('  DISCOVERED TRAIT SCHEMA')
	print('=' * 80)
	print(f'\nRationale: {schema.rationale}\n')
	print(f'{len(schema.dimensions)} dimensions discovered:\n')

	for i, dim in enumerate(schema.dimensions, 1):
		print(f'  {i}. {dim.name}')
		print(f'     {dim.description}')
		print(f'     Why chosen: {dim.why_chosen}')
		print(f'     1 (low)  = {dim.low_description}')
		print(f'     5 (high) = {dim.high_description}')
		print()


def _print_scores(scores: list[SessionScore], schema: TraitSchema, num_examples: int) -> None:
	dim_names = [d.name for d in schema.dimensions]

	print('=' * 80)
	print('  SESSION SCORE EXAMPLES')
	print('=' * 80)

	shown = scores[:num_examples]
	for i, score in enumerate(shown, 1):
		score_dict = score.scores_as_dict()
		print(f'\n--- Example {i}: session={score.session_id}  user={score.user_id} ---')
		print(f'Reasoning: {score.reasoning}')
		print('Scores:')
		for name in dim_names:
			val = score_dict.get(name, '?')
			bar = '#' * (val if isinstance(val, int) else 0)
			print(f'  {name:<30s}  {val}  {bar}')

	print()
	print('-' * 80)
	print(f'  Total scored: {len(scores)} sessions  (showing {len(shown)} examples above)')
	print('-' * 80)

	if len(scores) > 1:
		print('\nScore distribution across all sessions:\n')
		for name in dim_names:
			vals = [s.scores_as_dict().get(name) for s in scores]
			vals = [v for v in vals if v is not None]
			if vals:
				avg = sum(vals) / len(vals)
				variance = sum((v - avg) ** 2 for v in vals) / len(vals)
				std = variance**0.5
				print(f'  {name:<30s}  avg={avg:.1f}  std={std:.2f}  var={variance:.2f}  min={min(vals)}  max={max(vals)}')
		print()


def _print_personas(result: PersonaResult, schema: TraitSchema) -> None:
	dim_names = [d.name for d in schema.dimensions]

	print('=' * 80)
	print('  DISCOVERED PERSONAS')
	print('=' * 80)
	print(f'\n{result.num_clusters} personas  |  silhouette score: {result.silhouette_score:.4f}\n')

	for persona in sorted(result.personas, key=lambda p: p.size, reverse=True):
		pct = persona.size / len(result.assignments) * 100 if result.assignments else 0
		print(f'--- {persona.name} (id={persona.persona_id}, {persona.size} sessions, {pct:.0f}%) ---')
		print(f'  {persona.description}')
		print(f'  Distinguishing traits: {", ".join(persona.distinguishing_traits)}')
		print('  Centroid:')
		centroid_dict = {s.trait_name: s.score for s in persona.centroid}
		for name in dim_names:
			val = centroid_dict.get(name, 0)
			bar = '#' * round(val) if isinstance(val, (int, float)) else ''
			print(f'    {name:<30s}  {val:<5}  {bar}')
		print()


async def main() -> None:
	parser = argparse.ArgumentParser(description='Persona Discovery & Scoring demo')
	parser.add_argument('--discovery', type=int, default=10, help='Number of discovery sessions (default: 10)')
	parser.add_argument('--scoring', type=int, default=20, help='Number of scoring sessions (default: 20)')
	parser.add_argument('--min-events', type=int, default=20, help='Min events per session (default: 20)')
	parser.add_argument('--months-back', type=int, default=2, help='Months of history to sample (default: 2)')
	parser.add_argument('--model', type=str, default='gpt-4.1-mini', help='LLM model (default: gpt-4.1-mini)')
	parser.add_argument('--examples', type=int, default=5, help='Number of score examples to display (default: 5)')
	parser.add_argument('--concurrency', type=int, default=15, help='Max concurrent LLM calls (default: 15)')
	parser.add_argument(
		'--context-max-chars',
		type=int,
		default=12000,
		help='Max characters of discovery timeline sample to print (default: 12000; 0 = no limit)',
	)
	parser.add_argument(
		'--clusters',
		type=int,
		default=None,
		help='Force a specific number of persona clusters (default: auto-select via silhouette)',
	)
	parser.add_argument('--no-context', action='store_true', help='Skip printing the discovery session context sample')
	parser.add_argument('--output', type=str, default=None, help='Output directory for personas.json (default: none)')
	args = parser.parse_args()

	logging.basicConfig(
		level=logging.INFO,
		format='%(asctime)s %(levelname)-8s [%(name)s] %(message)s',
		stream=sys.stderr,
	)

	print(f'\nRunning persona pipeline: {args.discovery} discovery + {args.scoring} scoring sessions')
	print(f'Model: {args.model}  |  Min events: {args.min_events}  |  Months back: {args.months_back}\n')

	schema, scores, persona_result, discovery_timeline_sample, persona_tokens = await run_persona_pipeline(
		model=args.model,
		discovery_sessions=args.discovery,
		scoring_sessions=args.scoring,
		min_events=args.min_events,
		months_back=args.months_back,
		max_concurrent=args.concurrency,
		num_clusters=args.clusters,
	)

	if not args.no_context:
		_print_discovery_session_context(discovery_timeline_sample, max_chars=args.context_max_chars)

	_print_schema(schema)
	_print_scores(scores, schema, num_examples=args.examples)
	_print_personas(persona_result, schema)

	print(f'\nToken usage: {persona_tokens.input_tokens:,} input, {persona_tokens.output_tokens:,} output')

	if args.output:
		out_path = save_personas(schema, persona_result, Path(args.output))
		print(f'\nPersonas saved to {out_path}')


if __name__ == '__main__':
	asyncio.run(main())
