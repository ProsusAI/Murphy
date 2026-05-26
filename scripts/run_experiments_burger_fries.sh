#!/usr/bin/env bash
# run_experiments_burger_fries.sh
#
# Runs 5 broad feature-exploration experiments against burger-fries-toqan.vercel.app
# using Murphy's default built-in personas.
# Goal:    "explore and test the main features of this platform"
# Outputs: output/eval_with_embeddings/burger_fries/run_1 … run_5

set -euo pipefail

URL="https://burger-fries-toqan.vercel.app/#/"
EXPERIMENTS_DIR="./output/eval_with_embeddings/burger_fries"
GOAL="explore and test the main features of this platform"

mkdir -p "$EXPERIMENTS_DIR"

for i in $(seq 1 5); do
  echo ""
  echo "=========================================="
  echo " RUN ${i} / 5"
  echo "=========================================="

  if [[ $i -eq 1 ]]; then
    # First run: generate the test plan
    uv run murphy \
      --url "$URL" \
      --goal "$GOAL" \
      --no-auth \
      --output-dir "${EXPERIMENTS_DIR}/run_${i}"
  else
    # Subsequent runs: reuse the plan generated in run_1
    uv run murphy \
      --url "$URL" \
      --plan "${EXPERIMENTS_DIR}/run_1/test_plan.yaml" \
      --no-auth \
      --output-dir "${EXPERIMENTS_DIR}/run_${i}"
  fi
done

echo ""
echo "Done."
echo "  Plan:  ${EXPERIMENTS_DIR}/run_1/test_plan.yaml"
echo "  Runs:  ${EXPERIMENTS_DIR}/run_1 … run_5"
