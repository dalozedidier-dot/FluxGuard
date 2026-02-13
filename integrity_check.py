#!/usr/bin/env python3
"""
FluxGuard integrity check: score unique d'incohérence pour décider "ce batch est incohérent -> bloquer upstream".

Objectif:
- Convertir des sorties soak (NullTrace/VoidMark + éventuel drift) en un indicateur unique.
- Rester lightweight (stdlib only), sans imposer de dépendances.

Score:
- v_null  = failed_runs / runs  (si disponible via nulltrace_summary.json)
- v_void  = max(0, (var_entropy_bits - void_var_limit) / void_var_limit)
- v_drift = max z-shift des moyennes (optionnel via baseline/current CSV)

incoherence_score = w_null*v_null + w_drift*v_drift + w_void*v_void
Si incoherence_score > threshold:
- écrit un rapport JSON
- optionnel: déclenche une alerte (Slack/webhook/email)
- retourne exit code 3 (pratique pour CI)

Usage minimal:
  python integrity_check.py --ci-out _ci_out --threshold 0.25

Usage drift:
  python integrity_check.py --ci-out _ci_out --baseline-csv datasets/base.csv --current-csv datasets/curr.csv
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
from typing import Any, Dict, Iterable, Optional, Tuple


def _read_json(p: Path) -> Dict[str, Any]:
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _safe_div(num: float, den: float) -> float:
    if den == 0.0 or math.isclose(den, 0.0):
        return 0.0
    return num / den


def _coerce_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _coerce_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _try_load_nulltrace_summary(ci_out: Path) -> Tuple[Optional[Dict[str, Any]], Optional[Path]]:
    """
    Cherche un nulltrace_summary.json ou une variante future.
    Retourne (summary_dict, summary_path).
    """
    candidates = [
        ci_out / "nulltrace" / "nulltrace_summary.json",
        ci_out / "nulltrace" / "fluxguard_summary.json",  # futur éventuel
    ]
    for p in candidates:
        if not p.exists():
            continue
        j = _read_json(p)
        # si c'est un fluxguard_summary, essayer d'entrer dans la clé
        if "nulltrace" in j and isinstance(j["nulltrace"], dict):
            return j["nulltrace"], p
        return j, p
    return None, None


def _try_load_voidmark_summary(ci_out: Path) -> Tuple[Optional[Dict[str, Any]], Optional[Path]]:
    """
    Cherche voidmark summary dans fluxguard_summary.json (sortie actuelle) ou fichier dédié.
    Retourne (summary_dict, source_path).
    """
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
        # direct summary
        if isinstance(j.get("summary"), dict):
            return j["summary"], p
        if all(k in j for k in ("var_entropy_bits", "mean_entropy_bits")):
            return j, p
    return None, None


def _numeric_means_and_stds(csv_path: Path, max_rows: int = 200_000) -> Tuple[Dict[str, float], Dict[str, float]]:
    """
    Profil ultra léger: moyenne et std sur colonnes numériques.
    Std population (pas sample) pour stabilité.
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


def _drift_mean_zmax(baseline_csv: Path, current_csv: Path) -> Tuple[float, Dict[str, Any]]:
    """
    Drift: max z-shift des moyennes sur colonnes numériques.
    abs(mean_curr - mean_base) / std_base
    """
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
            zs.append((col, z))

    if not zs:
        return 0.0, {"zmax": 0.0, "column": None, "note": "no comparable numeric columns"}
    col, zmax = max(zs, key=lambda t: t[1])
    return float(zmax), {"zmax": float(zmax), "column": col, "compared_columns": len(zs)}


