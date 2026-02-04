#!/usr/bin/env python3
import hashlib
import json
import sys
import zipfile
from dataclasses import dataclass
from typing import Any, Dict, Tuple

def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def is_json(path: str) -> bool:
    return path.lower().endswith(".json")

def try_parse_json(b: bytes) -> Any:
    try:
        return json.loads(b.decode("utf-8"))
    except Exception:
        return None

def flatten_numbers(obj: Any, prefix: str = ""):
    # yield (path, float_value) for all floats found
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from flatten_numbers(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from flatten_numbers(v, f"{prefix}[{i}]")
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        # treat ints as floats for comparison, too
        yield (prefix, float(obj))

def compare_json(a: Any, b: Any, atol: float = 0.0):
    a_nums = dict(flatten_numbers(a))
    b_nums = dict(flatten_numbers(b))
    all_keys = sorted(set(a_nums) | set(b_nums))
    diffs = []
    for k in all_keys:
        if k not in a_nums or k not in b_nums:
            diffs.append((k, a_nums.get(k), b_nums.get(k), None))
            continue
        da = a_nums[k]
        db = b_nums[k]
        d = abs(da - db)
        if d > atol:
            diffs.append((k, da, db, d))
    return diffs

def zip_index(zip_path: str) -> Dict[str, Tuple[int, str]]:
    out = {}
    with zipfile.ZipFile(zip_path, "r") as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            b = z.read(info.filename)
            out[info.filename] = (info.file_size, sha256_bytes(b))
    return out

def read_member(zip_path: str, member: str) -> bytes:
    with zipfile.ZipFile(zip_path, "r") as z:
        return z.read(member)

def main() -> int:
    if len(sys.argv) != 3:
        print("usage: fluxguard_compare_zips.py A.zip B.zip", file=sys.stderr)
        return 2

    a_zip, b_zip = sys.argv[1], sys.argv[2]
    a_idx = zip_index(a_zip)
    b_idx = zip_index(b_zip)

    a_files = set(a_idx)
    b_files = set(b_idx)
    only_a = sorted(a_files - b_files)
    only_b = sorted(b_files - a_files)
    common = sorted(a_files & b_files)

    print(f"files: A={len(a_files)} B={len(b_files)} common={len(common)}")
    if only_a:
        print("\nonly in A:")
        for f in only_a[:50]:
            print(f"  {f}")
        if len(only_a) > 50:
            print(f"  ... ({len(only_a)-50} more)")
    if only_b:
        print("\nonly in B:")
        for f in only_b[:50]:
            print(f"  {f}")
        if len(only_b) > 50:
            print(f"  ... ({len(only_b)-50} more)")

    changed = []
    for f in common:
        if a_idx[f][1] != b_idx[f][1]:
            changed.append(f)

    print(f"\nchanged files: {len(changed)}")
    for f in changed[:50]:
        print(f"  {f}")
    if len(changed) > 50:
        print(f"  ... ({len(changed)-50} more)")

    # If JSON differs, print numeric diffs summary (top 20)
    for f in changed:
        if not is_json(f):
            continue
        a_b = read_member(a_zip, f)
        b_b = read_member(b_zip, f)
        a_j = try_parse_json(a_b)
        b_j = try_parse_json(b_b)
        if a_j is None or b_j is None:
            continue
        diffs = compare_json(a_j, b_j, atol=0.0)
        if diffs:
            diffs_sorted = sorted(diffs, key=lambda x: (x[3] is None, -(x[3] or 0.0)))
            print(f"\njson numeric diffs for {f}: {len(diffs)}")
            for k, va, vb, d in diffs_sorted[:20]:
                print(f"  {k}: {va} vs {vb} (absdiff={d})")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
