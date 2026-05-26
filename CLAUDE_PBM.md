# Task: Add Navigation Model to light-murphy

## Context

You are working on the `light-murphy` branch of the Murphy repository.
Murphy is an AI-driven website evaluation tool that uses browser-use agents to test web applications.

This task adds a **NavigationModel** — a URL transition graph built offline from existing Murphy run logs.
The graph records which pages were visited and in what order across past runs.
Before each test, the most-travelled pages are injected into the agent's prompt as navigation hints
so it navigates faster instead of exploring from scratch.

**Workflow:**
1. Run `scripts/seed_navigation_model.py` once to build the model from existing logs (offline, no live runs needed)
2. Run light-murphy — it reads the pre-built model and injects hints into every agent prompt
3. The model also updates itself after each live run, so it improves over time

**This is a local + CI/CD speed optimisation only. Do not touch any persona, thesis, or embedding similarity code.**

---

## What to build

### 1. New file: `murphy/process/__init__.py`
Empty. Just creates the package.

---

### 2. New file: `murphy/process/model.py`

Create a `NavigationModel` class with the following interface:

```python
from __future__ import annotations
import json
from pathlib import Path
from urllib.parse import urlparse


class NavigationModel:
    """Builds and persists a URL transition graph from Murphy run history.

    The graph is stored as:
        { base_url: { from_url: { to_url: count } } }

    On each run, the visited URL sequence is added to the graph.
    Before each run, the most-travelled pages are returned as navigation hints.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, dict[str, dict[str, int]]] = {}
        if path.exists():
            self._load()

    def update(self, base_url: str, pages_visited: list[str]) -> None:
        """Add a URL sequence from a completed test run to the graph."""
        base = self._base(base_url)
        if base not in self._data:
            self._data[base] = {}
        graph = self._data[base]
        # Filter to only URLs that belong to this base domain
        relevant = [p for p in pages_visited if self._base(p) == base]
        for i in range(len(relevant) - 1):
            from_url = self._normalise(relevant[i])
            to_url = self._normalise(relevant[i + 1])
            if from_url not in graph:
                graph[from_url] = {}
            graph[from_url][to_url] = graph[from_url].get(to_url, 0) + 1

    def get_hints(self, base_url: str) -> list[str] | None:
        """Return an ordered list of the most-visited pages for this base URL.

        Returns None if there is not enough data yet (fewer than 3 runs worth of transitions).
        """
        base = self._base(base_url)
        graph = self._data.get(base)
        if not graph:
            return None
        # Count total visits per URL (sum of all incoming transition counts)
        visit_counts: dict[str, int] = {}
        for destinations in graph.values():
            for url, count in destinations.items():
                visit_counts[url] = visit_counts.get(url, 0) + count
        if sum(visit_counts.values()) < 3:
            return None
        # Return top 10 most-visited pages, sorted by frequency
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
        """Extract scheme + netloc (e.g. https://app.example.com)."""
        parsed = urlparse(url)
        return f'{parsed.scheme}://{parsed.netloc}'

    @staticmethod
    def _normalise(url: str) -> str:
        """Strip query params and fragments, keep path."""
        parsed = urlparse(url)
        return f'{parsed.scheme}://{parsed.netloc}{parsed.path}'.rstrip('/')
```

---

### 3. Modify `murphy/prompts.py`

Find `build_execution_prompt` (currently at line ~593). Add one optional parameter
`navigation_hints: list[str] | None = None` and inject it into the returned string.

**New signature:**
```python
def build_execution_prompt(
    global_task: str,
    scenario: TestScenario,
    start_url: str,
    available_file_paths: list[str] | None = None,
    navigation_hints: list[str] | None = None,
) -> str:
```

**Add this block to the returned string, immediately before the `IMPORTANT:` line:**
```python
f'{_render_navigation_hints(navigation_hints)}'
```

**Add this helper function** anywhere in `prompts.py` (before `build_execution_prompt`):
```python
def _render_navigation_hints(hints: list[str] | None) -> str:
    if not hints:
        return ''
    pages = '\n'.join(f'  - {h}' for h in hints)
    return (
        f'NAVIGATION GUIDE (from previous runs on this site):\n'
        f'These pages are most commonly visited when testing this site. '
        f'Use them as a guide — navigate through these if relevant to your task, '
        f'but adapt freely if the UI looks different or your persona would take a different path.\n'
        f'{pages}\n\n'
    )
```

---

### 4. Modify `murphy/core/execution.py`

#### 4a. Add `navigation_model` parameter to `_execute_single_test`

Current signature:
```python
async def _execute_single_test(
    url: str,
    scenario: TestScenario,
    llm: BaseChatModel,
    browser_session: BrowserSession,
    goal: str | None,
    fixture_paths: list[Path] | None,
    max_steps: int,
    index: int,
    total: int,
    judge_llm: BaseChatModel | None = None,
    discovered_personas: tuple['PersonaResult', 'TraitSchema'] | None = None,
    output_dir: Path | None = None,
) -> TestResult:
```

