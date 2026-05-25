#!/usr/bin/env bash
# run_experiments_restaurants.sh
#
# Runs 5 broad feature-exploration experiments against work.toqan.ai
# using restaurant personas discovered from real PostHog sessions.
# Goal:    "explore and test the main features of this platform"
# Outputs: output/eval_with_embeddings/restaurant_feature_exploration/run_1 … run_5

set -euo pipefail

URL="https://work.toqan.ai/"
PERSONAS="./output/restaurant_personas_2/personas.json"
EXPERIMENTS_DIR="./output/eval_with_embeddings/restaurant_feature_exploration_2"
PLAN_PATH="./output/eval_with_embeddings/restaurant_feature_exploration_2/test_plan.yaml"
GOAL="explore and test the main features of this platform"

mkdir -p "$EXPERIMENTS_DIR"

for i in $(seq 1 5); do
  echo ""
  echo "=========================================="
  echo " RUN ${i} / 5"
  echo "=========================================="

  if [[ $i -eq 1 ]]; then
    uv run murphy \
      --url "$URL" \
      --plan "$PLAN_PATH" \
      --personas "$PERSONAS" \
      --no-auth \
      --output-dir "${EXPERIMENTS_DIR}/run_${i}"
  else
    uv run murphy \
      --url "$URL" \
      --plan "$PLAN_PATH" \
      --personas "$PERSONAS" \
      --no-auth \
      --output-dir "${EXPERIMENTS_DIR}/run_${i}"
  fi
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
echo "  Personas: ${PERSONAS}"
echo "  Plan:     ${PLAN_PATH}"
echo "  Runs:     ${EXPERIMENTS_DIR}/run_1 … run_5"
echo "  Similarity report: ${EXPERIMENTS_DIR}/persona_similarity_report.md"
