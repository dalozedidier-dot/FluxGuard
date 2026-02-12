from __future__ import annotations

import csv
import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


def _is_floatish(s: str) -> bool:
    try:
        float(s)
        return True
    except Exception:
        return False


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        if _is_floatish(s):
            return float(s)
    return None


def _median(xs: Sequence[float]) -> float:
    if not xs:
        return 0.0
    ys = sorted(xs)
    n = len(ys)
    mid = n // 2
    if n % 2 == 1:
        return float(ys[mid])
    return (ys[mid - 1] + ys[mid]) / 2.0


def _mad(xs: Sequence[float]) -> float:
    if not xs:
        return 0.0
    med = _median(xs)
    dev = [abs(x - med) for x in xs]
    return _median(dev)


def _quantile_sorted(sorted_xs: Sequence[float], q: float) -> float:
    if not sorted_xs:
        return 0.0
    if q <= 0.0:
        return float(sorted_xs[0])
    if q >= 1.0:
        return float(sorted_xs[-1])
    n = len(sorted_xs)
    pos = (n - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_xs[lo])
    w = pos - lo
    return float(sorted_xs[lo] * (1.0 - w) + sorted_xs[hi] * w)


def _safe_stdev(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return 0.0
    try:
        return float(statistics.pstdev(xs))
    except Exception:
        return 0.0


def read_table(path: Path, *, max_rows: Optional[int] = None) -> List[Dict[str, Any]]:
    """Lit un dataset tabulaire et renvoie une liste de dicts.

    Formats supportés:
      - CSV/TSV (stdlib)
      - JSON (liste d'objets ou {"rows":[...]})
      - JSONL/NDJSON (un objet par ligne)
      - Parquet (optionnel: pandas + pyarrow)
    """
    if not path.exists():
        raise FileNotFoundError(str(path))

    suffix = path.suffix.lower()
    if suffix in {".csv", ".tsv"}:
        dialect = "excel" if suffix == ".csv" else "excel-tab"
        rows: List[Dict[str, Any]] = []
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, dialect=dialect)
            if not reader.fieldnames:
                raise ValueError("Dataset sans header")
            for i, row in enumerate(reader):
                rows.append(dict(row))
                if max_rows is not None and i + 1 >= max_rows:
                    break
        return rows

    if suffix in {".json"}:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [dict(x) for x in data if isinstance(x, dict)]
        if isinstance(data, dict) and isinstance(data.get("rows"), list):
            return [dict(x) for x in data["rows"] if isinstance(x, dict)]
        raise ValueError("JSON non supporté: attend list[object] ou {'rows':[...]}")

    if suffix in {".jsonl", ".ndjson"}:
        rows = []
        with open(path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(dict(obj))
                if max_rows is not None and len(rows) >= max_rows:
                    break
        return rows

    if suffix in {".parquet"}:
        try:
            import pandas as pd  # type: ignore
        except Exception as e:
            raise RuntimeError("Parquet nécessite pandas+pyarrow (optionnels)") from e
        df = pd.read_parquet(path)
        if max_rows is not None:
            df = df.head(int(max_rows))
        return df.to_dict(orient="records")

    raise ValueError(f"Format non supporté: {suffix}")


def extract_numeric_columns(rows: List[Dict[str, Any]]) -> Dict[str, List[Optional[float]]]:
    """Retourne colonnes numériques alignées par index.

    Valeur = float si convertible, sinon None.
    """
    keys: List[str] = sorted({k for r in rows for k in r.keys()})
    cols: Dict[str, List[Optional[float]]] = {k: [] for k in keys}
    for r in rows:
        for k in keys:
            cols[k].append(_to_float(r.get(k)))
    return cols


def profile_table(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    cols = extract_numeric_columns(rows)
    total_rows = len(rows)
    prof: Dict[str, Any] = {"rows": total_rows, "columns": {}}

    all_keys = sorted({k for r in rows for k in r.keys()})
    for k in all_keys:
        raw_missing = 0
        raw_nonempty = 0
        raw_non_numeric = 0

        numeric: List[float] = []
        for r in rows:
            v = r.get(k)
            if v is None:
                raw_missing += 1
                continue
            if isinstance(v, str) and not v.strip():
                raw_missing += 1
                continue
            raw_nonempty += 1
            fv = _to_float(v)
            if fv is None:
                raw_non_numeric += 1
            else:
                numeric.append(float(fv))

        col_entry: Dict[str, Any] = {
            "missing": int(raw_missing),
            "nonempty": int(raw_nonempty),
            "non_numeric": int(raw_non_numeric),
            "numeric_count": int(len(numeric)),
        }

        if numeric:
            xs = numeric
            xs_sorted = sorted(xs)
            med = _median(xs_sorted)
            mad = _mad(xs_sorted)
            std = _safe_stdev(xs)
            mean = sum(xs) / len(xs)

            # Outliers robustes: z_MAD >= 3.5 (Iglewicz & Hoaglin)
            outliers = 0
            if mad > 0.0:
                for x in xs:
                    z = 0.6745 * (x - med) / mad
                    if abs(z) >= 3.5:
                        outliers += 1

            col_entry.update(
                {
                    "min": float(xs_sorted[0]),
                    "max": float(xs_sorted[-1]),
                    "mean": float(mean),
                    "std": float(std),
                    "median": float(med),
                    "mad": float(mad),
                    "p01": float(_quantile_sorted(xs_sorted, 0.01)),
                    "p05": float(_quantile_sorted(xs_sorted, 0.05)),
                    "p50": float(_quantile_sorted(xs_sorted, 0.50)),
                    "p95": float(_quantile_sorted(xs_sorted, 0.95)),
                    "p99": float(_quantile_sorted(xs_sorted, 0.99)),
                    "outliers_robust": int(outliers),
                }
            )

        prof["columns"][k] = col_entry

    return prof


def ks_statistic(x: Sequence[float], y: Sequence[float]) -> float:
    """KS statistic D (stdlib fallback, déterministe)."""
    if not x or not y:
        return 0.0
    xs = sorted(x)
    ys = sorted(y)
    nx = len(xs)
    ny = len(ys)

    i = 0
    j = 0
    cdf_x = 0.0
    cdf_y = 0.0
    d = 0.0

    while i < nx and j < ny:
        xv = xs[i]
        yv = ys[j]
        if xv <= yv:
            i += 1
            cdf_x = i / nx
        if yv <= xv:
            j += 1
            cdf_y = j / ny
        d = max(d, abs(cdf_x - cdf_y))

    return float(d)


def wasserstein_distance_1d(x: Sequence[float], y: Sequence[float], *, points: int = 101) -> float:
    """Wasserstein-1 approx par quantiles (stdlib, déterministe)."""
    if not x or not y:
        return 0.0
    xs = sorted(x)
    ys = sorted(y)
    acc = 0.0
    for i in range(points):
        q = i / (points - 1)
        acc += abs(_quantile_sorted(xs, q) - _quantile_sorted(ys, q))
    return float(acc / points)


def drift_tests(prev_rows: List[Dict[str, Any]], curr_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    prev_cols = extract_numeric_columns(prev_rows)
    curr_cols = extract_numeric_columns(curr_rows)

    report: Dict[str, Any] = {"columns": {}}

    shared = sorted(set(prev_cols.keys()) & set(curr_cols.keys()))
    for k in shared:
        px = [v for v in prev_cols[k] if isinstance(v, (int, float))]
        cy = [v for v in curr_cols[k] if isinstance(v, (int, float))]
        if len(px) < 2 or len(cy) < 2:
            continue

        # SciPy si dispo (sinon fallback)
        ks = None
        wass = None
        try:
            from scipy import stats  # type: ignore

            ks = float(stats.ks_2samp(px, cy).statistic)
            wass = float(stats.wasserstein_distance(px, cy))
        except Exception:
            ks = ks_statistic(px, cy)
            wass = wasserstein_distance_1d(px, cy)

        report["columns"][k] = {
            "prev_n": int(len(px)),
            "curr_n": int(len(cy)),
            "ks_d": float(ks),
            "wasserstein": float(wass),
        }

    return report
