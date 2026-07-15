# Goal context → embedding similarity experiment

Test whether aligning Murphy's eval timeline goal text with real user session goals
improves `embedding_similarity` vs persona centroids.

**Persona source:** `outputs_thesis/personas_databricks_data/personas.json`

| Field | Value |
|-------|-------|
| `persona_id` | 3 |
| Name | Relentless Troubleshooter |
| Slug | `relentless_troubleshooter` |
| Cluster size | 110 sessions |
| Baseline embed sim | 0.522 (`simple_goal/run_1`, scenario 4) |

## 1. Get conversations (Databricks)

Run **`persona_conversation_goals.sql`** in the Databricks SQL editor.

Returns top **10 conversations** from the persona cluster — one row per turn with
`origin_title`, full `user_message`, and `assistant_reply` (whole conversation,
not session-windowed).

Export CSV → group by `conversation_id` → use your LLM to derive a goal per conversation.

Regenerate the session pool for another persona:

```bash
python databricks/toqan_personas/test_goal/generate_session_values.py \
  --personas outputs_thesis/personas_databricks_data/personas.json \
  --persona-id 3 --pool-size 60
```

Paste output into the `pool` CTE in `persona_conversation_goals.sql`.

## 2. Phase 1 — Eval-only A/B (fast, no browser)

```bash
uv run python scripts/goal_embed_ablation.py \
  --treatment "YOUR LLM-DERIVED GOAL"
```

Baseline recorded in `persona_manifest.json`: **0.522**.

## 3. Phase 2 — One Murphy run (auto-generated plan, single persona)

Murphy explores the site from `--goal`, generates one scenario, and runs as the assigned persona:

```bash
./scripts/run_goal_embed_experiment.sh
```

Or manually:

```bash
printf '\n' | uv run murphy \
  --url https://work.toqan.ai/ \
  --personas outputs_thesis/personas_databricks_data/personas.json \
  --persona relentless_troubleshooter \
  --goal "YOUR LLM-DERIVED GOAL" \
  --no-auth --max-tests 1 --parallel 1 \
  --output-dir outputs_thesis/goal_run_embed
```

No hand-written test plan required. Murphy saves `test_plan.yaml` under the output dir for review.

Four-way comparison (source session + both Murphy runs + ceiling):

```bash
uv run python scripts/goal_embed_comparison.py \
  --run-dir outputs_thesis/goal_run_embed --save-report
```

## Files

| File | Purpose |
|------|---------|
| `persona_conversation_goals.sql` | Single Databricks query — 10 full conversations |
| `persona_manifest.json` | Persona + baseline embed sim |
| `generate_session_values.py` | Regenerate pool VALUES from personas.json |
