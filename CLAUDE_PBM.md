# Task: Add Goal-Keyed Navigation Model (PBM) to feat/lite-mode-PBM

## Context

You are working on the `feat/lite-mode-PBM` branch of the Murphy repository.
Murphy is an AI-driven website evaluation tool. This branch already has **lite mode** (`--lite` flag),
which skips test generation, judge, and reports in favour of a faster persona-based flow returning
`LiteResult` objects.

This task adds a **NavigationModel** — a URL transition graph built offline from existing Murphy run
logs. The graph records which pages were visited and in what order across past runs, keyed by
**goal** (e.g. "test checkout flow"). Before each test, the most-travelled pages for that goal are
injected into the agent prompt as navigation hints so the agent navigates faster instead of exploring
from scratch.

**Why goal-keying matters:** Without it, hints from "test checkout flow" runs pollute hints for
"test onboarding" runs. Hints should only come from past runs that had the same goal.

The model must work for **both** the normal execution path and the lite execution path.

**Workflow:**
1. Run `scripts/seed_navigation_model.py` once to build the model from existing logs (no live runs needed)
2. Run Murphy (`--lite` or normal) — it reads the pre-built model and injects hints into every agent prompt
3. The model updates itself after each live run, so it improves over time

---

## What to build

### 1. New file: `murphy/process/__init__.py`

Empty. Creates the package.

---

### 2. New file: `murphy/process/model.py`

```python
from __future__ import annotations
import json
from pathlib import Path
from urllib.parse import urlparse


class NavigationModel:
    """Builds and persists a goal-keyed URL transition graph from Murphy run history.

    Stored as: { base_url: { goal_key: { from_url: { to_url: count } } } }

    On each run, the visited URL sequence is added to the graph under the run's goal.
    Before each run, the most-travelled pages for that goal are returned as navigation hints.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, dict[str, dict[str, dict[str, int]]]] = {}
        if path.exists():
            self._load()

    def update(self, base_url: str, pages_visited: list[str], goal: str | None = None) -> None:
        """Add a URL sequence from a completed test run to the graph."""
        base = self._base(base_url)
        gkey = self._goal_key(goal)
        if base not in self._data:
            self._data[base] = {}
        if gkey not in self._data[base]:
            self._data[base][gkey] = {}
        graph = self._data[base][gkey]
        relevant = [p for p in pages_visited if self._base(p) == base]
        for i in range(len(relevant) - 1):
            from_url = self._normalise(relevant[i])
            to_url = self._normalise(relevant[i + 1])
            if from_url not in graph:
                graph[from_url] = {}
            graph[from_url][to_url] = graph[from_url].get(to_url, 0) + 1

    def get_hints(self, base_url: str, goal: str | None = None) -> list[str] | None:
        """Return an ordered list of the most-visited pages for this base URL and goal.

        Returns None if there is not enough data yet (fewer than 3 transitions).
        Falls back to goal_key='default' if no goal-specific data exists.
        """
        base = self._base(base_url)
        base_data = self._data.get(base)
        if not base_data:
            return None

        gkey = self._goal_key(goal)
        graph = base_data.get(gkey) or base_data.get('default')
        if not graph:
            return None

        visit_counts: dict[str, int] = {}
        for destinations in graph.values():
            for url, count in destinations.items():
                visit_counts[url] = visit_counts.get(url, 0) + count
        if sum(visit_counts.values()) < 3:
            return None
        sorted_pages = sorted(visit_counts, key=lambda u: visit_counts[u], reverse=True)
        return sorted_pages[:10]

    def save(self) -> None:
        """Persist the graph to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2))

    def _load(self) -> None:
        try:
            self._data = json.loads(self.path.read_text())
        except Exception:
            self._data = {}

    @staticmethod
    def _base(url: str) -> str:
        parsed = urlparse(url)
        return f'{parsed.scheme}://{parsed.netloc}'

    @staticmethod
    def _normalise(url: str) -> str:
        parsed = urlparse(url)
        return f'{parsed.scheme}://{parsed.netloc}{parsed.path}'.rstrip('/')

    @staticmethod
    def _goal_key(goal: str | None) -> str:
        if not goal:
            return 'default'
        return goal.strip().lower()
```

---

### 3. Modify `murphy/io/test_plan_io.py`

The goal must be persisted in the YAML so the seeding script can read it back from past runs.

#### 3a. Update `save_test_plan`

Current signature:
```python
def save_test_plan(url: str, test_plan: TestPlan, output_dir: Path) -> Path:
```

New signature:
```python
def save_test_plan(url: str, test_plan: TestPlan, output_dir: Path, goal: str | None = None) -> Path:
```

