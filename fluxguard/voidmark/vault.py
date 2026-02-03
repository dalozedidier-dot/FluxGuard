from __future__ import annotations

import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any, Dict, List, Tuple


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def read_target_bytes(target: Path) -> bytes:
    if target.is_file():
        return target.read_bytes()
    if target.is_dir():
        items: List[Tuple[str, str]] = []
        for p in sorted(target.rglob("*")):
            if p.is_file():
                rel = str(p.relative_to(target)).replace("\\", "/")
                items.append((rel, sha256_bytes(p.read_bytes())))
        blob = "\n".join(f"{a}:{b}" for a, b in items).encode("utf-8")
        return blob
    raise ValueError("Target doit être un fichier ou un dossier")


def flip_bits(data: bytes, rng: random.Random, prob: float) -> bytes:
    if prob <= 0.0:
        return data
    b = bytearray(data)
    for i in range(len(b)):
        if rng.random() < prob:
            bit = 1 << rng.randrange(0, 8)
            b[i] ^= bit
    return bytes(b)


def shannon_entropy_bits(data: bytes) -> float:
    if not data:
        return 0.0
    freq = [0] * 256
    for x in data:
        freq[x] += 1
    n = len(data)
    ent = 0.0
    for c in freq:
        if c == 0:
            continue
        p = c / n
        ent -= p * math.log2(p)
    return ent


def compute_stats(values: List[float]) -> Dict[str, Any]:
    if not values:
        return {"count": 0}

    # Agrégats stables cross-version Python:
    # math.fsum réduit les écarts d'arrondi entre interprètes.
    m = math.fsum(values) / len(values)
    v = math.fsum((x - m) ** 2 for x in values) / len(values)

    # Quantification volontaire: évite les micro-écarts à ~1e-15.
    m = round(m, 12)
    v = round(v, 12)

    return {
        "count": len(values),
        "mean_entropy_bits": m,
        "var_entropy_bits": v,
        "min_entropy_bits": round(min(values), 12),
        "max_entropy_bits": round(max(values), 12),
    }


def voidmark_run_stress_test(
    target: Path,
    runs: int,
    noise: float,
    output_dir: Path,
    seed: int = 0,
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    base = read_target_bytes(target)
    base_hash = sha256_bytes(base)

    if seed == 0:
        seed = int(base_hash[:8], 16)
    rng = random.Random(seed)

    vault_dir = output_dir / "vault"
    vault_dir.mkdir(parents=True, exist_ok=True)

    entropies: List[float] = []
    records_dir = output_dir / "runs"
    records_dir.mkdir(parents=True, exist_ok=True)

    for i in range(int(runs)):
        mutated = flip_bits(base, rng, float(noise))
        h = sha256_bytes(mutated)
        hb = bytes.fromhex(h)
        e = shannon_entropy_bits(hb)
        entropies.append(e)

        rec = {"run_index": i, "sha256": h, "entropy_bits": e}
        with open(records_dir / f"run_{i:05d}.json", "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=2, ensure_ascii=False, sort_keys=True)

    summary = compute_stats(entropies)

    mark = {
        "target": str(target),
        "base_sha256": base_hash,
        "seed": int(seed),
        "noise": float(noise),
        "runs": int(runs),
        "summary": summary,
    }
    with open(vault_dir / "voidmark_mark.json", "w", encoding="utf-8") as f:
        json.dump(mark, f, indent=2, ensure_ascii=False, sort_keys=True)

    return {"mark": str(vault_dir / "voidmark_mark.json"), "summary": summary}
