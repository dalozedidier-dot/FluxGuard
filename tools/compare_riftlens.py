#!/usr/bin/env python3
"""Compare deux sorties RiftLens (avant vs drift) et imprime un delta."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, Tuple


def load_report(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def edge_map(rep: dict) -> Dict[Tuple[str, str], float]:
    m: Dict[Tuple[str, str], float] = {}
    for e in rep.get("edges", []):
        a, b = e["a"], e["b"]
        if a > b:
            a, b = b, a
        m[(a, b)] = float(e["corr"])
    return m


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: tools/compare_riftlens.py <riftlens_dir_prev> <riftlens_dir_curr>", file=sys.stderr)
        raise SystemExit(2)

    d1 = Path(sys.argv[1])
    d2 = Path(sys.argv[2])

    reps1 = sorted(d1.glob("riftlens_report_thr_*.json"))
    reps2 = sorted(d2.glob("riftlens_report_thr_*.json"))
    if not reps1 or not reps2:
        print("Aucun report trouvé", file=sys.stderr)
        raise SystemExit(2)

    by_name2 = {p.name: p for p in reps2}

    for p1 in reps1:
        p2 = by_name2.get(p1.name)
        if not p2:
            continue
        r1 = load_report(p1)
        r2 = load_report(p2)
        m1 = edge_map(r1)
        m2 = edge_map(r2)
        thr = r1.get("threshold")

        gone = sorted([k for k in m1.keys() if k not in m2])
        new = sorted([k for k in m2.keys() if k not in m1])
        common = sorted([k for k in m1.keys() if k in m2])

        print(f"Seuil {thr}: prev={len(m1)} edges, curr={len(m2)} edges")
        if gone:
            print("  Disparues:", ", ".join([f"{a}-{b}" for a, b in gone]))
        if new:
            print("  Nouvelles:", ", ".join([f"{a}-{b}" for a, b in new]))

        top = sorted(common, key=lambda k: abs(m2[k] - m1[k]), reverse=True)[:5]
        if top:
            print("  Top deltas:")
            for a, b in top:
                d = m2[(a, b)] - m1[(a, b)]
                print(f"    {a}-{b}: {m1[(a, b)]:.6f} -> {m2[(a, b)]:.6f} (d={d:+.6f})")

    raise SystemExit(0)


if __name__ == "__main__":
    main()
