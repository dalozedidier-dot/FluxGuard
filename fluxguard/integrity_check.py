#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def read_json(p: Path) -> Dict[str, Any]:
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def safe_div(num: float, den: float) -> float:
    if den == 0.0 or math.isclose(den, 0.0):
        return 0.0
    return num / den


def try_load_nulltrace(ci_out: Path) -> Optional[Dict[str, Any]]:
    p = ci_out / "nulltrace" / "nulltrace_summary.json"
    if p.exists():
        return read_json(p)
    # fallback éventuel si tu changes plus tard les chemins
    p2 = ci_out / "nulltrace" / "fluxguard_summary.json"
    if p2.exists():
        j = read_json(p2)
        if isinstance(j.get("nulltrace"), dict):
            return j["nulltrace"]
    return None


def try_load_voidmark(ci_out: Path) -> Optional[Dict[str, Any]]:
    p = ci_out / "voidmark" / "fluxguard_summary.json"
    if p.exists():
        j = read_json(p)
        vm = j.get("voidmark")
        if isinstance(vm, dict) and isinstance(vm.get("summary"), dict):
            return vm["summary"]
    # fallback si un jour tu crées un voidmark_summary.json dédié
    p2 = ci_out / "voidmark" / "voidmark_summary.json"
    if p2.exists():
        return read_json(p2)
    return None


def numeric_means_and_stds(csv_path: Path, max_rows: int = 200_000) -> Tuple[Dict[str, float], Dict[str, float]]:
    """
    Profil ultra léger: moyenne et std sur colonnes numériques.
    Std population (pas sample) pour stabilité; ignorera les colonnes non numériques.
    """
    sums: Dict[str, float] = {}
    sums2: Dict[str, float] = {}
    counts: Dict[str, int] = {}

    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for i, row in enumerate(r):
            if i >= max_rows:
                break
            for k, v in row.items():
                if v is None:
                    continue
                v = v.strip()
                if v == "":
                    continue
                try:
                    x = float(v)
                except Exception:
                    continue
                sums[k] = sums.get(k, 0.0) + x
                sums2[k] = sums2.get(k, 0.0) + x * x
                counts[k] = counts.get(k, 0) + 1

    means: Dict[str, float] = {}
    stds: Dict[str, float] = {}
    for k, n in counts.items():
        if n <= 1:
            continue
        mu = sums[k] / float(n)
        var = (sums2[k] / float(n)) - (mu * mu)
        var = max(0.0, var)
        means[k] = mu
        stds[k] = math.sqrt(var)

    return means, stds


def drift_mean_z(baseline_csv: Path, current_csv: Path) -> float:
    """
    Drift: max z-shift des moyennes sur colonnes numériques.
    abs(mean_curr - mean_base) / std_base
    """
    base_means, base_stds = numeric_means_and_stds(baseline_csv)
    curr_means, _ = numeric_means_and_stds(current_csv)

    zs = []
    for col, mu_base in base_means.items():
        if col not in curr_means:
            continue
        sd = base_stds.get(col, 0.0)
        if sd <= 0.0:
            continue
        z = abs(curr_means[col] - mu_base) / sd
        if math.isfinite(z):
            zs.append(z)

    if not zs:
        return 0.0
    return max(zs)


def compute_inco(
    v_null: float,
    v_drift: float,
    v_void: float,
    weights: Tuple[float, float, float],
) -> float:
    w_null, w_drift, w_void = weights
    # violations déjà clampées >= 0
    return (w_null * v_null) + (w_drift * v_drift) + (w_void * v_void)


def main() -> None:
    ap = argparse.ArgumentParser(description="FluxGuard integrity check: score unique d'incohérence")
    ap.add_argument("--ci-out", type=Path, default=Path("_ci_out"))
    ap.add_argument("--threshold", type=float, default=0.25)

    ap.add_argument("--weights", type=str, default="0.3,0.4,0.3", help="w_null,w_drift,w_void")

    ap.add_argument("--null-min-score", type=float, default=0.10, help="cible: min_score NullTrace")
    ap.add_argument("--void-var-limit", type=float, default=0.01, help="cible: var_entropy_bits VoidMark")

    ap.add_argument("--baseline-csv", type=Path, default=None)
    ap.add_argument("--current-csv", type=Path, default=None)

    ap.add_argument("--output", type=Path, default=None, help="fichier json de sortie (sinon <ci-out>/integrity_incoherence.json)")
    args = ap.parse_args()

    ci_out: Path = args.ci_out
    null = try_load_nulltrace(ci_out)
    void = try_load_voidmark(ci_out)

    # 1) violation nulltrace
    v_null = 0.0
    null_details: Dict[str, Any] = {}
    if null:
        min_score = float(null.get("min_score", 1.0))
        # violation = combien on est en dessous de la cible (0 si OK)
        v_null = max(0.0, safe_div(args.null_min_score - min_score, args.null_min_score))
        null_details = {
            "min_score": min_score,
            "target_min_score": args.null_min_score,
            "v_null": v_null,
            "runs": int(null.get("runs", 0)),
            "failed_runs": int(null.get("failed_runs", 0)),
        }
    else:
        null_details = {"error": "nulltrace summary not found"}

    # 2) violation voidmark
    v_void = 0.0
    void_details: Dict[str, Any] = {}
    if void:
        var_e = float(void.get("var_entropy_bits", 0.0))
        # violation relative au plafond (0 si OK)
        v_void = max(0.0, safe_div(var_e - args.void_var_limit, args.void_var_limit))
        void_details = {
            "var_entropy_bits": var_e,
            "limit_var_entropy_bits": args.void_var_limit,
            "v_void": v_void,
        }
    else:
        void_details = {"error": "voidmark summary not found"}

    # 3) violation drift (stats shift)
    v_drift = 0.0
    drift_details: Dict[str, Any] = {}
    if args.baseline_csv and args.current_csv and args.baseline_csv.exists() and args.current_csv.exists():
        zmax = drift_mean_z(args.baseline_csv, args.current_csv)
        # ici: on peut laisser zmax tel quel comme "violation"
        v_drift = max(0.0, zmax)
        drift_details = {
            "baseline_csv": str(args.baseline_csv),
            "current_csv": str(args.current_csv),
            "zmax_mean_shift": zmax,
            "v_drift": v_drift,
        }
    else:
        drift_details = {
            "note": "no baseline/current csv provided, drift set to 0",
            "v_drift": 0.0,
        }

    # weights
    parts = [p.strip() for p in args.weights.split(",")]
    if len(parts) != 3:
        raise SystemExit("weights must be 'w_null,w_drift,w_void'")
    weights = (float(parts[0]), float(parts[1]), float(parts[2]))

    inco = compute_inco(v_null=v_null, v_drift=v_drift, v_void=v_void, weights=weights)

    out_path = args.output or (ci_out / "integrity_incoherence.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "threshold": float(args.threshold),
        "weights": {"w_null": weights[0], "w_drift": weights[1], "w_void": weights[2]},
        "violations": {
            "v_null": v_null,
            "v_drift": v_drift,
            "v_void": v_void,
        },
        "incoherence_score": inco,
        "components": {
            "nulltrace": null_details,
            "voidmark": void_details,
            "drift": drift_details,
        },
        "decision": "BLOCK" if inco > float(args.threshold) else "OK",
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=True)

    print(f"Incoherence score: {inco:.6f} (threshold={args.threshold:.6f}) -> {payload['decision']}")
    print(f"Report: {out_path}")

    if inco > float(args.threshold):
        raise SystemExit(3)


if __name__ == "__main__":
    main()
