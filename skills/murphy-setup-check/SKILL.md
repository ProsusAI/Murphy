---
name: murphy-setup-check
description: Prepares and validates a local Murphy installation for workshop or first-time use. Use when the user asks to verify Murphy setup, run a smoke test, check API keys, install dependencies, confirm Chromium/browser automation works, or make sure Murphy is ready before running a real evaluation.
---

# Murphy setup check

Prepare and validate a local Murphy environment. Do not commit or push files.

## Goal

Confirm that Murphy is ready for a real run by checking the local repo, required tooling, browser runtime, API-key configuration, and one tiny public-site Lite run.

Return one of these overall outcomes:

- `Ready for workshop`
- `Needs API key`
- `Needs dependency install`
- `Needs browser install`
- `Smoke test failed`

## Inputs

Resolve these from the request when present:

1. Murphy repo path
2. Whether the user wants install actions or validation only
3. Smoke-test URL

Defaults:

- Repo path: current workspace when it contains `pyproject.toml` for Murphy
- Mode: validate and install missing non-secret prerequisites
- Smoke-test URL: `https://example.com`

Ask one focused question only when the repo path is unclear.

## Checks

Run these checks in order:

1. Confirm the workspace is the Murphy repo by checking for `pyproject.toml` and the `murphy` package.
2. Check that `uv` is available.
3. Check whether `.env` exists. If it does not, copy `.env.example` to `.env`.
4. Check whether `.env` contains at least one non-empty supported provider key such as:
   - `OPENAI_API_KEY`
   - `ANTHROPIC_API_KEY`
   - `GOOGLE_API_KEY`
   - `AZURE_OPENAI_KEY`
   - `MISTRAL_API_KEY`
   - `GROQ_API_KEY`
   - `CEREBRAS_API_KEY`
   - `OPENROUTER_API_KEY`
5. If no provider key is configured, stop and report `Needs API key`. Do not invent, write, or modify secrets.
6. Run `uv sync`.
7. Check for `BROWSER_USE_EXECUTABLE_PATH` or an installed Chrome, Chromium, Brave, or Edge browser.
8. If no supported browser is installed, run `uvx playwright install chromium`. Do not add Playwright as a project dependency.
9. Run a tiny Murphy Lite smoke test on a public page with a visible browser.
10. Confirm that `evaluation_report.md` was written in the smoke-test output directory.

## Smoke test command

Use a unique output directory under `workshop/output/setup-check/`.

Run:

```bash
BROWSER_USE_HEADLESS=false uv run murphy \
  --url "https://example.com" \
  --goal "Open the homepage and confirm the main content is visible." \
  --lite \
  --no-auth \
  --parallel 1 \
  --max-steps 5 \
  --output-dir "<output-directory>"
```

Use a different public URL only if the user requests one.

## Failure handling

- If `uv` is missing, explain that Murphy uses `uv` for dependency management and stop.
- If the dependency install fails, report `Needs dependency install` with the failing command.
- If no supported browser is available and the fallback browser install fails, report `Needs browser install` with the failing command.
- If the smoke test cannot produce a report, report `Smoke test failed`.
- If a public target introduces bot protection, retry once on `https://example.com` and then stop.

## Response

Return:

- Overall status
- Repo path used
- Whether `.env` was created from `.env.example`
- Whether an API key was detected
- Whether dependencies were installed successfully
- Whether an existing supported browser was detected or Chromium was installed successfully
- Whether the smoke test browser opened
- Whether `evaluation_report.md` was created
- Smoke-test report path when available
- The next action for the user, if any

Keep the response concise and explicit about the first blocker.