Add one parameter at the end:
```python
    navigation_model: 'NavigationModel | None' = None,
```

#### 4b. Inject hints before `agent.run()`

Find where `task_prompt` is built (the `build_execution_prompt(...)` call).
Change it to:
```python
nav_hints = navigation_model.get_hints(url) if navigation_model else None
task_prompt = build_execution_prompt(
    goal or f'Evaluate {url}',
    scenario,
    url,
    available_file_paths=file_paths_str or None,
    navigation_hints=nav_hints,
)
```

You will also need to add `navigation_hints=nav_hints` to the import of `build_execution_prompt`
if it is imported at the top of the file — just pass the new kwarg through.

#### 4c. Update the model after `unique_pages` is built

Find the block where `unique_pages` is deduplicated (after `seen_urls`). Immediately after it,
add:
```python
if navigation_model is not None:
    navigation_model.update(url, unique_pages)
    navigation_model.save()
```

#### 4d. Thread `navigation_model` through `execute_tests_with_session`

Add the same optional parameter to both `execute_tests` and `execute_tests_with_session`:
```python
navigation_model: 'NavigationModel | None' = None,
```

Pass it down to every `_execute_single_test(...)` call (there are two: one in the sequential
path and one inside `_run_one` in the parallel path).

Also pass it through in `execute_tests` when it calls `execute_tests_with_session`.

---

### 5. Modify `murphy/core/pipeline.py`

In `run_execute()`, create a `NavigationModel` instance and pass it into
`execute_tests_with_session`.

Add the import at the top of the file:
```python
from murphy.process.model import NavigationModel
```

Inside `run_execute()`, before the call to `execute_tests_with_session`, add:
```python
nav_model_path = (output_dir or Path('./murphy/output')) / 'navigation_model.json'
navigation_model = NavigationModel(nav_model_path)
```

Then pass `navigation_model=navigation_model` to `execute_tests_with_session`.

---

### 6. Modify `murphy/api/cli.py`

In `_async_main`, before the call to `execute_tests_with_session`, add:
```python
from murphy.process.model import NavigationModel
nav_model_path = output_dir / 'navigation_model.json'
navigation_model = NavigationModel(nav_model_path)
```

Pass `navigation_model=navigation_model` to `execute_tests_with_session`.

Do this in both places where `execute_tests_with_session` is called
(the normal path and the `--ui` path via `_execute_fn`).

---

## What NOT to change

- Do not touch `murphy/personas/` — persona discovery and embedding similarity are unrelated
- Do not touch `murphy/core/judge.py` — judgement logic is unrelated
- Do not touch `murphy/core/generation.py` — test generation is unrelated
- Do not touch `murphy/core/analysis.py` — feature analysis is unrelated
- Do not modify the `TestResult` model — `pages_visited` already exists, use it as-is
- Do not change any existing function signatures in a breaking way — all new parameters must have defaults (`None`)

---

## Behaviour expectations

- **First run on a new platform**: no model file exists → `NavigationModel` initialises with empty data → `get_hints()` returns `None` → hints block is omitted from prompt → Murphy behaves exactly as it does today. No errors.
- **After a few runs**: model file accumulates transitions → `get_hints()` returns a list → hints block appears in the prompt → Murphy navigates faster.
- **Model file location**: `{output_dir}/navigation_model.json`. For CI/CD this should be committed or cached between runs so it persists across PRs. That is out of scope for this implementation — just make sure the file is written correctly.
- **Thread safety**: parallel tests may both call `save()` concurrently. This is acceptable for now — last write wins and data loss is minimal. Do not add locking.

---

### 7. New file: `scripts/seed_navigation_model.py`

This script builds a `navigation_model.json` offline from existing Murphy run logs.
Run it once before testing light-murphy to pre-populate the model so hints appear on the very first live run.

