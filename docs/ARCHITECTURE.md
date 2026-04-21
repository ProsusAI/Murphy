# Architecture

## Murphy File Organization (`murphy/`)

```
murphy/
├── __init__.py              # Package exports and version
├── __main__.py              # python -m murphy entry point
├── config.py                # Shared configuration constants
├── llm.py                   # Multi-provider LLM factory (OpenAI, Google, Anthropic, etc.)
├── models.py                # Pydantic models (TestPlan, TestResult, JudgeVerdict, etc.)
├── prompts.py               # All LLM prompt text
├── evaluate.py              # Backward-compatible re-exports
│
├── core/                    # Pipeline phases
│   ├── analysis.py          #   Phase 1: feature discovery via browser agent
│   ├── generation.py        #   Phase 2: test plan generation (feature-based + exploration-first)
│   ├── execution.py         #   Phase 3: test execution (sequential + parallel)
│   ├── judge.py             #   LLM judge for pass/fail verdicts
│   ├── quality.py           #   Test plan quality validation and retry logic
│   ├── summary.py           #   Results classification and report building
│   └── pipeline.py          #   Orchestrates phases for the REST API
│
├── io/                      # File I/O and reporting
│   ├── features_io.py       #   Read/write features markdown
│   ├── test_plan_io.py      #   Read/write YAML test plans
│   ├── report.py            #   Report generation orchestrator
│   ├── report_json.py       #   JSON report output
│   ├── report_markdown.py   #   Markdown report output
│   ├── report_helpers.py    #   Metrics, formatting, fix suggestions
│   ├── fixtures.py          #   Dummy upload files for test scenarios
│   └── regen_report.py      #   Regenerate markdown from existing JSON
│
├── api/                     # CLI, REST API, and web UI
│   ├── cli.py               #   CLI entry point and orchestration
│   ├── rest.py              #   FastAPI REST server
│   ├── server.py            #   Interactive web UI (aiohttp)
│   ├── auth.py              #   Auth detection and manual login flow
│   ├── jobs.py              #   Job dispatch, concurrency, webhooks
│   ├── request_models.py    #   API request/response schemas
│   └── templates.py         #   HTML rendering for web UI
│
└── browser/                 # Browser session helpers
    ├── actions.py           #   Custom agent actions (domain access, DOM refresh)
    ├── session_utils.py     #   Session stabilization and lifecycle
    └── patches.py           #   Monkey-patches for schema resolution
```

## REST API (`murphy-api`)

Murphy exposes a REST API via FastAPI for programmatic evaluation. Start with `murphy-api`.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/analyze` | Website analysis (feature discovery) |
| `POST` | `/generate-plan` | Test plan generation from analysis |
| `POST` | `/execute` | Test execution from plan |
| `POST` | `/evaluate` | Combined explore + plan generation |
| `GET` | `/jobs/{job_id}` | Job status polling (supports long-poll via `?poll=N`) |

### Execution modes

Every `POST` endpoint supports three modes:

1. **Synchronous** (default) — blocks until completion, returns `200` with result
2. **Async + webhook** (`webhook_url` set) — returns `202` with `job_id`, POSTs result to the webhook URL on completion
3. **Async + polling** (`"async": true`) — returns `202` with `job_id`, poll `/jobs/{job_id}` for result

Authentication is via `X-API-Key` header when `MURPHY_API_KEY` is set. Concurrent jobs are limited by `MURPHY_MAX_CONCURRENT_JOBS` (default: 2).

## Browser-Use Engine (`browser_use/`)

Browser-Use is vendored from [upstream](https://github.com/browser-use/browser-use) with local patches. It provides LLM-driven browser automation via CDP (Chrome DevTools Protocol).

Murphy uses these browser-use components:

| Component | Murphy usage |
|-----------|-------------|
| `Agent` | Runs analysis exploration, test execution, and goal-directed browsing |
| `BrowserSession` | Managed in `murphy/browser/session_utils.py` for lifecycle, tab control, and CDP recovery |
| `BrowserProfile` | Configured for headless mode, session pooling, and auth persistence |
| `Tools` | Extended with custom actions in `murphy/browser/actions.py` (domain access, DOM refresh) |
| `AgentHistoryList` | Consumed by the judge (`murphy/core/judge.py`) for evidence extraction |

For Murphy-specific patches to browser-use, see [BROWSER_USE_MODIFICATIONS.md](BROWSER_USE_MODIFICATIONS.md).
For browser-use's own architecture, see the [upstream repo](https://github.com/browser-use/browser-use).
