"""Full experiment grid with checkpoint/resume, rate limiting, and cost guard.

Conditions per task x input x depth:
  baseline   canonical prompt at every position (the reference run for metrics)
  perturbed  exactly ONE position uses paraphrase j; position in {first, middle, last}
             (deduped: depth 1 -> first; depth 2 -> first,last; depth>=3 -> all three)
  control    canonical chain repeated `control_repeats` times at temp 0 on one input
             -> quantifies residual nondeterminism (noise floor)

Usage:
  python -m src.experiment --dry-run          # count calls + cost estimate, no API
  python -m src.experiment --pilot            # 1 task, 3 paraphrases, all depths
  python -m src.experiment --yes              # full grid without interactive confirm

Raw output: results/raw/runs.jsonl (append-only; run_id is deterministic, so
re-running skips completed runs and retries failed ones).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from .chain_runner import canonical_prompts, run_chain
from .llm_client import (BudgetExceeded, LLMClient, estimate_tokens,
                         load_base_prompts, load_config, load_paraphrases,
                         load_tasks)

ROOT = Path(__file__).resolve().parents[1]
EST_OUTPUT_TOKENS = 300  # per-call output estimate for dry runs


@dataclass(frozen=True)
class RunSpec:
    run_id: str
    condition: str          # baseline | perturbed | control
    task: str
    input_id: str
    input_idx: int
    depth: int
    paraphrase_idx: int | None = None
    position: str | None = None      # first | middle | last
    position_idx: int | None = None
    repeat: int | None = None


def positions_for_depth(depth: int) -> list[tuple[str, int]]:
    if depth == 1:
        return [("first", 0)]
    if depth == 2:
        return [("first", 0), ("last", 1)]
    return [("first", 0), ("middle", depth // 2), ("last", depth - 1)]


def build_grid(cfg: dict, tasks: dict, *, task_filter: list[str] | None,
               n_paraphrases: int, n_inputs: int) -> list[RunSpec]:
    exp = cfg["experiment"]
    specs: list[RunSpec] = []
    for tname, task in sorted(tasks.items()):
        if task_filter and tname not in task_filter:
            continue
        inputs = task["inputs"][:n_inputs]
        for depth in exp["depths"]:
            for ii, inp in enumerate(inputs):
                specs.append(RunSpec(
                    run_id=f"{tname}|{inp['id']}|d{depth}|baseline",
                    condition="baseline", task=tname, input_id=inp["id"],
                    input_idx=ii, depth=depth))
                for pos, pidx in positions_for_depth(depth):
                    for j in range(n_paraphrases):
                        specs.append(RunSpec(
                            run_id=f"{tname}|{inp['id']}|d{depth}|p{j}|{pos}",
                            condition="perturbed", task=tname, input_id=inp["id"],
                            input_idx=ii, depth=depth, paraphrase_idx=j,
                            position=pos, position_idx=pidx))
            # control: canonical repeats on one input (noise floor)
            ci = exp["control_input_index"]
            if ci < len(inputs):
                for r in range(exp["control_repeats"]):
                    specs.append(RunSpec(
                        run_id=f"{tname}|{inputs[ci]['id']}|d{depth}|control|r{r}",
                        condition="control", task=tname,
                        input_id=inputs[ci]["id"], input_idx=ci,
                        depth=depth, repeat=r))
    return specs


def dry_run_report(cfg: dict, tasks: dict, base_prompts: dict,
                   specs: list[RunSpec]) -> float:
    prices = cfg["cost"]["prices"]
    model = cfg["models"]["agent"]
    p = prices.get(model, max(prices.values(), key=lambda x: x["output"]))
    calls = in_tok = out_tok = 0
    for s in specs:
        task = tasks[s.task]
        inp_tok = estimate_tokens(task["inputs"][s.input_idx]["text"])
        for i in range(s.depth):
            sys_tok = estimate_tokens(base_prompts[s.task][task["roles"][i]])
            calls += 1
            in_tok += sys_tok + (inp_tok if i == 0 else EST_OUTPUT_TOKENS)
            out_tok += EST_OUTPUT_TOKENS
    cost = in_tok * p["input"] / 1e6 + out_tok * p["output"] / 1e6
    by_cond = {}
    for s in specs:
        by_cond[s.condition] = by_cond.get(s.condition, 0) + 1
    print(f"planned runs : {len(specs)}  {by_cond}")
    print(f"planned calls: {calls}  (agent model: {model})")
    print(f"est tokens   : {in_tok:,} in / {out_tok:,} out")
    print(f"EST COST     : ${cost:.2f}  (budget ${cfg['cost']['budget_usd']:.2f})")
    return cost


def load_completed(raw_path: Path) -> set[str]:
    done = set()
    if raw_path.exists():
        with open(raw_path) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("status") == "ok":
                    done.add(rec["run_id"])
    return done


def prompts_for_spec(s: RunSpec, task: dict, base_prompts: dict,
                     paraphrases: dict) -> list[str]:
    prompts = canonical_prompts(base_prompts, task, s.depth)
    if s.condition == "perturbed":
        role = task["roles"][s.position_idx]
        prompts[s.position_idx] = paraphrases[s.task][role][s.paraphrase_idx]
    return prompts


async def execute(cfg: dict, tasks: dict, base_prompts: dict, paraphrases: dict,
                  specs: list[RunSpec]) -> None:
    raw_dir = ROOT / cfg["paths"]["raw_dir"]
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / "runs.jsonl"
    done = load_completed(raw_path)
    todo = [s for s in specs if s.run_id not in done]
    print(f"{len(done)} runs already completed; {len(todo)} to run")
    if not todo:
        return

    client = LLMClient(cfg)
    write_lock = asyncio.Lock()
    counter = {"done": 0, "failed": 0}

    async def one(s: RunSpec):
        task = tasks[s.task]
        rec = await run_chain(
            client, cfg, task=task,
            system_prompts=prompts_for_spec(s, task, base_prompts, paraphrases),
            input_text=task["inputs"][s.input_idx]["text"])
        rec.update({
            "run_id": s.run_id, "condition": s.condition, "input_id": s.input_id,
            "paraphrase_idx": s.paraphrase_idx, "position": s.position,
            "position_idx": s.position_idx, "repeat": s.repeat,
            "backend": cfg["backend"], "agent_model": cfg["models"]["agent"],
            "temperature": cfg["generation"]["temperature"],
            "seed": cfg["generation"]["seed"],
        })
        async with write_lock:
            with open(raw_path, "a") as f:
                f.write(json.dumps(rec) + "\n")
            counter["done"] += 1
            if rec["status"] != "ok":
                counter["failed"] += 1
            if counter["done"] % 50 == 0 or counter["done"] == len(todo):
                print(f"  [{counter['done']}/{len(todo)}] "
                      f"failed={counter['failed']} est ${client.cost.total_usd:.2f}")

    try:
        await asyncio.gather(*(one(s) for s in todo))
    except BudgetExceeded as e:
        print(f"\nBUDGET GUARD: {e}")
        sys.exit(2)
    print(f"finished. failures: {counter['failed']}  "
          f"est cost: ${client.cost.total_usd:.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true", help="skip confirmation")
    ap.add_argument("--pilot", action="store_true",
                    help="1 task, 3 paraphrases, all depths")
    ap.add_argument("--tasks", nargs="*", default=None)
    ap.add_argument("--n-paraphrases", type=int, default=None)
    ap.add_argument("--n-inputs", type=int, default=None)
    args = ap.parse_args()

    cfg = load_config(ROOT)
    tasks = load_tasks(ROOT, cfg)
    base_prompts = load_base_prompts(ROOT, cfg)
    paraphrases = load_paraphrases(ROOT, cfg)

    task_filter = args.tasks
    n_para = args.n_paraphrases or cfg["experiment"]["n_paraphrases"]
    n_inputs = args.n_inputs or cfg["experiment"]["n_inputs"]
    if args.pilot:
        task_filter, n_para = ["summarization"], 3

    missing = [t for t in (task_filter or tasks) if t not in paraphrases]
    if missing and not args.dry_run:
        sys.exit(f"No paraphrases for {missing}. Run src.paraphrase_gen + "
                 f"src.validate_paraphrases first.")

    specs = build_grid(cfg, tasks, task_filter=task_filter,
                       n_paraphrases=n_para, n_inputs=n_inputs)
    cost = dry_run_report(cfg, tasks, base_prompts, specs)
    if args.dry_run:
        return
    if cost > cfg["cost"]["budget_usd"]:
        sys.exit("Estimated cost exceeds budget; shrink the grid or raise budget.")
    if not args.yes and cfg["backend"] != "mock":
        if input("Proceed with these API calls? [y/N] ").strip().lower() != "y":
            sys.exit("aborted")
    asyncio.run(execute(cfg, tasks, base_prompts, paraphrases, specs))


if __name__ == "__main__":
    main()
