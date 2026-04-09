# Changelog

All notable changes to Murphy will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
