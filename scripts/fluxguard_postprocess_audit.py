\
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Iterable

def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

def quantize(obj: Any, ndigits: int = 12) -> Any:
    if isinstance(obj, float):
        return round(obj, ndigits)
    if isinstance(obj, dict):
        return {k: quantize(v, ndigits) for k, v in obj.items()}
    if isinstance(obj, list):
        return [quantize(v, ndigits) for v in obj]
    return obj

def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def find_targets(root: Path, recursive: bool) -> Iterable[Path]:
    if recursive:
        # handle layouts like _ci_out/full/..., _ci_out/riftlens/...
        for p in root.rglob("fluxguard_summary.json"):
            yield p
    else:
        p = root / "fluxguard_summary.json"
        if p.exists():
            yield p

def locate_voidmark_mark(summary_path: Path) -> Path | None:
    # Common layouts:
    #   full/step2_voidmark/vault/voidmark_mark.json
    # Summary structure often includes a relative path under full_chain.voidmark.mark
    try:
        summ = read_json(summary_path)
    except Exception:
        return None

    # Try structured pointer first
    try:
        mark_rel = summ["full_chain"]["voidmark"]["mark"]
        # mark_rel often starts with "_ci_out/" - normalize it relative to parent of root
        # If summary is at ".../_ci_out/full/fluxguard_summary.json", then root is ".../_ci_out/full"
        # We want to resolve mark_rel relative to the directory containing "_ci_out".
        # Heuristic: walk up until folder name "_ci_out" is found.
        cur = summary_path.parent
        base = None
        while cur != cur.parent:
            if cur.name == "_ci_out":
                base = cur
                break
            cur = cur.parent
        if base is not None and isinstance(mark_rel, str):
            if mark_rel.startswith("_ci_out/"):
                return (base / mark_rel[len("_ci_out/"):]).resolve()
            return (summary_path.parent / mark_rel).resolve()
    except Exception:
        pass

    # Fallback: search nearby
    for cand in summary_path.parent.rglob("voidmark_mark.json"):
        return cand
    return None

def ensure_path(d: dict, keys: list[str]) -> dict:
    cur = d
    for k in keys:
        if k not in cur or not isinstance(cur[k], dict):
            cur[k] = {}
        cur = cur[k]
    return cur

def process_one(summary_path: Path, write_mark: bool, do_quantize: bool, ndigits: int) -> None:
    summ = read_json(summary_path)

    # Fix timestamp
    summ["generated_at_utc"] = utc_now_iso()

    # Pull seed from mark if possible
    mark_path = locate_voidmark_mark(summary_path)
    seed = None
    mark = None
    if mark_path is not None and mark_path.exists():
        try:
            mark = read_json(mark_path)
            seed = mark.get("seed")
        except Exception:
            seed = None

    # Inject into summary if seed available
    if seed is not None:
        voidmark_node = ensure_path(summ, ["full_chain", "voidmark"])
        # Do NOT overwrite existing if present; but keep it consistent if different
        voidmark_node["seed_effective"] = int(seed)

    if do_quantize:
        summ = quantize(summ, ndigits)
        if mark is not None:
            mark = quantize(mark, ndigits)

    write_json(summary_path, summ)

    if write_mark and mark is not None and mark_path is not None:
        # Also ensure mark includes generated_at_utc for auditability
        if isinstance(mark, dict):
            mark.setdefault("generated_at_utc", summ["generated_at_utc"])
        write_json(mark_path, mark)

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="Folder containing fluxguard_summary.json (e.g. _ci_out/full) OR _ci_out with --recursive")
    ap.add_argument("--recursive", action="store_true", help="Find all fluxguard_summary.json under root")
    ap.add_argument("--write-mark", action="store_true", help="Rewrite voidmark_mark.json too (adds generated_at_utc, optional quantize)")
    ap.add_argument("--quantize", action="store_true", help="Round floats (default 12 decimals)")
    ap.add_argument("--ndigits", type=int, default=12, help="Decimals for rounding when --quantize is set")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        raise SystemExit(f"Root not found: {root}")

    targets = list(find_targets(root, args.recursive))
    if not targets:
        raise SystemExit("No fluxguard_summary.json found")

    for s in targets:
        process_one(s, write_mark=args.write_mark, do_quantize=args.quantize, ndigits=args.ndigits)
        print(f"Patched: {s}")

    print(f"Done. Patched {len(targets)} summaries.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
