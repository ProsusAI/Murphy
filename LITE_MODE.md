# Murphy Lite Mode

Lite mode is a faster, simpler Murphy run for quick product feedback. It is enabled with `--lite` in the CLI or `lite: true` in the REST API.

## What It Skips

- LLM test generation
- Interactive feature and test-plan review pauses
- Murphy judge calls
- Judge-generated executive summary

## What It Returns

Each scenario returns a structured `LiteResult`:

- `grade`: 1-10 overall experience score
- `flaws`: concrete problems or blockers
- `flaw_evidence`: captured evidence IDs and explanations linking flaws to relevant screenshots
- `improvements`: product or UX improvements
- `fixes`: implementation-level fixes
- `other_feedback`: additional useful observations

Murphy writes the structured results to JSON and Markdown reports.

## CLI

```bash
uv run murphy --url https://example.com --goal "Test agent creation flow" --lite
```

You can still use `--max-tests`, `--parallel`, `--provider`, `--model`, `--auth`, `--no-auth`, `--features`, and `--plan`.

## REST

Set `lite: true` on `/generate-plan`, `/evaluate`, or `/execute`.

```json
{
  "url": "https://example.com",
  "goal": "Test agent creation flow",
  "max_tests": 1,
  "lite": true
}
```

## Speed Experiment

Use the manual experiment runner:

```bash
uv run python exp_2/lite_speed/run_compare.py \
  --url https://work.toqan.ai \
  --goal "Test agent creation flow" \
  --max-tests 1 \
  --parallel 1 \
  --repetitions 1
```
