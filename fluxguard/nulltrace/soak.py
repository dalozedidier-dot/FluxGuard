from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional


def constraints_hash(constraints_path: Path) -> str:
    if not constraints_path.exists():
        return "0" * 64
    data = constraints_path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def _default_seed_from_constraints(ch: str) -> int:
    return int(ch[:8], 16)


def _percentile(xs: List[float], q: float) -> float:
    if not xs:
        return 0.0
    ys = sorted(xs)
    if q <= 0.0:
        return float(ys[0])
    if q >= 1.0:
        return float(ys[-1])
    n = len(ys)
    pos = (n - 1) * q
    lo = int(pos)
    hi = min(n - 1, lo + 1)
    w = pos - lo
    return float(ys[lo] * (1.0 - w) + ys[hi] * w)


def nulltrace_run_mass_soak(
    runs: int,
    output_dir: Path,
    constraints_path: Path,
    seed: int = 0,
    plot: bool = False,
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

    scores: List[float] = []

    for i in range(int(runs)):
        x = float(rng.random())
        passed = x >= 0.01
        record = {"run_index": i, "passed": bool(passed), "score": x}
        with open(runs_dir / f"run_{i:05d}.json", "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False, sort_keys=True)

        scores.append(x)
        if passed:
            ok += 1
        else:
            failures += 1

    min_score = min(scores) if scores else 0.0
    max_score = max(scores) if scores else 0.0
    mean_score = (sum(scores) / len(scores)) if scores else 0.0

    summary: Dict[str, Any] = {
        "runs": int(runs),
        "ok_runs": ok,
        "failed_runs": failures,
        "seed": int(seed),
        "constraints_path": str(constraints_path),
        "constraints_sha256": ch,
        "min_score": float(round(min_score, 12)),
        "max_score": float(round(max_score, 12)),
        "mean_score": float(round(mean_score, 12)),
        "p01": float(round(_percentile(scores, 0.01), 12)),
        "p05": float(round(_percentile(scores, 0.05), 12)),
        "p50": float(round(_percentile(scores, 0.50), 12)),
    }

    with open(output_dir / "nulltrace_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, sort_keys=True)

    if plot:
        try:
            from viz import save_histogram
        except Exception:
            save_histogram = None  # type: ignore

        if save_histogram is not None and scores:
            p = save_histogram(scores, output_dir / "nulltrace_scores_hist.png", title="NullTrace score histogram", xlabel="score")
            if p:
                summary["plot_scores_hist"] = p
                with open(output_dir / "nulltrace_summary.json", "w", encoding="utf-8") as f:
                    json.dump(summary, f, indent=2, ensure_ascii=False, sort_keys=True)

    return summary
