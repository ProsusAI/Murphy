"""Demo: run the Databricks persona discovery and scoring pipeline.

Usage::

    python -m murphy.personas.demo_databricks [--discovery N] [--scoring N] [--min-events N] [--event-date-from DATE] [--model MODEL] [--output DIR]

Reads session-grain rows from Unity Catalog ``murphy_evals_data`` (see
:mod:`murphy.config` for ``DATABRICKS_*`` settings). Does not use the PostHog API.

Requires: ``uv sync --extra databricks``, ``DATABRICKS_WAREHOUSE_ID``, and either
``DATABRICKS_TOKEN`` or a Databricks CLI login (``databricks auth login``; optional
``DATABRICKS_CONFIG_PROFILE``).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from murphy.config import (
	DATABRICKS_EVENT_DATE_FROM,
	PERSONA_DISCOVERY_SESSIONS,
	PERSONA_LLM_CONCURRENCY,
	PERSONA_MIN_EVENTS,
	PERSONA_SCORING_SESSIONS,
)
from murphy.personas.databricks_pipeline import run_databricks_persona_pipeline
from murphy.personas.demo import (
	_print_discovery_session_context,
	_print_personas,
	_print_schema,
	_print_scores,
)
from murphy.personas.storage import save_personas


async def main() -> None:
	parser = argparse.ArgumentParser(description='Databricks Persona Discovery & Scoring demo')
	parser.add_argument(
		'--discovery',
		type=int,
		default=PERSONA_DISCOVERY_SESSIONS,
		help=f'Number of discovery sessions (default: {PERSONA_DISCOVERY_SESSIONS})',
	)
	parser.add_argument(
		'--scoring',
		type=int,
		default=PERSONA_SCORING_SESSIONS,
		help=f'Number of scoring sessions (default: {PERSONA_SCORING_SESSIONS})',
	)
	parser.add_argument(
		'--min-events',
		type=int,
		default=PERSONA_MIN_EVENTS,
		help=f'Min events per session (default: {PERSONA_MIN_EVENTS})',
	)
	parser.add_argument(
		'--event-date-from',
		type=str,
		default=DATABRICKS_EVENT_DATE_FROM,
		help=f'Session start date filter YYYY-MM-DD (default: {DATABRICKS_EVENT_DATE_FROM})',
	)
	parser.add_argument('--model', type=str, default='gpt-5-mini', help='LLM model (default: gpt-5-mini)')
	parser.add_argument('--examples', type=int, default=5, help='Number of score examples to display (default: 5)')
	parser.add_argument(
		'--concurrency',
		type=int,
		default=PERSONA_LLM_CONCURRENCY,
		help=f'Max concurrent LLM calls (default: {PERSONA_LLM_CONCURRENCY})',
	)
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
		help='Persona cluster count (default: PERSONA_NUM_CLUSTERS); use 0 for auto (silhouette)',
	)
	parser.add_argument('--no-context', action='store_true', help='Skip printing the discovery session context sample')
	parser.add_argument('--output', type=str, default=None, help='Output directory for personas.json (default: none)')
	args = parser.parse_args()

	logging.basicConfig(
		level=logging.INFO,
		format='%(asctime)s %(levelname)-8s [%(name)s] %(message)s',
		stream=sys.stderr,
	)

	print(f'\nRunning Databricks persona pipeline: {args.discovery} discovery + {args.scoring} scoring sessions')
	print(f'Model: {args.model}  |  Min events: {args.min_events}  |  Event date from: {args.event_date_from}\n')

	pipeline_kw: dict[str, Any] = {
		'model': args.model,
		'discovery_sessions': args.discovery,
		'scoring_sessions': args.scoring,
		'min_events': args.min_events,
		'event_date_from': args.event_date_from,
		'max_concurrent': args.concurrency,
	}
	if args.clusters is not None:
		pipeline_kw['num_clusters'] = args.clusters
	schema, scores, persona_result, discovery_timeline_sample, persona_tokens = await run_databricks_persona_pipeline(
		**pipeline_kw
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
