Run the persona prompt optimizer against an eval report and display the proposed diff.

Usage: /optimize-persona-prompts [path/to/persona_similarity_report.json]

If no path is given, look for the most recent `persona_similarity_report*.json` under `output/`.

## Steps

1. Resolve the report path: use the argument if provided, otherwise find the newest `persona_similarity_report*.json` inside any `eval_with_embeddings/` subfolder under `output/` with `find output/ -path "*/eval_with_embeddings/persona_similarity_report*.json" | sort | tail -1`.
2. Find the personas file: look for `personas.json` in the same directory as the report, then fall back to `output/personas.json`.
3. Run the optimizer:
   ```
   uv run python scripts/optimize_persona_prompts.py \
     --report <report_path> \
     --personas-file <personas_path>
   ```
4. Show the full output to the user.
5. The script will prompt `[y/N]` to apply the changes directly to [murphy/personas/persona_labeling.py](murphy/personas/persona_labeling.py). Remind the user to review the diff before confirming.
6. After applying, remind the user to re-run the relabeling step (not full discovery) and repeat the eval loop to measure improvement.
