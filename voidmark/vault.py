from __future__ import annotations

import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def relpath(p: Path, base: Path) -> str:
    try:
        return p.resolve().relative_to(base.resolve()).as_posix()
    except Exception:
        import os
        return os.path.relpath(str(p), str(base)).replace("\\", "/")


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
    m = math.fsum(values) / len(values)
    v = math.fsum((x - m) ** 2 for x in values) / len(values)
    m = round(m, 12)
    v = round(v, 12)
    return {
        "count": len(values),
        "mean_entropy_bits": m,
        "var_entropy_bits": v,
        "min_entropy_bits": round(min(values), 12),
        "max_entropy_bits": round(max(values), 12),
    }


def _quantile(sorted_vals: List[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if q <= 0:
        return float(sorted_vals[0])
    if q >= 1:
        return float(sorted_vals[-1])
    pos = (len(sorted_vals) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_vals[lo])
    w = pos - lo
    return float(sorted_vals[lo] * (1 - w) + sorted_vals[hi] * w)


def _mad(values: List[float], median: float) -> float:
    if not values:
        return 0.0
    dev = sorted([abs(x - median) for x in values])
    return _quantile(dev, 0.5)


def fingerprint_csv(path: Path) -> Dict[str, Any]:
    import csv

    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV sans header")
        fieldnames = list(reader.fieldnames)

        cols: Dict[str, List[float]] = {k: [] for k in fieldnames}
        total = 0
        missing = 0

        for row in reader:
            total += 1
            for k in fieldnames:
                v = row.get(k)
                if v is None:
                    missing += 1
                    continue
                s = str(v).strip()
                if s == "":
                    missing += 1
                    continue
                try:
                    cols[k].append(float(s))
                except Exception:
                    pass

    numeric = {k: v for k, v in cols.items() if len(v) > 1}
    if not numeric:
        raise ValueError("Aucune colonne numérique exploitable pour fingerprint")

    fp: Dict[str, Any] = {
        "rows": int(total),
        "missing_cells": int(missing),
        "missing_rate": round(missing / max(1, total * len(fieldnames)), 12),
        "columns": {},
    }

    for k, vals in numeric.items():
        svals = sorted(vals)
        m = math.fsum(vals) / len(vals)
        var = math.fsum((x - m) ** 2 for x in vals) / len(vals)
        std = math.sqrt(var)
        med = _quantile(svals, 0.5)
        fp["columns"][k] = {
            "count": len(vals),
            "mean": round(m, 12),
            "std": round(std, 12),
            "min": round(min(vals), 12),
            "max": round(max(vals), 12),
            "median": round(med, 12),
            "q05": round(_quantile(svals, 0.05), 12),
            "q95": round(_quantile(svals, 0.95), 12),
            "mad": round(_mad(vals, med), 12),
        }
    return fp


def ks_2samp_lite(x: List[float], y: List[float]) -> Dict[str, float]:
    if not x or not y:
        return {"D": 0.0, "p_value": 1.0}
    x = sorted(x)
    y = sorted(y)
    nx = len(x)
    ny = len(y)
    i = 0
    j = 0
    cdfx = 0.0
    cdfy = 0.0
    d = 0.0
    while i < nx and j < ny:
        if x[i] <= y[j]:
            i += 1
            cdfx = i / nx
        else:
            j += 1
            cdfy = j / ny
        d = max(d, abs(cdfx - cdfy))
    en = math.sqrt(nx * ny / (nx + ny))
    lam = (en + 0.12 + 0.11 / en) * d
    s = 0.0
    for k in range(1, 101):
        s += ((-1) ** (k - 1)) * math.exp(-2 * (k * k) * (lam * lam))
    p = max(0.0, min(1.0, 2 * s))
    return {"D": round(d, 12), "p_value": round(p, 12)}


def compare_fingerprints(
    current_csv: Path,
    baseline_mark: Optional[Path],
    alpha: float = 0.05,
) -> Dict[str, Any]:
    cur_fp = fingerprint_csv(current_csv)
    signals: Dict[str, Any] = {"flag_drift": False, "checks": {}}
    if baseline_mark is None or not baseline_mark.exists():
        return {"fingerprint": cur_fp, "drift_signals": signals}

    base = json.loads(baseline_mark.read_text(encoding="utf-8"))
    base_fp = base.get("fingerprint")
    if not isinstance(base_fp, dict):
        return {"fingerprint": cur_fp, "drift_signals": signals}

    for col, stats_cur in cur_fp.get("columns", {}).items():
        stats_base = base_fp.get("columns", {}).get(col)
        if not isinstance(stats_base, dict):
            continue
        dm = float(stats_cur.get("mean", 0.0)) - float(stats_base.get("mean", 0.0))
        dmed = float(stats_cur.get("median", 0.0)) - float(stats_base.get("median", 0.0))
        dmad = float(stats_cur.get("mad", 0.0)) - float(stats_base.get("mad", 0.0))
        signals["checks"][f"delta_mean_{col}"] = round(dm, 12)
        signals["checks"][f"delta_median_{col}"] = round(dmed, 12)
        signals["checks"][f"delta_mad_{col}"] = round(dmad, 12)

    import csv

    def read_cols(csv_path: Path) -> Dict[str, List[float]]:
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return {}
            out = {k: [] for k in reader.fieldnames}
            for row in reader:
                for k, v in row.items():
                    try:
                        out[k].append(float(str(v).strip()))
                    except Exception:
                        pass
            return {k: v for k, v in out.items() if len(v) > 1}

    base_csv = base.get("data_fingerprint_source_csv")
    base_csv_path = Path(base_csv) if isinstance(base_csv, str) else None
    if base_csv_path and base_csv_path.exists():
        cols_base = read_cols(base_csv_path)
        cols_cur = read_cols(current_csv)
        for col in sorted(set(cols_base) & set(cols_cur)):
            res = ks_2samp_lite(cols_base[col], cols_cur[col])
            signals["checks"][f"ks_pvalue_{col}"] = res["p_value"]
            signals["checks"][f"ks_D_{col}"] = res["D"]
            if res["p_value"] < float(alpha):
                signals["flag_drift"] = True

    for k, v in signals["checks"].items():
        if k.startswith("delta_mean_") and abs(float(v)) > 0.05:
            signals["flag_drift"] = True

    return {"fingerprint": cur_fp, "drift_signals": signals}


def update_version_history(version_db: Path, entry: Dict[str, Any]) -> None:
    version_db.parent.mkdir(parents=True, exist_ok=True)
    if version_db.exists():
        try:
            db = json.loads(version_db.read_text(encoding="utf-8"))
        except Exception:
            db = []
    else:
        db = []
    if not isinstance(db, list):
        db = []
    db.append(entry)
    version_db.write_text(json.dumps(db, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def voidmark_run_stress_test(
    target: Path,
    runs: int,
    noise: float,
    output_dir: Path,
    seed: int = 0,
    fingerprint_csv_path: Optional[Path] = None,
    baseline_mark: Optional[Path] = None,
    ks_alpha: float = 0.05,
    version_db: Optional[Path] = None,
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

    fp_block: Dict[str, Any] = {}
    if fingerprint_csv_path is not None and fingerprint_csv_path.exists():
        fp_block = compare_fingerprints(fingerprint_csv_path, baseline_mark=baseline_mark, alpha=float(ks_alpha))

    mark: Dict[str, Any] = {
        "target_name": target.name,
        "target_kind": ("dir" if target.is_dir() else "file"),
        "base_sha256": base_hash,
        "seed": int(seed),
        "noise": float(noise),
        "runs": int(runs),
        "summary": summary,
    }
    if fp_block:
        mark["fingerprint"] = fp_block.get("fingerprint")
        mark["drift_signals"] = fp_block.get("drift_signals")
        mark["data_fingerprint_source_csv"] = str(fingerprint_csv_path)

    mark_path = vault_dir / "voidmark_mark.json"
    with open(mark_path, "w", encoding="utf-8") as f:
        json.dump(mark, f, indent=2, ensure_ascii=False, sort_keys=True)

    if version_db is not None:
        entry = {
            "base_sha256": base_hash,
            "mark_relpath": relpath(mark_path, version_db.parent),
            "data_fingerprint_source_csv_relpath": (
                relpath(fingerprint_csv_path, version_db.parent) if fingerprint_csv_path else None
            ),
            "flag_drift": bool(mark.get("drift_signals", {}).get("flag_drift", False)),
        }
        update_version_history(version_db, entry)

    return {"mark": "vault/voidmark_mark.json", "summary": summary, "drift_signals": mark.get("drift_signals")}
