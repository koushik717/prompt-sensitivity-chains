#!/usr/bin/env bash
# One-command pilot run. Prerequisites:
#   export ANTHROPIC_API_KEY=sk-ant-...   (do this in your terminal first)
# Usage: bash run_pilot.sh
set -euo pipefail
cd "$(dirname "$0")"

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "ERROR: run  export ANTHROPIC_API_KEY=sk-ant-...  first"; exit 1
fi

echo "== 1/6 installing dependencies (in .venv) =="
if [ ! -d .venv ]; then python3 -m venv .venv; fi
source .venv/bin/activate
python3 -m pip install -q --upgrade pip
python3 -m pip install -q anthropic sentence-transformers pandas matplotlib scipy pyyaml

echo "== 2/6 generating real paraphrases =="
python3 -m src.paraphrase_gen --force

echo "== 3/6 validating paraphrases (embedding similarity) =="
python3 -m src.validate_paraphrases || {
  echo; echo "Some paraphrases were flagged — open prompts/paraphrases/ and review them."; }

echo
echo "*** MANUAL STEP: read the files in prompts/paraphrases/ yourself. ***"
echo "*** Every paraphrase must mean the same thing as the base prompt. ***"
read -rp "Have you read them and do they all preserve meaning? [y/N] " ok
case "$ok" in y|Y) ;; *) echo "aborted — fix paraphrases first"; exit 1;; esac

echo "== 4/6 dry-run cost estimate (full grid, for reference) =="
python3 -m src.experiment --dry-run

echo "== 5/6 running PILOT (1 task, 3 paraphrases, all depths) =="
python3 -m src.experiment --pilot --yes

echo "== 6/6 pilot metrics + analysis =="
python3 -m src.metrics
python3 -m src.analysis

echo
echo "DONE. Pilot numbers are in results/summary_stats.md — paste that file"
echo "back into the chat for a sanity check before running the full grid."
