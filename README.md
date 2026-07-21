# Noise or Sensitivity? Prompt Perturbation vs Intrinsic Nondeterminism in Chained LLM Agents

Experiment harness, data, and paper for:

> **Noise or Sensitivity? Disentangling Prompt Perturbation Effects from
> Intrinsic Nondeterminism in Chained LLM Agents.** V. K. Nakka, 2026.
> arXiv link forthcoming. Paper source and PDF in [`paper/`](paper/).

Measures whether output divergence caused by semantically-equivalent prompt
paraphrases grows, shrinks, or stays constant as chain depth (number of
agents) increases in multi-agent LLM pipelines — against a matched
unperturbed control arm that isolates intrinsic temperature-0 sampling
nondeterminism. Released artifacts include all 1,470 raw run transcripts
(`results/raw/`), processed metrics (`results/processed/`), figures, the
validated paraphrase sets with their full review trail
(`prompts/paraphrases/MANUAL_REVIEW.md`), and the cascade-failure case study
(`results/case_studies/`). License: MIT.

## Research questions

1. **Primary:** does divergence (cosine distance of final output vs the
   canonical-prompt run) amplify with chain depth (1-4)?
2. **Secondary:** does perturbing an *early* agent's prompt cause more final
   divergence than perturbing a *late* agent's prompt?

## Design

Three 4-role task pipelines (depth truncated at 1/2/3/4; agent k's output is final):

| task | chain |
|---|---|
| summarization | extractor → summarizer → fact_checker → editor |
| research_plan | scoper → planner → critic → finalizer |
| code_review | analyzer → reviewer → security_checker → report_writer (JSON output) |

Grid: 3 tasks × 5 fixed inputs × 10 paraphrases × 4 depths × up-to-3
perturbation positions (first/middle/last, deduped per depth) = **1350
perturbed runs** + 60 baselines + 60 control repeats = 1470 runs / 4200 calls.

Controls: temperature 0 everywhere; exactly ONE position perturbed per run;
canonical-prompt baseline per (task, input, depth); 5 canonical repeats per
(task, depth) quantify residual nondeterminism (noise floor); everything
logged (full prompts/outputs, model version, timestamps, token counts).

## Models used (as reported in the paper)

| role | model | temperature |
|---|---|---|
| chain agents | `claude-haiku-4-5-20251001` | 0.0 |
| paraphrase generation | `claude-sonnet-4-6` | 0.9 |
| LLM-as-judge | `claude-sonnet-4-6` | 0.0 |

The paraphrase/judge model differs from the agent model by design. Sonnet 4.6
(rather than Sonnet 5) is used because Sonnet 5 rejects the `temperature`
parameter, and temperature control matters here (0.9 for paraphrase diversity,
0.0 for judge reproducibility). All reported judgments use **rubric v2**
(depth-appropriate rubrics in `tasks/*.yaml`; the graded artifact is the output
of the last agent that actually ran, so intermediate-stage outputs are not
penalized for not being final-stage artifacts).

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # pinned versions used for the paper
export ANTHROPIC_API_KEY=...
```

Set `backend: anthropic` in `config.yaml` for real runs. `backend: mock` runs
the entire pipeline offline with a deterministic fake LLM — useful for testing
the harness. **Mock results are plumbing validation only, never research data.**

## Run order

```bash
python -m src.paraphrase_gen           # 10 paraphrases per base prompt
python -m src.validate_paraphrases     # cosine sim > 0.85 vs base, else flagged
                                       #   -> MANUALLY REVIEW before continuing
python -m src.chain_runner --task summarization --depth 4   # smoke test
python -m src.experiment --dry-run     # call count + cost estimate
python -m src.experiment --pilot       # 1 task, 3 paraphrases, all depths
python -m src.experiment               # full grid (asks confirmation; --yes to skip)
python -m src.metrics                  # divergence, judge scores, schema checks
python -m src.analysis                 # CIs, trend tests, summary_stats.md
python -m src.figures                  # 4 vector PDFs
```

`experiment.py` checkpoints to `results/raw/runs.jsonl`; re-running skips
completed runs and retries failures. Failed API calls are retried (3x,
exponential backoff) then logged as failures — **never fabricated**. A running
cost estimate prints during execution and a budget guard (config, $50) aborts
if exceeded.

## Outputs

- `results/raw/runs.jsonl` — full per-run logs; `judgments.jsonl` — judge cache
- `results/processed/master_results.csv` + aggregation CSVs
- `results/figures/*.pdf` — divergence vs depth, per-task curves,
  success vs depth, divergence violins
- `results/summary_stats.md` — key numbers for the paper

## Metrics & statistics

- **Divergence:** 1 − cosine similarity (all-MiniLM-L6-v2 embeddings) between
  perturbed and canonical final outputs on the same input.
- **Success:** LLM-as-judge, fixed versioned rubric per task (in `tasks/*.yaml`),
  judge model ≠ agent model, temperature 0; 10% sample double-judged and
  agreement reported.
- **Schema violations:** JSON parse + required-key check (code_review).
- **Tail risk:** per-depth P90/P95/max divergence and catastrophe rate
  (divergence > 0.3) with bootstrap CIs (`results/processed/tail_metrics.csv`)
  — chains may fail catastrophically at increasing rates even when mean
  divergence is flat.
- **Stats:** bootstrap 95% CIs (5000 resamples), Spearman monotonic trend for
  divergence vs depth and for the catastrophe indicator, Mann-Whitney +
  Cliff's delta for position effect. Effect sizes reported alongside p-values.
- **Case studies:** `results/case_studies/` holds full transcripts of notable
  failure cascades (preserved verbatim; never overwritten by re-runs).

## Repo layout

```
config.yaml              model names, temperature, grid sizes, budget, prices
tasks/*.yaml             task definition, 5 inputs, judge rubric (versioned)
prompts/base_prompts.yaml       canonical system prompt per role per task
prompts/paraphrases/            generated paraphrase sets + validation report
src/                     paraphrase_gen | validate_paraphrases | chain_runner |
                         experiment | metrics | analysis | figures | llm_client
results/                 raw/ processed/ figures/
```
