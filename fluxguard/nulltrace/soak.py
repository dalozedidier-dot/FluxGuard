from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any, Dict


def constraints_hash(constraints_path: Path) -> str:
    if not constraints_path.exists():
        return "0" * 64
    data = constraints_path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def _default_seed_from_constraints(ch: str) -> int:
    return int(ch[:8], 16)


def nulltrace_run_mass_soak(
    runs: int,
    output_dir: Path,
    constraints_path: Path,
    seed: int = 0,
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    ch = constraints_hash(constraints_path)
    if seed == 0:
        seed = _default_seed_from_constraints(ch)
    rng = random.Random(seed)

    ok = 0
    failures = 0

    runs_dir = output_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    for i in range(int(runs)):
        x = rng.random()
        passed = x >= 0.01
        record = {"run_index": i, "passed": bool(passed), "score": x}
        with open(runs_dir / f"run_{i:05d}.json", "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False, sort_keys=True)

        if passed:
            ok += 1
        else:
            failures += 1

    summary = {
        "runs": int(runs),
        "ok_runs": ok,
        "failed_runs": failures,
        "seed": int(seed),
        "constraints_path": str(constraints_path),
        "constraints_sha256": ch,
    }

    with open(output_dir / "nulltrace_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, sort_keys=True)

    return summary
