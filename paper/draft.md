# Noise or Sensitivity? Disentangling Prompt Perturbation Effects from Intrinsic Nondeterminism in Chained LLM Agents

*Draft v2 — 2026-07-05. Numbers final (full grid, N=1470); all citations verified against the papers.*

## Abstract

Prompt sensitivity — the tendency of large language models to produce different
outputs under semantically equivalent prompt rewordings — is well documented for
single models, but its behavior in multi-agent pipelines, where one agent's
output becomes the next agent's input, has not been measured. We ask whether
paraphrase-induced divergence compounds with chain depth, and introduce the
control condition that turns out to be decisive: repeated runs of *unperturbed*
chains at temperature 0, which isolate intrinsic sampling nondeterminism from
prompt-attributable variance. Across 1,470 runs of three 4-stage pipelines
(summarization, research planning, code review) with 118 validated paraphrases
(120 generated; 2 degenerate duplicates of their base prompt detected and
excluded, with the 15 affected runs),
we find that (1) apparent divergence growth with depth is largely *not* a
prompt effect: unperturbed chains amplify intrinsic nondeterminism with depth,
reaching a 40% catastrophic-divergence rate at depth 3 on the most open-ended
task with no perturbation at all — a rate not distinguishable from perturbed
runs given our control sample size (p = 0.31, n_control = 5), implying that
intrinsic nondeterminism accounts for at minimum the majority of the observed
catastrophe rate; (2) the residual paraphrase-attributable effect is
modest and does not compound — excess divergence over the noise floor stays
flat or declines with depth; (3) perturbation *position* matters more than
count of downstream stages: perturbing the first agent yields significantly
more final-output divergence than perturbing the last (0.155 vs 0.116,
Mann-Whitney p = 2.1×10⁻¹⁰, Cliff's δ = 0.246); and (4) format-constrained
final stages act as attractors that repair both noise sources — our
summarization pipeline's divergence *decreases* with depth (Spearman
ρ = −0.196) and structured-output schema violations are 0%. Our results
caution that studies of prompt robustness in agent pipelines must control for
nondeterminism amplification, and suggest that practitioners should invest
prompt-hardening effort in early-position agents and convergent final stages.
Harness, prompts, raw runs, and analysis are released for reproduction.

## 1. Introduction

A growing share of LLM deployments are not single calls but *chains*: an
extractor feeding a summarizer feeding an editor; an analyzer feeding a
reviewer feeding a report writer. Each stage consumes the previous stage's
output as input, so any instability in an early stage has, in principle, the
entire remaining pipeline through which to propagate. At the same time, a
well-replicated line of work shows that individual LLMs are surprisingly
sensitive to semantically irrelevant prompt variation — formatting, phrasing,
and paraphrase changes can swing single-model benchmark performance by double
digits [Sclar et al. 2024; Zhu et al. 2023 (PromptBench); Mizrahi et al.
2024; Sun et al. 2023; Cao et al. 2024]. The natural worry, voiced but to our
knowledge never measured, is multiplicative: if one agent is prompt-sensitive,
is a chain of four agents four times as fragile — or worse?

This paper measures that question directly, and the measurement produces a
twist. The naive experiment — paraphrase one agent's system prompt, run the
chain, measure embedding divergence of the final output from a
canonical-prompt run — shows divergence growing with depth on two of our three
tasks, with catastrophic divergence (cosine divergence > 0.3) spiking from 0%
at depth 1 to 20% at depth 3 in the pooled data. Reported alone, that would
read as confirmation of compounding prompt sensitivity.

