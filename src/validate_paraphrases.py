"""Validate that every paraphrase is semantically close to its base prompt.

Each paraphrase must have cosine similarity > threshold (config, default 0.85)
to the canonical prompt under all-MiniLM-L6-v2. Failures are flagged for
manual review and the script exits nonzero.

Usage: python -m src.validate_paraphrases
Output: prompts/paraphrases/validation_report.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import yaml

from .embedding import get_embedder
from .llm_client import load_config

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    cfg = load_config(ROOT)
    threshold = cfg["paraphrase_validation"]["min_cosine_similarity"]
    embedder, emb_name = get_embedder(cfg["paraphrase_validation"]["embedding_model"])
    d = ROOT / cfg["paths"]["paraphrases_dir"]

    rows = []
    for p in sorted(d.glob("*.yaml")):
        if p.name.startswith("validation"):
            continue
        with open(p) as f:
            data = yaml.safe_load(f)
        texts = [data["base_prompt"]] + data["paraphrases"]
        embs = embedder.encode(texts, normalize_embeddings=True)
        sims = embs[1:] @ embs[0]
        for i, sim in enumerate(sims):
            rows.append({"task": data["task"], "role": data["role"],
                         "paraphrase_idx": i, "cosine_sim": float(sim),
                         "pass": bool(sim > threshold), "embedder": emb_name})

    df = pd.DataFrame(rows)
    report = d / "validation_report.csv"
    df.to_csv(report, index=False)

    failures = df[~df["pass"]]
    print(f"{len(df)} paraphrases checked; threshold {threshold}")
    print(f"min={df.cosine_sim.min():.3f} mean={df.cosine_sim.mean():.3f} "
          f"max={df.cosine_sim.max():.3f}")
    print(f"report: {report}")
    if len(failures):
        print(f"\nFLAGGED FOR MANUAL REVIEW ({len(failures)} failures):")
        print(failures.to_string(index=False))
        return 1
    print("all paraphrases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
