"""Tests for YAML test plan serialization roundtrips."""

import tempfile
from pathlib import Path

import yaml

from murphy.io.test_plan_io import load_test_plan, save_test_plan
from murphy.models import TestPlan, TestScenario


def _make_scenario(**overrides) -> TestScenario:
	defaults = dict(
		name='Login flow',
		description='Test the login flow end-to-end',
		priority='high',
		feature_category='authentication',
		target_feature='Login form',
		test_persona='happy_path',
		steps_description='1. Open login page\n2. Enter credentials\n3. Click submit',
		success_criteria='User is logged in and sees dashboard',
	)
	defaults.update(overrides)
	return TestScenario.model_validate(defaults)


def _make_plan(n: int = 3) -> TestPlan:
	scenarios = [_make_scenario(name=f'Test {i}', test_persona='happy_path' if i == 0 else 'adversarial') for i in range(n)]
	return TestPlan(scenarios=scenarios)


def test_save_and_load_roundtrip():
	"""save_test_plan then load_test_plan should produce identical data."""
	plan = _make_plan()
	with tempfile.TemporaryDirectory() as tmpdir:
		path = save_test_plan('https://example.com', plan, Path(tmpdir))
		assert path.exists()

		loaded_url, loaded_plan, _ = load_test_plan(path)
		assert loaded_url == 'https://example.com'
		assert len(loaded_plan.scenarios) == len(plan.scenarios)
		for orig, loaded in zip(plan.scenarios, loaded_plan.scenarios):
			assert orig.name == loaded.name
			assert orig.priority == loaded.priority
			assert orig.test_persona == loaded.test_persona
			assert orig.steps_description == loaded.steps_description
			assert orig.success_criteria == loaded.success_criteria


def test_save_creates_directory():
	with tempfile.TemporaryDirectory() as tmpdir:
		nested = Path(tmpdir) / 'deep' / 'nested'
		path = save_test_plan('https://example.com', _make_plan(1), nested)
		assert path.exists()


def test_save_includes_yaml_comments():
	with tempfile.TemporaryDirectory() as tmpdir:
		path = save_test_plan('https://example.com', _make_plan(1), Path(tmpdir))
		content = path.read_text()
		assert '# Murphy Test Plan' in content
		assert '# Edit freely' in content


def test_load_validates_scenario_fields():
	"""Loading a YAML with invalid scenario data should raise."""
	with tempfile.TemporaryDirectory() as tmpdir:
		path = Path(tmpdir) / 'test_plan.yaml'
		data = {
			'url': 'https://example.com',
			'scenarios': [{'name': 'Bad', 'priority': 'invalid_priority'}],
		}
		with open(path, 'w') as f:
			yaml.dump(data, f)

		try:
			load_test_plan(path)
			assert False, 'Should have raised'
		except Exception:
			pass  # Expected — pydantic validation rejects invalid priority


def test_load_rejects_missing_url():
	with tempfile.TemporaryDirectory() as tmpdir:
		path = Path(tmpdir) / 'test_plan.yaml'
		with open(path, 'w') as f:
			yaml.dump({'scenarios': []}, f)

		try:
			load_test_plan(path)
			assert False, 'Should have raised AssertionError'
		except AssertionError as e:
			assert 'url' in str(e)


def test_load_rejects_missing_scenarios():
	with tempfile.TemporaryDirectory() as tmpdir:
		path = Path(tmpdir) / 'test_plan.yaml'
		with open(path, 'w') as f:
			yaml.dump({'url': 'https://example.com'}, f)

		try:
			load_test_plan(path)
			assert False, 'Should have raised AssertionError'
		except AssertionError as e:
			assert 'scenarios' in str(e)


def test_empty_plan_roundtrip():
	plan = TestPlan(scenarios=[])
	with tempfile.TemporaryDirectory() as tmpdir:
		path = save_test_plan('https://example.com', plan, Path(tmpdir))
		loaded_url, loaded_plan, _ = load_test_plan(path)
		assert loaded_plan.scenarios == []