It would be wrong. Our design includes a control arm that most prior
robustness studies omit: the *same* chains, with *canonical* prompts at every
position, run repeatedly at temperature 0. These unperturbed repeats are not
identical — temperature-0 decoding is not deterministic in practice, with
accuracy variation of up to 15% documented across nominally deterministic
runs [Atil et al. 2024, arXiv:2408.04667; see also Ouyang et al. 2023 (code
generation); He / Thinking Machines Lab 2025] — and the small token-level differences they
contain are amplified by exactly the same chain dynamics as paraphrase
perturbations. On our most open-ended task
(research planning), unperturbed depth-3 chains reach a mean divergence of
0.297 and a 40% catastrophic-divergence rate; the corresponding perturbed
runs reach 0.322 and 57% — not distinguishable from the controls given our
control sample size (one-sided Mann-Whitney p = 0.31, n_control = 5). The
depth-3 "catastrophe spike" is real, but at minimum the majority of it is not
a prompt-sensitivity effect: it is the chain amplifying its own sampling
noise. This extends the finding that subtle nondeterminism compounds
across turns in multi-turn conversation [Laban et al. 2025, "LLMs Get Lost in
Multi-Turn Conversation"] to the multi-agent setting, and it means
that any study attributing chained-output divergence to a manipulated variable
must first subtract the divergence the pipeline generates on its own.

With the noise floor subtracted, three clean findings remain.

**Paraphrase sensitivity does not compound with depth.** Excess divergence
(perturbed mean minus control mean, within task × depth cells) is modest
everywhere and roughly flat or declining: +0.079 → +0.032 across depths 1→4
for summarization, a steady ≈ +0.025 for code review, and within noise for
research planning. The pooled raw trend (Spearman ρ = 0.089) is significant
but tiny, and per-task trends disagree in sign (code review +0.34,
summarization −0.20) — the opposite of a universal amplification law.

**Position beats depth.** Where the paraphrase lands matters more than how
many stages follow it in aggregate: perturbing the first agent produces
significantly more final divergence than perturbing the last (0.155 vs 0.116;
Mann-Whitney p = 2.1×10⁻¹⁰; Cliff's δ = 0.246). Because both position groups
face identical intrinsic noise, this comparison is naturally noise-robust.

**Convergent stages repair.** Stages whose task is to check, edit, or format
into a fixed schema act as attractors: summarization divergence *decreases*
with depth as the fact-checker and editor renormalize drafts; the code-review
pipeline's JSON-constrained report writer produced zero schema violations
across all perturbed depth-4 runs; and the depth-3 catastrophe rate collapses
from 20% to 2% at depth 4 once the constrained final stages run. This
corroborates, from an orthogonal experimental angle, the observation that
deeper cascades can *reduce* factual error scores ["Hallucination Cascade",
arXiv:2606.07937].

Our contributions:

1. **To our knowledge, the first controlled separation of paraphrase-induced
   divergence from intrinsic sampling nondeterminism in chained LLM
   pipelines**, showing that
   what appears to be compounding prompt sensitivity is largely nondeterminism
   amplification — unperturbed temperature-0 chains reach catastrophic
   divergence rates of 40% at depth 3 on open-ended tasks.
2. **A perturbation-position effect**: early-agent paraphrases cause
   significantly more final-output divergence than late-agent paraphrases
   (p = 2.1×10⁻¹⁰, Cliff's δ = 0.246), with practical implications for where
   prompt-hardening effort pays off.
3. **Evidence of convergent-stage repair**: constrained final stages attenuate
   both noise sources, independently corroborating cascade-reduction findings
   from hallucination tracking.

We release the full harness (checkpointed runner, validated paraphrase sets,
versioned judge rubrics, analysis pipeline), all 1,470 raw run transcripts,
and the processed data.

## 2. Related Work

**Single-model prompt sensitivity.** That LLMs are sensitive to semantically
irrelevant prompt variation is by now well established. PromptBench [Zhu et
al. 2023] measures robustness to adversarial prompt perturbations at
character, word, sentence, and semantic levels across 8 tasks; Sclar et al.
[2024] show that spurious formatting features alone — separators,
capitalization, spacing — induce large performance swings; Sun et al. [2023]
find that instruction-tuned models degrade on unseen paraphrases of their
task instructions; and Cao et al. [2024] document gaps of up to 45 points
between best- and worst-performing paraphrases of the same query, arguing for
worst-prompt evaluation as a lower bound. Mizrahi et al. [2024] make the
methodological case that single-prompt evaluation is unreliable, from 6.5M
evaluation instances. All of this work evaluates a *single* model per call.
Whether sensitivity compounds, attenuates, or transforms when a
prompt-sensitive model's output becomes another prompt-sensitive model's
input is the question this line of work leaves open, and the one we address.

**Error propagation in multi-agent LLM systems.** A rapidly growing 2026
literature studies how errors move through agent pipelines. Closest to us,
the Hallucination Cascade study [arXiv:2606.07937] tracks claim-level factual
inconsistency across sequential agents and finds that deeper cascades
*reduce* normalized hallucination scores (0.422 → 0.272 over three agents) at
a small cost in factual preservation — independently corroborating, via a
different measurement (claim-level factuality vs output-embedding
divergence), the convergent-stage repair we observe. From Spark to Fire
[arXiv:2603.04474] models collaboration as a dependency graph and shows that
a single injected atomic error seed can propagate to system-level false
consensus, identifying cascade amplification and topological sensitivity as
vulnerability classes. MAS-FIRE [arXiv:2602.19843] injects 15 fault types
into MAS pipelines for reliability evaluation, and AgentAsk
[arXiv:2510.07593] attributes MAS underperformance to errors at inter-agent
message handoffs, proposing edge-level clarification. The key difference in
our design: these works perturb with *errors* — injected faults, tracked
hallucinations, corrupted messages. Our perturbation is *benign by
construction* (validated semantically equivalent paraphrases), so any
divergence we measure is attributable to sensitivity rather than to the
propagation of a defect. And none of these works measures its pipeline's
unperturbed variance floor, which our results show can dominate the measured
effect.

**Nondeterminism of "deterministic" LLM inference.** Atil et al. [2024]
systematically document accuracy variation of up to 15% (and best-to-worst
output gaps up to 70%) across runs of LLMs configured to be deterministic;
Ouyang et al. [2023] report the same phenomenon for ChatGPT code generation.
The mechanism is now well understood: serving-time batch-size variation
interacts with non-batch-invariant kernels [He / Thinking Machines Lab 2025].
Most relevantly, Laban et al. [2025] show that in multi-turn conversation,
temperature-0 decoding still yields high unreliability because subtle
nondeterminism compounds across tokens and turns. Our control condition
extends this compounding result from the multi-turn single-agent setting to
multi-agent chains — and quantifies it per task and depth, showing it grows
to catastrophic levels (40% of unperturbed depth-3 runs on our most
open-ended task) exactly where a naive reading would attribute the failures
to prompt sensitivity.

**Positioning.** The sensitivity literature perturbs prompts but tests single
models; the cascade literature tests chains but perturbs with errors; the
nondeterminism literature perturbs nothing but stops at single calls or
single-agent conversations. To our knowledge no prior work runs benign prompt
perturbations through multi-stage pipelines *against a matched unperturbed
control*, which is precisely the design needed to separate the two variance
sources — and, in our data, the separation reverses the naive conclusion.

## 3. Method

### 3.1 Pipelines and tasks

Three 4-role pipelines, truncatable at depth k ∈ {1,2,3,4} (agent k's output
is the final output):

| Task | Chain | Final output |
|---|---|---|
| summarization | extractor → summarizer → fact_checker → editor | ~100-word summary |
| research_plan | scoper → planner → critic → finalizer | structured plan document |
| code_review | analyzer → reviewer → security_checker → report_writer | JSON report (keys: summary, issues, severity) |

Five fixed inputs per task, held constant across all conditions.

### 3.2 Perturbations

10 paraphrases per base system prompt (120 total), generated by
`claude-sonnet-4-6` at temperature 0.9 and validated by embedding similarity
(all-MiniLM-L6-v2 cosine ≥ 0.85 vs base). Six paraphrases below threshold were
manually reviewed and accepted (stylistic reframing, meaning preserved; review
documented in the repository). A post-hoc identity check found 2 of the 120
generated "paraphrases" to be byte-identical (after whitespace/case
normalization) to their base prompts; these were excluded, and the 15 runs
perturbed with them were dropped from the perturbed condition (they are
unperturbed chains), leaving 118 valid paraphrases and 1,335 analyzed
perturbed runs. Exactly **one** agent's prompt is perturbed per run, at
position first, middle (⌊depth/2⌋), or last (deduplicated per depth).

### 3.3 Conditions

- **baseline** — canonical prompts at every position; the reference run per
  (task, input, depth).
- **perturbed** — one position paraphrased: 3 tasks × 5 inputs × 10
  paraphrases × Σ positions(depth) = **1,350 runs** (15 excluded as
  pseudo-perturbed per §3.2; **1,335 analyzed**).
- **control** — canonical prompts, 5 repeats at temperature 0 per
  (task, depth) on one fixed input = **60 runs**; quantifies intrinsic
  nondeterminism (the noise floor).

Total: 1,470 runs / 4,200 agent calls; zero failed runs after retries; agents
`claude-haiku-4-5-20251001` at temperature 0, max 1,024 tokens; total
agent-call cost $13.68 (from logged per-call token counts).

### 3.4 Metrics

- **Divergence**: 1 − cosine similarity (all-MiniLM-L6-v2) between the final
  outputs of a perturbed (or control) run and its same-(task, input, depth)
  baseline run.
- **Catastrophic divergence**: divergence > 0.3 (transcript inspection
  confirms this threshold separates rewordings from semantic derailment; see
  §5 case study).
- **Excess divergence**: perturbed cell mean − control cell mean within
  (task, depth) — the paraphrase-attributable component.
- **Task success**: LLM-as-judge (`claude-sonnet-4-6`, temperature 0),
  depth-appropriate versioned rubrics (v2) grading the artifact the depth-k
  chain actually produces; judge model ≠ agent model; 10% double-judged →
  95.8% exact agreement, mean |Δ| 0.04 (n = 167).
- **Schema violations**: JSON parse + required-key check (code_review,
  depth 4 only).

Statistics: bootstrap 95% CIs (5,000 resamples); Spearman trend tests on
divergence and on the catastrophe indicator; Mann-Whitney U + Cliff's δ for
the position contrast. Effect sizes reported alongside p-values throughout.

## 4. Results

*(Figures: divergence_vs_depth.pdf, per_task_curves.pdf, success_vs_depth.pdf,
divergence_violins.pdf. Tables from excess_divergence.csv, tail_metrics.csv.)*

**4.1 Raw divergence grows weakly — and not uniformly — with depth.**
Pooled across tasks, mean divergence rises from 0.0996 [95% CI 0.0908,
0.1084] at depth 1 to 0.1272 [0.1186, 0.1364] at depth 4 — a 1.28×
amplification, with a Spearman trend of ρ = 0.089 (p = 1.2×10⁻³):
statistically detectable, but far from the multiplicative compounding the
fragility hypothesis predicts. The pooled number moreover conceals
qualitative disagreement between tasks: divergence *rises* with depth for
code review (ρ = 0.339, p = 1.5×10⁻¹³) and research planning (ρ = 0.225,
p = 2.2×10⁻⁶) but *falls* for summarization (ρ = −0.196, p = 2.8×10⁻⁵),
whose fact-checking and editing stages progressively pull perturbed drafts
back toward the baseline. There is no universal amplification law to report;
the sign of the depth effect is a property of the pipeline's stage structure,
not of chaining itself.

**4.2 The catastrophe spike is largely nondeterminism, not sensitivity.**
Pooled catastrophe rate: 0% (d1) → 2.3% (d2) → 20.0% (d3) → 2.3% (d4);
depth-3 spike driven entirely by research_plan (57.2%). Control chains at the
same cell: mean divergence 0.297, catastrophe rate 40%, vs perturbed 0.322 —
not distinguishable given the control sample size (one-sided Mann-Whitney
p = 0.31, n_control = 5). At minimum, intrinsic nondeterminism accounts for
the majority of the observed catastrophe rate at this cell; our control arm
is too small to bound any residual paraphrase contribution tightly.

Notably, the noise floor is strongly *task-dependent*: control divergence is
near zero for summarization at every depth (0.005–0.032), moderate for code
review (0.072–0.126), and large and depth-growing for research planning
(0.066 → 0.297 across d1→d3). The same chain architecture, run on the same
infrastructure at the same temperature, produces intrinsic output variance
spanning nearly two orders of magnitude depending on how open-ended the
stage artifacts are. This is itself a methodological result: single-number
robustness claims about "LLM chains" are underdetermined without specifying
the task's constraint structure, because the denominator against which any
perturbation effect must be judged varies by task and depth.

**4.3 Excess (paraphrase-attributable) divergence does not compound.**
Subtracting each (task, depth) cell's control mean from its perturbed mean
isolates the component of divergence attributable to the paraphrase. This
excess is modest everywhere and shows no depth amplification in any task:
for summarization it *declines* from +0.079 (d1) to +0.032 (d4); for code
review it holds nearly constant at ≈ +0.025 across all four depths; for
research planning it fluctuates within the noise (+0.038 at d1 to −0.037 at
d4 — a negative excess, i.e. perturbed runs diverging *less* than
unperturbed controls at depth 4). With n = 5 controls per cell these
excesses are descriptive rather than tightly estimated, but their pattern is
uniform: whatever divergence paraphrases inject, the chain does not multiply
it.

**4.4 Position, not depth, is where prompt wording matters.** Restricting to
depths ≥ 2 where both positions exist, perturbing the *first* agent yields a
mean final divergence of 0.1554 (n = 450) against 0.1163 (n = 440) for the
*last* agent — a significant difference (Mann-Whitney U, p = 2.1×10⁻¹⁰) with
a small-to-medium effect size (Cliff's δ = 0.246). Restricting to depth ≥ 3
where all three positions exist, the ordering is monotone in position:
first 0.169 > middle 0.138 > last 0.129. Because first- and
last-position groups within a cell face identical intrinsic noise, this
contrast is naturally robust to the noise-floor concerns of §4.2. The
practical reading: a paraphrase that lands early has its perturbation
propagated, reinterpreted, and built upon by every subsequent stage, while a
late paraphrase can only re-style the nearly finished artifact.

**4.5 Convergent stages repair both noise sources.** Three independent
observations triangulate the same mechanism. First, the pooled catastrophe
rate collapses from 20.0% at depth 3 to 2.3% at depth 4 — adding the final,
most format-constrained stage (editor / finalizer / report writer) *reduces*
catastrophic divergence. Second, summarization's negative depth trend (§4.1)
shows repair acting on paraphrase perturbations specifically. Third, the
structured-output check is perfect: 0% schema violations across all
perturbed depth-4 code-review runs — no paraphrase anywhere in the chain
ever broke the final JSON contract. Judge scores tell the same story from
the quality side: mean score dips at depth 3 (7.34 [7.20, 7.48]) exactly
where the open-ended critic stage maximizes divergence, then recovers at
depth 4 (7.85 [7.71, 7.99]). Constrained convergent stages act as attractors
in output space — a cheap architectural lever for chain reliability, and one
that corroborates the cascade-depth hallucination reduction reported by the
Hallucination Cascade study from a different measurement angle.

## 5. Case study: a cascade failure

Run `summarization|sum_4|d4|p2|middle` (divergence 1.010, the grid maximum):
a paraphrase of the *fact-checker* prompt led it to output an analysis *about*
the draft rather than a corrected draft; the downstream editor, receiving
analysis instead of a summary, declined to edit and asked for the missing
summary — producing a final output unrelated to the source article. The
failure is qualitative and structural (a role-contract violation between
stages), not a gradual drift. Full transcripts of the failed and baseline
runs: `results/case_studies/`.

## 6. Limitations

- Single agent-model family (Claude Haiku 4.5) and one embedding model
  (MiniLM); effect sizes may differ across model families and embedders.
- Three tasks, five inputs each; task heterogeneity in our own results warns
  against over-generalizing any single trend.
- Control arm is small (5 repeats per task × depth cell; 60 runs total) —
  sufficient to reveal the noise floor's magnitude and depth trend, not to
  tightly bound it. The perturbed-vs-control comparison at the critical cell
  is correspondingly low-powered (n_control = 5).
- Catastrophe threshold (0.3) is a single operating point chosen from
  transcript inspection; results should be (and in the repo, are) reproducible
  under nearby thresholds.
- Paraphrases were LLM-generated and initially LLM-validated (a potential
  circularity for an LLM-sensitivity study, documented in the repository);
  a full human review of all 118 active paraphrases was subsequently
  performed by an author, confirming meaning preservation.
- LLM-as-judge scores, though reliable (95.8% exact agreement), share training
  lineage with the agent model's vendor.
- Our chains are limited to 4 stages; whether the position effect and
  convergent-stage repair we observe persist, saturate, or reverse in much
  longer chains (tens to hundreds of agents) is an open question we did not
  test.

## 7. Conclusion

In four-stage LLM pipelines, semantically equivalent prompt rewordings do not
compound into runaway divergence: chains amplify their own sampling
nondeterminism far more than they amplify paraphrase perturbations, and
constrained late stages repair both. Robustness engineering for agent chains
should therefore (a) control for intrinsic nondeterminism before attributing
divergence to any manipulated variable, (b) invest prompt-hardening effort in
early-position agents, and (c) treat constrained, convergent final stages as a
cheap reliability mechanism.

## Acknowledgments

The author thanks Thai Le for feedback on an earlier draft of this paper.

## References

*(All entries verified against the papers on 2026-07-05.)*

- Zhu, K., et al. 2023. PromptBench: Towards Evaluating the Robustness of
  Large Language Models on Adversarial Prompts. arXiv:2306.04528.
- Sclar, M., Choi, Y., Tsvetkov, Y., Suhr, A. 2024. Quantifying Language
  Models' Sensitivity to Spurious Features in Prompt Design (or: How I
  learned to start worrying about prompt formatting). ICLR 2024.
  arXiv:2310.11324.
- Sun, J., et al. 2023. Evaluating the Zero-shot Robustness of
  Instruction-tuned Language Models. arXiv:2306.11270.
- Cao, B., et al. 2024. On the Worst Prompt Performance of Large Language
  Models. arXiv:2406.10248.
- Mizrahi, M., Kaplan, G., Malkin, D., Dror, R., Shahaf, D., Stanovsky, G.
  2024. State of What Art? A Call for Multi-Prompt LLM Evaluation. TACL 12,
  933–949. arXiv:2401.00595.
- Hallucination Cascade: Analyzing Error Propagation in Multi-Agent LLM
  Systems. 2026. arXiv:2606.07937.
- From Spark to Fire: Modeling and Mitigating Error Cascades in LLM-Based
  Multi-Agent Collaboration. 2026. arXiv:2603.04474.
- MAS-FIRE: Fault Injection and Reliability Evaluation for LLM-Based
  Multi-Agent Systems. 2026. arXiv:2602.19843.
- AgentAsk: Multi-Agent Systems Need to Ask. ACL 2026. arXiv:2510.07593.
- Atil, B., et al. 2024. Non-Determinism of "Deterministic" LLM Settings.
  arXiv:2408.04667. [source of the up-to-15% accuracy-variation figure and
  the up-to-70% best-worst gap]
- Ouyang, S., Zhang, J. M., Harman, M., Wang, M. 2023. An Empirical Study of
  the Non-determinism of ChatGPT in Code Generation. arXiv:2308.02828; ACM
  TOSEM 34(2), 2025.
- He, H. / Thinking Machines Lab. 2025. Defeating Nondeterminism in LLM
  Inference. thinkingmachines.ai blog, Sept 2025. [batch-invariance analysis]
- Laban, P., Hayashi, H., Zhou, Y., Neville, J. 2025. LLMs Get Lost in
  Multi-Turn Conversation. arXiv:2505.06120.
