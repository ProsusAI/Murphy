from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

from murphy.personas.bridge import slugify_persona_name
from murphy.personas.storage import load_personas


def slugify(value: str) -> str:
	return re.sub(r'[^a-z0-9]+', '_', value.lower()).strip('_')


def _trait_score(persona, keywords: tuple[str, ...], default: float = 3.0) -> float:
	matches = [
		score.score
		for score in persona.centroid
		if any(keyword in score.trait_name.lower() for keyword in keywords)
	]
	return max(matches, default=default)


def bind_personas(personas) -> list[str]:
	baseline = max(personas, key=lambda persona: _trait_score(persona, ('routine', 'habit')))
	allergy = max(personas, key=lambda persona: _trait_score(persona, ('allergen', 'safety')))
	remaining = [persona for persona in personas if persona.persona_id not in {baseline.persona_id, allergy.persona_id}]
	dietary = max(
		remaining,
		key=lambda persona: (
			_trait_score(persona, ('dietary', 'diet')),
			_trait_score(persona, ('efficiency', 'decisive')),
		),
	)
	remaining = [persona for persona in remaining if persona.persona_id != dietary.persona_id]
	no_supply = min(remaining, key=lambda persona: _trait_score(persona, ('friction', 'tolerance', 'patience')))
	return [
		slugify_persona_name(baseline.name),
		slugify_persona_name(allergy.name),
		slugify_persona_name(dietary.name),
		slugify_persona_name(no_supply.name),
	]


def main() -> None:
	parser = argparse.ArgumentParser(description='Create one Murphy plan for each workshop group.')
	parser.add_argument('--input', type=Path, default=Path(__file__).with_name('just_eat_validation_plan.yaml'))
	parser.add_argument('--output', type=Path, default=Path(__file__).with_name('plans'))
	parser.add_argument('--personas', type=Path, default=Path(__file__).parent / 'output' / 'personas.json')
	args = parser.parse_args()

	data = yaml.safe_load(args.input.read_text())
	_, persona_result = load_personas(args.personas)
	persona_slugs = bind_personas(persona_result.personas)
	if len(data['scenarios']) != len(persona_slugs):
		raise ValueError('The workshop plan must contain four scenarios.')
	args.output.mkdir(parents=True, exist_ok=True)
	for index, (scenario, persona_slug) in enumerate(zip(data['scenarios'], persona_slugs, strict=True), 1):
		scenario['test_persona'] = persona_slug
		path = args.output / f'{index:02d}_{slugify(scenario["name"])}.yaml'
		path.write_text(yaml.safe_dump({'url': data['url'], 'scenarios': [scenario]}, sort_keys=False))
		print(f'{path}: {persona_slug}')


if __name__ == '__main__':
	main()
