# Contributing to Murphy

Thanks for your interest in contributing to Murphy!

## Development Setup

```bash
# 1. Clone and install
git clone https://github.com/ProsusAI/Murphy.git
cd Murphy
uv sync

# 2. Install Chromium
uv run playwright install chromium

# 3. Set up your environment
cp .env.example .env
# Add your OPENAI_API_KEY
```

## Running Tests

```bash
uv run pytest -vxs tests/murphy/          # Murphy unit tests
uv run pytest -vxs tests/browser_use/     # Browser engine tests
uv run pytest -vxs tests/                 # All tests
```

## Quality Checks

```bash
uv run pyright                            # Type checking
uv run ruff check --fix                   # Lint + autofix
uv run ruff format                        # Code formatting
uv run pre-commit run --all-files         # All pre-commit hooks
```

## Code Style

- Use **tabs** for indentation (not spaces)
- Use modern Python >= 3.11 typing: `str | None`, `list[str]`, `dict[str, Any]`
- Use async Python throughout
- Use Pydantic v2 models for data structures
- Keep console logging in methods prefixed with `_log_`

## Making Changes

1. Write or update tests that verify the existing behavior
2. Write failing tests for your new behavior
3. Implement the changes
4. Run the full test suite: `uv run pytest -vxs tests/`
5. Run quality checks: `uv run pyright && uv run ruff check --fix`

## CI and External Contributors

CI requires an `OPENAI_API_KEY` secret, which is not available to pull requests from forks. Please run tests locally before submitting.

## Pull Requests

- Keep PRs focused on a single change
- Include tests for new functionality
- Update relevant documentation if needed
- Run `uv run pre-commit run --all-files` before submitting

## Contributor License Agreement (CLA)

By contributing, you agree to assign copyright of your contribution to MIH AI B.V. Your contributions are licensed under the Apache License, Version 2.0. You confirm that you have the right to submit the contribution and that it does not knowingly violate any third-party intellectual property rights.

## Vendored browser-use

The `browser_use/` directory contains a vendored and modified copy of [browser-use](https://github.com/browser-use/browser-use). See `docs/BROWSER_USE_MODIFICATIONS.md` for details on local modifications. If your change touches `browser_use/`, please document the modification in `docs/BROWSER_USE_MODIFICATIONS.md`.
