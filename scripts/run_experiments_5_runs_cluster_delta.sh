#!/usr/bin/env bash
# run_experiments_5_runs_cluster_delta.sh
#
# Runs the medium goal 5 times using the pre-built personas with ceiling metrics.
# Goal:    "test the creation of a RAG agent, using startup_handbook.pdf"
# Outputs: output/eval_with_embeddings/5_runs_cluster_delta/run_1 … run_5

set -euo pipefail

URL="https://work.toqan.ai/"
PERSONAS="./output/eval_with_embeddings/5_runs_cluster_delta/personas.json"
EXPERIMENTS_DIR="./output/eval_with_embeddings/5_runs_cluster_delta"
GOAL="test the creation of a RAG agent, using startup_handbook.pdf"

mkdir -p "$EXPERIMENTS_DIR"

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
      --auth \
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
