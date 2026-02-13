#!/usr/bin/env python3
"""
FluxGuard integrity check: score unique d'incohérence pour décider "ce batch est incohérent -> bloquer upstream".

But:
- Transformer des résultats soak (NullTrace / VoidMark / drift stats) en un indicateur unique et auditable.
- Rester lightweight (stdlib only). Certaines métriques utilisent des fallbacks quand SciPy/pandas ne sont pas présents.

Score (toutes les composantes sont des "violations" >= 0):
- v_null  : par défaut ratio failed_runs/runs (si dispo). Si min_score est disponible, on peut aussi
            l'exploiter via --null-min-score (mode auto).
- v_void  : max(0, (var_entropy_bits - void_var_limit) / void_var_limit)
- v_drift : zmax = max_col abs(mean_curr - mean_base) / std_base (optionnel via baseline/current CSV)

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
        ci_out / "nulltrace" / "fluxguard_summary.json",  # futur éventuel
    ]
    for p in candidates:
        if not p.exists():
            continue
        j = _read_json(p)
        if "nulltrace" in j and isinstance(j["nulltrace"], dict):
            return j["nulltrace"], p
        return j, p
    return None, None


def _try_load_voidmark_summary(ci_out: Path) -> Tuple[Optional[Dict[str, Any]], Optional[Path]]:
    """Cherche voidmark summary. Retourne (summary_dict, source_path)."""
    candidates = [
        ci_out / "voidmark" / "fluxguard_summary.json",
        ci_out / "voidmark" / "voidmark_summary.json",
        ci_out / "voidmark" / "vault" / "voidmark_mark.json",
    ]
    for p in candidates:
        if not p.exists():
            continue
        j = _read_json(p)
        if p.name == "fluxguard_summary.json":
            vm = j.get("voidmark")
            if isinstance(vm, dict) and isinstance(vm.get("summary"), dict):
                return vm["summary"], p
        if p.name == "voidmark_mark.json":
            if isinstance(j.get("summary"), dict):
                return j["summary"], p
        if isinstance(j.get("summary"), dict):
            return j["summary"], p
        if all(k in j for k in ("var_entropy_bits", "mean_entropy_bits")):
            return j, p
    return None, None


def _numeric_means_and_stds(csv_path: Path, max_rows: int = 200_000) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Profil ultra léger: moyenne et std sur colonnes numériques (fallback stdlib)."""
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
                s = str(v).strip()
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

    zmax = 0.0
    for col, mu_base in base_means.items():
        if col not in curr_means:
            continue
        sd = base_stds.get(col, 0.0)
        if sd <= 0.0:
            continue
        z = abs(curr_means[col] - mu_base) / sd
        if math.isfinite(z):
            zmax = max(zmax, z)

    return zmax


def _post_json(url: str, payload: Dict[str, Any], timeout_s: int = 8) -> Tuple[bool, str]:
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return True, f"HTTP {resp.status}"
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


def main() -> None:
    ap = argparse.ArgumentParser(description="FluxGuard integrity check: score unique d'incohérence")
    ap.add_argument("--ci-out", type=Path, default=Path("_ci_out"))
    ap.add_argument("--threshold", type=float, default=0.25)

    ap.add_argument("--weights", type=str, default="0.3,0.4,0.3", help="w_null,w_drift,w_void")

    # NullTrace
    ap.add_argument("--null-min-score", type=float, default=0.10, help="cible min_score si dispo")
    ap.add_argument(
        "--null-mode",
        type=str,
        default="auto",
        choices=["auto", "failed_ratio", "min_score"],
        help="auto=utilise min_score si présent sinon failed_ratio",
    )

    # VoidMark
    ap.add_argument("--void-var-limit", type=float, default=0.01, help="limite var_entropy_bits")

    # Drift (optionnel)
    ap.add_argument("--baseline-csv", type=Path, default=None)
    ap.add_argument("--current-csv", type=Path, default=None)

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
        min_score = _coerce_float(null.get("min_score"), default=float("nan"))

        null_details.update(
            {
                "runs": runs,
                "failed_runs": failed_runs,
                "min_score": None if math.isnan(min_score) else min_score,
                "target_min_score": float(args.null_min_score),
            }
        )

        mode = args.null_mode
        if mode == "auto":
            mode = "min_score" if (not math.isnan(min_score)) else "failed_ratio"

        if mode == "min_score" and not math.isnan(min_score):
            # violation relative: 0 si min_score >= target
            v_null = max(0.0, _safe_div(args.null_min_score - min_score, args.null_min_score))
            null_details["null_mode"] = "min_score"
        else:
            # fallback: ratio échecs
            v_null = _safe_div(float(failed_runs), float(runs)) if runs > 0 else 0.0
            null_details["null_mode"] = "failed_ratio"

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
        v_drift = max(0.0, zmax)
        drift_details = {
            "baseline_csv": str(args.baseline_csv),
            "current_csv": str(args.current_csv),
            "zmax_mean_shift": zmax,
        }
    else:
        drift_details = {
            "note": "no baseline/current csv provided or files missing, drift set to 0",
            "baseline_csv": str(args.baseline_csv) if args.baseline_csv else None,
            "current_csv": str(args.current_csv) if args.current_csv else None,
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
    print(f"    nulltrace: source={null_details.get('source')} mode={null_details.get('null_mode')} "
          f"runs={null_details.get('runs')} failed_runs={null_details.get('failed_runs')} "
          f"min_score={null_details.get('min_score')} -> v_null={v_null:.6f}")
    print(f"    voidmark : source={void_details.get('source')} var_entropy_bits={void_details.get('var_entropy_bits')} "
          f"limit={void_details.get('limit_var_entropy_bits')} -> v_void={v_void:.6f}")
    print(f"    drift    : baseline={drift_details.get('baseline_csv')} current={drift_details.get('current_csv')} "
          f"zmax={drift_details.get('zmax_mean_shift', 0.0)} -> v_drift={v_drift:.6f}")
    print(f"  incoherence_score: {inco:.6f} (threshold={args.threshold:.6f}) -> {payload['decision']}")
    print(f"  report: {out_path}")

    # ---- Alerting only on BLOCK ----
    if inco > float(args.threshold):
        summary_text = (
            f"FluxGuard BLOCK: incoherence_score={inco:.6f} threshold={args.threshold:.6f}\n"
            f"v_null={v_null:.6f} v_drift={v_drift:.6f} v_void={v_void:.6f}\n"
            f"nulltrace_source={null_details.get('source')} voidmark_source={void_details.get('source')}\n"
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
            # best-effort log
            for a in alert_msgs:
                print(f"  alert: {a['type']} ok={a['ok']} detail={a['detail']}", file=sys.stderr)

        raise SystemExit(3)


if __name__ == "__main__":
    main()
