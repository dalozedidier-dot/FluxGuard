#!/usr/bin/env python3
"""
FluxGuard integrity check: score unique d'incohérence pour décider "ce batch est incohérent -> bloquer upstream".

But:
- Transformer des résultats soak (NullTrace / VoidMark / drift stats) en un indicateur unique et auditable.
- Rester lightweight (stdlib only). Certaines métriques utilisent des fallbacks quand SciPy/pandas ne sont pas présents.

Violations (toutes >= 0):
- v_null  : dérivée d'un score NullTrace (au choix: p05 par défaut, ou min/mean/p50/p01, etc.).
            La violation est normalisée: max(0, (target - score) / target).
            Fallback possible: ratio failed_runs/runs si aucun score n'est dispo.
- v_void  : max(0, (var_entropy_bits - void_var_limit) / void_var_limit)
- v_drift : drift de moyennes (zmax = max_col abs(mean_curr-mean_base)/std_base) normalisé par un seuil:
            max(0, (zmax - drift_z_limit) / drift_z_limit)

Score:
  incoherence_score = w_null*v_null + w_drift*v_drift + w_void*v_void

Si incoherence_score > threshold:
- écrit un rapport JSON (toujours)
- optionnel: déclenche une alerte (Slack / webhook / email SMTP)
- retourne exit code 3 (pratique pour CI)

Usage minimal:
  python integrity_check.py --ci-out _ci_out --threshold 0.25

Usage drift:
  python integrity_check.py --ci-out _ci_out --baseline-csv datasets/base.csv --current-csv datasets/curr.csv

Notes:
- Par défaut, on utilise p05 côté NullTrace: beaucoup plus stable que min_score (évite de bloquer sur un seul outlier).
- Le script logge les composantes (v_null/v_drift/v_void) et les sources trouvées, même quand c'est OK.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import smtplib
import ssl
import sys
import urllib.request
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def _read_json(p: Path) -> Dict[str, Any]:
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _safe_div(num: float, den: float) -> float:
    if den == 0.0 or math.isclose(den, 0.0):
        return 0.0
    return num / den


def _coerce_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
        if not math.isfinite(v):
            return default
        return v
    except Exception:
        return default


def _coerce_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _try_load_nulltrace_summary(ci_out: Path) -> Tuple[Optional[Dict[str, Any]], Optional[Path]]:
    """Cherche un nulltrace_summary.json (ou variante future). Retourne (summary_dict, summary_path)."""
    candidates = [
        ci_out / "nulltrace" / "nulltrace_summary.json",
        ci_out / "nulltrace" / "fluxguard_summary.json",
    ]
    for p in candidates:
        if p.exists():
            j = _read_json(p)
            # si fluxguard_summary.json: structure possible {"nulltrace": {...}}
            if "nulltrace" in j and isinstance(j["nulltrace"], dict):
                return j["nulltrace"], p
            return j, p
    return None, None


def _try_load_voidmark_summary(ci_out: Path) -> Tuple[Optional[Dict[str, Any]], Optional[Path]]:
    """Retourne (voidmark_summary_dict, path)."""
    candidates = [
        ci_out / "voidmark" / "fluxguard_summary.json",
        ci_out / "voidmark" / "voidmark_summary.json",
    ]
    for p in candidates:
        if p.exists():
            j = _read_json(p)
            if "voidmark" in j and isinstance(j["voidmark"], dict):
                # {"voidmark": {"summary": {...}}}
                vm = j["voidmark"]
                if isinstance(vm.get("summary"), dict):
                    return vm["summary"], p
                return vm, p
            return j, p
    return None, None


def _numeric_means_and_stds(csv_path: Path, max_rows: int = 200_000) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Profil ultra léger: moyenne et std sur colonnes numériques (stdlib only)."""
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
                s = v.strip()
                if s == "":
                    continue
                try:
                    x = float(s)
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


def _drift_mean_zmax(baseline_csv: Path, current_csv: Path) -> float:
    """Drift: max z-shift des moyennes sur colonnes numériques."""
    base_means, base_stds = _numeric_means_and_stds(baseline_csv)
    curr_means, _ = _numeric_means_and_stds(current_csv)

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

    return max(zs) if zs else 0.0


def _post_json(url: str, payload: Dict[str, Any]) -> Tuple[bool, str]:
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return True, f"http {resp.status}"
    except Exception as e:
        return False, str(e)


def _send_email(
    smtp_host: str,
    smtp_port: int,
    smtp_user: Optional[str],
    smtp_password: Optional[str],
    email_from: str,
    email_to: str,
    subject: str,
    body: str,
) -> Tuple[bool, str]:
    try:
        msg = EmailMessage()
        msg["From"] = email_from
        msg["To"] = email_to
        msg["Subject"] = subject
        msg.set_content(body)

        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.starttls(context=context)
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.send_message(msg)
        return True, "sent"
    except Exception as e:
        return False, str(e)


