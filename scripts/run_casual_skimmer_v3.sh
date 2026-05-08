#!/usr/bin/env bash
# run_casual_skimmer_v3.sh
#
# Runs the medium goal 5 times for Casual Skimmer only, using personas_v2.json.
# Run 1: generates a fresh test plan (reflects updated hints + description).
# After run 1: filters plan to casual_skimmer scenarios only.
# Runs 2-5: execute with the filtered plan.
# Outputs: output/eval_with_embeddings/medium_goal_v2_casual/run_1 … run_5

set -euo pipefail

URL="https://work.toqan.ai/"
PERSONAS="./output/similarity_run/personas_v2.json"
EXPERIMENTS_DIR="./output/eval_with_embeddings/medium_goal_v2_casual"
GOAL="test the creation of a RAG agent, using startup_handbook.pdf"
FULL_PLAN_PATH="${EXPERIMENTS_DIR}/run_1/test_plan.yaml"
FILTERED_PLAN_PATH="${EXPERIMENTS_DIR}/casual_skimmer_plan.yaml"

mkdir -p "$EXPERIMENTS_DIR"

# ── Run 1: generate fresh test plan ──────────────────────────────────────────
echo ""
echo "=========================================="
echo " RUN 1 / 5  (generating new test plan)"
echo "=========================================="

uv run murphy \
  --url "$URL" \
  --goal "$GOAL" \
  --personas "$PERSONAS" \
  --no-auth \
  --output-dir "${EXPERIMENTS_DIR}/run_1"

if [[ ! -f "$FULL_PLAN_PATH" ]]; then
  echo "ERROR: test plan was not created at ${FULL_PLAN_PATH}." >&2
  exit 1
fi

# ── Filter plan to casual_skimmer only ───────────────────────────────────────
echo ""
echo "Filtering test plan to casual_skimmer scenarios only..."

python3 - << EOF
import yaml
from pathlib import Path

plan = yaml.safe_load(Path('${FULL_PLAN_PATH}').read_text())
filtered_scenarios = [s for s in plan['scenarios'] if s.get('test_persona') == 'casual_skimmer']

if not filtered_scenarios:
    print("ERROR: no casual_skimmer scenarios found in the generated plan.")
    exit(1)

filtered_plan = {
    'url': plan['url'],
    'generated_at': plan['generated_at'],
    'scenarios': filtered_scenarios,
}
Path('${FILTERED_PLAN_PATH}').write_text(yaml.dump(filtered_plan, allow_unicode=True, sort_keys=False))
print(f"Filtered plan: {len(filtered_scenarios)} casual_skimmer scenario(s) saved to ${FILTERED_PLAN_PATH}")
EOF

# ── Runs 2–5: use filtered plan ───────────────────────────────────────────────
for i in $(seq 2 5); do
  echo ""
  echo "=========================================="
  echo " RUN ${i} / 5  (casual_skimmer only)"
  echo "=========================================="

  uv run murphy \
    --url "$URL" \
    --goal "$GOAL" \
    --plan "$FILTERED_PLAN_PATH" \
    --personas "$PERSONAS" \
    --no-auth \
    --output-dir "${EXPERIMENTS_DIR}/run_${i}"
done

# ── Aggregate all runs ────────────────────────────────────────────────────────
echo ""
echo "=========================================="
echo " All 5 runs complete — aggregating results"
echo "=========================================="

uv run python -m murphy.io.prepare_logs \
  --output-root "$EXPERIMENTS_DIR" \
  --out "${EXPERIMENTS_DIR}/eval_run_rows.jsonl"

# ── Persona similarity report ─────────────────────────────────────────────────
echo ""
echo "=========================================="
echo " Running persona similarity eval"
echo "=========================================="

uv run python scripts/eval_persona_similarity.py \
  --output-dir "$EXPERIMENTS_DIR" \
  --personas-file "$PERSONAS"

echo ""
echo "Done."
echo "  Runs:    ${EXPERIMENTS_DIR}/run_1 … run_5"
echo "  Results: ${EXPERIMENTS_DIR}/eval_run_rows.jsonl"
echo "  Similarity report: ${EXPERIMENTS_DIR}/persona_similarity_report.md"
