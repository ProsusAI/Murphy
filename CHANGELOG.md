# Changelog

All notable changes to Murphy will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.2.0] - 2026-06-02

### Added
- Lite mode (`--lite` CLI flag / `lite: true` in the REST API) for a faster, simpler run aimed at quick product feedback: Murphy builds a compact persona plan directly from the goal or available analysis, then runs a lighter browser-agent prompt
- Lite runs return a structured `LiteResult` per scenario with a 1–10 `grade` plus `flaws`, `improvements`, `fixes`, and `other_feedback`, summarised in a dedicated terminal output
- `lite` field on the `/generate-plan`, `/evaluate`, and `/execute` REST API request models
- `LITE_MODE.md` documentation describing the mode, what it skips, and how to run it

### Changed
- Lite mode skips LLM test generation, the Murphy judge, full JSON/Markdown report generation, and interactive review pauses
- Disabled the unused `write_file` tool in Murphy runs

## [1.1.0] - 2026-04-07

### Added
- Per-persona feature suggestions: each persona now produces 1–3 concrete, actionable feature/UX improvement suggestions grounded in what it observed during testing; suggestions are included in HTML reports, Markdown reports, and the executive summary
- Discovered personas carry a tailored `suggestion_instruction` generated during labeling, producing persona-grounded suggestions instead of generic ones
- New built-in UI-focused personas — `classic_ui` (readability, contrast, familiar patterns), `modern_ui` (current aesthetics, dark-mode, micro-interactions), and `layout_auditor_ui` (spacing consistency, alignment, grid adherence) — with dedicated trait schemas and judge evaluation criteria
- Smart screenshot selection for the judge: screenshots are now chosen by action signal strength (navigation, input, errors, final step) instead of simple recency, so the judge sees the most informative visual progression
- Dynamic personas generated from real user sessions and events via PostHog integration, replacing static persona definitions during evaluation runs
- `--discover-personas` CLI flag to run the persona discovery pipeline before test generation and save results to `{output_dir}/personas.json`
- `--personas [PATH]` CLI flag to reuse previously discovered personas (defaults to `{output_dir}/personas.json`)
- Token usage reporting: persona-discovery and Murphy-execution token totals are now tracked via `TokenCost`, logged at the end of a run, and included in the JSON/Markdown evaluation reports (new `TokenUsage` model on `EvaluationReport`)
- Configurable persona pipeline: trait schema and personas are discovered from real sessions, each session is scored against those traits, and the resulting trait vectors are clustered to produce personas; all stages are tunable via environment variables (`PERSONA_DISCOVERY_SESSIONS`, `PERSONA_SCORING_SESSIONS`, `PERSONA_MIN_EVENTS`, `PERSONA_NUM_CLUSTERS`, `PERSONA_MAX_CLUSTERS`, `PERSONA_LLM_CONCURRENCY`, `PERSONA_MONTHS_BACK`, `EMBEDDING_MODEL`, `EMBEDDING_DEVICE`, `POSTHOG_*`)
- Multi-provider LLM support: `--provider` and `--model` flags for OpenAI, Google Gemini, Anthropic Claude, Azure OpenAI, Mistral, Groq, DeepSeek, Cerebras, Ollama, OpenRouter, and Browser Use
- Separate `--judge-provider` and `--judge-model` flags for using a different model for verdicts
- `provider` field in REST API request models (`/analyze`, `/generate-plan`, `/execute`, `/evaluate`)
- `--open` flag to re-open the interactive web UI for a previously completed run without re-running any tests (no browser or LLM required)
- Step-by-step execution trace view in the UI (`View trace ->`) showing each agent step with goal, evaluation, actions, screenshots, memory, and reasoning
- Interactive agent path graph in the UI (`View graph ->`) visualising the full decision tree with colour-coded nodes (success/failure evaluations) and labelled action edges; click any node to inspect step details
- Missing signals reporting in judge verdicts (UX observations that don't affect the verdict)
- Agent history saved as JSON per test in `output/agent_history/`

### Fixed
- Discovered personas now use their pre-computed persona block in the execution prompt instead of regenerating it
- UTF-8 surrogate encoding error (`ModelProviderError: 'utf-8' codec can't encode character`)
- Occasional infinite verify loop during test execution
- Pages URL incorrect in reporting and trace visualization
- Angry user persona double-click test failing due to unidentified element ID
- Agent not reporting missing validation indicators
- Stale Murphy runs left behind after aborting previous runs are now cleaned up on startup

### Changed
- Feature suggestions are produced only by the agent (removed duplicate suggestion generation from the judge) and the report section is now collapsible
- Removed actions column from results main page in the UI

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
