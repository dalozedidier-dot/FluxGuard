from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from io_utils import drift_tests, profile_table, read_table


def pearson_corr(x: List[float], y: List[float]) -> float:
    n = min(len(x), len(y))
    if n < 2:
        return 0.0
    mx = sum(x) / n
    my = sum(y) / n
    vx = sum((a - mx) ** 2 for a in x)
    vy = sum((b - my) ** 2 for b in y)
    if vx <= 0.0 or vy <= 0.0:
        return 0.0
    cov = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    return float(cov / math.sqrt(vx * vy))


def _pairwise_numeric_vectors(rows: List[Dict[str, Any]]) -> Dict[str, List[float]]:
    """Extrait colonnes numériques (valeurs float) en gardant uniquement les lignes exploitables.

    Règle: une colonne est conservée si elle a au moins 2 valeurs numériques.
    """
    keys = sorted({k for r in rows for k in r.keys()})
    tmp: Dict[str, List[float]] = {k: [] for k in keys}

    for r in rows:
        for k in keys:
            v = r.get(k)
            if v is None:
                continue
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                tmp[k].append(float(v))
                continue
            if isinstance(v, str):
                s = v.strip()
                if not s:
                    continue
                try:
                    tmp[k].append(float(s))
                except Exception:
                    continue

    numeric = {k: v for k, v in tmp.items() if len(v) >= 2}
    if not numeric:
        raise ValueError("Aucune colonne numérique exploitable")
    return numeric


def build_coherence_graph(data: Dict[str, List[float]], threshold: float) -> dict:
    keys = sorted(data.keys())
    edges: List[dict] = []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            raw = pearson_corr(data[a], data[b])
            if abs(raw) >= threshold:
                r = round(float(raw), 12)
                edges.append({"a": a, "b": b, "corr": round(r, 12)})
    return {"nodes": keys, "edges": edges, "threshold": float(threshold)}


def _corr_matrix(data: Dict[str, List[float]]) -> Tuple[List[str], List[List[float]]]:
    keys = sorted(data.keys())
    mat: List[List[float]] = []
    for i in range(len(keys)):
        row: List[float] = []
        for j in range(len(keys)):
            if i == j:
                row.append(1.0)
            else:
                row.append(float(pearson_corr(data[keys[i]], data[keys[j]])))
        mat.append(row)
    return keys, mat


def write_report(report: dict, outpath: Path) -> None:
    outpath.parent.mkdir(parents=True, exist_ok=True)
    with open(outpath, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, sort_keys=True)


def riftlens_run_csv(
    input_csv: Path,
    thresholds: List[float],
    output_dir: Path,
    shadow_prev: Optional[Path] = None,
    stat_tests: bool = False,
    profile: bool = False,
    plot: bool = False,
) -> dict:
    """RiftLens vNext

    - Support CSV/TSV/JSON/JSONL/Parquet via io_utils.read_table
    - Profiling optionnel
    - Drift tests optionnels (KS + Wasserstein) si shadow_prev fourni
    - Plots optionnels (matplotlib si dispo)
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    curr_rows = read_table(input_csv)
    data = _pairwise_numeric_vectors(curr_rows)

    reports = []
    for thr in thresholds:
        graph = build_coherence_graph(data, threshold=float(thr))
        out = output_dir / f"riftlens_report_thr_{float(thr):.2f}.json"
        write_report(graph, out)
        reports.append({"threshold": float(thr), "report": str(out)})

    extra: Dict[str, Any] = {}

    if profile:
        prof = profile_table(curr_rows)
        prof_path = output_dir / "riftlens_profile.json"
        write_report(prof, prof_path)
        extra["profile"] = str(prof_path)

    if stat_tests and shadow_prev is not None:
        prev_rows = read_table(shadow_prev)
        drift = drift_tests(prev_rows, curr_rows)
        drift_path = output_dir / "riftlens_drift_report.json"
        write_report(drift, drift_path)
        extra["drift"] = str(drift_path)

    if plot:
        try:
            from viz import save_heatmap
        except Exception:
            save_heatmap = None  # type: ignore

        if save_heatmap is not None:
            labels, mat = _corr_matrix(data)
            out_png = output_dir / "riftlens_corr_heatmap.png"
            p = save_heatmap(mat, labels, out_png, title="RiftLens correlation heatmap")
            if p:
                extra["plot_corr_heatmap"] = p

    result: Dict[str, Any] = {"input": str(input_csv), "reports": reports}
    result.update(extra)
    if shadow_prev is not None:
        result["shadow_prev"] = str(shadow_prev)
    result["options"] = {"stat_tests": bool(stat_tests), "profile": bool(profile), "plot": bool(plot)}
    return result