def _post_json(url: str, payload: Dict[str, Any], timeout_s: int = 10) -> Tuple[bool, str]:
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return True, f"HTTP {resp.status}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _send_email(
    smtp_host: str,
    smtp_port: int,
    use_starttls: bool,
    username: Optional[str],
    password: Optional[str],
    mail_from: str,
    mail_to: Iterable[str],
    subject: str,
    body: str,
) -> Tuple[bool, str]:
    try:
        msg = EmailMessage()
        msg["From"] = mail_from
        msg["To"] = ", ".join(mail_to)
        msg["Subject"] = subject
        msg.set_content(body)

        if use_starttls:
            context = ssl.create_default_context()
            with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as s:
                s.ehlo()
                s.starttls(context=context)
                s.ehlo()
                if username and password:
                    s.login(username, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as s:
                if username and password:
                    s.login(username, password)
                s.send_message(msg)

        return True, "sent"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def main() -> None:
    ap = argparse.ArgumentParser(description="FluxGuard integrity check: score unique d'incohérence")
    ap.add_argument("--ci-out", type=Path, default=Path("_ci_out"), help="répertoire contenant nulltrace/ voidmark/ etc.")
    ap.add_argument("--threshold", type=float, default=0.25)

    ap.add_argument("--weights", type=str, default="0.3,0.4,0.3", help="w_null,w_drift,w_void (somme recommandée=1)")

    ap.add_argument("--void-var-limit", type=float, default=0.01, help="plafond var_entropy_bits (VoidMark)")

    ap.add_argument("--baseline-csv", type=Path, default=None)
    ap.add_argument("--current-csv", type=Path, default=None)

    ap.add_argument("--output", type=Path, default=None, help="fichier json de sortie (sinon <ci-out>/integrity_incoherence.json)")

    # alerting optionnel
    ap.add_argument("--slack-webhook", type=str, default=None)
    ap.add_argument("--webhook", type=str, default=None)

    ap.add_argument("--smtp-host", type=str, default=None)
    ap.add_argument("--smtp-port", type=int, default=587)
    ap.add_argument("--smtp-starttls", action="store_true")
    ap.add_argument("--smtp-user", type=str, default=None)
    ap.add_argument("--smtp-password", type=str, default=None)
    ap.add_argument("--email-from", type=str, default=None)
    ap.add_argument("--email-to", action="append", default=[])

    args = ap.parse_args()

    ci_out: Path = args.ci_out

    # weights
    parts = [p.strip() for p in args.weights.split(",")]
    if len(parts) != 3:
        print("ERROR: --weights doit être 'w_null,w_drift,w_void'", file=sys.stderr)
        raise SystemExit(2)
    w_null, w_drift, w_void = (float(parts[0]), float(parts[1]), float(parts[2]))

    # NullTrace
    null_summary, null_path = _try_load_nulltrace_summary(ci_out)
    v_null = 0.0
    null_details: Dict[str, Any] = {"source": str(null_path) if null_path else None}

    if null_summary:
        runs = _coerce_int(null_summary.get("runs", 0), 0)
        failed = _coerce_int(null_summary.get("failed_runs", null_summary.get("failures", 0)), 0)
        ok = _coerce_int(null_summary.get("ok_runs", 0), 0)

        # v_null = fraction de violations (simple et stable)
        denom = float(runs if runs > 0 else (ok + failed if (ok + failed) > 0 else 1))
        v_null = max(0.0, _safe_div(float(failed), denom))

        null_details.update(
            {
                "runs": runs,
                "failed_runs": failed,
                "ok_runs": ok,
                "v_null": v_null,
            }
        )
    else:
        null_details.update({"error": "nulltrace summary not found", "v_null": 0.0})

    # VoidMark
    void_summary, void_path = _try_load_voidmark_summary(ci_out)
    v_void = 0.0
    void_details: Dict[str, Any] = {"source": str(void_path) if void_path else None}

    if void_summary:
        var_e = _coerce_float(void_summary.get("var_entropy_bits", 0.0), 0.0)
        # v_void = dépassement relatif du plafond
        v_void = max(0.0, _safe_div(var_e - float(args.void_var_limit), float(args.void_var_limit)))
        void_details.update(
            {
                "var_entropy_bits": var_e,
                "limit_var_entropy_bits": float(args.void_var_limit),
                "v_void": v_void,
            }
        )
    else:
        void_details.update({"error": "voidmark summary not found", "v_void": 0.0})

    # Drift
    v_drift = 0.0
    drift_details: Dict[str, Any] = {}
    if args.baseline_csv and args.current_csv and args.baseline_csv.exists() and args.current_csv.exists():
        zmax, meta = _drift_mean_zmax(args.baseline_csv, args.current_csv)
        v_drift = max(0.0, float(zmax))
        drift_details = {
            "baseline_csv": str(args.baseline_csv),
            "current_csv": str(args.current_csv),
            "zmax_mean_shift": float(zmax),
            "meta": meta,
            "v_drift": v_drift,
        }
    else:
        drift_details = {
            "note": "no baseline/current csv provided, drift set to 0",
            "v_drift": 0.0,
        }

    inco = (w_null * v_null) + (w_drift * v_drift) + (w_void * v_void)

    out_path = args.output or (ci_out / "integrity_incoherence.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "threshold": float(args.threshold),
        "weights": {"w_null": w_null, "w_drift": w_drift, "w_void": w_void},
        "violations": {"v_null": v_null, "v_drift": v_drift, "v_void": v_void},
        "incoherence_score": float(inco),
        "components": {"nulltrace": null_details, "voidmark": void_details, "drift": drift_details},
        "decision": "BLOCK" if inco > float(args.threshold) else "OK",
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=True)

    print(f"Incoherence score: {inco:.6f} (threshold={args.threshold:.6f}) -> {payload['decision']}")
    print(f"Report: {out_path}")

    if inco > float(args.threshold):
        # alerting optionnel
        alert_msgs = []
        summary_text = (
            f"FluxGuard incoherence_score={inco:.6f} threshold={args.threshold:.6f} decision=BLOCK\n"
            f"v_null={v_null:.6f} v_drift={v_drift:.6f} v_void={v_void:.6f}"
        )

        if args.slack_webhook:
            ok, msg = _post_json(args.slack_webhook, {"text": summary_text})
            alert_msgs.append({"type": "slack", "ok": ok, "detail": msg})

        if args.webhook:
            ok, msg = _post_json(args.webhook, {"event": "fluxguard_incoherence_block", "payload": payload})
            alert_msgs.append({"type": "webhook", "ok": ok, "detail": msg})

        if args.smtp_host and args.email_from and args.email_to:
            ok, msg = _send_email(
                smtp_host=args.smtp_host,
                smtp_port=int(args.smtp_port),
                use_starttls=bool(args.smtp_starttls),
                username=args.smtp_user,
                password=args.smtp_password,
                mail_from=args.email_from,
                mail_to=args.email_to,
                subject="FluxGuard: incoherence BLOCK",
                body=summary_text + "\n\nReport path: " + str(out_path),
            )
            alert_msgs.append({"type": "email", "ok": ok, "detail": msg})

        if alert_msgs:
            payload_alert = {"alerts": alert_msgs}
            alert_path = out_path.with_name("integrity_alerts.json")
            with open(alert_path, "w", encoding="utf-8") as f:
                json.dump(payload_alert, f, indent=2, ensure_ascii=False, sort_keys=True)
            print(f"Alerts report: {alert_path}")

        raise SystemExit(3)


if __name__ == "__main__":
    main()
