"""Persona persistence — save and load discovered personas as JSON."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from murphy.personas.pipeline_models import PersonaResult, TraitSchema

logger = logging.getLogger(__name__)

PERSONAS_FILENAME = 'personas.json'


def save_personas(schema: TraitSchema, result: PersonaResult, output_dir: Path) -> Path:
	"""Serialize discovered personas (schema + result) to ``output_dir/personas.json``."""
	output_dir.mkdir(parents=True, exist_ok=True)
	path = output_dir / PERSONAS_FILENAME
	payload = {
		'schema': schema.model_dump(),
		'result': result.model_dump(),
	}
	path.write_text(json.dumps(payload, indent=2))
	logger.info('Saved discovered personas to %s', path)
	return path


def load_personas(path: Path) -> tuple[TraitSchema, PersonaResult]:
	"""Deserialize discovered personas from a JSON file."""
	data = json.loads(path.read_text())
	schema = TraitSchema.model_validate(data['schema'])
	result = PersonaResult.model_validate(data['result'])
	logger.info('Loaded %d discovered personas from %s', len(result.personas), path)
	return schema, result
