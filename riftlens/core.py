from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Dict, List


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except Exception:
        return False


def read_numeric_csv(path: Path) -> Dict[str, List[float]]:
    """
    Lit un CSV avec header.
    Conserve uniquement les colonnes numériques.
    Ignore les cellules non numériques.
    """
    cols: Dict[str, List[float]] = {}
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV sans header")
        for name in reader.fieldnames:
            cols[name] = []

        for row in reader:
            for k, v in row.items():
                if v is None:
                    continue
                v = v.strip()
                if _is_float(v):
                    cols[k].append(float(v))

    numeric = {k: v for k, v in cols.items() if len(v) > 1}
    if not numeric:
        raise ValueError("Aucune colonne numérique exploitable")
    return numeric


def pearson_corr(x: List[float], y: List[float]) -> float:
    n = min(len(x), len(y))
    if n < 2:
        return 0.0
    x = x[:n]
    y = y[:n]
    mx = sum(x) / n
    my = sum(y) / n
    vx = sum((a - mx) ** 2 for a in x)
    vy = sum((b - my) ** 2 for b in y)
    if vx <= 0.0 or vy <= 0.0:
        return 0.0
    cov = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    return cov / math.sqrt(vx * vy)


def build_coherence_graph(data: Dict[str, List[float]], threshold: float) -> dict:
    keys = sorted(data.keys())
    edges: List[dict] = []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            r = pearson_corr(data[a], data[b])
            if abs(r) >= threshold:
                edges.append({"a": a, "b": b, "corr": r})
    return {"nodes": keys, "edges": edges, "threshold": threshold}


def write_report(report: dict, outpath: Path) -> None:
    outpath.parent.mkdir(parents=True, exist_ok=True)
    import json

    with open(outpath, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)


def riftlens_run_csv(input_csv: Path, thresholds: List[float], output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = read_numeric_csv(input_csv)
    reports = []
    for thr in thresholds:
        graph = build_coherence_graph(data, threshold=float(thr))
        out = output_dir / f"riftlens_report_thr_{float(thr):.2f}.json"
        write_report(graph, out)
        reports.append({"threshold": float(thr), "report": str(out)})
    return {"input": str(input_csv), "reports": reports}
