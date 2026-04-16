#!/usr/bin/env bash
# run_experiments.sh
#
# Runs the saved test plan 10 times using discovered personas.
# Plan:    output/plan/test_plan.yaml
# Outputs: output/experiments_evaluation/run_1 … run_10
# Results: output/experiments_evaluation/eval_run_rows.jsonl

set -euo pipefail

URL="https://work.toqan.ai/"
PERSONAS="./output/personas.json"
PLAN_PATH="./output/plan/test_plan.yaml"
EXPERIMENTS_DIR="./output/experiments_evaluation"

if [[ ! -f "$PLAN_PATH" ]]; then
  echo "ERROR: test plan not found at ${PLAN_PATH}." >&2
  exit 1
fi

mkdir -p "$EXPERIMENTS_DIR"

# ── Runs 1–10 ────────────────────────────────────────────────────────────────
for i in $(seq 1 10); do
  echo ""
  echo "=========================================="
  echo " RUN ${i} / 10"
  echo "=========================================="

  uv run murphy \
    --url "$URL" \
    --plan "$PLAN_PATH" \
    --personas "$PERSONAS" \
    --no-auth \
    --output-dir "${EXPERIMENTS_DIR}/run_${i}"
done

# ── Aggregate all runs ───────────────────────────────────────────────────────
echo ""
echo "=========================================="
echo " All 10 runs complete — aggregating results"
echo "=========================================="

uv run python -m murphy.io.prepare_logs \
  --output-root "$EXPERIMENTS_DIR" \
  --out "${EXPERIMENTS_DIR}/eval_run_rows.jsonl"

echo ""
echo "Done."
echo "  Plan:    ${PLAN_PATH}"
echo "  Runs:    ${EXPERIMENTS_DIR}/run_1 … run_10"
echo "  Results: ${EXPERIMENTS_DIR}/eval_run_rows.jsonl"
