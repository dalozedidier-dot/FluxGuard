from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from alerts import AlertConfig, notify
from nulltrace.soak import nulltrace_run_mass_soak
from riftlens.core import riftlens_run_csv
from voidmark.vault import voidmark_run_stress_test


def utc_timestamp() -> str:
    sde = os.getenv("SOURCE_DATE_EPOCH")
    if sde:
        dt = datetime.fromtimestamp(int(sde), tz=timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    ensure_dir(path.parent)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=True)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class DaemonState:
    last_path: Optional[str] = None
    last_sha256: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"last_path": self.last_path, "last_sha256": self.last_sha256}

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "DaemonState":
        return DaemonState(last_path=d.get("last_path"), last_sha256=d.get("last_sha256"))


def load_state(path: Path) -> DaemonState:
    if not path.exists():
        return DaemonState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return DaemonState.from_dict(data)
    except Exception:
        pass
    return DaemonState()


def save_state(path: Path, state: DaemonState) -> None:
    write_json(path, state.to_dict())


def resolve_watch_target(watch: Path, *, pattern: str) -> Optional[Path]:
    if watch.is_file():
        return watch

    if watch.is_dir():
        newest: Optional[Tuple[float, Path]] = None
        for p in watch.rglob("*"):
            if not p.is_file():
                continue
            if not fnmatch.fnmatch(p.name, pattern):
                continue
            try:
                m = p.stat().st_mtime
            except Exception:
                continue
            if newest is None or m > newest[0]:
                newest = (m, p)
        return newest[1] if newest else None

    return None


def run_pipeline(
    *,
    pipeline: str,
    curr: Path,
    shadow_prev: Optional[Path],
    output_dir: Path,
    constraints: Path,
    nulltrace_runs: int,
    voidmark_runs: int,
    voidmark_noise: float,
    rift_thresholds: list[float],
    rift_stat_tests: bool,
    rift_profile: bool,
    plots: bool,
) -> Dict[str, Any]:
    ensure_dir(output_dir)

    result: Dict[str, Any] = {"pipeline": pipeline, "input": str(curr)}

    if pipeline in {"riftlens", "monitor", "chain"}:
        step = output_dir / "riftlens"
        rift = riftlens_run_csv(
            input_csv=curr,
            thresholds=rift_thresholds,
            output_dir=step,
            shadow_prev=shadow_prev,
            stat_tests=rift_stat_tests,
            profile=rift_profile,
            plot=plots,
        )
        result["riftlens"] = rift

    if pipeline in {"nulltrace", "monitor"}:
        step = output_dir / "nulltrace"
        nt = nulltrace_run_mass_soak(
            runs=int(nulltrace_runs),
            output_dir=step,
            constraints_path=constraints,
            seed=0,
            plot=plots,
        )
        result["nulltrace"] = nt

    if pipeline in {"voidmark", "monitor", "chain"}:
        step = output_dir / "voidmark"
        vm = voidmark_run_stress_test(
            target=curr,
            runs=int(voidmark_runs),
            noise=float(voidmark_noise),
            output_dir=step,
            seed=0,
            plot=plots,
        )
        result["voidmark"] = vm

    return result


def daemon_loop(
    *,
    watch: Path,
    pattern: str,
    interval_s: int,
    pipeline: str,
    output_dir: Path,
    state_file: Path,
    once: bool,
    shadow_prev: Optional[Path],
    constraints: Path,
    nulltrace_runs: int,
    voidmark_runs: int,
    voidmark_noise: float,
    rift_thresholds: list[float],
    rift_stat_tests: bool,
    rift_profile: bool,
    plots: bool,
    alert_var_entropy_gt: float,
    alert_nulltrace_min_score_lt: float,
    alerts: AlertConfig,
) -> None:
    ensure_dir(output_dir)
    ensure_dir(state_file.parent)

    state = load_state(state_file)

    while True:
        curr = resolve_watch_target(watch, pattern=pattern)
        tick: Dict[str, Any] = {
            "generated_at_utc": utc_timestamp(),
            "watch": str(watch),
            "pattern": pattern,
            "pipeline": pipeline,
            "status": "idle",
        }

        if curr is None:
            tick["status"] = "no_input"
            write_json(output_dir / "daemon_last_tick.json", tick)
        else:
            sha = sha256_file(curr)
            changed = (state.last_path != str(curr)) or (state.last_sha256 != sha)

            tick["current_path"] = str(curr)
            tick["current_sha256"] = sha
            tick["changed"] = bool(changed)

            if changed:
                run_id = utc_timestamp().replace(":", "").replace("-", "").replace("Z", "Z")
                run_dir = output_dir / "daemon_runs" / run_id
                ensure_dir(run_dir)

                tick["status"] = "running"
                write_json(run_dir / "daemon_tick_meta.json", tick)

                try:
                    out = run_pipeline(
                        pipeline=pipeline,
                        curr=curr,
                        shadow_prev=shadow_prev,
                        output_dir=run_dir,
                        constraints=constraints,
                        nulltrace_runs=nulltrace_runs,
                        voidmark_runs=voidmark_runs,
                        voidmark_noise=voidmark_noise,
                        rift_thresholds=rift_thresholds,
                        rift_stat_tests=rift_stat_tests,
                        rift_profile=rift_profile,
                        plots=plots,
                    )
                    tick["status"] = "ok"
                    tick["run_dir"] = str(run_dir)
                    tick["result"] = out

                    # Alert logic
                    alerts_fired: list[dict] = []

                    try:
                        vm = out.get("voidmark", {}).get("summary", {})
                        ve = vm.get("var_entropy_bits")
                        if isinstance(ve, (int, float)) and ve > float(alert_var_entropy_gt):
                            alerts_fired.append(
                                {"type": "voidmark_var_entropy", "value": float(ve), "threshold": float(alert_var_entropy_gt)}
                            )
                    except Exception:
                        pass

                    try:
                        nt = out.get("nulltrace", {})
                        min_score = nt.get("min_score")
                        if isinstance(min_score, (int, float)) and min_score < float(alert_nulltrace_min_score_lt):
                            alerts_fired.append(
                                {"type": "nulltrace_min_score", "value": float(min_score), "threshold": float(alert_nulltrace_min_score_lt)}
                            )
                    except Exception:
                        pass

                    tick["alerts_fired"] = alerts_fired

                    if alerts_fired:
                        title = "FluxGuard alert"
                        msg = json.dumps({"input": str(curr), "alerts": alerts_fired, "run_dir": str(run_dir)}, ensure_ascii=False)
                        notify(alerts, title=title, message=msg, payload={"alerts": alerts_fired, "run_dir": str(run_dir)})

                    write_json(run_dir / "daemon_tick_summary.json", tick)

                    state.last_path = str(curr)
                    state.last_sha256 = sha
                    save_state(state_file, state)

                except Exception as e:
                    tick["status"] = "error"
                    tick["error"] = {"type": type(e).__name__, "message": str(e)}
                    write_json(run_dir / "daemon_tick_summary.json", tick)

                write_json(output_dir / "daemon_last_tick.json", tick)
            else:
                tick["status"] = "no_change"
                write_json(output_dir / "daemon_last_tick.json", tick)

        if once:
            break
        time.sleep(max(1, int(interval_s)))
