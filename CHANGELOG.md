# Changelog

All notable changes to Murphy will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.1.0] - 2026-04-07

### Added
- Multi-provider LLM support: `--provider` and `--model` flags for OpenAI, Google Gemini, Anthropic Claude, Azure OpenAI, Mistral, Groq, DeepSeek, Cerebras, Ollama, OpenRouter, and Browser Use
- Separate `--judge-provider` and `--judge-model` flags for using a different model for verdicts
- `provider` field in REST API request models (`/analyze`, `/generate-plan`, `/execute`, `/evaluate`)
- `--open` flag to re-open the interactive web UI for a previously completed run without re-running any tests (no browser or LLM required)
- Step-by-step execution trace view in the UI (`View trace ->`) showing each agent step with goal, evaluation, actions, screenshots, memory, and reasoning
- Interactive agent path graph in the UI (`View graph ->`) visualising the full decision tree with colour-coded nodes (success/failure evaluations) and labelled action edges; click any node to inspect step details
- Missing signals reporting in judge verdicts (UX observations that don't affect the verdict)
- Agent history saved as JSON per test in `output/agent_history/`

### Fixed
- UTF-8 surrogate encoding error (`ModelProviderError: 'utf-8' codec can't encode character`)
- Occasional infinite verify loop during test execution
- Pages URL incorrect in reporting and trace visualization
- Angry user persona double-click test failing due to unidentified element ID
- Agent not reporting missing validation indicators

### Changed
- Removed actions column from results main page in the UI

## [2.0.0] - 2026-03-31

### Added
- Persona discovery and persona assignment, now used directly by Murphy during evaluation runs

## [1.0.0] - 2026-03-05

### Added
- Three-phase evaluation pipeline: feature discovery, test plan generation, and test execution
- AI browser agent powered by vendored browser-use engine
- Auth detection and manual login flow with persistent browser profiles
- Goal-directed exploration-first test generation (`--goal`)
- Multi-persona test scenarios (happy path, confused novice, adversarial, edge case, explorer, impatient user, frustrated user)
- Murphy judge for authoritative pass/fail verdicts with trait evaluations and feedback quality scoring
- Quality gate with automatic retry for generated test plans
- Parallel test execution with session pooling and auth cookie transfer (`--parallel`)
- Interactive web UI for test plan review and live execution (`--ui`)
- Structured reports: JSON + Markdown with executive summaries
- Resume from any phase via `--features` or `--plan` flags
- Human-in-the-loop pauses between phases for review/editing
- Docker support with multi-arch builds (amd64, arm64)
- REST API mode via `murphy-api` entry point
- Pre-commit hooks: ruff, pyright, codespell, gitleaks
- CI/CD: test matrix, lint, Docker image publishing to GHCR
