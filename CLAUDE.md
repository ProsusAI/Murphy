# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Murphy is an AI-driven website evaluation system. It uses an LLM agent to browse a website and generate/execute test scenarios, then uses a separate LLM judge to assess pass/fail results. Built on a vendored fork of [browser-use](https://github.com/browser-use/browser-use).

## Commands

```bash
# Install dependencies
uv sync
uv run playwright install chromium

# Run Murphy
uv run murphy --url https://example.com
uv run murphy --url https://example.com --goal "test checkout flow"
uv run murphy --url https://example.com --feedback   # lightweight persona feedback mode
uv run murphy --url https://example.com --ui          # with web UI

# Start REST API server
murphy-api

# Tests
uv run pytest -vxs tests/murphy/          # unit tests
uv run pytest -vxs tests/browser_use/     # browser engine tests
uv run pytest -vxs tests/murphy/core/test_judge.py   # single test file

# Type checking and linting
uv run pyright
uv run ruff check --fix
uv run ruff format
uv run pre-commit run --all-files
```

## Architecture

### Three-Phase Pipeline

1. **Analysis** (`murphy/core/analysis.py`) — AI agent explores the website, discovers pages and features. Outputs `<site>_features.md`, then pauses for user review.
2. **Generation** (`murphy/core/generation.py`) — LLM reads features and generates `test_plan.yaml`, then pauses for user review.
3. **Execution & Judgment** (`murphy/core/execution.py`, `murphy/core/judge.py`) — AI agent executes each test scenario; a separate judge LLM scores pass/fail with trait-aware questions. Outputs `evaluation_report.json` and `evaluation_report.md`.

The CLI entry point (`murphy/api/cli.py`) orchestrates all three phases. For the REST API, `murphy/core/pipeline.py` handles orchestration.

### Key Modules

| Path | Purpose |
|------|---------|
| `murphy/models.py` | Core Pydantic data models: `TestPlan`, `TestScenario`, `TestResult`, `JudgeVerdict`, `TraitVector`, `PersonaFeedback` |
| `murphy/prompts.py` | All LLM prompt text |
| `murphy/llm.py` | Multi-provider LLM factory (`create_llm(model, provider)`) |
| `murphy/core/judge.py` | `TRAIT_JUDGE_QUESTIONS`, `TEST_TYPE_RULES`, `murphy_judge()` |
| `murphy/core/quality.py` | Test plan validation + retry logic |
| `murphy/core/summary.py` | Results classification + report building |
| `murphy/io/` | File I/O: features markdown, YAML test plans, JSON/markdown reports |
| `murphy/api/rest.py` | FastAPI REST server |
| `murphy/api/auth.py` | Authentication detection + manual login support |
| `browser_use/` | Vendored browser-use fork with Murphy-specific patches |

### Personas & Trait System

Murphy has 10 `TestPersona` types (happy path, confused novice, adversarial, edge case, explorer, impatient user, angry user, boomer UI, gen-z UI, whitespace police UI). Each persona has:
- A `TraitVector` (8 behavioral dimensions, each 0.0–1.0)
- A `TestType` (`ux`, `security`, `boundary`, or `design`)

The judge uses `TRAIT_JUDGE_QUESTIONS` to select evaluation questions based on which trait dimensions score highest for a given persona. This is the core mechanism that makes each persona evaluate the site differently.

### Feedback Mode

`--feedback` is a lightweight mode that skips the judge and full reporting pipeline. Instead, each persona rates the site 1–10 with comments. This is intended for fast iteration during development. Outputs `feedback.jsonl`. See `FEEDBACK_MODE.md` for details.

### Vendored browser-use

The `browser_use/` directory is a local fork of the upstream `browser-use` library. Patches and their rationale are documented in `docs/BROWSER_USE_MODIFICATIONS.md`. Do not upgrade this dependency via `uv` without reviewing that document.

## Code Conventions

- **Indentation:** tabs (not spaces)
- **Typing:** Python 3.11+ union syntax (`str | None`, `list[str]`)
- **Async:** `async/await` throughout — all I/O is async
- **Data models:** Pydantic v2
- **Logging methods:** prefixed with `_log_` for console output
- **Line length:** 130 characters (configured in `ruff`)