In the data dict, add `'goal': goal` after `'url'`:
```python
data = {
    'url': url,
    'goal': goal,
    'generated_at': datetime.now(timezone.utc).isoformat(),
    'scenarios': [s.model_dump() for s in test_plan.scenarios],
}
```

#### 3b. Update `load_test_plan`

Current return type: `tuple[str, TestPlan]`

New return type: `tuple[str, TestPlan, str | None]`

```python
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
```

#### 3c. Update all callers of `load_test_plan`

Search the codebase for `load_test_plan(` and update any unpacking from `url, plan = load_test_plan(...)` to `url, plan, goal = load_test_plan(...)`. The `goal` can be discarded with `_` in callers that don't use it.

---

### 4. Modify `murphy/prompts.py`

#### 4a. Add `_render_navigation_hints` helper

Add this function before `build_lite_prompt` (around line 541):

```python
def _render_navigation_hints(hints: list[str] | None) -> str:
    if not hints:
        return ''
    pages = '\n'.join(f'  - {h}' for h in hints)
    return (
        f'NAVIGATION GUIDE (from previous runs on this site with this goal):\n'
        f'These pages are most commonly visited when testing this goal on this site. '
        f'Use them as a guide — navigate through these if relevant to your task, '
        f'but adapt freely if the UI looks different or your persona would take a different path.\n'
        f'{pages}\n\n'
    )
```

#### 4b. Add `navigation_hints` to `build_lite_prompt`

Current signature (`murphy/prompts.py:541`):
```python
def build_lite_prompt(
    scenario: TestScenario,
    start_url: str,
    analysis: WebsiteAnalysis | None = None,
    discovered_personas: tuple[PersonaResult, TraitSchema] | None = None,
) -> str:
```

New signature:
```python
def build_lite_prompt(
    scenario: TestScenario,
    start_url: str,
    analysis: WebsiteAnalysis | None = None,
    discovered_personas: tuple[PersonaResult, TraitSchema] | None = None,
    navigation_hints: list[str] | None = None,
) -> str:
```

In the returned string, add `f'{_render_navigation_hints(navigation_hints)}'` immediately before the
`f'Rules:\n'` line (around line 576).

#### 4c. Add `navigation_hints` to `build_execution_prompt`

Current signature (`murphy/prompts.py:590`):
```python
def build_execution_prompt(
    global_task: str,
    scenario: TestScenario,
    start_url: str,
    available_file_paths: list[str] | None = None,
    discovered_personas: tuple[PersonaResult, TraitSchema] | None = None,
) -> str:
```

New signature:
```python
def build_execution_prompt(
    global_task: str,
    scenario: TestScenario,
    start_url: str,
    available_file_paths: list[str] | None = None,
    discovered_personas: tuple[PersonaResult, TraitSchema] | None = None,
    navigation_hints: list[str] | None = None,
) -> str:
```

In the returned string, add `f'{_render_navigation_hints(navigation_hints)}'` immediately before the
`f'IMPORTANT: You are already logged in...'` line (around line 613).

---

### 5. Modify `murphy/core/execution.py`

#### 5a. Add `navigation_model` to `_execute_single_test`

Current signature ends with:
```python
    use_lite: bool = False,
    analysis: WebsiteAnalysis | None = None,
) -> TestResult:
```

Add one parameter:
```python
    use_lite: bool = False,
    analysis: WebsiteAnalysis | None = None,
    navigation_model: 'NavigationModel | None' = None,
) -> TestResult:
```

#### 5b. Inject hints in the lite path

The lite path calls `build_lite_prompt(...)` (around line 141). Change it to:

```python
nav_hints = navigation_model.get_hints(url, goal) if navigation_model else None
task_prompt = build_lite_prompt(
    scenario,
    url,
    analysis=analysis,
    discovered_personas=discovered_personas,
    navigation_hints=nav_hints,
)
```

#### 5c. Update the model after the lite path builds `unique_pages`

The lite path builds `unique_pages` (around lines 176–180). Immediately after that block, add:

```python
if navigation_model is not None:
    navigation_model.update(url, unique_pages, goal)
    navigation_model.save()
```

#### 5d. Inject hints in the normal path

The normal path calls `build_execution_prompt(...)` (around line 200). Change it to:

```python
nav_hints = navigation_model.get_hints(url, goal) if navigation_model else None
task_prompt = build_execution_prompt(
    goal or f'Evaluate {url}',
    scenario,
    url,
    available_file_paths=file_paths_str or None,
    discovered_personas=discovered_personas,
    navigation_hints=nav_hints,
)
```

#### 5e. Update the model after the normal path builds `unique_pages`

The normal path builds `unique_pages` (around lines 270–274). Immediately after that block, add:

