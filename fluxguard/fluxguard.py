#!/usr/bin/env python3
"""
FluxGuard - CLI unique, modulaire, léger, déterministe, sans dépendances externes.

Exemples:
  python fluxguard.py nulltrace --runs 10
  python fluxguard.py riftlens --input datasets/example.csv
  python fluxguard.py voidmark --input datasets/example.csv
  python fluxguard.py all --shadow-prev datasets/example.csv --shadow-curr datasets/example.csv
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
    """Timestamp utile pour traçabilité. Reproductible si SOURCE_DATE_EPOCH est défini."""
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
        description="FluxGuard: observation brute, traçabilité déterministe, modules isolés",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_null = sub.add_parser("nulltrace", help="Mass-soak déterministe (NullTrace)")
    p_null.add_argument("--runs", type=int, default=100)
    p_null.add_argument("--seed", type=int, default=0, help="Seed RNG (0 = dérivé des contraintes)")
    p_null.add_argument("--constraints", type=Path, default=Path(".github/constraints.txt"))
    p_null.add_argument("--output-dir", type=Path, default=Path("_ci_out/nulltrace"))

    p_rift = sub.add_parser("riftlens", help="Analyse CSV et graphe de cohérence (RiftLens)")
    p_rift.add_argument("--input", type=Path, required=True)
    p_rift.add_argument("--thresholds", nargs="+", type=float, default=[0.25, 0.5, 0.7, 0.8])
    p_rift.add_argument("--output-dir", type=Path, default=Path("_ci_out/riftlens"))

    p_void = sub.add_parser("voidmark", help="Vault immuable et stress test (VoidMark)")
    p_void.add_argument("--input", type=Path, required=True)
    p_void.add_argument("--runs", type=int, default=200)
    p_void.add_argument("--noise", type=float, default=0.05, help="Probabilité de flip de bit")
    p_void.add_argument("--seed", type=int, default=0)
    p_void.add_argument("--output-dir", type=Path, default=Path("_ci_out/voidmark"))

    p_all = sub.add_parser("all", help="Chaîne complète (séquentielle, auditables)")
    p_all.add_argument("--shadow-prev", type=Path, required=True)
    p_all.add_argument("--shadow-curr", type=Path, required=True)
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
            )
            summary["nulltrace"] = result
            print(f"NullTrace terminé: {result.get('ok_runs', 0)}/{args.runs} OK")

        elif args.command == "riftlens":
            result = riftlens_run_csv(
                input_csv=args.input,
                thresholds=args.thresholds,
                output_dir=args.output_dir,
            )
            summary["riftlens"] = result
            print(f"RiftLens terminé: {len(result.get('reports', []))} rapports")

        elif args.command == "voidmark":
            result = voidmark_run_stress_test(
                target=args.input,
                runs=args.runs,
                noise=args.noise,
                output_dir=args.output_dir,
                seed=args.seed,
            )
            summary["voidmark"] = result
            m = result.get("summary", {}).get("mean_entropy_bits")
            if isinstance(m, (int, float)):
                print(f"VoidMark terminé: entropie moyenne {m:.3f} bits")
            else:
                print("VoidMark terminé: entropie moyenne indisponible")

        elif args.command == "all":
            result = run_full_chain(
                shadow_prev=args.shadow_prev,
                shadow_curr=args.shadow_curr,
                output_dir=args.output_dir,
            )
            summary["full_chain"] = result
            print("Chaîne complète terminée")

    except Exception as e:
        summary["status"] = "error"
        summary["error"] = {"type": type(e).__name__, "message": str(e)}
        exit_code = 2
        print(f"ERREUR: {type(e).__name__}: {e}", file=sys.stderr)

    if isinstance(outdir, Path):
        write_json(outdir / "fluxguard_summary.json", summary)
        print(f"Summary sauvegardé: {outdir / 'fluxguard_summary.json'}")

    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
