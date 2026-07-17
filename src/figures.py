"""Publication-quality vector figures (PDF).

  1. divergence_vs_depth.pdf  - overall curve with bootstrap 95% CI + noise floor
  2. per_task_curves.pdf      - per-task divergence vs depth
  3. success_vs_depth.pdf     - judge score vs depth with CI
  4. divergence_violins.pdf   - divergence distribution per depth (violin)

Usage: python -m src.figures
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from .llm_client import load_config

ROOT = Path(__file__).resolve().parents[1]

plt.rcParams.update({
    "figure.figsize": (5.0, 3.4), "figure.dpi": 150,
    "font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
    "pdf.fonttype": 42,  # embed TrueType -> editable text in the PDF
})
COLORS = ["#4053d3", "#ddb310", "#b51d14"]


def fig_divergence_vs_depth(by_depth, noise_floor, out):
    g = by_depth[by_depth.task == "ALL"].sort_values("depth")
    fig, ax = plt.subplots()
    ax.fill_between(g.depth, g.ci_lo, g.ci_hi, alpha=0.20, color=COLORS[0],
                    label="bootstrap 95% CI")
    ax.plot(g.depth, g.mean_divergence, "o-", color=COLORS[0], ms=4,
            label="mean divergence")
    if pd.notna(noise_floor):
        ax.axhline(noise_floor, ls="--", lw=1, color="gray",
                   label=f"noise floor ({noise_floor:.3f})")
    ax.set_xlabel("Chain depth (number of agents)")
    ax.set_ylabel("Cosine divergence vs canonical run")
    ax.set_xticks(g.depth)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "divergence_vs_depth.pdf")
    plt.close(fig)


def fig_per_task(by_depth, out):
    fig, ax = plt.subplots()
    tasks = [t for t in by_depth.task.unique() if t != "ALL"]
    for i, t in enumerate(sorted(tasks)):
        g = by_depth[by_depth.task == t].sort_values("depth")
        c = COLORS[i % len(COLORS)]
        ax.fill_between(g.depth, g.ci_lo, g.ci_hi, alpha=0.15, color=c)
        ax.plot(g.depth, g.mean_divergence, "o-", ms=4, color=c, label=t)
    ax.set_xlabel("Chain depth (number of agents)")
    ax.set_ylabel("Cosine divergence vs canonical run")
    ax.set_xticks(sorted(by_depth.depth.unique()))
    ax.legend(frameon=False, fontsize=8, title="task")
    fig.tight_layout()
    fig.savefig(out / "per_task_curves.pdf")
    plt.close(fig)


def fig_success(succ, out):
    g = succ.sort_values("depth")
    fig, ax = plt.subplots()
    ax.errorbar(g.depth, g.mean_score,
                yerr=[g.mean_score - g.ci_lo, g.ci_hi - g.mean_score],
                fmt="o-", ms=4, capsize=3, color=COLORS[2])
    ax.set_xlabel("Chain depth (number of agents)")
    ax.set_ylabel("LLM-as-judge score (0-10)")
    ax.set_xticks(g.depth)
    ax.set_ylim(0, 10)
    fig.tight_layout()
    fig.savefig(out / "success_vs_depth.pdf")
    plt.close(fig)


def fig_violins(df, out):
    depths = sorted(df.depth.unique())
    data = [df[df.depth == d]["divergence"].dropna().values for d in depths]
    fig, ax = plt.subplots()
    parts = ax.violinplot(data, positions=depths, widths=0.7,
                          showmedians=True, showextrema=False)
    for pc in parts["bodies"]:
        pc.set_facecolor(COLORS[0]); pc.set_alpha(0.5)
    parts["cmedians"].set_color("black")
    ax.set_xlabel("Chain depth (number of agents)")
    ax.set_ylabel("Cosine divergence vs canonical run")
    ax.set_xticks(depths)
    fig.tight_layout()
    fig.savefig(out / "divergence_violins.pdf")
    plt.close(fig)


def main():
    cfg = load_config(ROOT)
    proc = ROOT / cfg["paths"]["processed_dir"]
    out = ROOT / cfg["paths"]["figures_dir"]
    out.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(proc / "metrics.csv")
    by_depth = pd.read_csv(proc / "divergence_by_depth.csv")
    succ = pd.read_csv(proc / "success_by_depth.csv")
    ctrl = pd.read_csv(proc / "control_metrics.csv")
    noise_floor = ctrl["divergence"].mean() if len(ctrl) else float("nan")

    fig_divergence_vs_depth(by_depth, noise_floor, out)
    fig_per_task(by_depth, out)
    fig_success(succ, out)
    fig_violins(df, out)
    print(f"wrote 4 PDFs to {out}")


if __name__ == "__main__":
    main()
