"""Report generation — JSON output and screenshot management."""

from __future__ import annotations

import shutil
from pathlib import Path

from murphy.io.report_helpers import _slugify
from murphy.models import EvaluationReport, TestResult


def copy_screenshots_to_output(report: EvaluationReport, output_dir: Path, *, clear_previous: bool = True) -> None:
	"""Copy test screenshots to a stable output directory, organized by test.

	Idempotent: skips results whose screenshots already live inside the output dir
	(happens when save_callback invokes this incrementally after each test).
	"""
	screenshots_dir = output_dir / 'screenshots'
	if clear_previous and screenshots_dir.exists():
		shutil.rmtree(screenshots_dir)
	screenshots_dir_resolved = screenshots_dir.resolve()
	for i, result in enumerate(report.results, 1):
		if not result.screenshot_paths:
			continue
		# Filter out None entries up front (screenshot_paths is list[str | None])
		valid_paths = [p for p in result.screenshot_paths if p]
		if not valid_paths:
			continue

		# Stash original source paths (temp dir) before we ever rewrite them.
		if not hasattr(result, '_original_screenshot_paths'):
			result._original_screenshot_paths = list(valid_paths)  # type: ignore[attr-defined]
		source_paths: list[str] = getattr(result, '_original_screenshot_paths', valid_paths)

		# Already copied on a previous incremental call — skip only if files still exist
		if all(str(Path(p).resolve()).startswith(str(screenshots_dir_resolved)) for p in valid_paths):
			if all(Path(p).exists() for p in valid_paths):
				_rewrite_primary_screenshot_path(result, valid_paths, output_dir)
				continue

		test_dir = screenshots_dir / f'test_{i:02d}_{_slugify(result.scenario.name)}'
		test_dir.mkdir(parents=True, exist_ok=True)
		copied_paths: list[str] = []
		for src_path_str in source_paths:
			src = Path(src_path_str).resolve()
			dst = (test_dir / Path(src_path_str).name).resolve()
			if src.exists() and src != dst:
				shutil.copy2(src, dst)
				copied_paths.append(str(dst))
		# Update paths to point to copied location
		result.screenshot_paths = copied_paths  # type: ignore[assignment]
		_rewrite_primary_screenshot_path(result, copied_paths, output_dir)


def _rewrite_primary_screenshot_path(
	result: TestResult,
	copied_paths: list[str],
	output_dir: Path,
) -> None:
	primary = result.primary_screenshot_path
	if not primary:
		return

	if not hasattr(result, '_original_primary_screenshot_path'):
		result._original_primary_screenshot_path = primary  # type: ignore[attr-defined]
	original_primary: str = getattr(result, '_original_primary_screenshot_path', primary)
	primary_basename = Path(original_primary).name

	matched = next((p for p in copied_paths if Path(p).name == primary_basename), None)
	if matched and Path(matched).exists():
		result.primary_screenshot_path = str(Path(matched).relative_to(output_dir.resolve()))
	else:
		result.primary_screenshot_path = None


def write_json_report(report: EvaluationReport, output_dir: Path) -> Path:
	path = output_dir / 'evaluation_report.json'
	path.write_text(report.model_dump_json(indent=2))
	return path
