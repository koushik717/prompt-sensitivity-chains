"""Per-run metrics vs the canonical-prompt baseline on the same (task, input, depth):

  - embedding cosine divergence of the final output (1 - cosine similarity)
  - output length and length ratio vs baseline
  - JSON schema violation flag (structured tasks only)
  - task success score via LLM-as-judge (fixed, versioned rubric; judge model
    separate from agent model; temperature 0)
  - judge reliability: a 10% sample is judged twice, agreement reported
  - control runs -> nondeterminism noise floor

Judgments are cached in results/raw/judgments.jsonl (resume-safe).
Usage: python -m src.metrics
Output: results/processed/metrics.csv, control_metrics.csv, judge_reliability.csv
"""
from __future__ import annotations

import asyncio
import json
import random
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .llm_client import LLMClient, load_config, load_tasks

ROOT = Path(__file__).resolve().parents[1]

JUDGE_SYSTEM_TEMPLATE = (
    "You are an impartial evaluator. Grade strictly according to the rubric.\n\n"
    "RUBRIC (version {version}):\n{rubric}"
)
JUDGE_USER_TEMPLATE = (
    "ORIGINAL TASK INPUT:\n---\n{input}\n---\n\n"
    "OUTPUT TO GRADE:\n---\n{output}\n---"
)


def load_runs(cfg) -> list[dict]:
    path = ROOT / cfg["paths"]["raw_dir"] / "runs.jsonl"
    runs, seen = [], {}
    with open(path) as f:
        for line in f:
            rec = json.loads(line)
            seen[rec["run_id"]] = rec  # later lines win (resume reruns)
    runs = [r for r in seen.values() if r["status"] == "ok"]
    return runs


def embed_outputs(cfg, texts: list[str]) -> tuple[np.ndarray, str]:
    from .embedding import get_embedder
    model, name = get_embedder(cfg["paraphrase_validation"]["embedding_model"])
    return (model.encode(texts, normalize_embeddings=True,
                         show_progress_bar=False), name)


def schema_violation(task: dict, output: str, depth: int) -> bool | None:
    """Only meaningful when the structured-output agent (last role) actually ran."""
    if not task.get("structured_output") or depth < len(task["roles"]):
        return None
    try:
        m = re.search(r"\{.*\}", output, re.DOTALL)
        obj = json.loads(m.group(0) if m else output)
        required = set(task["output_schema"]["required_keys"])
        return not required.issubset(obj.keys())
    except (json.JSONDecodeError, AttributeError, TypeError):
        return True


def parse_judge(text: str) -> int | None:
    try:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        score = int(json.loads(m.group(0))["score"])
        return score if 0 <= score <= 10 else None
    except Exception:  # noqa: BLE001
        return None


async def judge_runs(cfg, tasks, runs: list[dict]) -> tuple[dict, list[dict]]:
    """Judge every ok run's final output; cache; re-judge a 10% sample twice."""
    cache_path = ROOT / cfg["paths"]["raw_dir"] / "judgments.jsonl"
    cache: dict[str, dict] = {}
    if cache_path.exists():
        with open(cache_path) as f:
            for line in f:
                j = json.loads(line)
                cache[f"{j['run_id']}#{j['pass_n']}"] = j

    client = LLMClient(cfg)
    rng = random.Random(cfg["generation"]["seed"])
    resample = {r["run_id"] for r in runs if rng.random() < 0.10}

    async def judge_one(run: dict, pass_n: int):
        key = f"{run['run_id']}#{pass_n}"
        if key in cache:
            return
        task = tasks[run["task"]]
        inp = next(i["text"] for i in task["inputs"] if i["id"] == run["input_id"])
        # depth-appropriate rubric: grade the artifact the depth-k chain
        # actually produces (falls back to the full-pipeline rubric)
        rubric = task.get("judge_rubrics_by_depth", {}).get(
            run["depth"], task["judge_rubric"])
        comp = await client.complete(
            system=JUDGE_SYSTEM_TEMPLATE.format(
                version=task["judge_rubric_version"], rubric=rubric),
            user=JUDGE_USER_TEMPLATE.format(input=inp, output=run["final_output"]),
            model=cfg["models"]["judge"],
            temperature=cfg["generation"]["judge_temperature"],
            max_tokens=256, is_judge=True)
        j = {"run_id": run["run_id"], "pass_n": pass_n,
             "score": parse_judge(comp.text), "raw": comp.text,
             "judge_model": comp.model,
             "rubric_version": task["judge_rubric_version"]}
        cache[key] = j
        with open(cache_path, "a") as f:
            f.write(json.dumps(j) + "\n")

    jobs = [judge_one(r, 1) for r in runs]
    jobs += [judge_one(r, 2) for r in runs if r["run_id"] in resample]
    await asyncio.gather(*jobs)
    print(f"judging done ({len(jobs)} jobs, est ${client.cost.total_usd:.2f})")

    scores = {rid_pass.split("#")[0]: j["score"]
              for rid_pass, j in cache.items() if j["pass_n"] == 1}
    reliability = []
    for r in runs:
        if r["run_id"] in resample:
            s1 = cache.get(f"{r['run_id']}#1", {}).get("score")
            s2 = cache.get(f"{r['run_id']}#2", {}).get("score")
            if s1 is not None and s2 is not None:
                reliability.append({"run_id": r["run_id"], "score_1": s1,
                                    "score_2": s2, "abs_diff": abs(s1 - s2)})
    return scores, reliability


