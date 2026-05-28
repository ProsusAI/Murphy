# Murphy — AI-Driven Website Evaluation

Murphy automatically evaluates websites by generating and executing test scenarios in a real browser with an AI judge. It supports two planning strategies — **broad feature discovery** (default) and **goal-directed exploration** (`--goal`) — followed by test execution. It produces structured evaluation reports with pass/fail results, failure categorization, and actionable summaries.

Built on top of [browser-use](https://github.com/browser-use/browser-use) (AI browser automation library).

## Prerequisites

- Python >= 3.11
- An LLM API key — default model is `gpt-5-mini` (OpenAI), but Murphy supports multiple providers (see [Model Providers](#model-providers))

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
Then set your key (at minimum one provider):
```
OPENAI_API_KEY=sk-...
```
See [Model Providers](#model-providers) for other providers.

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

# Run persona discovery first, then use those personas for testing
uv run murphy --url https://example.com --discover-personas

# Reuse previously discovered personas (defaults to murphy/output/personas.json)
uv run murphy --url https://example.com --personas
uv run murphy --url https://example.com --personas path/to/personas.json
```

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
| `personas.json` | Discovered personas (only generated with `--discover-personas`) |
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
| `--provider` | `openai` | LLM provider (see [Model Providers](#model-providers)) |
| `--model` | `gpt-5-mini` | LLM model name as it appears in the provider's docs |
| `--judge-provider` | *(same as `--provider`)* | LLM provider for judging verdicts |
| `--judge-model` | *(same as `--model`)* | LLM model for judging verdicts |
| `--output-dir` | `./murphy/output` | Output directory for all generated files |
| `--category` | | Site category hint (`ecommerce`, `saas`, `content`, `social`) |
| `--open` | `false` | Open the interactive UI for a previously completed run (no browser or LLM required); `--url` is not needed |
| `--ui` | `false` | Launch interactive web UI instead of terminal output |
| `--no-highlights` | `false` | Disable bounding boxes on interactive elements in the browser |
| `--max-steps` | `30` | Max agent steps per exploration/execution phase |
| `--parallel` | `3` | Number of tests to run concurrently |
| `--discover-personas` | `false` | Run persona discovery pipeline before test generation; saves `personas.json` to the output directory (requires `POSTHOG_API_KEY`, `POSTHOG_PROJECT_ID`, `POSTHOG_HOST`) |
| `--personas` | | Reuse previously discovered personas (defaults to `{output-dir}/personas.json`, or specify a path) |

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

For agent polling, `/jobs/{job_id}` accepts an optional `poll_attempt` query parameter as a no-op nonce, e.g. `/jobs/<job_id>?poll=30&poll_attempt=1`.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#rest-api-murphy-api) for full endpoint documentation.

---

## Model Providers

Murphy supports multiple LLM providers via [browser-use](https://github.com/browser-use/browser-use). Use `--provider` and `--model` to select any supported provider. Model names are passed exactly as they appear in the provider's documentation — no renaming needed.

```bash
# Default: OpenAI
uv run murphy --url https://example.com --model gpt-5-mini

# Google Gemini
uv run murphy --url https://example.com --provider google --model gemini-2.5-pro

# Anthropic Claude
uv run murphy --url https://example.com --provider anthropic --model claude-sonnet-4-20250514

# Azure OpenAI
uv run murphy --url https://example.com --provider azure --model gpt-4o

# Mistral
uv run murphy --url https://example.com --provider mistral --model mistral-large-latest

# Mix providers: cheap model for agent tasks, stronger model for judging
uv run murphy --url https://example.com \
  --provider google --model gemini-2.5-flash \
  --judge-provider openai --judge-model gpt-5-mini
```

Set the corresponding API key as an environment variable (see [Environment Variables](#environment-variables)).

| Provider | `--provider` value | Example `--model` |
|----------|-------------------|-------------------|
| OpenAI | `openai` (default) | `gpt-5-mini`, `gpt-4o`, `o3` |
| Google Gemini | `google` | `gemini-2.5-pro`, `gemini-2.5-flash` |
| Anthropic | `anthropic` | `claude-sonnet-4-20250514`, `claude-haiku-4-5-20251001` |
| Azure OpenAI | `azure` | `gpt-4o`, `gpt-4o-mini` |
| Mistral | `mistral` | `mistral-large-latest`, `mistral-small-latest` |
| Groq | `groq` | `llama3-70b-8192` |
| DeepSeek | `deepseek` | `deepseek-chat` |
| Cerebras | `cerebras` | `llama-3.3-70b` |
| Ollama | `ollama` | `llama3`, `mistral` |
| OpenRouter | `openrouter` | `meta-llama/llama-3-70b` |
| Browser Use | `bu` | `bu-latest` |

---

## Environment Variables

All variables are optional unless noted. See `.env.example` for a template.

### LLM Providers

Set the API key for whichever provider you use (at least one is required):

| Variable | Provider |
|----------|----------|
| `OPENAI_API_KEY` | OpenAI (default) |
| `GOOGLE_API_KEY` | Google Gemini |
| `ANTHROPIC_API_KEY` | Anthropic Claude |
| `AZURE_OPENAI_KEY` | Azure OpenAI (also needs `AZURE_OPENAI_ENDPOINT`) |
| `MISTRAL_API_KEY` | Mistral |
| `GROQ_API_KEY` | Groq |
| `CEREBRAS_API_KEY` | Cerebras |
| `OPENROUTER_API_KEY` | OpenRouter |
| `BROWSER_USE_API_KEY` | Browser Use |

### REST API

| Variable | Default | Description |
|----------|---------|-------------|
| `MURPHY_API_KEY` | *(none)* | API key for REST API authentication (open access if unset) |
| `MURPHY_API_HOST` | `0.0.0.0` | Host to bind the API server |
| `MURPHY_API_PORT` | `8000` | Port for the API server |
| `MURPHY_MAX_CONCURRENT_JOBS` | `2` | Maximum concurrent browser jobs |
| `MURPHY_REQUEST_TIMEOUT` | `1800` | HTTP keep-alive timeout (seconds) |
| `MURPHY_JOB_TIMEOUT_OVERRIDE` | *(none)* | Override all per-endpoint job timeouts (seconds) |

### Persona Discovery

Required when using `--discover-personas`. Murphy queries PostHog to pull user sessions and events, which it uses to derive realistic personas. Requires a PostHog instance with posthog-js >= 1.93.0 (the client-side `$elements_chain` string format).

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTHOG_API_KEY` | *(required)* | PostHog personal API key |
| `POSTHOG_PROJECT_ID` | *(required)* | PostHog project ID |
| `POSTHOG_HOST` | `https://eu.posthog.com` | PostHog instance URL (use `https://us.posthog.com` for the US cloud) |

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