```python
if navigation_model is not None:
    navigation_model.update(url, unique_pages, goal)
    navigation_model.save()
```

#### 5f. Thread `navigation_model` through `execute_tests` and `execute_tests_with_session`

Both functions currently end their parameter lists with:
```python
    use_lite: bool = False,
    analysis: WebsiteAnalysis | None = None,
```

Add `navigation_model` to both:
```python
    use_lite: bool = False,
    analysis: WebsiteAnalysis | None = None,
    navigation_model: 'NavigationModel | None' = None,
```

In `execute_tests`, pass it through to `execute_tests_with_session`:
```python
navigation_model=navigation_model,
```

In `execute_tests_with_session`, pass it down to every `_execute_single_test(...)` call — there are
three: the sequential path call, the `_run_one` inner function call for parallel runs, and any
remaining standalone call. All need `navigation_model=navigation_model`.

---

### 6. Modify `murphy/core/pipeline.py`

Add import at the top:
```python
from murphy.process.model import NavigationModel
```

In `run_execute()`, add before the `execute_tests_with_session` call:
```python
nav_model_path = (output_dir or Path('./murphy/output')) / 'navigation_model.json'
navigation_model = NavigationModel(nav_model_path)
```

Then pass to `execute_tests_with_session`:
```python
navigation_model=navigation_model,
```

---

### 7. Modify `murphy/api/cli.py`

In `_async_main`, before each `execute_tests_with_session` call (there are two — the normal path
around line 366 and the `--ui` path around line 403), add:
```python
from murphy.process.model import NavigationModel
nav_model_path = output_dir / 'navigation_model.json'
navigation_model = NavigationModel(nav_model_path)
```

Pass `navigation_model=navigation_model` and `goal=args.goal` to both calls.

Note: `args.goal` is already threaded through as `goal=args.goal` in both calls. The NavigationModel
will use it as the goal key.

---

### 8. New file: `scripts/seed_navigation_model.py`

Builds a `navigation_model.json` offline from existing Murphy run logs. The script reads the
goal from `run_1/test_plan.yaml` (the `goal` field). If the YAML doesn't have a `goal` field
(older runs), it falls back to joining the `target_feature` values from the scenarios.

The `--input` flag accepts **one or more directories** so you can merge sequences from multiple
run folders into a single model:

```
python scripts/seed_navigation_model.py \
  --input output/medium_goal_v3 output/other_folder output/yet_another
```

```python
#!/usr/bin/env python3
"""Seed NavigationModel from existing Murphy agent_history logs.

Usage:
    python scripts/seed_navigation_model.py
    python scripts/seed_navigation_model.py --input output/my_runs --output output/navigation_model.json
    python scripts/seed_navigation_model.py --input output/run_a output/run_b --output output/navigation_model.json
    python scripts/seed_navigation_model.py --all-runs
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))

from murphy.process.model import NavigationModel

_UUID_RE = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
    re.IGNORECASE,
)


def normalise_uuid(url: str) -> str:
    return _UUID_RE.sub('{id}', url)


def extract_urls_from_history(history_path: Path) -> list[str]:
    try:
        data = json.loads(history_path.read_text())
    except Exception:
        return []
    raw: list[str] = []
    for step in data.get('history', []):
        url = step.get('state', {}).get('url', '')
        if url and url.startswith('http'):
            raw.append(normalise_uuid(url))
    deduped: list[str] = []
    for url in raw:
        if not deduped or url != deduped[-1]:
            deduped.append(url)
    return deduped


def extract_goal_from_test_plan(run_dir: Path) -> str | None:
    """Read goal from run_1/test_plan.yaml.

    Tries the 'goal' field first (present in runs after the goal-keyed PBM was added).
    Falls back to joining target_feature values from scenarios (older runs).
    """
    plan_path = run_dir / 'run_1' / 'test_plan.yaml'
    if not plan_path.exists():
        # Try the run_dir itself (in case the dir IS run_1)
        plan_path = run_dir / 'test_plan.yaml'
    if not plan_path.exists():
        return None
    try:
        import yaml
        data = yaml.safe_load(plan_path.read_text())
        if not isinstance(data, dict):
            return None
        # Prefer explicit goal field
        if data.get('goal'):
            return str(data['goal']).strip()
        # Fall back: join target_feature values
        features = [
            s.get('target_feature', '')
            for s in data.get('scenarios', [])
            if s.get('target_feature')
        ]
        if features:
            return ', '.join(dict.fromkeys(features))  # deduplicated, order-preserved
    except Exception:
        pass
    return None


def load_successful_scenario_names(report_path: Path) -> set[str] | None:
    try:
        data = json.loads(report_path.read_text())
        return {r['scenario']['name'] for r in data.get('results', []) if r.get('success')}
    except Exception:
        return None


def seed(input_dirs: list[Path], output_path: Path, all_runs: bool) -> None:
    model = NavigationModel(output_path)
    total_sequences = 0

    for input_dir in input_dirs:
        run_dirs = sorted(input_dir.glob('run_*/'))
        if not run_dirs:
            print(f'No run directories found under {input_dir}, skipping.')
            continue

        for run_dir in run_dirs:
            agent_history_dir = run_dir / 'agent_history'
            if not agent_history_dir.exists():
                continue
            report_path = run_dir / 'evaluation_report.json'
            successful_names: set[str] | None = None
            if not all_runs and report_path.exists():
                successful_names = load_successful_scenario_names(report_path)

            goal = extract_goal_from_test_plan(input_dir)

            for history_file in sorted(agent_history_dir.glob('test_*.json')):
                if successful_names is not None:
                    stem = history_file.stem
                    matched = any(
                        name.lower().replace(' ', '_') in stem.lower() for name in successful_names
                    )
                    if not matched:
                        continue
                urls = extract_urls_from_history(history_file)
                if len(urls) < 2:
                    continue
                parsed = urlparse(urls[0])
                base_url = f'{parsed.scheme}://{parsed.netloc}'
                model.update(base_url, urls, goal)
                total_sequences += 1

    model.save()
    print(f'Seeded {total_sequences} URL sequences into {output_path}')
    if model._data:
        sample_base = next(iter(model._data))
        sample_goal = next(iter(model._data[sample_base]))
        hints = model.get_hints(sample_base, sample_goal)
        print(f'Hints for {sample_base} / goal="{sample_goal}": {hints}')
    else:
        print('Warning: model is empty — no sequences were added.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--input', type=Path, nargs='+',
        default=[Path('output/eval_with_embeddings/medium_goal_v3')],
        help='One or more run directories to seed from',
    )
    parser.add_argument('--output', type=Path, default=Path('output/navigation_model.json'))
    parser.add_argument('--all-runs', action='store_true')
    args = parser.parse_args()
    seed(args.input, args.output, args.all_runs)


if __name__ == '__main__':
    main()
```

