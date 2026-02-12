from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from riftlens.core import riftlens_run_csv
from voidmark.vault import voidmark_run_stress_test


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=True)


def run_full_chain(
    shadow_prev: Path,
    shadow_curr: Path,
    output_dir: Path,
    *,
    rift_thresholds: Optional[List[float]] = None,
    rift_stat_tests: bool = False,
    rift_profile: bool = False,
    plots: bool = False,
    voidmark_runs: int = 100,
    voidmark_noise: float = 0.02,
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    step0 = output_dir / "step0_inputs"
    step0.mkdir(parents=True, exist_ok=True)
    inputs_report = {
        "shadow_prev": str(shadow_prev),
        "shadow_curr": str(shadow_curr),
        "shadow_prev_sha256": sha256_file(shadow_prev) if shadow_prev.is_file() else None,
        "shadow_curr_sha256": sha256_file(shadow_curr) if shadow_curr.is_file() else None,
    }
    write_json(step0 / "inputs_report.json", inputs_report)

    step1 = output_dir / "step1_riftlens"
    rift = riftlens_run_csv(
        input_csv=shadow_curr,
        thresholds=rift_thresholds or [0.5, 0.7, 0.8],
        output_dir=step1,
        shadow_prev=shadow_prev,
        stat_tests=rift_stat_tests,
        profile=rift_profile,
        plot=plots,
    )

    step2 = output_dir / "step2_voidmark"
    void = voidmark_run_stress_test(
        target=output_dir,
        runs=int(voidmark_runs),
        noise=float(voidmark_noise),
        output_dir=step2,
        seed=0,
        plot=plots,
    )

    chain = {"inputs": str(step0 / "inputs_report.json"), "riftlens": rift, "voidmark": void}
    write_json(output_dir / "full_chain_report.json", chain)
    return chain
