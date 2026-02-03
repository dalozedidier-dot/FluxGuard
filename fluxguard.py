#!/usr/bin/env python3
"""
FluxGuard - CLI unique, modulaire, leger, deterministe.

Nouveautes v10:
- RiftLens: ruptures locales (fenetres) et mode causal lite (lags)
- VoidMark: fingerprint statistique CSV, drift_signals, versioning append-only
- NullTrace: mode data-aware + regles auditees
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from riftlens.core import riftlens_run_csv  # noqa: E402
from nulltrace.soak import nulltrace_run_mass_soak  # noqa: E402
from voidmark.vault import voidmark_run_stress_test  # noqa: E402
from orchestrator.chain import run_full_chain  # noqa: E402


def utc_timestamp() -> str:
    sde = os.getenv("SOURCE_DATE_EPOCH")
    if sde:
        dt = datetime.fromtimestamp(int(sde), tz=timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: dict) -> None:
    ensure_dir(path.parent)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="FluxGuard: observation brute, tracabilite deterministe, modules isoles",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_null = sub.add_parser("nulltrace", help="Mass-soak deterministe (NullTrace)")
    p_null.add_argument("--runs", type=int, default=200)
    p_null.add_argument("--seed", type=int, default=0, help="Seed RNG (0 = derive des contraintes)")
    p_null.add_argument("--constraints", type=Path, default=Path(".github/constraints.txt"))
    p_null.add_argument("--output-dir", type=Path, default=Path("_ci_out/nulltrace"))
    p_null.add_argument("--data-aware", action="store_true", help="Active les checks data-aware")
    p_null.add_argument("--input", type=Path, default=None, help="CSV source (requis si --data-aware)")
    p_null.add_argument("--rules", type=Path, default=None, help="Fichier rules.yml simple (optionnel)")
    p_null.add_argument("--sample-rows", type=int, default=50, help="Taille de fenetre pour checks")

    p_rift = sub.add_parser("riftlens", help="Analyse CSV et graphe (RiftLens)")
    p_rift.add_argument("--input", type=Path, required=True)
    p_rift.add_argument("--thresholds", nargs="+", type=float, default=[0.1, 0.3, 0.5, 0.7, 0.9, 0.95])
    p_rift.add_argument("--output-dir", type=Path, default=Path("_ci_out/riftlens"))
    p_rift.add_argument("--local-ruptures", action="store_true", help="Active ruptures locales (fenetres)")
    p_rift.add_argument("--window", type=int, default=100)
    p_rift.add_argument("--step", type=int, default=100)
    p_rift.add_argument("--delta-edges", type=int, default=1, help="Seuil de changement d'aretes")
    p_rift.add_argument("--mode", type=str, default="corr", choices=["corr", "causal"])
    p_rift.add_argument("--max-lag", type=int, default=3)

    p_void = sub.add_parser("voidmark", help="Vault immuable + fingerprint stats (VoidMark)")
    p_void.add_argument("--input", type=Path, required=True)
    p_void.add_argument("--runs", type=int, default=500)
    p_void.add_argument("--noise", type=float, default=0.02, help="Probabilite de flip de bit")
    p_void.add_argument("--seed", type=int, default=0)
    p_void.add_argument("--output-dir", type=Path, default=Path("_ci_out/voidmark"))
    p_void.add_argument("--baseline-mark", type=Path, default=None, help="Baseline voidmark_mark.json pour drift")
    p_void.add_argument("--version-db", type=Path, default=None)

    p_all = sub.add_parser("all", help="Chaine complete (sequentielle, auditable)")
    p_all.add_argument("--shadow-prev", type=Path, required=True)
    p_all.add_argument("--shadow-curr", type=Path, required=True)
    p_all.add_argument("--rift-thresholds", nargs="+", type=float, default=[0.1, 0.3, 0.5, 0.7, 0.9, 0.95])
    p_all.add_argument("--rift-local-ruptures", action="store_true")
    p_all.add_argument("--rift-window", type=int, default=100)
    p_all.add_argument("--rift-step", type=int, default=100)
    p_all.add_argument("--rift-delta-edges", type=int, default=1)
    p_all.add_argument("--rift-mode", type=str, default="corr", choices=["corr", "causal"])
    p_all.add_argument("--rift-max-lag", type=int, default=3)
    p_all.add_argument("--void-runs", type=int, default=500)
    p_all.add_argument("--void-noise", type=float, default=0.02)
    p_all.add_argument("--void-seed", type=int, default=0)
    p_all.add_argument("--void-baseline-mark", type=Path, default=None)
    p_all.add_argument("--version-db", type=Path, default=None)
    p_all.add_argument("--output-dir", type=Path, default=Path("_ci_out/full"))

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    outdir = getattr(args, "output_dir", None)
    if isinstance(outdir, Path):
        ensure_dir(outdir)

    summary: dict = {
        "generated_at_utc": utc_timestamp(),
        "command": args.command,
        "status": "ok",
    }

    exit_code = 0

    try:
        if args.command == "nulltrace":
            result = nulltrace_run_mass_soak(
                runs=args.runs,
                output_dir=args.output_dir,
                constraints_path=args.constraints,
                seed=args.seed,
                data_aware=bool(args.data_aware),
                input_csv=args.input,
                rules_path=args.rules,
                sample_rows=args.sample_rows,
            )
            summary["nulltrace"] = result
            print(f"NullTrace termine: {result.get('ok_runs', 0)}/{args.runs} OK")

        elif args.command == "riftlens":
            result = riftlens_run_csv(
                input_csv=args.input,
                thresholds=args.thresholds,
                output_dir=args.output_dir,
                local_ruptures=bool(args.local_ruptures),
                window=args.window,
                step=args.step,
                delta_edges_threshold=args.delta_edges,
                mode=args.mode,
                max_lag=args.max_lag,
            )
            summary["riftlens"] = result
            print(f"RiftLens termine: {len(result.get('reports', []))} rapports")

        elif args.command == "voidmark":
            result = voidmark_run_stress_test(
                target=args.input,
                runs=args.runs,
                noise=args.noise,
                output_dir=args.output_dir,
                seed=args.seed,
                fingerprint_csv_path=args.input,
                baseline_mark=args.baseline_mark,
                ks_alpha=0.05,
                version_db=args.version_db,
            )
            summary["voidmark"] = result
            m = result.get("summary", {}).get("mean_entropy_bits")
            if isinstance(m, (int, float)):
                print(f"VoidMark termine: entropie moyenne {m:.3f} bits")
            else:
                print("VoidMark termine: entropie moyenne indisponible")

        elif args.command == "all":
            result = run_full_chain(
                shadow_prev=args.shadow_prev,
                shadow_curr=args.shadow_curr,
                output_dir=args.output_dir,
                rift_thresholds=args.rift_thresholds,
                rift_local_ruptures=bool(args.rift_local_ruptures),
                rift_window=args.rift_window,
                rift_step=args.rift_step,
                rift_delta_edges=args.rift_delta_edges,
                rift_mode=args.rift_mode,
                rift_max_lag=args.rift_max_lag,
                void_runs=args.void_runs,
                void_noise=args.void_noise,
                void_seed=args.void_seed,
                void_baseline_mark=args.void_baseline_mark,
                version_db=args.version_db,
            )
            summary["full_chain"] = result
            print("Chaine complete terminee")

    except Exception as e:
        summary["status"] = "error"
        summary["error"] = {"type": type(e).__name__, "message": str(e)}
        exit_code = 2
        print(f"ERREUR: {type(e).__name__}: {e}", file=sys.stderr)

    if isinstance(outdir, Path):
        write_json(outdir / "fluxguard_summary.json", summary)
        print(f"Summary sauvegarde: {outdir / 'fluxguard_summary.json'}")

    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
