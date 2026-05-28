"""YAML serialization for Murphy test plans.

Saves test plans to a human-editable YAML file before execution,
and loads them back (with validation) for re-runs.
"""

from datetime import datetime, timezone
from pathlib import Path

import yaml

from murphy.models import TestPlan, TestScenario


def save_test_plan(url: str, test_plan: TestPlan, output_dir: Path, goal: str | None = None) -> Path:
	"""Save a test plan to YAML for human review/editing."""
	output_dir.mkdir(parents=True, exist_ok=True)
	path = output_dir / 'test_plan.yaml'

	data = {
		'url': url,
		'goal': goal,
		'generated_at': datetime.now(timezone.utc).isoformat(),
		'scenarios': [s.model_dump() for s in test_plan.scenarios],
	}

	with open(path, 'w') as f:
		f.write(f'# Murphy Test Plan — {url}\n')
		f.write(f'# Generated: {data["generated_at"]}\n')
		f.write('# Edit freely: add/remove/modify scenarios, then re-run with --plan flag.\n\n')
		yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

	return path


def load_test_plan(path: Path) -> tuple[str, TestPlan, str | None]:
	"""Load and validate a test plan from YAML. Returns (url, test_plan, goal)."""
	with open(path) as f:
		data = yaml.safe_load(f)

	assert isinstance(data, dict), f'Expected YAML dict, got {type(data)}'
	assert 'url' in data, "YAML missing 'url' field"
	assert 'scenarios' in data, "YAML missing 'scenarios' field"

	scenarios = [TestScenario.model_validate(s) for s in data['scenarios']]
	goal = data.get('goal')
	return data['url'], TestPlan(scenarios=scenarios), goal
