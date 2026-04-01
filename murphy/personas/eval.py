"""Persona evaluation experiment runner.

Usage::

    python -m murphy.personas.eval [options]

Runs a grid of discovery/scoring combinations, sweeps cluster counts for each,
and writes results to a Markdown report.

For each discovery size the script runs discovery once and fetches the maximum
requested scoring sessions once, then reuses the schema and scores across
scoring-size subsets and cluster sweeps to avoid redundant LLM calls.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from browser_use.llm import ChatOpenAI
from browser_use.tokens.service import TokenCost
from murphy.config import (
	POSTHOG_API_KEY,
	POSTHOG_HOST,
	POSTHOG_PROJECT_ID,
)
from murphy.personas.clustering import cluster_sessions
from murphy.personas.compressor import compress_session
from murphy.personas.discovery import run_discovery
from murphy.personas.models import AnalyticsSession
from murphy.personas.persona_labeling import build_persona_result, label_personas
from murphy.personas.pipeline import (
	_unique_user_ids,
	fetch_person_contexts,
	fetch_population_paths,
)
from murphy.personas.pipeline_models import PersonaResult, SessionScore, TraitSchema
from murphy.personas.posthog_adapter import PostHogAdapter
from murphy.personas.posthog_client import PostHogClient
from murphy.personas.scoring import run_scoring

logger = logging.getLogger(__name__)


# ── Data containers ──────────────────────────────────────────────────────────


@dataclass
class TokenSnapshot:
	input_tokens: int = 0
	output_tokens: int = 0


@dataclass
class ClusterResult:
	k: int
	silhouette: float
	persona_result: PersonaResult
	label_input_tokens: int = 0
	label_output_tokens: int = 0
	duration_s: float = 0.0


@dataclass
class SessionSample:
	"""A single session shown as raw events, compressed timeline, and LLM scores."""

	session_id: str
	user_id: str
	event_count: int
	raw_events: list[str]
	compressed_timeline: str
	score: SessionScore | None


@dataclass
class ExperimentResult:
	discovery_sessions_requested: int
	scoring_sessions_requested: int
	discovery_sessions_fetched: int
	scoring_sessions_fetched: int
	scored_sessions_retained: int
	schema: TraitSchema
	discovery_input_tokens: int = 0
	discovery_output_tokens: int = 0
	scoring_input_tokens: int = 0
	scoring_output_tokens: int = 0
	discovery_duration_s: float = 0.0
	scoring_duration_s: float = 0.0
	cluster_results: list[ClusterResult] = field(default_factory=list)
	session_samples: list[SessionSample] = field(default_factory=list)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _snapshot(token_cost: TokenCost, model: str) -> TokenSnapshot:
	usage = token_cost.get_usage_tokens_for_model(model)
	return TokenSnapshot(input_tokens=usage.prompt_tokens, output_tokens=usage.completion_tokens)


def _delta(before: TokenSnapshot, after: TokenSnapshot) -> TokenSnapshot:
	return TokenSnapshot(
		input_tokens=after.input_tokens - before.input_tokens,
		output_tokens=after.output_tokens - before.output_tokens,
	)


def _format_raw_events(session: AnalyticsSession, max_events: int = 60) -> list[str]:
	"""Format raw events as compact one-line strings for the report."""
	lines: list[str] = []
	for evt in session.events[:max_events]:
		ts = evt.timestamp.strftime('%H:%M:%S')
		props_preview = ''
		interesting_keys = [
			k
			for k in evt.properties
			if not k.startswith('$') or k in ('$pathname', '$current_url', '$el_text', '$exception_type')
		]
		if interesting_keys:
			snippets = []
			for k in interesting_keys[:4]:
				v = evt.properties[k]
				if isinstance(v, str) and len(v) > 60:
					v = v[:57] + '...'
				snippets.append(f'{k}={v}')
			props_preview = '  ' + ', '.join(snippets)
		lines.append(f'[{ts}] {evt.event_name}{props_preview}')
	if len(session.events) > max_events:
		lines.append(f'... ({len(session.events) - max_events} more events)')
	return lines


def _build_session_samples(
	sessions: list[AnalyticsSession],
	scores: list[SessionScore],
	person_contexts: dict[str, dict[str, Any]],
	n: int = 3,
) -> list[SessionSample]:
	"""Pick n sessions spread across the list and build sample objects."""
	if not sessions or not scores:
		return []
	score_map = {s.session_id: s for s in scores}

	# Pick evenly spaced sessions that were actually scored
	scored_sessions = [s for s in sessions if s.session_id in score_map]
	if not scored_sessions:
		return []

	step = max(1, len(scored_sessions) // (n + 1))
	picked = [scored_sessions[step * (i + 1) - 1] for i in range(n) if step * (i + 1) - 1 < len(scored_sessions)]

	samples: list[SessionSample] = []
	for session in picked:
		compressed = compress_session(session, person_contexts.get(session.user_id))
		samples.append(
			SessionSample(
				session_id=session.session_id,
				user_id=session.user_id,
				event_count=session.event_count,
				raw_events=_format_raw_events(session),
				compressed_timeline=compressed,
				score=score_map.get(session.session_id),
			)
		)
	return samples


# ── Cluster sweep ────────────────────────────────────────────────────────────


async def run_cluster_sweep(
	llm: ChatOpenAI,
	token_cost: TokenCost,
	model: str,
	schema: TraitSchema,
	scores: list[SessionScore],
	cluster_values: list[int],
) -> list[ClusterResult]:
	"""Cluster + label for each requested k value, collecting metrics."""
	results: list[ClusterResult] = []
	valid_ks = [k for k in cluster_values if k < len(scores)]
	total = len(valid_ks)

	for idx, k in enumerate(valid_ks, 1):
		print(f'    [{idx}/{total}] k={k} ...', end='', flush=True)
		before = _snapshot(token_cost, model)
		t0 = time.monotonic()

		clustering = cluster_sessions(scores, schema, k=k)
		cluster_sizes = [int((clustering.labels == i).sum()) for i in range(clustering.k)]
		labels = await label_personas(llm, schema, clustering.centroids, cluster_sizes)
		persona_result = build_persona_result(schema, scores, clustering, labels)

		duration = time.monotonic() - t0
		after_snap = _snapshot(token_cost, model)
		tok = _delta(before, after_snap)

		results.append(
			ClusterResult(
				k=clustering.k,
				silhouette=clustering.silhouette,
				persona_result=persona_result,
				label_input_tokens=tok.input_tokens,
				label_output_tokens=tok.output_tokens,
				duration_s=duration,
			)
		)

		names = [p.name for p in persona_result.personas]
		print(f' silhouette={clustering.silhouette:.4f}  ({duration:.1f}s)  {names}')
		logger.info(
			'k=%d  silhouette=%.4f  personas=%s',
			clustering.k,
			clustering.silhouette,
			names,
		)

	skipped = len(cluster_values) - total
	if skipped:
		print(f'    (skipped {skipped} k values — not enough scored sessions)')

	return results


# ── Markdown report ──────────────────────────────────────────────────────────


def _write_markdown_report(
	experiments: list[ExperimentResult],
	model: str,
	min_events: int,
	months_back: int,
	concurrency: int,
	output_path: Path,
) -> None:
	lines: list[str] = []
	ts = datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

	lines.append('# Persona Evaluation Results')
	lines.append('')
	lines.append(f'Generated: {ts}')
	lines.append('')
	lines.append('## Run Configuration')
	lines.append('')
	lines.append(f'- **Model**: {model}')
	lines.append(f'- **Min events per session**: {min_events}')
	lines.append(f'- **Months back**: {months_back}')
	lines.append(f'- **Max concurrency**: {concurrency}')
	lines.append('')

	# ── Summary table ────────────────────────────────────────────────────
	lines.append('## Summary')
	lines.append('')
	lines.append('| Discovery | Scoring | Scored | Dimensions | Best k | Best Silhouette |')
	lines.append('|-----------|---------|--------|------------|--------|-----------------|')
	for exp in experiments:
		best = max(exp.cluster_results, key=lambda r: r.silhouette) if exp.cluster_results else None
		best_k = str(best.k) if best else '-'
		best_sil = f'{best.silhouette:.4f}' if best else '-'
		lines.append(
			f'| {exp.discovery_sessions_requested} '
			f'| {exp.scoring_sessions_requested} '
			f'| {exp.scored_sessions_retained} '
			f'| {len(exp.schema.dimensions)} '
			f'| {best_k} '
			f'| {best_sil} |'
		)
	lines.append('')

	# ── Silhouette comparison ────────────────────────────────────────────
	all_ks = sorted({r.k for exp in experiments for r in exp.cluster_results})
	if all_ks:
		lines.append('## Silhouette Scores by Cluster Count')
		lines.append('')
		header = '| Discovery / Scoring | ' + ' | '.join(f'k={k}' for k in all_ks) + ' |'
		sep = '|---------------------|' + '|'.join('-------' for _ in all_ks) + '|'
		lines.append(header)
		lines.append(sep)
		for exp in experiments:
			sil_map = {r.k: r.silhouette for r in exp.cluster_results}
			label = f'{exp.discovery_sessions_requested} / {exp.scoring_sessions_requested}'
			cells = ' | '.join(f'{sil_map[k]:.4f}' if k in sil_map else '-' for k in all_ks)
			lines.append(f'| {label} | {cells} |')
		lines.append('')

	# ── Per-experiment detail ────────────────────────────────────────────
	for idx, exp in enumerate(experiments, 1):
		lines.append('---')
		lines.append('')
		lines.append(
			f'## Experiment {idx}: Discovery={exp.discovery_sessions_requested}, Scoring={exp.scoring_sessions_requested}'
		)
		lines.append('')

		lines.append('### Data')
		lines.append('')
		lines.append(f'- Discovery sessions fetched: {exp.discovery_sessions_fetched}')
		lines.append(f'- Scoring sessions fetched: {exp.scoring_sessions_fetched}')
		lines.append(f'- Sessions successfully scored: {exp.scored_sessions_retained}')
		lines.append('')

		lines.append('### Timing')
		lines.append('')
		lines.append(f'- Discovery: {exp.discovery_duration_s:.1f}s')
		lines.append(f'- Scoring: {exp.scoring_duration_s:.1f}s')
		sweep_total = sum(r.duration_s for r in exp.cluster_results)
		lines.append(f'- Cluster sweep (total): {sweep_total:.1f}s')
		lines.append('')

		lines.append('### Token Usage')
		lines.append('')
		lines.append('| Phase | Input | Output |')
		lines.append('|-------|-------|--------|')
		lines.append(f'| Discovery | {exp.discovery_input_tokens:,} | {exp.discovery_output_tokens:,} |')
		lines.append(f'| Scoring | {exp.scoring_input_tokens:,} | {exp.scoring_output_tokens:,} |')
		label_in = sum(r.label_input_tokens for r in exp.cluster_results)
		label_out = sum(r.label_output_tokens for r in exp.cluster_results)
		lines.append(f'| Labeling (all k) | {label_in:,} | {label_out:,} |')
		total_in = exp.discovery_input_tokens + exp.scoring_input_tokens + label_in
		total_out = exp.discovery_output_tokens + exp.scoring_output_tokens + label_out
		lines.append(f'| **Total** | **{total_in:,}** | **{total_out:,}** |')
		lines.append('')

		lines.append('### Discovered Trait Schema')
		lines.append('')
		lines.append(f'> {exp.schema.rationale}')
		lines.append('')
		lines.append(f'{len(exp.schema.dimensions)} dimensions:')
		lines.append('')
		for i, dim in enumerate(exp.schema.dimensions, 1):
			lines.append(f'{i}. **{dim.name}**: {dim.description}')
			lines.append(f'   - Low (1): {dim.low_description}')
			lines.append(f'   - High (5): {dim.high_description}')
		lines.append('')

		dim_names = [d.name for d in exp.schema.dimensions]
		for cr in exp.cluster_results:
			lines.append(f'### k={cr.k} (silhouette={cr.silhouette:.4f})')
			lines.append('')

			for persona in sorted(cr.persona_result.personas, key=lambda p: p.size, reverse=True):
				pct = persona.size / len(cr.persona_result.assignments) * 100 if cr.persona_result.assignments else 0
				lines.append(f'**{persona.name}** ({persona.size} sessions, {pct:.0f}%)')
				lines.append('')
				lines.append(f'> {persona.description}')
				lines.append('')
				lines.append(f'Distinguishing traits: {", ".join(persona.distinguishing_traits)}')
				lines.append('')
				centroid_dict = {s.trait_name: s.score for s in persona.centroid}
				lines.append('| Dimension | Score |')
				lines.append('|-----------|-------|')
				for name in dim_names:
					val = centroid_dict.get(name, 0)
					if isinstance(val, float):
						lines.append(f'| {name} | {val:.2f} |')
					else:
						lines.append(f'| {name} | {val} |')
				lines.append('')

			sizes = sorted([p.size for p in cr.persona_result.personas], reverse=True)
			lines.append(f'Cluster sizes: {sizes}')
			lines.append(
				f'Labeling tokens: {cr.label_input_tokens:,} input, {cr.label_output_tokens:,} output ({cr.duration_s:.1f}s)'
			)
			lines.append('')

	# ── Session samples (raw vs compressed + scores) ────────────────
	any_samples = any(exp.session_samples for exp in experiments)
	if any_samples:
		lines.append('---')
		lines.append('')
		lines.append('## Session Samples: Raw vs Compressed vs Scores')
		lines.append('')
		lines.append(
			'Below are example sessions showing the raw event stream, the compressed '
			'timeline sent to the LLM, and the resulting trait scores.'
		)
		lines.append('')

		sample_num = 0
		for exp in experiments:
			if not exp.session_samples:
				continue
			for sample in exp.session_samples:
				sample_num += 1
				lines.append(f'### Sample {sample_num} — session `{sample.session_id}`')
				lines.append('')
				lines.append(f'- **User**: `{sample.user_id}`')
				lines.append(f'- **Raw event count**: {sample.event_count}')
				lines.append(
					f'- **From experiment**: discovery={exp.discovery_sessions_requested}, '
					f'scoring={exp.scoring_sessions_requested}'
				)
				lines.append('')

				lines.append('#### Raw Event Stream')
				lines.append('')
				lines.append('```')
				lines.extend(sample.raw_events)
				lines.append('```')
				lines.append('')

				lines.append('#### Compressed Timeline (LLM input)')
				lines.append('')
				lines.append('```')
				lines.extend(sample.compressed_timeline.splitlines())
				lines.append('```')
				lines.append('')

				if sample.score:
					lines.append('#### Trait Scores')
					lines.append('')
					lines.append('| Dimension | Score |')
					lines.append('|-----------|-------|')
					for ds in sample.score.scores:
						lines.append(f'| {ds.trait_name} | {ds.score} |')
					lines.append('')
					if sample.score.reasoning:
						reasoning_clean = sample.score.reasoning.replace('\n', ' ').strip()
						lines.append(f'**LLM Reasoning:** {reasoning_clean}')
						lines.append('')
				else:
					lines.append('*(no score available for this session)*')
					lines.append('')

			break  # only show samples from first experiment that has them

	output_path.parent.mkdir(parents=True, exist_ok=True)
	output_path.write_text('\n'.join(lines))
	logger.info('Report written to %s', output_path)


# ── Main ─────────────────────────────────────────────────────────────────────


async def main() -> None:
	parser = argparse.ArgumentParser(description='Persona evaluation experiment runner')
	parser.add_argument(
		'--discovery-sizes',
		type=str,
		default='200,500',
		help='Comma-separated discovery session counts (default: 200,500)',
	)
	parser.add_argument(
		'--scoring-sizes',
		type=str,
		default='500,1000',
		help='Comma-separated scoring session counts (default: 500,1000)',
	)
	parser.add_argument(
		'--clusters',
		type=str,
		default='4,5,6,7,8,9,10',
		help='Comma-separated cluster counts to sweep (default: 4,5,6,7,8,9,10)',
	)
	parser.add_argument('--min-events', type=int, default=100, help='Min events per session (default: 100)')
	parser.add_argument('--months-back', type=int, default=2, help='Months of history (default: 2)')
	parser.add_argument('--model', type=str, default='gpt-5-mini', help='LLM model (default: gpt-5-mini)')
	parser.add_argument('--concurrency', type=int, default=15, help='Max concurrent LLM calls (default: 15)')
	parser.add_argument(
		'--output',
		type=str,
		default='persona_eval_results.md',
		help='Output file path (default: persona_eval_results.md)',
	)
	args = parser.parse_args()

	discovery_sizes = [int(x.strip()) for x in args.discovery_sizes.split(',')]
	scoring_sizes = sorted(int(x.strip()) for x in args.scoring_sizes.split(','))
	cluster_values = [int(x.strip()) for x in args.clusters.split(',')]

	logging.basicConfig(
		level=logging.INFO,
		format='%(asctime)s %(levelname)-8s [%(name)s] %(message)s',
		stream=sys.stderr,
	)

	n_bases = len(discovery_sizes) * len(scoring_sizes)
	n_evals = n_bases * len(cluster_values)
	overall_t0 = time.monotonic()
	print('\nPersona Evaluation Experiment')
	print(f'Discovery sizes: {discovery_sizes}')
	print(f'Scoring sizes:   {scoring_sizes}')
	print(f'Cluster sweep:   {cluster_values}')
	print(f'Model: {args.model}  |  Min events: {args.min_events}  |  Months back: {args.months_back}')
	print(f'Total base experiments: {n_bases}  ({len(discovery_sizes)} discovery x {len(scoring_sizes)} scoring)')
	print(f'Total cluster evaluations: {n_evals}')
	print()

	all_experiments: list[ExperimentResult] = []

	async with PostHogClient(
		api_key=POSTHOG_API_KEY,
		project_id=POSTHOG_PROJECT_ID,
		host=POSTHOG_HOST,
	) as client:
		adapter = PostHogAdapter(client)
		llm = ChatOpenAI(model=args.model, temperature=0.3)
		token_cost = TokenCost()
		token_cost.register_llm(llm)

		after_date = datetime.now(tz=timezone.utc) - timedelta(days=args.months_back * 30)
		after_iso = after_date.strftime('%Y-%m-%d %H:%M:%S')

		person_contexts: dict[str, dict[str, Any]] = {}

		exp_counter = 0
		for disc_idx, disc_size in enumerate(discovery_sizes, 1):
			max_scoring = max(scoring_sizes)

			# ── Phase 1: Discovery (once per discovery size) ──────────
			print(f'\n{"=" * 80}')
			print(f'  DISCOVERY [{disc_idx}/{len(discovery_sizes)}]: {disc_size} sessions')
			print(f'{"=" * 80}')

			before = _snapshot(token_cost, args.model)
			t0 = time.monotonic()

			disc_sessions = await adapter.get_sessions(
				num_sessions=disc_size,
				min_events=args.min_events,
				after=after_iso,
				offset=0,
			)
			disc_count = len(disc_sessions)
			print(f'  Fetched {disc_count} discovery sessions')

			disc_user_ids = _unique_user_ids(disc_sessions)
			new_ctx = await fetch_person_contexts(client, [uid for uid in disc_user_ids if uid not in person_contexts])
			person_contexts.update(new_ctx)

			population_paths = await fetch_population_paths(client, after_iso)

			schema = await run_discovery(
				llm,
				disc_sessions,
				person_contexts,
				population_paths=population_paths,
				max_concurrent=args.concurrency,
			)

			disc_duration = time.monotonic() - t0
			after_snap = _snapshot(token_cost, args.model)
			disc_tokens = _delta(before, after_snap)

			print(f'  Discovered {len(schema.dimensions)} dimensions in {disc_duration:.1f}s')
			for dim in schema.dimensions:
				print(f'    - {dim.name}')

			# ── Phase 2: Scoring (fetch max, score once) ─────────────
			print(f'\n  SCORING: up to {max_scoring} sessions (offset={disc_size})')

			before = _snapshot(token_cost, args.model)
			t0 = time.monotonic()

			score_sessions = await adapter.get_sessions(
				num_sessions=max_scoring,
				min_events=args.min_events,
				after=after_iso,
				offset=disc_size,
			)
			score_count = len(score_sessions)
			print(f'  Fetched {score_count} scoring sessions')

			score_user_ids = _unique_user_ids(score_sessions)
			new_user_ids = [uid for uid in score_user_ids if uid not in person_contexts]
			if new_user_ids:
				new_ctx = await fetch_person_contexts(client, new_user_ids)
				person_contexts.update(new_ctx)

			all_scores = await run_scoring(
				llm,
				schema,
				score_sessions,
				person_contexts,
				max_concurrent=args.concurrency,
			)

			scoring_duration = time.monotonic() - t0
			after_snap = _snapshot(token_cost, args.model)
			scoring_tokens = _delta(before, after_snap)

			print(f'  Scored {len(all_scores)} sessions in {scoring_duration:.1f}s')

			session_samples = _build_session_samples(score_sessions, all_scores, person_contexts, n=3)
			print(f'  Captured {len(session_samples)} session samples for report')

			# ── Phase 3: Cluster sweep per scoring size ──────────────
			for score_idx, score_size in enumerate(scoring_sizes, 1):
				exp_counter += 1
				scores_subset = all_scores[:score_size]

				print(
					f'\n  CLUSTER SWEEP [{exp_counter}/{n_bases}]: '
					f'discovery={disc_size}, scoring={score_size} '
					f'({len(scores_subset)} scored sessions)'
				)

				# Proportional token attribution when using a subset
				if len(scores_subset) < len(all_scores) and len(all_scores) > 0:
					ratio = len(scores_subset) / len(all_scores)
					sub_scoring_tokens = TokenSnapshot(
						input_tokens=int(scoring_tokens.input_tokens * ratio),
						output_tokens=int(scoring_tokens.output_tokens * ratio),
					)
					sub_scoring_duration = scoring_duration * ratio
				else:
					sub_scoring_tokens = scoring_tokens
					sub_scoring_duration = scoring_duration

				exp = ExperimentResult(
					discovery_sessions_requested=disc_size,
					scoring_sessions_requested=score_size,
					discovery_sessions_fetched=disc_count,
					scoring_sessions_fetched=min(score_count, score_size),
					scored_sessions_retained=len(scores_subset),
					schema=schema,
					discovery_input_tokens=disc_tokens.input_tokens,
					discovery_output_tokens=disc_tokens.output_tokens,
					scoring_input_tokens=sub_scoring_tokens.input_tokens,
					scoring_output_tokens=sub_scoring_tokens.output_tokens,
					discovery_duration_s=disc_duration,
					scoring_duration_s=sub_scoring_duration,
				)

				exp.session_samples = session_samples

				exp.cluster_results = await run_cluster_sweep(
					llm,
					token_cost,
					args.model,
					schema,
					scores_subset,
					cluster_values,
				)
				all_experiments.append(exp)

				if exp.cluster_results:
					best = max(exp.cluster_results, key=lambda r: r.silhouette)
					print(f'  Best: k={best.k} (silhouette={best.silhouette:.4f})')

	output_path = Path(args.output)
	_write_markdown_report(
		all_experiments,
		model=args.model,
		min_events=args.min_events,
		months_back=args.months_back,
		concurrency=args.concurrency,
		output_path=output_path,
	)

	elapsed = time.monotonic() - overall_t0
	print(f'\n{"=" * 80}')
	print(f'  DONE  ({elapsed:.1f}s elapsed)')
	print(f'{"=" * 80}')
	print(f'\nResults written to {output_path}')
	final = _snapshot(token_cost, args.model)
	print(f'Total token usage: {final.input_tokens:,} input, {final.output_tokens:,} output')

	if all_experiments:
		print('\nSilhouette summary:')
		for exp in all_experiments:
			if exp.cluster_results:
				best = max(exp.cluster_results, key=lambda r: r.silhouette)
				worst = min(exp.cluster_results, key=lambda r: r.silhouette)
				print(
					f'  disc={exp.discovery_sessions_requested} '
					f'score={exp.scoring_sessions_requested}: '
					f'best k={best.k} ({best.silhouette:.4f}), '
					f'worst k={worst.k} ({worst.silhouette:.4f})'
				)


if __name__ == '__main__':
	asyncio.run(main())
