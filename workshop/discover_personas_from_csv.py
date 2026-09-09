from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from murphy.llm import create_llm
from murphy.personas.clustering import cluster_sessions
from murphy.personas.discovery import run_discovery
from murphy.personas.models import AnalyticsEvent, AnalyticsSession
from murphy.personas.persona_labeling import build_persona_result, label_personas
from murphy.personas.scoring import run_scoring
from murphy.personas.storage import save_personas

REQUIRED_COLUMNS = {
	'uuid',
	'event',
	'distinct_id',
	'session_id',
	'timestamp',
	'properties',
	'elements_chain',
}


def _parse_properties(value: str) -> dict[str, Any]:
	if not value:
		return {}
	parsed = json.loads(value)
	if not isinstance(parsed, dict):
		raise ValueError('The properties value must contain a JSON object.')
	return parsed


def load_sessions(path: Path) -> list[AnalyticsSession]:
	grouped: dict[str, list[AnalyticsEvent]] = defaultdict(list)
	with path.open(newline='') as source:
		reader = csv.DictReader(source)
		missing = REQUIRED_COLUMNS.difference(reader.fieldnames or [])
		if missing:
			raise ValueError(f'Missing CSV columns: {", ".join(sorted(missing))}')
		for row in reader:
			session_id = row['session_id']
			grouped[session_id].append(
				AnalyticsEvent(
					event_id=row['uuid'],
					event_name=row['event'],
					user_id=row['distinct_id'],
					session_id=session_id,
					timestamp=datetime.fromisoformat(row['timestamp']),
					properties=_parse_properties(row['properties']),
					elements_chain=row['elements_chain'],
					source='posthog_csv',
					raw=row,
				)
			)

	sessions: list[AnalyticsSession] = []
	for session_id, events in grouped.items():
		events.sort(key=lambda event: event.timestamp)
		sessions.append(
			AnalyticsSession(
				session_id=session_id,
				user_id=events[0].user_id,
				started_at=events[0].timestamp,
				ended_at=events[-1].timestamp,
				event_count=len(events),
				events=events,
				source='posthog_csv',
			)
		)
	return sorted(sessions, key=lambda session: session.session_id)


def population_paths(sessions: list[AnalyticsSession]) -> str:
	counts: Counter[str] = Counter()
	for session in sessions:
		for event in session.events:
			if event.event_name == '$pageview':
				path = event.properties.get('$pathname')
				if isinstance(path, str) and path:
					counts[path] += 1
	lines = ['Top pages by visit count:']
	lines.extend(f'  {path} — {count} visits' for path, count in counts.most_common(30))
	return '\n'.join(lines)


async def discover(args: argparse.Namespace) -> None:
	sessions = load_sessions(args.input)
	if len(sessions) < args.discovery_sessions + args.scoring_sessions:
		raise ValueError(
			f'The CSV has {len(sessions)} sessions, but '
			f'{args.discovery_sessions + args.scoring_sessions} are required.'
		)

	shuffled = sessions.copy()
	random.Random(args.seed).shuffle(shuffled)
	discovery_sessions = shuffled[: args.discovery_sessions]
	scoring_sessions = shuffled[args.discovery_sessions : args.discovery_sessions + args.scoring_sessions]

	llm = create_llm(args.model, provider=args.provider)
	contexts: dict[str, dict[str, Any]] = {}
	schema = await run_discovery(
		llm,
		discovery_sessions,
		contexts,
		population_paths=population_paths(sessions),
		max_concurrent=args.concurrency,
	)
	scores = await run_scoring(
		llm,
		schema,
		scoring_sessions,
		contexts,
		max_concurrent=args.concurrency,
	)
	clustering = cluster_sessions(scores, schema, k=args.clusters)
	cluster_sizes = [int((clustering.labels == index).sum()) for index in range(clustering.k)]
	labels = await label_personas(llm, schema, clustering.centroids, cluster_sizes)
	result = build_persona_result(schema, scores, clustering, labels)
	path = save_personas(schema, result, args.output)

	print(f'Loaded {len(sessions)} sessions from {args.input}')
	print(f'Discovered {len(schema.dimensions)} trait dimensions')
	print(f'Created {len(result.personas)} personas')
	for persona in sorted(result.personas, key=lambda item: item.size, reverse=True):
		print(f'- {persona.name}: {persona.size} scoring sessions')
	print(f'Saved personas to {path}')


def main() -> None:
	parser = argparse.ArgumentParser(description='Discover Murphy personas from a PostHog event CSV.')
	parser.add_argument('--input', type=Path, default=Path(__file__).with_name('synthetic_posthog_events.csv'))
	parser.add_argument('--output', type=Path, default=Path(__file__).with_name('output'))
	parser.add_argument('--discovery-sessions', type=int, default=20)
	parser.add_argument('--scoring-sessions', type=int, default=40)
	parser.add_argument('--clusters', type=int, default=5)
	parser.add_argument('--concurrency', type=int, default=8)
	parser.add_argument('--seed', type=int, default=42)
	parser.add_argument('--provider', default='openai')
	parser.add_argument('--model', default='gpt-5-mini')
	args = parser.parse_args()

	import asyncio

	asyncio.run(discover(args))


if __name__ == '__main__':
	main()
