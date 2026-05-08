"""Re-run persona labeling with the current LABEL_SYSTEM and save as personas_v2.json."""

import asyncio
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv

load_dotenv()

import numpy as np

from browser_use.llm import ChatOpenAI
from murphy.personas.persona_labeling import label_personas
from murphy.personas.pipeline_models import Persona
from murphy.personas.storage import load_personas


async def main(personas_path: Path, output_path: Path, model: str = 'gpt-4o') -> None:
	schema, old_result = load_personas(personas_path)
	llm = ChatOpenAI(model=model)

	dim_names = [d.name for d in schema.dimensions]
	k = len(old_result.personas)
	centroids = np.zeros((k, len(dim_names)))
	cluster_sizes: list[int] = []
	for p in sorted(old_result.personas, key=lambda x: x.persona_id):
		scores_dict = {d.trait_name: float(d.score) for d in p.centroid}
		for j, name in enumerate(dim_names):
			centroids[p.persona_id, j] = scores_dict.get(name, 3.0)
		cluster_sizes.append(p.size)

	print(f'Re-labeling {k} personas with updated LABEL_SYSTEM...')
	labels = await label_personas(llm, schema, centroids, cluster_sizes)
	label_map = {desc.persona_id: desc for desc in labels.personas}

	new_personas: list[Persona] = []
	for old_p in old_result.personas:
		desc = label_map.get(old_p.persona_id)
		if desc:
			description = desc.description.replace(f'The {desc.name}', f'The {old_p.name}', 1)
			new_p = old_p.model_copy(
				update={
					'description': description,
				}
			)
			print(f'  [{old_p.name}] updated')
		else:
			new_p = old_p
		new_personas.append(new_p)

	new_result = old_result.model_copy(update={'personas': new_personas})
	payload = {'schema': schema.model_dump(), 'result': new_result.model_dump()}
	output_path.write_text(json.dumps(payload, indent=2))
	print(f'\nSaved to {output_path}')


if __name__ == '__main__':
	personas_path = Path('output/similarity_run/personas.json')
	output_path = Path('output/similarity_run/personas_v2.json')
	asyncio.run(main(personas_path, output_path))
