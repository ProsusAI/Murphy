#!/bin/bash
set -e

URL="https://work.toqan.ai"
GOAL="test the agent creation functionality"
PERSONAS="output/eval_with_embeddings/5_runs_cluster_delta/personas.json"
OUTPUT_BASE="output/simple_goal_ceiling_scores"

echo "=== Deleting browser profile ==="
rm -rf "$(dirname "$0")/../browser_profile"

echo "=== Run 1 (generating test plan) ==="
uv run murphy \
  --url "$URL" \
  --goal "$GOAL" \
  --lite \
  --personas "$PERSONAS" \
  --output-dir "$OUTPUT_BASE/run_1"

for i in $(seq 2 10); do
  echo "=== Run $i ==="
  uv run murphy \
    --url "$URL" \
    --lite \
    --plan "$OUTPUT_BASE/run_1/test_plan.yaml" \
    --personas "$PERSONAS" \
    --output-dir "$OUTPUT_BASE/run_$i"
done

echo "=== All 10 runs complete ==="
