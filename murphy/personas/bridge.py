"""Thin adapter between discovered personas and the Murphy test pipeline.

Slugifies names, formats distribution/execution/judge blocks from the
enriched ``Persona`` fields produced during the labeling step.
"""

from __future__ import annotations

import re

from murphy.personas.pipeline_models import Persona, PersonaResult, TraitSchema


def slugify_persona_name(name: str) -> str:
	"""Convert a human-readable persona name to a slug, e.g. "Power Explorer" -> "power_explorer"."""
	slug = name.lower().strip()
	slug = re.sub(r'[^a-z0-9]+', '_', slug)
	return slug.strip('_')


def get_discovered_persona_names(result: PersonaResult) -> list[str]:
	"""Return slugified persona names from a discovery result."""
	return [slugify_persona_name(p.name) for p in result.personas]


def lookup_persona_by_slug(slug: str, result: PersonaResult) -> Persona | None:
	"""Reverse-lookup: find the Persona whose slugified name matches *slug*."""
	for p in result.personas:
		if slugify_persona_name(p.name) == slug:
			return p
	return None


def build_discovered_persona_distribution_text(result: PersonaResult, schema: TraitSchema) -> str:
	"""Format the MANDATORY PERSONA DISTRIBUTION block for test generation prompts."""
	total_sessions = sum(p.size for p in result.personas)
	dim_names = [d.name for d in schema.dimensions]
	lines: list[str] = []
	for persona in sorted(result.personas, key=lambda p: p.size, reverse=True):
		slug = slugify_persona_name(persona.name)
		pct = round(persona.size / total_sessions * 100) if total_sessions else 0
		centroid_dict = {s.trait_name: s.score for s in persona.centroid}
		trait_summary = ', '.join(f'{d}={centroid_dict.get(d, "?")}' for d in dim_names)
		orientation = persona.test_orientation or 'ux'
		lines.append(
			f'- {slug} (~{pct}%, {orientation}): {persona.description} [Traits (1–5 scale: 1–2.5=low, 2.5–4=medium, 4–5=high): {trait_summary}]'
		)
	return '\n'.join(lines)


def build_discovered_success_criteria_block(result: PersonaResult) -> str:
	"""Format the PERSONA-SPECIFIC SUCCESS CRITERIA GUIDANCE block."""
	lines: list[str] = []
	for persona in result.personas:
		slug = slugify_persona_name(persona.name)
		orientation = persona.test_orientation or 'ux'
		label = 'UX' if orientation == 'ux' else 'Resilience'
		guidance = persona.success_criteria_guidance or 'No specific guidance.'
		lines.append(f'- {slug} ({label}): "{guidance}"')
	return '\n'.join(lines)


def render_discovered_persona_for_execution(
	persona_slug: str,
	result: PersonaResult,
	schema: TraitSchema,
) -> str:
	"""Format the PERSONA BEHAVIOR block for execution prompts."""
	persona = lookup_persona_by_slug(persona_slug, result)
	if persona is None:
		return f'Your persona: **{persona_slug}** (unknown discovered persona)'

	dim_names = [d.name for d in schema.dimensions]
	centroid_dict = {s.trait_name: s.score for s in persona.centroid}

	lines = [f'Your persona: **{persona_slug}**']
	lines.append(f'Character: {persona.description}')
	orientation = persona.test_orientation or 'ux'
	lines.append(f'Test type: {orientation}')
	lines.append('Trait profile (1–5 scale: 1–2.5=low, 2.5–4=medium, 4–5=high):')
	for d in dim_names:
		lines.append(f'  {d}: {centroid_dict.get(d, "?")}')
	for hint in persona.execution_hints:
		lines.append(f'→ {hint}')
	return '\n'.join(lines)


def build_discovered_judge_context(
	persona_slug: str,
	result: PersonaResult,
	schema: TraitSchema,
) -> str:
	"""Format judge evaluation context for a discovered persona."""
	persona = lookup_persona_by_slug(persona_slug, result)
	if persona is None:
		return f'## Persona: {persona_slug}\n(Unknown discovered persona — no trait context available)\n'

	dim_names = [d.name for d in schema.dimensions]
	centroid_dict = {s.trait_name: s.score for s in persona.centroid}
	orientation = persona.test_orientation or 'ux'

	lines: list[str] = []
	lines.append(f'## Persona: {persona_slug}')
	lines.append(f'## Test type: {orientation}')
	if orientation == 'ux':
		lines.append(
			'## Test type rule: Silent handling with no visible feedback is a FAIL. The user must understand what happened.'
		)
	else:
		lines.append(
			'## Test type rule: Silent sanitization is CORRECT behavior. Only fail on crash, data leak, or code execution.'
		)
	lines.append('')
	lines.append('## Trait profile (discovered dimensions, 1–5 scale: 1–2.5=low, 2.5–4=medium, 4–5=high):')
	for d in dim_names:
		lines.append(f'- **{d}**: {centroid_dict.get(d, "?")}')
	lines.append('')
	lines.append('## Persona-specific evaluation questions:')
	lines.append('')
	for q in persona.judge_questions:
		lines.append(f'- {q}')
	lines.append('')
	return '\n'.join(lines)
