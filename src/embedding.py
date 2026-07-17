"""Embedding provider.

Primary: sentence-transformers all-MiniLM-L6-v2 (required for real results).
Fallback: deterministic hashed bag-of-words+bigrams (pure numpy) used ONLY when
sentence-transformers / the model download is unavailable (e.g. offline mock
testing). The embedder name is exposed so downstream artifacts can record which
one produced the numbers.
"""
from __future__ import annotations

import hashlib
import re

import numpy as np

_DIM = 512


class HashingEmbedder:
    """Deterministic lexical embedder: hashed unigrams + bigrams, L2-normalized.

    NOT a semantic embedding — suitable only for offline plumbing tests.
    """

    name = "hashing-bow-512 (FALLBACK, lexical only)"

    def encode(self, texts, normalize_embeddings=True, show_progress_bar=False):
        out = np.zeros((len(texts), _DIM), dtype=np.float32)
        for i, t in enumerate(texts):
            toks = re.findall(r"[a-z0-9']+", t.lower())
            grams = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
            for g in grams:
                h = hashlib.md5(g.encode()).digest()
                idx = int.from_bytes(h[:4], "little") % _DIM
                sign = 1.0 if h[4] % 2 else -1.0
                out[i, idx] += sign
            n = np.linalg.norm(out[i])
            if normalize_embeddings and n > 0:
                out[i] /= n
        return out


def get_embedder(model_name: str):
    """Returns (embedder, name). Falls back with a loud warning if ST unusable."""
    try:
        from sentence_transformers import SentenceTransformer
        emb = SentenceTransformer(model_name)
        return emb, model_name
    except Exception as e:  # noqa: BLE001 — offline/missing-model fallback
        emb = HashingEmbedder()
        print(f"WARNING: sentence-transformers unavailable ({type(e).__name__}); "
              f"using {emb.name}. Do NOT report these numbers as research results.")
        return emb, emb.name
