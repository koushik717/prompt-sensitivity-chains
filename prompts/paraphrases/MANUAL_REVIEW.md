# Manual paraphrase review — 2026-07-04

Paraphrases generated with `claude-sonnet-4-6` (temperature 0.9), 10 per base prompt,
120 total. Automated validation: all-MiniLM-L6-v2 cosine similarity vs base prompt,
threshold 0.85 (see validation_report.csv). Stats: min=0.788, mean=0.915, max=1.000.

## Flagged items (6/120 below threshold) — all reviewed and ACCEPTED

| task | role | idx | cosine | verdict |
|---|---|---|---|---|
| code_review | analyzer | 6 | 0.829 | accepted — meaning preserved |
| research_plan | finalizer | 4 | 0.829 | accepted — meaning preserved |
| summarization | editor | 4 | 0.850 | accepted — meaning preserved |
| summarization | fact_checker | 1 | 0.788 | accepted — meaning preserved |
| summarization | fact_checker | 8 | 0.793 | accepted — meaning preserved |
| summarization | summarizer | 7 | 0.794 | accepted — meaning preserved |

Rationale: in every flagged case the paraphrase specifies the same task, the same
constraints (word limits, "preserve numbers", "output only X"), and the same output
format as the base prompt. The similarity dips are driven by stylistic reframings
("Your role is that of...", "Your function is...") that MiniLM penalizes, not by
semantic changes. A sample of 5 unflagged paraphrases was also reviewed with the
same outcome.

Reviewed by: automated LLM review (Claude, this session). Limitation to note in the
paper: paraphrase semantic-equivalence review was performed by an LLM, which is a
potential circularity for an LLM-sensitivity study; a human spot-check of
prompts/paraphrases/*.yaml is recommended before submission (est. 10 minutes).

## Post-hoc identity check — 2026-07-05

A normalized string comparison found 2 of 120 generated "paraphrases" to be
byte-identical (whitespace/case-normalized) to their base prompts:
research_plan/critic #0 and research_plan/finalizer #0 (these produced the
max cosine = 1.000 in validation_report.csv). Both are EXCLUDED from the
paraphrase set; the 15 runs perturbed with them are excluded from the
perturbed condition in metrics.py (they are unperturbed chains). 118 valid
paraphrases remain; 1,335 perturbed runs analyzed.

## Human review — 2026-07-05

Full human review of all 118 active paraphrases in HUMAN_REVIEW_SHEET.md
performed by the author (V. Koushik); all confirmed meaning-preserving.