```python
#!/usr/bin/env python3
"""Seed NavigationModel from existing Murphy agent_history logs.

Usage:
    python scripts/seed_navigation_model.py
    python scripts/seed_navigation_model.py --input output/eval_with_embeddings --output output/navigation_model.json
    python scripts/seed_navigation_model.py --all-runs   # include failed runs too
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Add repo root to path so murphy package is importable without install
sys.path.insert(0, str(Path(__file__).parent.parent))

from murphy.process.model import NavigationModel

# Matches UUIDs (8-4-4-4-12 hex) anywhere in a URL path segment
_UUID_RE = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
    re.IGNORECASE,
)


def normalise_uuid(url: str) -> str:
    """Replace all UUIDs in a URL with the literal placeholder ``{id}``."""
    return _UUID_RE.sub('{id}', url)


def extract_urls_from_history(history_path: Path) -> list[str]:
    """Return the ordered, deduplicated URL sequence from one agent_history file."""
    try:
        data = json.loads(history_path.read_text())
    except Exception:
        return []

    raw: list[str] = []
    for step in data.get('history', []):
        url = step.get('state', {}).get('url', '')
        if url and url.startswith('http'):
            raw.append(normalise_uuid(url))

    # Deduplicate consecutive duplicates (same page reloaded / minor fragment change)
    deduped: list[str] = []
    for url in raw:
        if not deduped or url != deduped[-1]:
            deduped.append(url)
    return deduped


def load_successful_scenario_names(report_path: Path) -> set[str] | None:
    """Return the set of *successful* scenario names from an evaluation_report.json.

    Returns None if the report cannot be parsed (caller should fall back to all runs).
    """
    try:
        data = json.loads(report_path.read_text())
        return {
            r['scenario']['name']
            for r in data.get('results', [])
            if r.get('success')
        }
    except Exception:
        return None


def seed(input_dir: Path, output_path: Path, all_runs: bool) -> None:
    model = NavigationModel(output_path)

    # Walk: input_dir/run_N/
    run_dirs = sorted(input_dir.glob('run_*/'))
    if not run_dirs:
        print(f'No run directories found under {input_dir}')
        sys.exit(1)

    total_sequences = 0

    for run_dir in run_dirs:
        agent_history_dir = run_dir / 'agent_history'
        if not agent_history_dir.exists():
            continue

        # Determine which test names (if any) succeeded
        report_path = run_dir / 'evaluation_report.json'
        successful_names: set[str] | None = None
        if not all_runs and report_path.exists():
            successful_names = load_successful_scenario_names(report_path)

        for history_file in sorted(agent_history_dir.glob('test_*.json')):
            # Skip failed runs unless --all-runs
            if successful_names is not None:
                # File names like test_01_some_scenario_name.json
                # Match by checking if any successful name appears in the file stem
                stem = history_file.stem  # e.g. "test_01_login_flow"
                matched = any(
                    name.lower().replace(' ', '_') in stem.lower()
                    for name in successful_names
                )
                if not matched:
                    continue

            urls = extract_urls_from_history(history_file)
            if len(urls) < 2:
                continue

            # base_url = scheme + netloc of the first URL in the sequence
            from urllib.parse import urlparse
            parsed = urlparse(urls[0])
            base_url = f'{parsed.scheme}://{parsed.netloc}'

            model.update(base_url, urls)
            total_sequences += 1

    model.save()
    print(f'Seeded {total_sequences} URL sequences into {output_path}')

    # Quick sanity check
    from urllib.parse import urlparse
    # find any base_url from data
    if model._data:
        sample_base = next(iter(model._data))
        hints = model.get_hints(sample_base)
        print(f'Hints for {sample_base}: {hints}')
    else:
        print('Warning: model is empty — no sequences were added.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--input',
        type=Path,
        default=Path('output/eval_with_embeddings/medium_goal_v3'),
        help='Root directory containing run_N sub-directories',
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('output/navigation_model.json'),
        help='Path to write navigation_model.json',
    )
    parser.add_argument(
        '--all-runs',
        action='store_true',
        help='Include failed runs (default: successful runs only, fallback to all if no report)',
    )
    args = parser.parse_args()
    seed(args.input, args.output, args.all_runs)


if __name__ == '__main__':
    main()
```

**How to run it** (from repo root, after implementing the NavigationModel class):

```bash
# Default: uses output/eval_with_embeddings, writes output/navigation_model.json
python scripts/seed_navigation_model.py

# Include failed runs too (recommended if pass rate was low)
python scripts/seed_navigation_model.py --all-runs

# Custom paths
python scripts/seed_navigation_model.py \
  --input /path/to/your/runs \
  --output output/navigation_model.json
```

Then run light-murphy pointing at the same output dir so it picks up the pre-seeded model:

```bash
# light-murphy reads {output_dir}/navigation_model.json automatically
uv run murphy --url https://your-site.com --output output/ --auto
```

On the first run it will print/inject the `NAVIGATION GUIDE` block from the seeded data.

---

## Validation

After implementing, verify manually:
1. `NavigationModel('nonexistent.json')` does not crash
2. After calling `update()` with a URL list and `save()`, the JSON file is written and readable
3. `get_hints()` returns `None` on an empty model
4. `get_hints()` returns a list after a few `update()` calls
5. Run the seeding script: `python scripts/seed_navigation_model.py --all-runs` — check it prints hints and writes `output/navigation_model.json`
6. Run light-murphy with `--url` and `--output output/` — confirm it reads the pre-seeded model and the first run includes the `NAVIGATION GUIDE` block in the agent prompt (add a temporary `print(task_prompt)` in `_execute_single_test` if needed)
7. Time two back-to-back runs: the seeded run should reach target pages in fewer steps than a cold run
8. Existing tests still pass: `uv run pytest tests/`
