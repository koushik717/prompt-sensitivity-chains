#!/usr/bin/env bash
# Full grid + metrics + analysis + figures. Run ONLY after the pilot numbers
# have been sanity-checked. Usage: bash run_full_grid.sh
set -euo pipefail
cd "$(dirname "$0")"

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "ERROR: run  export ANTHROPIC_API_KEY=sk-ant-...  first"; exit 1
fi

source .venv/bin/activate

python3 -m src.experiment          # prints cost estimate, asks confirmation
python3 -m src.metrics
python3 -m src.analysis
python3 -m src.figures

echo
echo "DONE. Deliverables:"
echo "  results/processed/master_results.csv"
echo "  results/summary_stats.md"
echo "  results/figures/*.pdf (4 publication figures)"
