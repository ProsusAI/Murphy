# Murphy — AI-Driven Website Evaluation

Murphy automatically evaluates websites by generating and executing test scenarios in a real browser with an AI judge. It supports two planning strategies — **broad feature discovery** (default) and **goal-directed exploration** (`--goal`) — followed by test execution. It produces structured evaluation reports with pass/fail results, failure categorization, and actionable summaries.

Built on top of [browser-use](https://github.com/browser-use/browser-use) (AI browser automation library).

## Prerequisites

- Python >= 3.11
- An OpenAI API key (`OPENAI_API_KEY`) — default model is `gpt-5-mini`

## Which setup should I use?

| | **Local (uv)** | **Docker** |
|---|---|---|
| **Best for** | Sites requiring login (`--auth`), development | Public sites, reproducible environments |
| **Auth support** | Full — opens a visible browser for manual login | No — browser runs headless with no visible window, so `--auth` cannot work |
| **Review pauses** | Works — you edit files on disk and press Enter | Works — files are on a mounted volume, press Enter in the same terminal |
| **Requires** | Python >= 3.11, uv, Chromium | Docker |

**Rule of thumb:** use **local** if the site requires authentication. Both setups are interactive — Murphy pauses for you to review and edit the generated test plan (and features, when not using `--goal`) before continuing.

## Setup (local)

**1. Install [uv](https://docs.astral.sh/uv/):**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**2. Clone and install dependencies:**
```bash
git clone https://github.com/ProsusAI/Murphy.git
cd Murphy
uv sync
```

**3. Install Chromium:**
```bash
uv run playwright install chromium
```

**4. Create `.env` with your API key:**
```bash
cp .env.example .env
```
Then set your key:
```
OPENAI_API_KEY=sk-...
```

## Setup (Docker)

> **Note:** Docker runs the browser in headless mode. The `--auth` flag (manual login) will not work — use the local setup above if your site requires login.

**1. Build the image:**
```bash
docker build -f docker/Dockerfile . -t murphy --no-cache
```

**2. Create `.env` with your API key** (same as above).

**3. Run via the helper script:**
```bash
./run.sh --url https://example.com [options]
```

The script mounts `murphy/` and `.env` into the container and runs `python -m murphy` with your arguments.

## Usage

All examples below use `uv run murphy`. If running via Docker, replace with `./run.sh`.

```bash
# Full run: auto-detect auth -> analyze site -> generate tests -> execute
uv run murphy --url https://example.com

# Goal-directed: explores with focus, skips feature discovery, generates plan directly
uv run murphy --url https://example.com --goal "test the checkout flow"

# Site requires login — opens browser for manual auth first (local only, not Docker)
uv run murphy --url https://example.com --auth

# Public site, skip auth detection entirely
uv run murphy --url https://example.com --no-auth

# Resume from previously generated/edited files
uv run murphy --url https://example.com --features murphy/output/example_com_features.md
uv run murphy --url https://example.com --plan murphy/output/test_plan.yaml

# Open the interactive UI for a previously completed run (no browser or LLM required)
uv run murphy --open
uv run murphy --open --output-dir ./murphy/output/my-run
```

### Running experiments

A frozen plan lives at `murphy/output/eval_test_1.yaml` (copy of a generated `test_plan.yaml`). Run Murphy **10 times** with isolated outputs under `murphy/output/run_1/` … `run_10/`. Each folder gets a **snapshot** of the plan (`eval_test_1.yaml`), plus `agent_history/`, `screenshots/`, `evaluation_report.json`, and `evaluation_report.md`.

```bash
uv run python scripts/run_eval_batches.py
# Custom count / pass extra murphy flags after --
uv run python scripts/run_eval_batches.py --runs 10 -- --no-auth --parallel 2
```

Use `--continue-on-fail` to run all batches even when one exits non-zero.

**Export a flat eval dataset** from all `run_*/evaluation_report.json` files (single JSONL/CSV — one line per **run × scenario**):

```bash
uv run python -m murphy.io.prepare_logs --output-root murphy/output --eval-id eval_test_1
```

Default output: `murphy/output/eval_run_rows.jsonl`. Each row includes **identity** (`eval_id`, `run_id`, `scenario_index`, …), **scenario definition** (`success_criteria`, `steps_description`, `test_persona`, …), **execution** (`step_count`, `duration_s`, `pages_visited`, `form_fills`, `errors`), **agent self-assessment** (from the structured `done` action: `agent_self_verdict`, `agent_reason`, …), **judge verdict** (`judge_verdict`, `judge_reasoning`, `failure_category`, `feedback_quality`, `missing_signals`), **derived** `verdict_agreement`, and **provenance** (`report_timestamp`, `agent_history_path`, `screenshot_paths` relative to the output root). Run-level rollups (`pass_rate`, etc.) are computed downstream from this file.

Use `--format csv`, `--out <path>`, `--max-narrative-chars` (truncate long judge/agent text; `0` clears those narrative fields), `--redact-term` (repeatable) and `--redact-terms-file` to mask emails (`[REDACTED_EMAIL]`) and custom terms (`[REDACTED_ORG]`). Murphy may emit `feedback_type` values beyond a minimal enum (e.g. `none`, `modal_dialog`, `error_page`); they are passed through as stored.

**Analysis tips:** group by `scenario_index` or `scenario_name` across runs for **per-scenario flakiness**; group by `test_persona` for **persona-level** metrics; aggregate by `run_id` for **batch-level** drift.

https://github.com/user-attachments/assets/7fbc441d-e02f-4321-aba7-3aec0cb17163


## How It Works

Murphy supports two planning strategies, both followed by the same execution phase:

**Strategy A — Feature discovery (default, no `--goal`):**
An AI agent navigates the site, discovers pages, and catalogs features. Murphy saves an editable `<site>_features.md` and pauses for review. Then an LLM reads the features and produces test scenarios, saving an editable `test_plan.yaml` with another pause for review.

**Strategy B — Goal-directed exploration (`--goal`):**
An AI agent explores the site with the given goal in mind, then synthesizes a test plan directly from the exploration. Murphy saves an editable `test_plan.yaml` and pauses for review. No `features.md` is generated — the exploration replaces broad feature discovery.

**Execution (both strategies):** An AI agent runs each test scenario in a real browser, and a separate judge LLM evaluates pass/fail. Saves `evaluation_report.json` and `evaluation_report.md`.

You can resume from any point by passing `--features` or `--plan` with a previously generated (and optionally edited) file.

## Output

Default output directory: `./murphy/output/`

| File | Description |
|------|-------------|
| `<site>_features.md` | Discovered features, pages, and user flows (editable; only generated without `--goal`) |
| `test_plan.yaml` | Generated test scenarios with steps and success criteria (editable) |
| `evaluation_report.json` | Full structured results (machine-readable) |
| `evaluation_report.md` | Human-readable summary with pass/fail per test |

## Example Output

After a run, `evaluation_report.md` looks like this (abbreviated):

```markdown
# Evaluation Report: Example Store

> **An e-commerce site with product listings, search, and checkout.**

| | |
|---|---|
| URL | https://example.com |
| Category | ecommerce |
| Date | 2026-03-07 |

## Results at a Glance

**6/8 tests passed (75.0%)**
- Website Issues: 1
- Test Limitations: 1

| Test | Persona | Result | Category | Duration |
|------|---------|--------|----------|----------|
| Search for existing product | Happy Path | Passed | | 42s |
| Submit empty checkout form | Edge Case | Passed | | 38s |
| XSS payload in search bar | Adversarial | Passed | | 35s |
| Add item without logging in | Confused Novice | Failed | Website Issue | 51s |
| Rapid checkout button clicks | Impatient User | Passed | | 29s |
| ...  | ... | ... | ... | ... |

## Executive Summary

The site handles core flows well but lacks feedback for unauthenticated
actions — adding an item to cart silently fails with no error message.

### Key Findings
1. No feedback when guest user attempts cart actions (Website Issue)
2. Search handles XSS payloads correctly via silent sanitization
3. Empty form submission shows clear inline validation errors

### Recommended Actions
1. Show a login prompt or error when unauthenticated users attempt cart actions
2. Add rate-limiting feedback for rapid repeated submissions
3. Improve loading indicators on slow network requests
```

The full JSON report (`evaluation_report.json`) contains structured results, action traces, screenshots, trait evaluations, and feedback quality scores.

## All CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--url` | *(required)* | Target URL to evaluate |
| `--goal` | | Free-text goal to bias test generation (e.g. `"test the checkout flow"`) |
| `--auth` | `false` | Skip auto-detection, go straight to manual login wait |
| `--no-auth` | `false` | Skip auth detection entirely, treat site as public |
| `--features` | | Path to existing features markdown (skips feature discovery) |
| `--plan` | | Path to existing YAML test plan (skips planning, goes straight to execution) |
| `--max-tests` | `8` | Maximum number of test scenarios to generate |
| `--model` | `gpt-5-mini` | LLM model for agent tasks |
| `--judge-model` | `gpt-5-mini` | LLM model for judging verdicts |
| `--output-dir` | `./murphy/output` | Output directory for all generated files |
| `--category` | | Site category hint (`ecommerce`, `saas`, `content`, `social`) |
| `--open` | `false` | Open the interactive UI for a previously completed run (no browser or LLM required); `--url` is not needed |
| `--ui` | `false` | Launch interactive web UI instead of terminal output |
| `--no-highlights` | `false` | Disable bounding boxes on interactive elements in the browser |
| `--max-steps` | `30` | Max agent steps per exploration/execution phase |
| `--parallel` | `3` | Number of tests to run concurrently |

## Interactive UI

Launch the web UI during a run with:
```bash
murphy --url https://example.com --ui
```

Re-open the UI for a previously completed run (no browser or LLM required):
```bash
murphy --open
murphy --open --output-dir ./murphy/output/my-run
```

The UI lets you review the generated test plan, run all tests with a live progress bar, and view detailed results with pass/fail verdicts, failure analysis, step-by-step execution traces, and an interactive agent path graph.

---

## REST API

Murphy exposes a REST API for programmatic evaluation. Start the server with:

```bash
murphy-api
```

Endpoints: `/analyze`, `/generate-plan`, `/execute`, `/evaluate`, `/jobs/{job_id}`. Each POST endpoint supports synchronous, async+webhook, and async+polling modes. Auth via `X-API-Key` header.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#rest-api-murphy-api) for full endpoint documentation.

---

## Environment Variables

All variables are optional unless noted. See `.env.example` for a template.

### LLM Provider

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI API key (required) |

### REST API

| Variable | Default | Description |
|----------|---------|-------------|
| `MURPHY_API_KEY` | *(none)* | API key for REST API authentication (open access if unset) |
| `MURPHY_API_HOST` | `0.0.0.0` | Host to bind the API server |
| `MURPHY_API_PORT` | `8000` | Port for the API server |
| `MURPHY_MAX_CONCURRENT_JOBS` | `2` | Maximum concurrent browser jobs |
| `MURPHY_REQUEST_TIMEOUT` | `1800` | HTTP keep-alive timeout (seconds) |
| `MURPHY_JOB_TIMEOUT_OVERRIDE` | *(none)* | Override all per-endpoint job timeouts (seconds) |

### Browser

| Variable | Default | Description |
|----------|---------|-------------|
| `BROWSER_USE_EXECUTABLE_PATH` | *(auto)* | Path to Chrome/Chromium executable |
| `BROWSER_USE_HEADLESS` | `true` | Run browser in headless mode |
| `BROWSER_USE_LOGGING_LEVEL` | `info` | Logging level |

---

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for details on the codebase structure, including the Murphy evaluation pipeline and the vendored browser-use engine.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development workflow, testing, code style, and contribution guidelines.
