#!/usr/bin/env python3
import json
import sys
import zipfile
from typing import Any, Dict

SUMMARY = "full/fluxguard_summary.json"
VOIDMARK = "full/step2_voidmark/vault/voidmark_mark.json"

def read_json(z: zipfile.ZipFile, member: str) -> Any:
    b = z.read(member)
    return json.loads(b.decode("utf-8"))

def main() -> int:
    if len(sys.argv) != 2:
        print("usage: fluxguard_audit_summary.py fluxguard.zip", file=sys.stderr)
        return 2

    zip_path = sys.argv[1]
    with zipfile.ZipFile(zip_path, "r") as z:
        names = set(z.namelist())
        for need in (SUMMARY, VOIDMARK):
            if need not in names:
                print(f"missing: {need}")
                return 1

        s = read_json(z, SUMMARY)
        m = read_json(z, VOIDMARK)

        ts = s.get("generated_at_utc")
        if ts == "1970-01-01T00:00:00Z":
            print("FAIL: generated_at_utc is epoch default (1970)")
        else:
            print(f"OK: generated_at_utc={ts}")

        # seed consistency
        summary_seed = None
        # support multiple candidate keys
        if isinstance(s.get("full_chain"), dict):
            v = s["full_chain"].get("voidmark")
            if isinstance(v, dict):
                summary_seed = v.get("seed_effective") or v.get("seed") or v.get("void_seed")
        mark_seed = m.get("seed_effective") or m.get("seed") or m.get("void_seed")

        print(f"summary seed candidate: {summary_seed}")
        print(f"voidmark mark seed candidate: {mark_seed}")

        if summary_seed is None:
            print("WARN: summary does not expose seed_effective, recommend adding it")
        if mark_seed is None:
            print("WARN: voidmark_mark.json does not expose seed, recommend adding it")

        if summary_seed is not None and mark_seed is not None and str(summary_seed) != str(mark_seed):
            print("FAIL: seed mismatch between summary and voidmark_mark.json")
        elif summary_seed is not None and mark_seed is not None:
            print("OK: seed values match")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
