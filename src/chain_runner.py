"""Run a sequential agent chain of depth 1-4.

Agent i receives (system_prompt_i, input_i) where input_1 is the task input
document and input_{i+1} is agent i's raw output. The depth-k final output is
agent k's output. Everything is logged: full prompts, full outputs, model
version, timestamps, token counts.

Smoke test: python -m src.chain_runner --task summarization --input 0 --depth 4
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
from pathlib import Path

from .llm_client import LLMClient, load_base_prompts, load_config, load_tasks

ROOT = Path(__file__).resolve().parents[1]


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


async def run_chain(client: LLMClient, cfg: dict, *, task: dict,
                    system_prompts: list[str], input_text: str) -> dict:
    """Run one chain; returns a fully-logged record (never fabricates output:
    on failure the record carries status='failed' and stops at the failing agent)."""
    depth = len(system_prompts)
    record = {
        "started_at": utcnow(),
        "task": task["name"],
        "depth": depth,
        "agents": [],
        "final_output": None,
        "status": "ok",
        "error": None,
    }
    current = input_text
    for i, sys_prompt in enumerate(system_prompts):
        role = task["roles"][i]
        try:
            comp = await client.complete(
                system=sys_prompt, user=current,
                model=cfg["models"]["agent"],
                temperature=cfg["generation"]["temperature"],
                max_tokens=cfg["generation"]["max_tokens"],
            )
        except Exception as e:  # noqa: BLE001 — logged as failure, never fabricated
            record["status"] = "failed"
            record["error"] = f"agent {i} ({role}): {e}"
            break
        record["agents"].append({
            "position": i, "role": role, "system_prompt": sys_prompt,
            "input": current, "output": comp.text, "model": comp.model,
            "input_tokens": comp.input_tokens, "output_tokens": comp.output_tokens,
            "stop_reason": comp.stop_reason, "latency_s": round(comp.latency_s, 3),
            "timestamp": utcnow(),
        })
        current = comp.text
    if record["status"] == "ok":
        record["final_output"] = current
    record["finished_at"] = utcnow()
    return record


def canonical_prompts(base_prompts: dict, task: dict, depth: int) -> list[str]:
    return [" ".join(base_prompts[task["name"]][r].split()) for r in task["roles"][:depth]]


async def _smoke(task_name: str, input_idx: int, depth: int):
    cfg = load_config(ROOT)
    tasks = load_tasks(ROOT, cfg)
    base = load_base_prompts(ROOT, cfg)
    task = tasks[task_name]
    client = LLMClient(cfg)
    rec = await run_chain(
        client, cfg, task=task,
        system_prompts=canonical_prompts(base, task, depth),
        input_text=task["inputs"][input_idx]["text"],
    )
    print(f"status: {rec['status']}  agents run: {len(rec['agents'])}")
    for a in rec["agents"]:
        print(f"\n--- agent {a['position']} ({a['role']}) "
              f"[{a['input_tokens']}in/{a['output_tokens']}out tok] ---")
        print(a["output"][:400])
    print(f"\nest cost: ${client.cost.total_usd:.4f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="summarization")
    ap.add_argument("--input", type=int, default=0)
    ap.add_argument("--depth", type=int, default=4)
    a = ap.parse_args()
    asyncio.run(_smoke(a.task, a.input, a.depth))
