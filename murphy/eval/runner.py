"""Orchestrate the persona similarity eval for a single Murphy output directory.

Used by both the CLI (--eval-similarity flag) and the standalone
murphy.eval.cli runner.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from browser_use.llm import BaseChatModel
from murphy.eval.models import PersonaSimilarityResult, SimilarityReport
from murphy.eval.similarity import evaluate_similarity
from murphy.models import EvaluationReport
from murphy.personas.bridge import lookup_persona_by_slug
from murphy.personas.pipeline_models import PersonaResult, TraitSchema

logger = logging.getLogger(__name__)

_RUN_DIR_RE = re.compile(r'^run_(\d+)$')


# ── File helpers ──────────────────────────────────────────────────────────────


def discover_run_dirs(output_dir: Path) -> list[tuple[int, Path]]:
	"""Return (run_index, run_dir) pairs sorted by run_index."""
	runs: list[tuple[int, Path]] = []
	for p in output_dir.iterdir():
		if not p.is_dir():
			continue
		m = _RUN_DIR_RE.fullmatch(p.name)
		if m:
			runs.append((int(m.group(1)), p))
	return sorted(runs, key=lambda x: x[0])


def resolve_agent_history(run_dir: Path, scenario_index: int) -> Path | None:
	adir = run_dir / 'agent_history'
	if not adir.is_dir():
		return None
	matches = sorted(adir.glob(f'test_{scenario_index:02d}_*.json'))
	return matches[0] if matches else None


# ── Markdown ──────────────────────────────────────────────────────────────────


def _similarity_label(score: float) -> str:
	if score >= 0.85:
		return 'HIGH'
	if score >= 0.70:
		return 'MEDIUM'
	return 'LOW'


def _similarity_emoji(score: float) -> str:
	if score >= 0.85:
		return '🟢'
	if score >= 0.70:
		return '🟡'
	return '🔴'


def _make_bar(score: float, width: int = 20) -> str:
	filled = round(score * width)
	return '█' * filled + '░' * (width - filled)


def _delta_str(delta: float) -> str:
	return f'+{delta:.2f}' if delta >= 0 else f'{delta:.2f}'


def _short_trait(name: str, max_len: int = 24) -> str:
	return name if len(name) <= max_len else name[: max_len - 1] + '…'


def build_markdown_report(report_data: dict[str, Any]) -> str:
	lines: list[str] = []

	# ── Header ────────────────────────────────────────────────────────────────
	num_results = len(report_data.get('results', []))
	num_personas = len({r['persona_name'] for r in report_data.get('results', [])})
	lines.append('# Persona Similarity Report')
	lines.append(
		f'Generated: {report_data["timestamp"]}  ·  '
		f'Output: `{report_data["output_dir"]}`  ·  '
		f'{num_results} tests across {num_personas} personas'
	)
	lines.append('')
	lines.append('**Ratings:** 🟢 HIGH ≥ 85%  ·  🟡 MEDIUM ≥ 70%  ·  🔴 LOW < 70%')
	lines.append('')
	lines.append("**LLM match** measures how closely Murphy's trait scores match the real-user centroid (1 = perfect).")
	lines.append('')
	lines.append(
		"**Embedding sim** measures cosine distance between Murphy's behavioral timeline and the persona's mean session embedding."
	)
	lines.append('')
	key_takeaways = report_data.get('key_takeaways') or []
	if key_takeaways:
		lines.append('## Key Takeaways')
		lines.append('')
		for i, takeaway in enumerate(key_takeaways, 1):
			lines.append(f'**{i}.** {takeaway}')
			lines.append('')
		lines.append('')

	lines.append('---')
	lines.append('')

	results: list[dict[str, Any]] = report_data.get('results', [])
	if not results:
		lines.append('No discovered-persona tests found.')
		lines.append('')
		lines.append(
			'Make sure you ran Murphy with `--personas <path>` so that test scenarios are assigned to discovered personas.'
		)
		return '\n'.join(lines)

	by_persona_llm: dict[str, list[float]] = defaultdict(list)
	by_persona_emb: dict[str, list[float]] = defaultdict(list)
	by_persona_dims: dict[str, list[dict]] = defaultdict(list)
	by_persona_llm_ceil: dict[str, list[float]] = defaultdict(list)
	by_persona_emb_ceil: dict[str, list[float]] = defaultdict(list)
	for r in results:
		by_persona_llm[r['persona_name']].append(r['overall_similarity_score'])
		emb = r.get('embedding_similarity')
		if emb is not None:
			by_persona_emb[r['persona_name']].append(emb)
		for dim in r['dimensions']:
			by_persona_dims[r['persona_name']].append(dim)
		llm_ceil = r.get('llm_ceiling')
		if llm_ceil is not None:
			by_persona_llm_ceil[r['persona_name']].append(llm_ceil)
		emb_ceil = r.get('embedding_ceiling')
		if emb_ceil is not None:
			by_persona_emb_ceil[r['persona_name']].append(emb_ceil)

	has_embeddings = bool(by_persona_emb)
	has_ceiling = bool(by_persona_llm_ceil)

	# ── Summary table ─────────────────────────────────────────────────────────
	lines.append('## Summary')
	lines.append('')
	if has_embeddings and has_ceiling:
		lines.append('| Persona | Tests | LLM Match | LLM Ceiling | Emb Sim | Emb Ceiling | Strongest match | Biggest gap |')
		lines.append('|---------|-------|-----------|-------------|---------|-------------|-----------------|-------------|')
		for persona_name, llm_scores in sorted(by_persona_llm.items()):
			avg_llm = sum(llm_scores) / len(llm_scores)
			emb_scores = by_persona_emb.get(persona_name, [])
			avg_emb = f'{sum(emb_scores) / len(emb_scores):.2f}' if emb_scores else '—'
			llm_ceil_scores = by_persona_llm_ceil.get(persona_name, [])
			llm_ceil_str = f'{round(sum(llm_ceil_scores) / len(llm_ceil_scores) * 100)}%' if llm_ceil_scores else '—'
			emb_ceil_scores = by_persona_emb_ceil.get(persona_name, [])
			emb_ceil_str = f'{sum(emb_ceil_scores) / len(emb_ceil_scores):.2f}' if emb_ceil_scores else '—'
			bar = _make_bar(avg_llm)
			pct = round(avg_llm * 100)
			emoji = _similarity_emoji(avg_llm)
			dims = by_persona_dims[persona_name]
			best = min(dims, key=lambda d: abs(d['delta']))
			worst = max(dims, key=lambda d: abs(d['delta']))
			best_cell = f'{_short_trait(best["trait_name"])} ({_delta_str(best["delta"])})'
			worst_cell = f'{_short_trait(worst["trait_name"])} ({_delta_str(worst["delta"])})'
			lines.append(
				f'| {persona_name} | {len(llm_scores)} | `{bar}` {pct}% {emoji} | {llm_ceil_str} | {avg_emb} | {emb_ceil_str} | {best_cell} | {worst_cell} |'
			)
	elif has_embeddings:
		lines.append('| Persona | Tests | LLM Match | Emb Sim | Strongest match | Biggest gap |')
		lines.append('|---------|-------|-----------|---------|-----------------|-------------|')
		for persona_name, llm_scores in sorted(by_persona_llm.items()):
			avg_llm = sum(llm_scores) / len(llm_scores)
			emb_scores = by_persona_emb.get(persona_name, [])
			avg_emb = f'{sum(emb_scores) / len(emb_scores):.2f}' if emb_scores else '—'
			bar = _make_bar(avg_llm)
			pct = round(avg_llm * 100)
			emoji = _similarity_emoji(avg_llm)
			dims = by_persona_dims[persona_name]
			best = min(dims, key=lambda d: abs(d['delta']))
			worst = max(dims, key=lambda d: abs(d['delta']))
			best_cell = f'{_short_trait(best["trait_name"])} ({_delta_str(best["delta"])})'
			worst_cell = f'{_short_trait(worst["trait_name"])} ({_delta_str(worst["delta"])})'
			lines.append(
				f'| {persona_name} | {len(llm_scores)} | `{bar}` {pct}% {emoji} | {avg_emb} | {best_cell} | {worst_cell} |'
			)
	else:
		lines.append('| Persona | Tests | LLM Match | Strongest match | Biggest gap |')
		lines.append('|---------|-------|-----------|-----------------|-------------|')
		for persona_name, llm_scores in sorted(by_persona_llm.items()):
			avg = sum(llm_scores) / len(llm_scores)
			bar = _make_bar(avg)
			pct = round(avg * 100)
			emoji = _similarity_emoji(avg)
			dims = by_persona_dims[persona_name]
			best = min(dims, key=lambda d: abs(d['delta']))
			worst = max(dims, key=lambda d: abs(d['delta']))
			best_cell = f'{_short_trait(best["trait_name"])} ({_delta_str(best["delta"])})'
			worst_cell = f'{_short_trait(worst["trait_name"])} ({_delta_str(worst["delta"])})'
			lines.append(f'| {persona_name} | {len(llm_scores)} | `{bar}` {pct}% {emoji} | {best_cell} | {worst_cell} |')
	lines.append('')

	# ── Detailed results ──────────────────────────────────────────────────────
	lines.append('## Detailed Results')
	lines.append('')
	for r in results:
		overall = r['overall_similarity_score']
		emb = r.get('embedding_similarity')
		bar = _make_bar(overall)
		pct = round(overall * 100)
		emoji = _similarity_emoji(overall)
		lines.append(f'### {r["test_scenario_name"]}')
		lines.append(f'**Persona:** `{r["persona_slug"]}`')
		lines.append('')
		llm_ceiling = r.get('llm_ceiling')
		emb_ceiling = r.get('embedding_ceiling')
		header = f'**LLM match:** `{bar}` {pct}% {emoji}'
		if llm_ceiling is not None:
			ceil_pct = round(llm_ceiling * 100)
			pct_of_ceil = round(overall / llm_ceiling * 100) if llm_ceiling > 0 else 0
			header += f' _(ceiling {ceil_pct}%, {pct_of_ceil}% of ceiling)_'
		if emb is not None:
			header += f'  ·  **Embedding sim:** {emb:.3f}'
			if emb_ceiling is not None:
				emb_ceil_pct = round(emb_ceiling * 100)
				emb_pct_of_ceil = round(emb / emb_ceiling * 100) if emb_ceiling > 0 else 0
				header += f' _(ceiling {emb_ceil_pct}%, {emb_pct_of_ceil}% of ceiling)_'
		lines.append(header)
		lines.append('')
		lines.append('| Trait Dimension | Murphy | Real Users | Delta |')
		lines.append('|----------------|--------|-----------|-------|')
		for dim in r['dimensions']:
			delta = dim['delta']
			sign = '+' if delta >= 0 else ''
			lines.append(f'| {dim["trait_name"]} | {dim["murphy_score"]:.1f} | {dim["persona_score"]:.1f} | {sign}{delta:.1f} |')
		lines.append('')
		rat = r.get('rationale')
		if rat:
			dims = r['dimensions']
			best = min(dims, key=lambda d: abs(d['delta']))
			worst = max(dims, key=lambda d: abs(d['delta']))
			lines.append(f'↳ 🟢 **Best match — {best["trait_name"]} ({_delta_str(best["delta"])}):** {rat["best_match"]}  ')
			lines.append(f'↳ 🔴 **Biggest gap — {worst["trait_name"]} ({_delta_str(worst["delta"])}):** {rat["biggest_gap"]}  ')
			if emb is not None:
				lines.append(f'↳ 📐 **Embedding ({emb:.3f}):** {rat["embedding"]}')
			lines.append('')
		else:
			reasoning = r.get('scoring_reasoning', '').strip()
			if reasoning:
				lines.append(f'**Scoring rationale:** {reasoning}')
				lines.append('')

	return '\n'.join(lines)


# ── Orchestrator ──────────────────────────────────────────────────────────────


async def run_similarity_eval(
	output_dir: Path,
	schema: TraitSchema,
	persona_result: PersonaResult,
	llm: BaseChatModel,
) -> SimilarityReport | None:
	"""Evaluate persona similarity for all discovered-persona tests in output_dir.

	Supports both single-run layout (evaluation_report.json at root) and
	batch-run layout (run_1/, run_2/, ... subdirs).

	Returns the SimilarityReport, or None if no matching tests were found.
	"""
	if (output_dir / 'evaluation_report.json').is_file():
		run_dirs: list[tuple[int, Path]] = [(1, output_dir)]
	else:
		run_dirs = discover_run_dirs(output_dir)
		if not run_dirs:
			logger.warning('No evaluation_report.json found in %s or its run_* subdirs', output_dir)
			return None

	similarity_results: list[PersonaSimilarityResult] = []

	for _run_idx, run_dir in run_dirs:
		report_path = run_dir / 'evaluation_report.json'
		if not report_path.is_file():
			logger.warning('Skipping %s: no evaluation_report.json', run_dir.name)
			continue

		report = EvaluationReport.model_validate_json(report_path.read_text(encoding='utf-8'))
		logger.info('Scoring similarity for %s (%d scenarios)', run_dir.name, len(report.results))

		for scenario_idx, result in enumerate(report.results, start=1):
			persona_slug = result.scenario.test_persona
			persona = lookup_persona_by_slug(persona_slug, persona_result)
			if persona is None:
				continue

			history_path = resolve_agent_history(run_dir, scenario_idx)
			if history_path is None:
				logger.warning('No agent history for scenario %d (%s)', scenario_idx, result.scenario.name)
				continue

			logger.info('  Evaluating "%s" (persona=%s)', result.scenario.name, persona_slug)
			try:
				similarity = await evaluate_similarity(
					persona=persona,
					schema=schema,
					history_path=history_path,
					scenario_name=result.scenario.name,
					scenario_steps=result.scenario.steps_description,
					llm=llm,
				)
				similarity_results.append(similarity)
			except Exception:
				logger.exception('Similarity eval failed for "%s"', result.scenario.name)

	if not similarity_results:
		return None

	from murphy.eval.similarity import generate_key_takeaways

	report = SimilarityReport(
		personas_file='',  # caller can set this
		output_dir=str(output_dir),
		timestamp=datetime.now().isoformat(timespec='seconds'),
		results=similarity_results,
	)
	report.key_takeaways = await generate_key_takeaways(report, llm)
	return report


def write_similarity_reports(report: SimilarityReport, output_dir: Path) -> tuple[Path, Path]:
	"""Write persona_similarity_report.json and .md to output_dir. Returns (json_path, md_path)."""
	json_path = output_dir / 'persona_similarity_report.json'
	json_path.write_text(report.model_dump_json(indent=2), encoding='utf-8')

	md_path = output_dir / 'persona_similarity_report.md'
	md_path.write_text(build_markdown_report(json.loads(report.model_dump_json())), encoding='utf-8')
	return json_path, md_path
