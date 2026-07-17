"""LLM client with two backends:

- "anthropic": real API calls via the Anthropic SDK (async, with retries).
- "mock": fully deterministic offline backend for testing the harness plumbing.
  The mock output is a pure function of (system_prompt, user_message), so
  paraphrased prompts produce different-but-related outputs and divergence can
  propagate through a chain, exercising every code path without API cost.

Also owns cost tracking (running USD estimate, budget guard).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Completion:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    stop_reason: str = "end_turn"
    latency_s: float = 0.0


@dataclass
class CostTracker:
    prices: dict            # model -> {"input": $/Mtok, "output": $/Mtok}
    budget_usd: float
    total_usd: float = 0.0
    calls: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def price(self, model: str, input_tokens: int, output_tokens: int) -> float:
        p = self.prices.get(model)
        if p is None:  # unknown model: use the most expensive listed price
            p = max(self.prices.values(), key=lambda x: x["output"])
        return input_tokens * p["input"] / 1e6 + output_tokens * p["output"] / 1e6

    async def add(self, model: str, input_tokens: int, output_tokens: int) -> float:
        async with self.lock:
            self.total_usd += self.price(model, input_tokens, output_tokens)
            self.calls += 1
            if self.total_usd > self.budget_usd:
                raise BudgetExceeded(
                    f"Estimated spend ${self.total_usd:.2f} exceeds budget "
                    f"${self.budget_usd:.2f}. Aborting; completed runs are checkpointed."
                )
            return self.total_usd


class BudgetExceeded(RuntimeError):
    pass


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (~4 chars/token) used for dry runs and the mock backend."""
    return max(1, len(text) // 4)


# ----------------------------------------------------------------------------- mock

_CONNECTORS = [
    "notably", "in addition", "furthermore", "however", "specifically",
    "as a result", "importantly", "in this context", "overall", "meanwhile",
]


def mock_generate(system_prompt: str, user_message: str, max_tokens: int) -> str:
    """Deterministic pseudo-completion.

    Content words are drawn from the user message (so outputs stay 'on topic'
    and successive chain stages remain related), but selection and ordering are
    seeded by a hash of BOTH prompts — so perturbing the system prompt perturbs
    the output, and that perturbation feeds forward through the chain.
    """
    seed = hashlib.sha256((system_prompt + "\x1f" + user_message).encode()).digest()
    rng = random.Random(seed)
    words = re.findall(r"[A-Za-z0-9']+", user_message.lower())
    if not words:
        words = ["empty", "input"]
    uniq = sorted(set(words))
    keep = max(5, int(len(uniq) * 0.7))
    chosen = rng.sample(uniq, min(keep, len(uniq)))
    rng.shuffle(chosen)

    # If the system prompt demands JSON, honor it so schema checks are exercised.
    if "json" in system_prompt.lower() and '"summary"' in system_prompt:
        sev = rng.choice(["low", "medium", "high", "critical"])
        issues = [
            {"title": " ".join(rng.sample(chosen, min(3, len(chosen)))),
             "severity": rng.choice(["low", "medium", "high", "critical"]),
             "fix": " ".join(rng.sample(chosen, min(5, len(chosen))))}
            for _ in range(rng.randint(1, 3))
        ]
        # deterministically make ~5% of outputs schema-violating to exercise the flag
        if rng.random() < 0.05:
            return "The report could not be structured: " + " ".join(chosen[:12])
        return json.dumps({"summary": " ".join(chosen[:8]), "issues": issues,
                           "severity": sev})

    sentences, i = [], 0
    target_words = min(110, max(40, max_tokens // 8))
    count = 0
    while count < target_words and chosen:
        n = rng.randint(6, 12)
        chunk = [chosen[(i + k) % len(chosen)] for k in range(n)]
        i += n
        s = f"{rng.choice(_CONNECTORS).capitalize()}, {' '.join(chunk)}."
        sentences.append(s)
        count += n
    return " ".join(sentences)


def mock_judge(system_prompt: str, user_message: str) -> str:
    """Deterministic judge: score derived from hash of the judged content only."""
    h = hashlib.sha256(user_message.encode()).digest()
    score = 4 + h[0] % 6  # 4..9
    return json.dumps({"score": score, "rationale": "mock deterministic judgment"})


# ----------------------------------------------------------------------------- client

class LLMClient:
    def __init__(self, config: dict):
        self.config = config
        self.backend = config["backend"]
        rl = config["rate_limit"]
        self.semaphore = asyncio.Semaphore(rl["max_concurrent"])
        self.min_interval = 60.0 / rl["requests_per_minute"]
        self.max_retries = rl["max_retries"]
        self.retry_base = rl["retry_base_delay_s"]
        self._last_request = 0.0
        self._pace_lock = asyncio.Lock()
        self.cost = CostTracker(prices=config["cost"]["prices"],
                                budget_usd=config["cost"]["budget_usd"])
        self._anthropic = None
        if self.backend == "anthropic":
            import anthropic
            self._anthropic = anthropic.AsyncAnthropic()

    async def _pace(self):
        async with self._pace_lock:
            now = time.monotonic()
            wait = self.min_interval - (now - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()

    async def complete(self, *, system: str, user: str, model: str,
                       temperature: float, max_tokens: int,
                       is_judge: bool = False) -> Completion:
        async with self.semaphore:
            if self.backend == "mock":
                text = (mock_judge(system, user) if is_judge
                        else mock_generate(system, user, max_tokens))
                comp = Completion(text=text, model=f"mock/{model}",
                                  input_tokens=estimate_tokens(system) + estimate_tokens(user),
                                  output_tokens=estimate_tokens(text))
                await self.cost.add(model, comp.input_tokens, comp.output_tokens)
                return comp

            last_err = None
            for attempt in range(self.max_retries + 1):
                await self._pace()
                t0 = time.monotonic()
                try:
                    resp = await self._anthropic.messages.create(
                        model=model, system=system, max_tokens=max_tokens,
                        temperature=temperature,
                        messages=[{"role": "user", "content": user}],
                    )
                    comp = Completion(
                        text="".join(b.text for b in resp.content if b.type == "text"),
                        model=resp.model,
                        input_tokens=resp.usage.input_tokens,
                        output_tokens=resp.usage.output_tokens,
                        stop_reason=resp.stop_reason or "end_turn",
                        latency_s=time.monotonic() - t0,
                    )
                    total = await self.cost.add(model, comp.input_tokens, comp.output_tokens)
                    if self.cost.calls % 25 == 0:
                        print(f"  [cost] {self.cost.calls} calls, est ${total:.2f}")
                    return comp
                except BudgetExceeded:
                    raise
                except Exception as e:  # noqa: BLE001 — retried, then surfaced
                    last_err = e
                    if attempt < self.max_retries:
                        await asyncio.sleep(self.retry_base * 2 ** attempt)
            raise RuntimeError(f"API call failed after {self.max_retries + 1} attempts: {last_err}")


# ----------------------------------------------------------------------------- config/io helpers

def load_config(root: Path) -> dict:
    with open(root / "config.yaml") as f:
        return yaml.safe_load(f)


def load_tasks(root: Path, config: dict) -> dict:
    tasks = {}
    for p in sorted((root / config["paths"]["tasks_dir"]).glob("*.yaml")):
        with open(p) as f:
            t = yaml.safe_load(f)
        tasks[t["name"]] = t
    return tasks


def load_base_prompts(root: Path, config: dict) -> dict:
    with open(root / config["paths"]["base_prompts"]) as f:
        return yaml.safe_load(f)


def load_paraphrases(root: Path, config: dict) -> dict:
    """-> {task: {role: [p1..pN]}} (excluding the canonical prompt)."""
    out = {}
    d = root / config["paths"]["paraphrases_dir"]
    for p in sorted(d.glob("*.yaml")):
        if p.name.startswith("validation"):
            continue
        with open(p) as f:
            data = yaml.safe_load(f)
        out.setdefault(data["task"], {})[data["role"]] = data["paraphrases"]
    return out