def degenerate_paraphrases(cfg, tasks) -> set[tuple[str, int, int]]:
    """(task, position_idx, paraphrase_idx) triples whose 'paraphrase' is
    byte-identical (whitespace/case-normalized) to the base prompt.
    Runs perturbed with these are not perturbations; exclude and disclose."""
    from .llm_client import load_base_prompts, load_paraphrases
    base = load_base_prompts(ROOT, cfg)
    paras = load_paraphrases(ROOT, cfg)
    norm = lambda s: re.sub(r"\s+", " ", s.strip().lower())  # noqa: E731
    out = set()
    for tname, task in tasks.items():
        for ridx, role in enumerate(task["roles"]):
            b = norm(base[tname][role])
            for j, p in enumerate(paras.get(tname, {}).get(role, [])):
                if norm(p) == b:
                    out.add((tname, ridx, j))
    return out


def main():
    cfg = load_config(ROOT)
    tasks = load_tasks(ROOT, cfg)
    runs = load_runs(cfg)
    print(f"{len(runs)} ok runs loaded")

    degen = degenerate_paraphrases(cfg, tasks)
    if degen:
        before = len(runs)
        excluded = [r for r in runs if r["condition"] == "perturbed"
                    and (r["task"], r.get("position_idx"),
                         r.get("paraphrase_idx")) in degen]
        runs = [r for r in runs if r not in excluded]
        print(f"degenerate paraphrases (identical to base): "
              f"{sorted(degen)} -> excluded {before - len(runs)} "
              f"pseudo-perturbed runs")

    by_id = {r["run_id"]: r for r in runs}
    baselines = {(r["task"], r["input_id"], r["depth"]): r
                 for r in runs if r["condition"] == "baseline"}

    # --- embeddings (batch) ---
    texts = [r["final_output"] for r in runs]
    embs, emb_name = embed_outputs(cfg, texts)
    emb_by_id = {r["run_id"]: embs[i] for i, r in enumerate(runs)}

    # --- judge ---
    scores, reliability = asyncio.run(judge_runs(cfg, tasks, runs))

    rows, control_rows = [], []
    for r in runs:
        base = baselines.get((r["task"], r["input_id"], r["depth"]))
        if base is None:
            continue
        div = float(1.0 - emb_by_id[r["run_id"]] @ emb_by_id[base["run_id"]])
        row = {
            "run_id": r["run_id"], "task": r["task"], "input_id": r["input_id"],
            "depth": r["depth"], "condition": r["condition"],
            "paraphrase_idx": r.get("paraphrase_idx"),
            "position": r.get("position"), "position_idx": r.get("position_idx"),
            "divergence": div,
            "out_len": len(r["final_output"]),
            "base_len": len(base["final_output"]),
            "len_ratio": len(r["final_output"]) / max(1, len(base["final_output"])),
            "schema_violation": schema_violation(tasks[r["task"]],
                                                 r["final_output"], r["depth"]),
            "judge_score": scores.get(r["run_id"]),
            "base_judge_score": scores.get(base["run_id"]),
            "agent_model": r["agent_model"], "backend": r["backend"],
            "embedder": emb_name,
        }
        if r["condition"] == "control":
            control_rows.append(row)
        elif r["condition"] == "perturbed":
            rows.append(row)

    out = ROOT / cfg["paths"]["processed_dir"]
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out / "metrics.csv", index=False)
    pd.DataFrame(control_rows).to_csv(out / "control_metrics.csv", index=False)
    rel = pd.DataFrame(reliability)
    rel.to_csv(out / "judge_reliability.csv", index=False)

    print(f"metrics.csv: {len(rows)} perturbed rows; "
          f"control rows: {len(control_rows)}")
    if len(rel):
        print(f"judge reliability (n={len(rel)}): exact agreement "
              f"{(rel.abs_diff == 0).mean():.2%}, mean |diff| {rel.abs_diff.mean():.2f}")


if __name__ == "__main__":
    main()
