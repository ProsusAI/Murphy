"""Demo: run the persona discovery and scoring pipeline and display results.

Usage::

    python -m murphy.personas.demo [--discovery N] [--scoring N] [--min-events N] [--months-back N] [--model MODEL] [--examples N]

Defaults to 10 discovery sessions and 20 scoring sessions for a quick demo run.
Set higher values (100/200) for production-quality results.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from murphy.personas.pipeline import run_persona_pipeline
from murphy.personas.pipeline_models import SessionScore, TraitSchema


def _print_schema(schema: TraitSchema) -> None:
	print('\n' + '=' * 80)
	print('  DISCOVERED TRAIT SCHEMA')
	print('=' * 80)
	print(f'\nRationale: {schema.rationale}\n')
	print(f'{len(schema.dimensions)} dimensions discovered:\n')

	for i, dim in enumerate(schema.dimensions, 1):
		print(f'  {i}. {dim.name}')
		print(f'     {dim.description}')
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


async def main() -> None:
	parser = argparse.ArgumentParser(description='Persona Discovery & Scoring demo')
	parser.add_argument('--discovery', type=int, default=10, help='Number of discovery sessions (default: 10)')
	parser.add_argument('--scoring', type=int, default=20, help='Number of scoring sessions (default: 20)')
	parser.add_argument('--min-events', type=int, default=20, help='Min events per session (default: 20)')
	parser.add_argument('--months-back', type=int, default=2, help='Months of history to sample (default: 2)')
	parser.add_argument('--model', type=str, default='gpt-4.1-mini', help='LLM model (default: gpt-4.1-mini)')
	parser.add_argument('--examples', type=int, default=5, help='Number of score examples to display (default: 5)')
	parser.add_argument('--concurrency', type=int, default=15, help='Max concurrent LLM calls (default: 15)')
	args = parser.parse_args()

	logging.basicConfig(
		level=logging.INFO,
		format='%(asctime)s %(levelname)-8s [%(name)s] %(message)s',
		stream=sys.stderr,
	)

	print(f'\nRunning persona pipeline: {args.discovery} discovery + {args.scoring} scoring sessions')
	print(f'Model: {args.model}  |  Min events: {args.min_events}  |  Months back: {args.months_back}\n')

	schema, scores = await run_persona_pipeline(
		model=args.model,
		discovery_sessions=args.discovery,
		scoring_sessions=args.scoring,
		min_events=args.min_events,
		months_back=args.months_back,
		max_concurrent=args.concurrency,
	)

	_print_schema(schema)
	_print_scores(scores, schema, num_examples=args.examples)


if __name__ == '__main__':
	asyncio.run(main())
