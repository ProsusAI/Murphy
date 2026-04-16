# Persona Feedback Mode (`--feedback`)

Feedback mode is a lightweight alternative to Murphy's full evaluation pipeline. Instead of running each test through a judge LLM for a pass/fail verdict and generating a structured report, each persona browses the site and returns a **grade (1–10)** with **qualitative comments**. This is designed for rapid, iterative UX feedback — especially during development — without the overhead of the full judge + report pipeline.

## How it works

1. **Planning** proceeds as normal — Murphy discovers features (or uses `--goal` / `--plan`) and generates a test plan. When `--feedback` is active the plan uses concise scenarios (1–3 intent-based steps, single-sentence success criteria).
2. **Execution** swaps the standard execution prompt for a lean persona feedback prompt. Each persona agent browses the site following its scenario steps and produces a single `PersonaFeedback` object (`grade` + `comments`) instead of a full `ScenarioExecutionVerdict`.
3. **No judge** — the murphy judge LLM call is skipped entirely. The persona's self-reported grade is used directly (`grade >= 5` = pass).
4. **Feedback is appended** to a JSONL file after each persona finishes.
5. **No report generation** — the standard `evaluation_report.json` / `evaluation_report.md` are not written. A concise per-persona summary is printed to stdout instead.

## Running it

```bash
# Feedback mode with default settings (discovers features, generates plan, runs all personas)
uv run murphy --url https://example.com --feedback

# Combine with --goal for targeted feedback
uv run murphy --url "https://autopmf-weather.vercel.app/" --goal "check the weather forecast" --feedback

# Resume from an existing plan
uv run murphy --url https://example.com --plan murphy/output/test_plan.yaml --feedback
```

All other flags (`--provider`, `--model`, `--parallel`, `--max-tests`, `--auth`, etc.) work as normal.

## Personas

Each test scenario is assigned one of ten personas. Personas are grouped into three test types that control how the grade is interpreted:

| Persona | Test Type | Description |
|---------|-----------|-------------|
| `happy_path` | ux | Skilled user completing the expected flow directly |
| `confused_novice` | ux | First-time user who misclicks, submits empty forms, needs visible guidance |
| `adversarial` | security | Probes for XSS, SQL injection, hidden endpoints |
| `edge_case` | boundary | Empty inputs, special characters, max-length strings |
| `explorer` | ux | Unexpected navigation, unusual feature combinations |
| `impatient_user` | ux | Rapid clicks, skipped steps, no patience for loading |
| `angry_user` | security | Rage-clicks, force-navigation, rapid form submissions |
| `boomer_ui` | design | Evaluates readability, font size, label clarity, contrast, familiar patterns |
| `genz_ui` | design | Evaluates visual modernity, dark mode, micro-interactions, visual personality |
| `whitespace_police_ui` | design | Evaluates spacing consistency, margins, padding, vertical rhythm |

### Test types

The test type determines pass/fail semantics:

- **ux** — silent handling with no visible feedback is a fail; the user must understand what happened.
- **security** — silent sanitization is correct behavior; only crashes, data leaks, or code execution fail.
- **boundary** — graceful degradation (even silent) is a pass; only unhandled exceptions or corrupted state fail.
- **design** — evaluates visual design quality; functional correctness is not in scope.

### Trait vectors

Each persona has a trait vector with eight dimensions that shape both the agent's browsing behavior and its grading criteria:

| Dimension | Levels | What it controls |
|-----------|--------|------------------|
| `technical_literacy` | low / medium / high | Whether the persona understands UI conventions |
| `patience` | low / medium / high | How long the persona waits before treating silence as broken |
| `intent` | benign / exploratory / adversarial | Whether the persona is cooperative, curious, or attacking |
| `exploration` | low / medium / high | Whether the persona sticks to the expected path or wanders |
| `reading_comprehension` | low / medium / high | Whether the persona reads body text or only scans bold labels and icons |
| `visual_density_preference` | low / medium / high | Whether the persona prefers spacious or information-dense layouts |
| `aesthetic_era` | classic / modern / experimental | What visual style the persona expects |
| `layout_strictness` | low / medium / high | How precisely the persona evaluates spacing and alignment |

The full trait definitions are in `murphy/models.py` under `PERSONA_REGISTRY`.

## Output

### Feedback file

Feedback is appended as newline-delimited JSON to:

```
murphy/output/output_feedback/feedback.jsonl
```

Each line is a JSON object:

```json
{
  "timestamp": "2026-04-14T15:33:45.512640+00:00",
  "sessionId": "561fbde78350c9c3",
  "persona": "happy_path",
  "grade": 5,
  "comments": "Saving an article is discoverable but the app did not provide any visible confirmation...",
  "processed": false,
  "processedAt": null
}
```

| Field | Description |
|-------|-------------|
| `timestamp` | ISO-8601 UTC timestamp |
| `sessionId` | Deterministic hash of the persona's trait vector + test type — stable across runs for the same persona configuration |
| `persona` | Persona name (e.g. `happy_path`, `boomer_ui`) |
| `grade` | Integer 1–10 (1 = terrible, 10 = excellent) |
| `comments` | Qualitative observation and improvement suggestions |
| `processed` | Always `false` on write — intended for downstream consumers to mark as handled |
| `processedAt` | Always `null` on write |

The file is **append-only** — multiple runs accumulate in the same file. The `sessionId` is deterministic so downstream consumers can group or deduplicate entries by persona configuration across runs.

### Terminal summary

A concise summary is also printed to stdout after all personas finish:

```
============================================================
Persona Feedback Complete — 10 persona(s)
============================================================
  [happy_path] grade=True — Save affordances present but no visible confirmation...
  [confused_novice] grade=False — Save buttons are small icon-only controls...
  [adversarial] grade=True — Inputs accept literal script text but it does not execute...
  ...
```

### What is not generated

In feedback mode, the following standard outputs are **skipped**:

- `evaluation_report.json`
- `evaluation_report.md`
- Executive summary
- Per-test judge verdicts, trait evaluations, and feedback quality scores

## Differences from standard mode

| | Standard mode | Feedback mode (`--feedback`) |
|---|---|---|
| **Execution prompt** | Full `build_execution_prompt` with validation rules, fallback ladders, loop detection | Lean `build_persona_feedback_prompt` — browse as persona, return grade + comments |
| **Agent output model** | `ScenarioExecutionVerdict` (success, reason, process/logical/usability evaluations) | `PersonaFeedback` (grade 1–10, comments) |
| **Judge** | Murphy judge LLM evaluates action trace for pass/fail | Skipped — grade is self-reported by the persona agent |
| **Pass/fail** | Judge verdict | `grade >= 5` |
| **Output files** | `evaluation_report.json`, `evaluation_report.md` | `feedback.jsonl` (append-only) |
| **Plan style** | Full steps with alternatives and detailed success criteria | Concise: 1–3 intent-based steps, single-sentence criteria |

## Key source files

| File | Role |
|------|------|
| `murphy/api/cli.py` | CLI flag definition and feedback-mode control flow |
| `murphy/prompts.py` | `build_persona_feedback_prompt` — the lean execution prompt |
| `murphy/core/execution.py` | `_execute_single_test` (feedback branch), `_submit_feedback` |
| `murphy/models.py` | `PersonaFeedback`, `PERSONA_REGISTRY`, `TraitVector`, `agent_config_session_id` |
