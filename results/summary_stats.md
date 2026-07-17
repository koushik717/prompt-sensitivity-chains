# Summary statistics

## Provenance

- Total runs: **1470** (failures: **0**); agent calls: 4200 (1,891,503 in / 2,357,075 out tokens)
- Agent-call cost (exact, from logged tokens): **$13.68**
- Models: agents = `claude-haiku-4-5-20251001` (temp 0.0), paraphrase = `claude-sonnet-4-6` (temp 0.9), judge = `claude-sonnet-4-6` (temp 0.0, rubric v2)
- Embedder: `all-MiniLM-L6-v2`

- Perturbed runs analyzed: **1335** (backend: anthropic, agent model: claude-haiku-4-5-20251001)
- Nondeterminism noise floor (control, temp 0): **0.0926** mean cosine divergence (n=60)

## Primary: divergence vs depth

- Depth 1 mean divergence: **0.0996** [0.0908, 0.1084]
- Depth 4 mean divergence: **0.1272** [0.1186, 0.1364]
- Amplification ratio (d4/d1): **1.28x**
- Spearman trend (depth vs divergence): rho = **0.089**, p = 1.16e-03

Per-task Spearman rho: code_review: 0.339 (p=1.5e-13), research_plan: 0.225 (p=2.2e-06), summarization: -0.196 (p=2.8e-05)

## Tail risk: catastrophic divergence (divergence > 0.3)

- Depth 1: P90 = **0.1757**, P95 = **0.1884**, max = **0.2671**, catastrophe rate = **0.00%** [0.00%, 0.00%] (n=150)
- Depth 2: P90 = **0.2128**, P95 = **0.2654**, max = **0.3936**, catastrophe rate = **2.33%** [0.67%, 4.33%] (n=300)
- Depth 3: P90 = **0.3880**, P95 = **0.4404**, max = **0.5977**, catastrophe rate = **20.00%** [16.40%, 23.60%] (n=445)
- Depth 4: P90 = **0.2286**, P95 = **0.2538**, max = **1.0098**, catastrophe rate = **2.27%** [0.91%, 3.64%] (n=440)

- Spearman trend (depth vs catastrophe indicator): rho = **0.018**, p = 5.19e-01

## Noise-adjusted: paraphrase-attributable excess divergence

Excess = perturbed mean − control mean within the same (task, depth) cell. Control n is small (5/cell); treat as descriptive.

- code_review d1: perturbed **0.111** [0.099, 0.124] vs control **0.088** (n=5) → excess **+0.023**
- code_review d2: perturbed **0.099** [0.088, 0.113] vs control **0.072** (n=5) → excess **+0.027**
- code_review d3: perturbed **0.099** [0.089, 0.110] vs control **0.074** (n=5) → excess **+0.025**
- code_review d4: perturbed **0.152** [0.143, 0.161] vs control **0.126** (n=5) → excess **+0.025**
- research_plan d1: perturbed **0.104** [0.092, 0.116] vs control **0.066** (n=5) → excess **+0.038**
- research_plan d2: perturbed **0.173** [0.164, 0.183] vs control **0.110** (n=5) → excess **+0.063**
- research_plan d3: perturbed **0.322** [0.305, 0.338] vs control **0.297** (n=5) → excess **+0.024**
- research_plan d4: perturbed **0.182** [0.173, 0.190] vs control **0.218** (n=5) → excess **-0.037**
- summarization d1: perturbed **0.084** [0.065, 0.103] vs control **0.005** (n=5) → excess **+0.079**
- summarization d2: perturbed **0.058** [0.044, 0.074] vs control **0.002** (n=5) → excess **+0.056**
- summarization d3: perturbed **0.075** [0.062, 0.088] vs control **0.032** (n=5) → excess **+0.042**
- summarization d4: perturbed **0.052** [0.036, 0.072] vs control **0.019** (n=5) → excess **+0.032**

## Secondary: perturbation position (first vs last, depth >= 2)

- Mean divergence, first-position perturbation: **0.1554** (n=450)
- Mean divergence, last-position perturbation: **0.1163** (n=440)
- Mann-Whitney U p = 2.14e-10; Cliff's delta = **0.246** (positive = earlier perturbation diverges more)

## Success (LLM-as-judge, 0-10)

- Depth 1: mean score **8.43** [8.29, 8.58] (n=150)
- Depth 2: mean score **8.14** [8.03, 8.26] (n=300)
- Depth 3: mean score **7.34** [7.20, 7.48] (n=445)
- Depth 4: mean score **7.85** [7.71, 7.99] (n=440)

## Schema violation rate (structured tasks)

- Depth 4: **0.00%**

## Judge reliability (10% double-judged sample)

- n = 164; exact agreement **96.34%**; mean |diff| **0.04**