---

## What NOT to change

- `murphy/personas/` — persona discovery and embedding similarity are unrelated
- `murphy/core/judge.py` — judgement logic is unrelated
- `murphy/core/generation.py` — test generation is unrelated
- `murphy/core/analysis.py` — feature analysis is unrelated
- `TestResult` model — `pages_visited` already exists, use it as-is
- All new parameters must have defaults (`None`) — no breaking signature changes

---

## JSON structure

```json
{
  "https://example.com": {
    "test checkout flow": {
      "https://example.com/cart": {
        "https://example.com/checkout": 7,
        "https://example.com/shipping": 3
      }
    },
    "test onboarding": {
      "https://example.com": {
        "https://example.com/signup": 5
      }
    },
    "default": {
      "https://example.com": {
        "https://example.com/products": 2
      }
    }
  }
}
```

The goal key is the `args.goal` string lowercased and stripped. Runs without a goal use `"default"`.
`get_hints()` looks up the exact goal key first, falls back to `"default"` if not found.

---

## Behaviour expectations

- **First run / no model file**: `NavigationModel` initialises with empty data → `get_hints()` returns
  `None` → hints block omitted from prompt → Murphy behaves exactly as today. No errors.
- **After a few runs**: model accumulates transitions per goal → `get_hints()` returns a list → hints
  block appears in the prompt → Murphy navigates faster.
- **Goal mismatch**: if the current goal has no data, `get_hints()` falls back to `"default"` bucket,
  or returns `None` if that is also empty.
- **Lite mode**: hints are injected into `build_lite_prompt` the same way as the normal path.
- **Model file location**: `{output_dir}/navigation_model.json`.
- **Thread safety**: parallel tests may call `save()` concurrently — last write wins. No locking needed.

---

## Validation

1. `NavigationModel('nonexistent.json')` does not crash
2. After `update(base, pages, goal)` + `save()`, JSON file is written and readable with goal key
3. `get_hints(base, goal)` returns `None` on an empty model
4. `get_hints(base, goal)` returns a list after a few `update()` calls with the same goal
5. `get_hints(base, 'unknown goal')` falls back to `"default"` bucket if it exists
6. `python scripts/seed_navigation_model.py --all-runs` prints `Hints for ... / goal="..."` and writes JSON
7. Run `uv run murphy --url https://your-site.com --goal "test checkout" --output output/` — check that
   `NAVIGATION GUIDE` block appears in the agent prompt
8. Run same with `--lite` — same check for lite mode
9. Existing tests still pass: `uv run pytest tests/`
