#!/usr/bin/env python3
"""Generate SQL VALUES for persona session sampling.

Two modes:

  --mode pool   (default) Candidate pool for persona_conversation_goals.sql.
                SQL picks top 10 conversations with messages from this pool.

  --mode fixed  Legacy: first N assignment session_ids (may have message_count=0).

Usage (from repo root):

    python databricks/toqan_personas/test_goal/generate_session_values.py \\
        --personas outputs_thesis/personas_databricks_data/personas.json \\
        --persona-id 3 --pool-size 40

Paste output into the `pool` CTE in persona_conversation_goals.sql.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
	parser = argparse.ArgumentParser(description='Generate SQL VALUES for persona session sampling')
	parser.add_argument(
		'--personas',
		type=Path,
		default=Path('outputs_thesis/personas_databricks_data/personas.json'),
		help='Path to personas.json',
	)
	parser.add_argument('--persona-id', type=int, default=3, help='persona_id from result.personas')
	parser.add_argument('--pool-size', type=int, default=40, help='Candidate pool size (mode=pool)')
	parser.add_argument('--limit', type=int, default=5, help='Rows in mode=fixed')
	parser.add_argument(
		'--mode',
		choices=('pool', 'fixed'),
		default='pool',
		help='pool: VALUES for candidate pool; fixed: numbered first N assignments',
	)
	args = parser.parse_args()

	if not args.personas.is_file():
		raise SystemExit(f'Personas file not found: {args.personas}')

	data = json.loads(args.personas.read_text(encoding='utf-8'))
	result = data['result']
	persona = next((p for p in result['personas'] if p['persona_id'] == args.persona_id), None)
	if persona is None:
		ids = [p['persona_id'] for p in result['personas']]
		raise SystemExit(f'persona_id {args.persona_id} not found. Available: {ids}')

	all_assignments = [a for a in result['assignments'] if a['persona_id'] == args.persona_id]
	if not all_assignments:
		raise SystemExit(f'No assignments for persona_id {args.persona_id}')

	print(f'-- persona_id={args.persona_id} name={persona["name"]!r} cluster_size={persona["size"]}')
	print(f'-- source: {args.personas}')
	print(f'-- mode={args.mode}')

	if args.mode == 'pool':
		pool = all_assignments[: args.pool_size]
		print(f'-- pool: {len(pool)} candidate session keys (SQL filters message_count > 0, LIMIT 5)')
		for a in pool:
			print(f"    ('{a['session_id']}'),")
	else:
		picks = all_assignments[: args.limit]
		for i, a in enumerate(picks, 1):
			print(f"      ({i}, '{a['session_id']}'),")


if __name__ == '__main__':
	main()
