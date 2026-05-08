#!/usr/bin/env bash
# run_experiments_medium_goal_v2_2.sh
#
# Runs the medium goal 5 times using personas_v2.json (score-grounded descriptions).
# Goal:    "test the creation of a RAG agent, using startup_handbook.pdf"
# Outputs: output/eval_with_embeddings/medium_goal_v2_2/run_1 … run_5

set -euo pipefail

URL="https://work.toqan.ai/"
PERSONAS="./output/similarity_run/personas_v2.json"
EXPERIMENTS_DIR="./output/eval_with_embeddings/medium_goal_v2_2"
GOAL="test the creation of a RAG agent, using startup_handbook.pdf"

mkdir -p "$EXPERIMENTS_DIR"

# ── Runs 1–5 ─────────────────────────────────────────────────────────────────
for i in $(seq 1 5); do
  echo ""
  echo "=========================================="
  echo " RUN ${i} / 5"
  echo "=========================================="

  if [[ $i -eq 1 ]]; then
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
echo "  Goal:    ${GOAL}"
echo "  Plan:    ${PLAN_PATH}"
echo "  Runs:    ${EXPERIMENTS_DIR}/run_1 … run_5"
echo "  Results: ${EXPERIMENTS_DIR}/eval_run_rows.jsonl"
echo "  Similarity report: ${EXPERIMENTS_DIR}/persona_similarity_report.md"
