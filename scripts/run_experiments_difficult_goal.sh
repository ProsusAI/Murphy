#!/usr/bin/env bash
# run_experiments_difficult_goal.sh
#
# Runs the saved test plan 10 times using discovered personas.
# Goal:    "test the creation of a RAG agent that runs on a schedule, using startup_handbook.pdf and the scheduling functionality"
# Plan:    generated on run 1, saved to output/eval_with_embeddings/difficult_goal/run_1/test_plan.yaml
# Outputs: output/eval_with_embeddings/difficult_goal/run_1 … run_10
# Results: output/eval_with_embeddings/difficult_goal/eval_run_rows.jsonl

set -euo pipefail

URL="https://work.toqan.ai/"
PERSONAS="./output/similarity_run/personas.json"
EXPERIMENTS_DIR="./output/eval_with_embeddings/difficult_goal"
GOAL="test the creation of a RAG agent that runs on a schedule, using startup_handbook.pdf and the scheduling functionality"

mkdir -p "$EXPERIMENTS_DIR"

# ── Runs 1–10 ────────────────────────────────────────────────────────────────
for i in $(seq 1 10); do
  echo ""
  echo "=========================================="
  echo " RUN ${i} / 10"
  echo "=========================================="

  if [[ $i -eq 1 ]]; then
    # First run: generate the test plan from scratch
    uv run murphy \
      --url "$URL" \
      --goal "$GOAL" \
      --personas "$PERSONAS" \
      --no-auth \
      --output-dir "${EXPERIMENTS_DIR}/run_${i}"

    PLAN_PATH="${EXPERIMENTS_DIR}/run_1/test_plan.yaml"

    if [[ ! -f "$PLAN_PATH" ]]; then
      echo "ERROR: test plan was not created at ${PLAN_PATH}." >&2
      exit 1
    fi
  else
    # Subsequent runs: reuse the plan from run 1
    uv run murphy \
      --url "$URL" \
      --goal "$GOAL" \
      --plan "$PLAN_PATH" \
      --personas "$PERSONAS" \
      --no-auth \
      --output-dir "${EXPERIMENTS_DIR}/run_${i}"
  fi
done

# ── Aggregate all runs ───────────────────────────────────────────────────────
echo ""
echo "=========================================="
echo " All 10 runs complete — aggregating results"
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
echo "  Goal:    ${GOAL}"
echo "  Plan:    ${PLAN_PATH}"
echo "  Runs:    ${EXPERIMENTS_DIR}/run_1 … run_10"
echo "  Results: ${EXPERIMENTS_DIR}/eval_run_rows.jsonl"
echo "  Similarity report: ${EXPERIMENTS_DIR}/persona_similarity_report.md"
