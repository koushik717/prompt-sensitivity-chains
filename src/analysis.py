"""Aggregate analysis.

Primary: divergence vs depth (bootstrap 95% CIs, Spearman monotonic trend).
Secondary: perturbation-position effect (first vs last; Mann-Whitney + Cliff's delta).
Also: success vs depth, schema violations, noise floor from control condition.

Usage: python -m src.analysis
Output: results/processed/master_results.csv, divergence_by_depth.csv,
        position_effect.csv, results/summary_stats.md
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from .llm_client import load_config

ROOT = Path(__file__).resolve().parents[1]
N_BOOT = 5000
SEED = 0
CATASTROPHE_THRESHOLD = 0.3  # divergence above this = catastrophic chain failure


def bootstrap_ci(x: np.ndarray, stat=np.mean, n=N_BOOT, alpha=0.05,
                 seed=SEED) -> tuple[float, float, float]:
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) == 0:
        return (np.nan, np.nan, np.nan)
    rng = np.random.default_rng(seed)
    boots = np.array([stat(rng.choice(x, size=len(x), replace=True))
                      for _ in range(n)])
    return (float(stat(x)), float(np.percentile(boots, 100 * alpha / 2)),
            float(np.percentile(boots, 100 * (1 - alpha / 2))))


def cliffs_delta(a: np.ndarray, b: np.ndarray) -> float:
    """Effect size in [-1, 1]: P(a > b) - P(a < b)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    gt = sum((x > b).sum() for x in a)
    lt = sum((x < b).sum() for x in a)
    return float((gt - lt) / (len(a) * len(b)))


def provenance(cfg) -> dict:
    """Run counts, failure count, and exact agent-call cost from raw logs."""
    import json
    path = ROOT / cfg["paths"]["raw_dir"] / "runs.jsonl"
    seen = {}
    with open(path) as f:
        for line in f:
            rec = json.loads(line)
            seen[rec["run_id"]] = rec
    prices = cfg["cost"]["prices"]
    cost = calls = in_tok = out_tok = 0
    failures = 0
    for rec in seen.values():
        if rec["status"] != "ok":
            failures += 1
            continue
        for a in rec["agents"]:
            p = prices.get(a["model"].split("/")[-1],
                           max(prices.values(), key=lambda x: x["output"]))
            cost += a["input_tokens"] * p["input"] / 1e6 \
                + a["output_tokens"] * p["output"] / 1e6
            calls += 1
            in_tok += a["input_tokens"]
            out_tok += a["output_tokens"]
    return {"total_runs": len(seen), "failures": failures,
            "agent_calls": calls, "input_tokens": in_tok,
            "output_tokens": out_tok, "agent_cost_usd": cost}


