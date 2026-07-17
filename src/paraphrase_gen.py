"""Generate N semantically-equivalent paraphrases per base system prompt.

anthropic backend: asks the paraphrase model for a JSON array of paraphrases.
mock backend: deterministic rule-based surface rewrites (wording/order changes
that preserve meaning), so the offline pipeline is end-to-end runnable.

Usage: python -m src.paraphrase_gen [--force]
Output: prompts/paraphrases/{task}__{role}.yaml
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
from pathlib import Path

import yaml

from .llm_client import LLMClient, load_base_prompts, load_config

ROOT = Path(__file__).resolve().parents[1]

GEN_SYSTEM = (
    "You rewrite system prompts. Produce paraphrases that are semantically "
    "equivalent to the original: same role, same task, same constraints, same "
    "output requirements. Vary wording, sentence order, and phrasing only. "
    "Never add, drop, or weaken any instruction."
)

GEN_USER_TEMPLATE = (
    "Original system prompt:\n---\n{prompt}\n---\n"
    "Write exactly {n} distinct paraphrases. Respond with ONLY a JSON array of "
    "{n} strings, no other text."
)

# --- mock: meaning-preserving surface rewrites --------------------------------

_REWRITES = [
    ("You are a", "Act as a"), ("You are an", "Act as an"),
    ("Given a", "When given a"), ("Given an", "When given an"),
    ("Output only", "Respond with only"), ("Do not", "Never"),
    ("roughly", "approximately"), ("produce", "generate"),
    ("write", "compose"), ("identify", "pinpoint"), ("list", "enumerate"),
]
_PREFIXES = ["", "Your role: ", "Task definition: ", "Instructions: "]
_SUFFIXES = ["", " Follow these instructions exactly.", " Adhere strictly to this role."]


def _mock_paraphrase(base: str, idx: int) -> str:
    rng = random.Random(f"{base}|{idx}")
    text = " ".join(base.split())
    n_swaps = 1 + idx % 3
    applicable = [(a, b) for a, b in _REWRITES if a in text]
    rng.shuffle(applicable)
    for a, b in applicable[:n_swaps]:
        text = text.replace(a, b, 1)
    if idx % 2 == 0:
        # swap the last two sentences when possible (order-only change)
        parts = re.split(r"(?<=\.)\s+", text)
        if len(parts) >= 3:
            parts[-2], parts[-1] = parts[-1], parts[-2]
            text = " ".join(parts)
    return (_PREFIXES[idx % len(_PREFIXES)] + text + _SUFFIXES[idx % len(_SUFFIXES)]).strip()


# --- real backend --------------------------------------------------------------

async def _llm_paraphrases(client: LLMClient, cfg: dict, base: str, n: int) -> list[str]:
    comp = await client.complete(
        system=GEN_SYSTEM,
        user=GEN_USER_TEMPLATE.format(prompt=base, n=n),
        model=cfg["models"]["paraphrase"],
        temperature=cfg["generation"]["paraphrase_temperature"],
        max_tokens=4096,
    )
    text = comp.text.strip()
    m = re.search(r"\[.*\]", text, re.DOTALL)
    arr = json.loads(m.group(0) if m else text)
    if len(arr) != n or not all(isinstance(x, str) and x.strip() for x in arr):
        raise ValueError(f"Paraphrase model returned bad output: {text[:200]}")
    return [x.strip() for x in arr]


async def main(force: bool = False):
    cfg = load_config(ROOT)
    base_prompts = load_base_prompts(ROOT, cfg)
    n = cfg["experiment"]["n_paraphrases"]
    out_dir = ROOT / cfg["paths"]["paraphrases_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    client = LLMClient(cfg)

    for task, roles in base_prompts.items():
        for role, base in roles.items():
            base = " ".join(base.split())
            out_path = out_dir / f"{task}__{role}.yaml"
            if out_path.exists() and not force:
                print(f"skip (exists): {out_path.name}")
                continue
            if cfg["backend"] == "mock":
                paras = [_mock_paraphrase(base, i) for i in range(n)]
            else:
                paras = await _llm_paraphrases(client, cfg, base, n)
            with open(out_path, "w") as f:
                yaml.safe_dump(
                    {"task": task, "role": role, "base_prompt": base,
                     "generator_model": cfg["models"]["paraphrase"],
                     "backend": cfg["backend"], "paraphrases": paras},
                    f, sort_keys=False, width=100)
            print(f"wrote {out_path.name} ({len(paras)} paraphrases)")
    print(f"done. est cost so far: ${client.cost.total_usd:.4f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="regenerate existing sets")
    asyncio.run(main(force=ap.parse_args().force))