def _pick_null_score(null: Dict[str, Any], mode: str) -> Tuple[Optional[float], str]:
    """Retourne (score, mode_effectif)."""
    # normaliser des alias
    aliases = {
        "mean": "mean_score",
        "median": "p50",
        "p10": "p05",  # si l'utilisateur pense p10, p05 est le plus proche dispo
    }
    mode = aliases.get(mode, mode)

    # auto: préférer p05, sinon mean_score, sinon p50, sinon min_score
    if mode == "auto":
        for key in ("p05", "mean_score", "p50", "min_score"):
            v = null.get(key)
            if v is not None:
                return _coerce_float(v, default=float("nan")), key
        return None, "failed_ratio"

    if mode == "failed_ratio":
        return None, "failed_ratio"

    v = null.get(mode)
    if v is None:
        # fallback: min_score si présent, sinon rien
        if null.get("min_score") is not None:
            return _coerce_float(null.get("min_score"), default=float("nan")), "min_score"
        return None, "failed_ratio"

    return _coerce_float(v, default=float("nan")), mode


def main() -> None:
    ap = argparse.ArgumentParser(description="FluxGuard integrity check: score unique d'incohérence")

    ap.add_argument("--ci-out", type=Path, default=Path("_ci_out"))
    ap.add_argument("--threshold", type=float, default=0.25)

    ap.add_argument("--weights", type=str, default="0.3,0.4,0.3", help="w_null,w_drift,w_void")

    # NullTrace
    ap.add_argument("--null-target", "--null-min-score", dest="null_target", type=float, default=0.10,
                    help="cible score NullTrace (comparée à p05/mean/min selon --null-mode)")
    ap.add_argument(
        "--null-mode",
        type=str,
        default="p05",
        choices=["p05", "p01", "p50", "mean_score", "min_score", "failed_ratio", "auto"],
        help="score NullTrace à utiliser. p05 est stable. auto=préfère p05 si dispo.",
    )

    # VoidMark
    ap.add_argument("--void-var-limit", type=float, default=0.01, help="limite var_entropy_bits")

    # Drift (optionnel)
    ap.add_argument("--baseline-csv", type=Path, default=None)
    ap.add_argument("--current-csv", type=Path, default=None)
    ap.add_argument("--drift-z-limit", type=float, default=3.0, help="seuil z (en sigma) au-delà duquel drift > 0")

    # Alerting optionnel
    ap.add_argument("--slack-webhook", type=str, default=None)
    ap.add_argument("--webhook", type=str, default=None)

    ap.add_argument("--smtp-host", type=str, default=None)
    ap.add_argument("--smtp-port", type=int, default=587)
    ap.add_argument("--smtp-user", type=str, default=None)
    ap.add_argument("--smtp-password", type=str, default=None)
    ap.add_argument("--email-from", type=str, default=None)
    ap.add_argument("--email-to", type=str, default=None)

    ap.add_argument(
        "--output",
        type=Path,
        default=None,
        help="fichier json de sortie (sinon <ci-out>/integrity_incoherence.json)",
    )

    args = ap.parse_args()
    ci_out: Path = args.ci_out

    null, null_path = _try_load_nulltrace_summary(ci_out)
    void, void_path = _try_load_voidmark_summary(ci_out)

    # ---- Null violation (v_null) ----
    v_null = 0.0
    null_details: Dict[str, Any] = {"source": str(null_path) if null_path else None}

    if null:
        runs = _coerce_int(null.get("runs"), 0)
        failed_runs = _coerce_int(null.get("failed_runs"), 0)

        score, eff_mode = _pick_null_score(null, args.null_mode)
        null_details.update(
            {
                "runs": runs,
                "failed_runs": failed_runs,
                "null_mode": eff_mode,
                "target": float(args.null_target),
                "score": None if (score is None or (isinstance(score, float) and math.isnan(score))) else float(score),
            }
        )

        if eff_mode == "failed_ratio" or score is None or (isinstance(score, float) and math.isnan(score)):
            # fallback: ratio échecs
            v_null = _safe_div(float(failed_runs), float(runs)) if runs > 0 else 0.0
            null_details["computed_from"] = "failed_runs/runs"
        else:
            v_null = max(0.0, _safe_div(float(args.null_target) - float(score), float(args.null_target)))
            null_details["computed_from"] = eff_mode

        # ajouter quelques champs utiles si présents
        for k in ("min_score", "mean_score", "p01", "p05", "p50", "max_score"):
            if k in null:
                null_details[k] = _coerce_float(null.get(k), default=float("nan"))

    else:
        null_details["error"] = "nulltrace summary not found"

    # ---- Void violation (v_void) ----
    v_void = 0.0
    void_details: Dict[str, Any] = {"source": str(void_path) if void_path else None}
    if void:
        var_entropy = _coerce_float(void.get("var_entropy_bits"), 0.0)
        v_void = max(0.0, _safe_div(var_entropy - args.void_var_limit, args.void_var_limit))
        void_details.update(
            {
                "var_entropy_bits": var_entropy,
                "limit_var_entropy_bits": float(args.void_var_limit),
            }
        )
    else:
        void_details["error"] = "voidmark summary not found"

    # ---- Drift violation (v_drift) ----
    v_drift = 0.0
    drift_details: Dict[str, Any] = {}
    if args.baseline_csv and args.current_csv and args.baseline_csv.exists() and args.current_csv.exists():
        zmax = _drift_mean_zmax(args.baseline_csv, args.current_csv)
        v_drift = max(0.0, _safe_div(zmax - float(args.drift_z_limit), float(args.drift_z_limit)))
        drift_details = {
            "baseline_csv": str(args.baseline_csv),
            "current_csv": str(args.current_csv),
            "zmax_mean_shift": zmax,
            "drift_z_limit": float(args.drift_z_limit),
        }
    else:
        drift_details = {
            "note": "no baseline/current csv provided or files missing, drift set to 0",
            "baseline_csv": str(args.baseline_csv) if args.baseline_csv else None,
            "current_csv": str(args.current_csv) if args.current_csv else None,
            "drift_z_limit": float(args.drift_z_limit),
        }

    # weights
    parts = [p.strip() for p in args.weights.split(",")]
    if len(parts) != 3:
        raise SystemExit("weights must be 'w_null,w_drift,w_void'")
    w_null, w_drift, w_void = float(parts[0]), float(parts[1]), float(parts[2])

    inco = (w_null * v_null) + (w_drift * v_drift) + (w_void * v_void)

    out_path = args.output or (ci_out / "integrity_incoherence.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "threshold": float(args.threshold),
        "weights": {"w_null": w_null, "w_drift": w_drift, "w_void": w_void},
        "violations": {"v_null": v_null, "v_drift": v_drift, "v_void": v_void},
        "incoherence_score": inco,
        "components": {"nulltrace": null_details, "voidmark": void_details, "drift": drift_details},
        "decision": "BLOCK" if inco > float(args.threshold) else "OK",
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=True)

    # ---- Always log a readable summary (important for CI) ----
    print("FluxGuard integrity check")
    print(f"  weights: w_null={w_null:.3f} w_drift={w_drift:.3f} w_void={w_void:.3f}")
    print("  components:")
    print(
        f"    nulltrace: source={null_details.get('source')} mode={null_details.get('null_mode')} "
        f"runs={null_details.get('runs')} failed_runs={null_details.get('failed_runs')} "
        f"score={null_details.get('score')} target={args.null_target} -> v_null={v_null:.6f}"
    )
    print(
        f"    voidmark : source={void_details.get('source')} var_entropy_bits={void_details.get('var_entropy_bits')} "
        f"limit={void_details.get('limit_var_entropy_bits')} -> v_void={v_void:.6f}"
    )
    print(
        f"    drift    : baseline={drift_details.get('baseline_csv')} current={drift_details.get('current_csv')} "
        f"zmax={drift_details.get('zmax_mean_shift', 0.0)} z_limit={drift_details.get('drift_z_limit')} -> v_drift={v_drift:.6f}"
    )
    print(f"  incoherence_score: {inco:.6f} (threshold={args.threshold:.6f}) -> {payload['decision']}")
    print(f"  report: {out_path}")

    # ---- Alerting only on BLOCK ----
    if inco > float(args.threshold):
        summary_text = (
            f"FluxGuard BLOCK: incoherence_score={inco:.6f} threshold={args.threshold:.6f}\\n"
            f"v_null={v_null:.6f} v_drift={v_drift:.6f} v_void={v_void:.6f}\\n"
            f"nulltrace_source={null_details.get('source')} voidmark_source={void_details.get('source')}\\n"
        )

        alert_msgs = []

        if args.slack_webhook:
            ok, msg = _post_json(args.slack_webhook, {"text": summary_text})
            alert_msgs.append({"type": "slack", "ok": ok, "detail": msg})

        if args.webhook:
            ok, msg = _post_json(args.webhook, {"event": "fluxguard_incoherence_block", "payload": payload})
            alert_msgs.append({"type": "webhook", "ok": ok, "detail": msg})

        if args.smtp_host and args.email_from and args.email_to:
            ok, msg = _send_email(
                smtp_host=args.smtp_host,
                smtp_port=args.smtp_port,
                smtp_user=args.smtp_user,
                smtp_password=args.smtp_password,
                email_from=args.email_from,
                email_to=args.email_to,
                subject="FluxGuard BLOCK: incoherence_score",
                body=summary_text,
            )
            alert_msgs.append({"type": "email", "ok": ok, "detail": msg})

        if alert_msgs:
            for a in alert_msgs:
                print(f"  alert: {a['type']} ok={a['ok']} detail={a['detail']}", file=sys.stderr)

        raise SystemExit(3)


if __name__ == "__main__":
    main()