def main():
    cfg = load_config(ROOT)
    proc = ROOT / cfg["paths"]["processed_dir"]
    df = pd.read_csv(proc / "metrics.csv")
    ctrl = pd.read_csv(proc / "control_metrics.csv")
    prov = provenance(cfg)

    # ---- noise floor: control divergence (canonical repeats vs baseline) ----
    noise_floor = float(ctrl["divergence"].mean()) if len(ctrl) else np.nan
    # per-(task, depth) noise floor and paraphrase-attributable EXCESS divergence.
    # Intrinsic temp-0 nondeterminism itself grows with depth on open-ended
    # tasks, so raw perturbed divergence overstates the paraphrase effect;
    # excess = perturbed mean - control mean within the same (task, depth) cell.
    ctrl_cell = ctrl.groupby(["task", "depth"])["divergence"].mean()
    excess_rows = []
    for (t, d), g in df.groupby(["task", "depth"]):
        nf = float(ctrl_cell.get((t, d), np.nan))
        m, lo, hi = bootstrap_ci(g["divergence"].values)
        excess_rows.append({"task": t, "depth": d, "n": len(g),
                            "perturbed_mean": m, "ci_lo": lo, "ci_hi": hi,
                            "control_mean": nf, "excess": m - nf,
                            "n_control": int(ctrl[(ctrl.task == t) &
                                                  (ctrl.depth == d)].shape[0])})
    excess = pd.DataFrame(excess_rows)
    excess.to_csv(proc / "excess_divergence.csv", index=False)

    # ---- divergence vs depth ----
    rows = []
    for (depth,), g in df.groupby(["depth"]):
        m, lo, hi = bootstrap_ci(g["divergence"].values)
        rows.append({"task": "ALL", "depth": depth, "n": len(g),
                     "mean_divergence": m, "ci_lo": lo, "ci_hi": hi})
    for (task, depth), g in df.groupby(["task", "depth"]):
        m, lo, hi = bootstrap_ci(g["divergence"].values)
        rows.append({"task": task, "depth": depth, "n": len(g),
                     "mean_divergence": m, "ci_lo": lo, "ci_hi": hi})
    by_depth = pd.DataFrame(rows)
    by_depth.to_csv(proc / "divergence_by_depth.csv", index=False)

    rho, p_rho = stats.spearmanr(df["depth"], df["divergence"])
    trend_by_task = {t: stats.spearmanr(g["depth"], g["divergence"])
                     for t, g in df.groupby("task")}

    # ---- tail risk: catastrophic failures, not just mean shift ----
    def tail_stats(g: pd.DataFrame) -> dict:
        x = g["divergence"].values
        cat = x > CATASTROPHE_THRESHOLD
        cat_rate, cat_lo, cat_hi = bootstrap_ci(cat.astype(float))
        return {"n": len(x), "p50": float(np.percentile(x, 50)),
                "p90": float(np.percentile(x, 90)),
                "p95": float(np.percentile(x, 95)), "max": float(x.max()),
                "catastrophe_rate": cat_rate,
                "cat_ci_lo": cat_lo, "cat_ci_hi": cat_hi}

    tail_rows = [{"task": "ALL", "depth": d, **tail_stats(g)}
                 for d, g in df.groupby("depth")]
    tail_rows += [{"task": t, "depth": d, **tail_stats(g)}
                  for (t, d), g in df.groupby(["task", "depth"])]
    tail = pd.DataFrame(tail_rows)
    tail.to_csv(proc / "tail_metrics.csv", index=False)
    # monotone trend in catastrophe rate across depth (ALL tasks)
    tail_all = tail[tail.task == "ALL"].sort_values("depth")
    cat_rho, cat_p = stats.spearmanr(df["depth"],
                                     (df["divergence"] > CATASTROPHE_THRESHOLD)
                                     .astype(int))

    # ---- position effect (only depths where both first and last exist) ----
    pos_df = df[(df.depth >= 2) & df.position.isin(["first", "last"])]
    first = pos_df[pos_df.position == "first"]["divergence"].values
    last = pos_df[pos_df.position == "last"]["divergence"].values
    if len(first) and len(last):
        u, p_pos = stats.mannwhitneyu(first, last, alternative="two-sided")
        delta = cliffs_delta(first, last)
    else:
        u = p_pos = delta = np.nan
    pos_rows = []
    for pos, g in df[df.depth >= 3].groupby("position"):
        m, lo, hi = bootstrap_ci(g["divergence"].values)
        pos_rows.append({"position": pos, "n": len(g), "mean_divergence": m,
                         "ci_lo": lo, "ci_hi": hi})
    pd.DataFrame(pos_rows).to_csv(proc / "position_effect.csv", index=False)

    # ---- success vs depth ----
    succ = df.dropna(subset=["judge_score"])
    succ_rows = [{"depth": d,
                  **dict(zip(["mean_score", "ci_lo", "ci_hi"],
                             bootstrap_ci(g["judge_score"].values))),
                  "n": len(g)}
                 for d, g in succ.groupby("depth")]
    pd.DataFrame(succ_rows).to_csv(proc / "success_by_depth.csv", index=False)

    # ---- master results ----
    df.to_csv(proc / "master_results.csv", index=False)

    # ---- schema violations (structured tasks) ----
    sv = df.dropna(subset=["schema_violation"])
    sv_rate = sv.groupby("depth")["schema_violation"].mean() if len(sv) else None

    # ---- judge reliability ----
    rel_path = proc / "judge_reliability.csv"
    rel = pd.read_csv(rel_path) if rel_path.exists() else pd.DataFrame()

    # ---- summary markdown ----
    d1 = by_depth[(by_depth.task == "ALL") & (by_depth.depth == 1)].iloc[0]
    d4 = by_depth[(by_depth.task == "ALL") & (by_depth.depth == df.depth.max())].iloc[0]
    lines = [
        "# Summary statistics",
        "",
        "## Provenance",
        "",
        f"- Total runs: **{prov['total_runs']}** "
        f"(failures: **{prov['failures']}**); "
        f"agent calls: {prov['agent_calls']} "
        f"({prov['input_tokens']:,} in / {prov['output_tokens']:,} out tokens)",
        f"- Agent-call cost (exact, from logged tokens): "
        f"**${prov['agent_cost_usd']:.2f}**",
        f"- Models: agents = `{cfg['models']['agent']}` (temp "
        f"{cfg['generation']['temperature']}), paraphrase = "
        f"`{cfg['models']['paraphrase']}` (temp "
        f"{cfg['generation']['paraphrase_temperature']}), judge = "
        f"`{cfg['models']['judge']}` (temp "
        f"{cfg['generation']['judge_temperature']}, rubric v2)",
        f"- Embedder: `{df.embedder.iloc[0]}`",
        "",
        f"- Perturbed runs analyzed: **{len(df)}** "
        f"(backend: {df.backend.iloc[0]}, agent model: {df.agent_model.iloc[0]})",
        f"- Nondeterminism noise floor (control, temp 0): "
        f"**{noise_floor:.4f}** mean cosine divergence (n={len(ctrl)})",
        "",
        "## Primary: divergence vs depth",
        "",
        f"- Depth 1 mean divergence: **{d1.mean_divergence:.4f}** "
        f"[{d1.ci_lo:.4f}, {d1.ci_hi:.4f}]",
        f"- Depth {int(d4.depth)} mean divergence: **{d4.mean_divergence:.4f}** "
        f"[{d4.ci_lo:.4f}, {d4.ci_hi:.4f}]",
        f"- Amplification ratio (d{int(d4.depth)}/d1): "
        f"**{d4.mean_divergence / max(d1.mean_divergence, 1e-9):.2f}x**",
        f"- Spearman trend (depth vs divergence): rho = **{rho:.3f}**, "
        f"p = {p_rho:.2e}",
        "",
        "Per-task Spearman rho: "
        + ", ".join(f"{t}: {r.statistic:.3f} (p={r.pvalue:.1e})"
                    for t, r in trend_by_task.items()),
        "",
        "## Tail risk: catastrophic divergence "
        f"(divergence > {CATASTROPHE_THRESHOLD})",
        "",
    ] + [
        f"- Depth {int(r.depth)}: P90 = **{r.p90:.4f}**, P95 = **{r.p95:.4f}**, "
        f"max = **{r['max']:.4f}**, catastrophe rate = "
        f"**{r.catastrophe_rate:.2%}** [{r.cat_ci_lo:.2%}, {r.cat_ci_hi:.2%}] "
        f"(n={int(r.n)})"
        for _, r in tail_all.iterrows()
    ] + [
        "",
        f"- Spearman trend (depth vs catastrophe indicator): "
        f"rho = **{cat_rho:.3f}**, p = {cat_p:.2e}",
        "",
        "## Noise-adjusted: paraphrase-attributable excess divergence",
        "",
        "Excess = perturbed mean − control mean within the same (task, depth) "
        "cell. Control n is small (5/cell); treat as descriptive.",
        "",
    ] + [
        f"- {r.task} d{int(r.depth)}: perturbed **{r.perturbed_mean:.3f}** "
        f"[{r.ci_lo:.3f}, {r.ci_hi:.3f}] vs control **{r.control_mean:.3f}** "
        f"(n={int(r.n_control)}) → excess **{r.excess:+.3f}**"
        for _, r in excess.iterrows()
    ] + [
        "",
        "## Secondary: perturbation position (first vs last, depth >= 2)",
        "",
        f"- Mean divergence, first-position perturbation: **{np.mean(first):.4f}** "
        f"(n={len(first)})",
        f"- Mean divergence, last-position perturbation: **{np.mean(last):.4f}** "
        f"(n={len(last)})",
        f"- Mann-Whitney U p = {p_pos:.2e}; Cliff's delta = **{delta:.3f}** "
        f"(positive = earlier perturbation diverges more)",
        "",
        "## Success (LLM-as-judge, 0-10)",
        "",
    ]
    for r in succ_rows:
        lines.append(f"- Depth {int(r['depth'])}: mean score "
                     f"**{r['mean_score']:.2f}** "
                     f"[{r['ci_lo']:.2f}, {r['ci_hi']:.2f}] (n={r['n']})")
    if sv_rate is not None:
        lines += ["", "## Schema violation rate (structured tasks)", ""]
        lines += [f"- Depth {int(d)}: **{v:.2%}**" for d, v in sv_rate.items()]
    if len(rel):
        lines += ["", "## Judge reliability (10% double-judged sample)", "",
                  f"- n = {len(rel)}; exact agreement "
                  f"**{(rel.abs_diff == 0).mean():.2%}**; "
                  f"mean |diff| **{rel.abs_diff.mean():.2f}**"]
    if df.backend.iloc[0].startswith("mock") or df.backend.iloc[0] == "mock":
        lines += ["", "> **NOTE:** these numbers come from the deterministic MOCK "
                  "backend and validate the pipeline only. They are NOT research "
                  "findings. Re-run with backend: anthropic for real data."]
    (ROOT / "results" / "summary_stats.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
