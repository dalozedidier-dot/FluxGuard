#!/usr/bin/env python3
"""
FluxGuard - CLI unique, modulaire, léger, déterministe, sans dépendances externes.

Exemples:
  python fluxguard.py nulltrace --runs 10
  python fluxguard.py riftlens --input datasets/example.csv --profile
  python fluxguard.py voidmark --input datasets/example.csv
  python fluxguard.py all --shadow-prev datasets/example.csv --shadow-curr datasets/example.csv
  python fluxguard.py daemon --watch datasets --pattern "*.csv" --pipeline monitor --interval-s 300 --once
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alerts import AlertConfig  # noqa: E402
from daemon import daemon_loop  # noqa: E402
from nulltrace.soak import nulltrace_run_mass_soak  # noqa: E402
from orchestrator.chain import run_full_chain  # noqa: E402
from riftlens.core import riftlens_run_csv  # noqa: E402
from voidmark.vault import voidmark_run_stress_test  # noqa: E402


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
    p_null.add_argument("--seed", type=int, default=0)
    p_null.add_argument("--constraints", type=Path, default=Path(".github/constraints.txt"))
    p_null.add_argument("--plot", action="store_true", help="Génère une visualisation si matplotlib est disponible")
    p_null.add_argument("--output-dir", type=Path, default=Path("_ci_out/nulltrace"))

    p_rift = sub.add_parser("riftlens", help="Analyse dataset et graphe de cohérence (RiftLens)")
    p_rift.add_argument("--input", type=Path, required=True)
    p_rift.add_argument("--shadow-prev", type=Path, default=None, help="Dataset baseline (drift tests optionnels)")
    p_rift.add_argument("--thresholds", nargs="+", type=float, default=[0.25, 0.5, 0.7, 0.8])
    p_rift.add_argument("--stat-tests", action="store_true", help="KS + Wasserstein si shadow-prev est fourni")
    p_rift.add_argument("--profile", action="store_true", help="Profiling automatique (missing/outliers/stats)")
    p_rift.add_argument("--plot", action="store_true", help="Heatmap corr si matplotlib est disponible")
    p_rift.add_argument("--output-dir", type=Path, default=Path("_ci_out/riftlens"))

    p_void = sub.add_parser("voidmark", help="Vault immuable et stress test (VoidMark)")
    p_void.add_argument("--input", type=Path, required=True)
    p_void.add_argument("--runs", type=int, default=200)
    p_void.add_argument("--noise", type=float, default=0.05, help="Probabilité de flip de bit")
    p_void.add_argument("--seed", type=int, default=0)
    p_void.add_argument("--plot", action="store_true", help="Histogramme entropie si matplotlib est disponible")
    p_void.add_argument("--output-dir", type=Path, default=Path("_ci_out/voidmark"))

    p_all = sub.add_parser("all", help="Chaîne complète (séquentielle, auditables)")
    p_all.add_argument("--shadow-prev", type=Path, required=True)
    p_all.add_argument("--shadow-curr", type=Path, required=True)
    p_all.add_argument("--rift-thresholds", nargs="+", type=float, default=None)
    p_all.add_argument("--rift-stat-tests", action="store_true")
    p_all.add_argument("--rift-profile", action="store_true")
    p_all.add_argument("--plot", action="store_true")

    # Flags tolérés (compat / tests historiques). Ignorés si présents.
    p_all.add_argument("--rift-local-ruptures", action="store_true")
    p_all.add_argument("--rift-window", type=int, default=None)
    p_all.add_argument("--rift-step", type=int, default=None)

    p_all.add_argument("--output-dir", type=Path, default=Path("_ci_out/full"))

    p_daemon = sub.add_parser("daemon", help="Mode monitoring continu (daemon)")
    p_daemon.add_argument("--watch", type=Path, required=True, help="Fichier ou dossier à surveiller")
    p_daemon.add_argument("--pattern", type=str, default="*.csv", help="Pattern (si watch est un dossier)")
    p_daemon.add_argument("--interval-s", type=int, default=300, help="Intervalle de polling")
    p_daemon.add_argument(
        "--pipeline",
        type=str,
        default="monitor",
        choices=["monitor", "riftlens", "voidmark", "nulltrace", "chain"],
        help="Pipeline exécuté à chaque tick",
    )
    p_daemon.add_argument("--shadow-prev", type=Path, default=None, help="Baseline pour drift tests (RiftLens)")
    p_daemon.add_argument("--constraints", type=Path, default=Path(".github/constraints.txt"))
    p_daemon.add_argument("--nulltrace-runs", type=int, default=10)
    p_daemon.add_argument("--voidmark-runs", type=int, default=50)
    p_daemon.add_argument("--voidmark-noise", type=float, default=0.02)
    p_daemon.add_argument("--rift-thresholds", nargs="+", type=float, default=[0.5, 0.7, 0.8])
    p_daemon.add_argument("--rift-stat-tests", action="store_true")
    p_daemon.add_argument("--rift-profile", action="store_true")
    p_daemon.add_argument("--plot", action="store_true")
    p_daemon.add_argument("--alert-var-entropy-gt", type=float, default=0.01)
    p_daemon.add_argument("--alert-nulltrace-min-score-lt", type=float, default=0.10)

    p_daemon.add_argument("--alert-slack-webhook", type=str, default=None)
    p_daemon.add_argument("--alert-webhook", type=str, default=None)

    p_daemon.add_argument("--smtp-host", type=str, default=None)
    p_daemon.add_argument("--smtp-port", type=int, default=465)
    p_daemon.add_argument("--smtp-username", type=str, default=None)
    p_daemon.add_argument("--smtp-password", type=str, default=None)
    p_daemon.add_argument("--smtp-use-tls", action="store_true")
    p_daemon.add_argument("--alert-email-from", type=str, default=None)
    p_daemon.add_argument("--alert-email-to", type=str, default=None)

    p_daemon.add_argument("--state-file", type=Path, default=Path("_ci_out/daemon_state.json"))
    p_daemon.add_argument("--output-dir", type=Path, default=Path("_ci_out/daemon"))
    p_daemon.add_argument("--once", action="store_true", help="Exécute un tick puis quitte")

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
                plot=bool(args.plot),
            )
            summary["nulltrace"] = result
            print(f"NullTrace terminé: {result.get('ok_runs', 0)}/{args.runs} OK")

        elif args.command == "riftlens":
            result = riftlens_run_csv(
                input_csv=args.input,
                thresholds=args.thresholds,
                output_dir=args.output_dir,
                shadow_prev=args.shadow_prev,
                stat_tests=bool(args.stat_tests),
                profile=bool(args.profile),
                plot=bool(args.plot),
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
                plot=bool(args.plot),
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
                rift_thresholds=args.rift_thresholds,
                rift_stat_tests=bool(args.rift_stat_tests),
                rift_profile=bool(args.rift_profile),
                plots=bool(args.plot),
            )
            summary["full_chain"] = result
            print("Chaîne complète terminée")

        elif args.command == "daemon":
            alerts = AlertConfig(
                slack_webhook=args.alert_slack_webhook,
                generic_webhook=args.alert_webhook,
                smtp_host=args.smtp_host,
                smtp_port=int(args.smtp_port),
                smtp_username=args.smtp_username,
                smtp_password=args.smtp_password,
                smtp_use_tls=bool(args.smtp_use_tls),
                email_from=args.alert_email_from,
                email_to=args.alert_email_to,
            )

            daemon_loop(
                watch=args.watch,
                pattern=args.pattern,
                interval_s=int(args.interval_s),
                pipeline=args.pipeline,
                output_dir=args.output_dir,
                state_file=args.state_file,
                once=bool(args.once),
                shadow_prev=args.shadow_prev,
                constraints=args.constraints,
                nulltrace_runs=int(args.nulltrace_runs),
                voidmark_runs=int(args.voidmark_runs),
                voidmark_noise=float(args.voidmark_noise),
                rift_thresholds=list(args.rift_thresholds),
                rift_stat_tests=bool(args.rift_stat_tests),
                rift_profile=bool(args.rift_profile),
                plots=bool(args.plot),
                alert_var_entropy_gt=float(args.alert_var_entropy_gt),
                alert_nulltrace_min_score_lt=float(args.alert_nulltrace_min_score_lt),
                alerts=alerts,
            )
            summary["daemon"] = {"status": "ok", "output_dir": str(args.output_dir)}
            print("Daemon terminé")

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
