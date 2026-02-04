#!/usr/bin/env python3
import os
import re
import sys
from pathlib import Path
from typing import List, Tuple

UTC_HELPER = r'''
from datetime import datetime, timezone

def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
'''.strip() + "\n"

def backup(path: Path) -> None:
    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists():
        bak.write_bytes(path.read_bytes())

def find_py_files(root: Path) -> List[Path]:
    out = []
    for p in root.rglob("*.py"):
        if any(part in {".venv", "venv", "__pycache__", ".git"} for part in p.parts):
            continue
        out.append(p)
    return out

def patch_timestamp(text: str) -> Tuple[str, int]:
    # Replace obvious epoch defaults for generated_at_utc
    n = 0
    # examples:
    # "generated_at_utc": "1970-01-01T00:00:00Z"
    # generated_at_utc = "1970-01-01T00:00:00Z"
    text2, c1 = re.subn(r'generated_at_utc\s*=\s*["\']1970-01-01T00:00:00Z["\']', 'generated_at_utc = utc_now_iso()', text)
    n += c1
    text3, c2 = re.subn(r'(["\']generated_at_utc["\']\s*:\s*)["\']1970-01-01T00:00:00Z["\']', r'\1utc_now_iso()', text2)
    n += c2
    return text3, n

def ensure_helper(text: str) -> Tuple[str, int]:
    if "def utc_now_iso" in text:
        return text, 0
    # insert after imports block if possible
    m = re.search(r'^(import\s+.+\n|from\s+.+\n)+', text, flags=re.M)
    if m:
        i = m.end()
        return text[:i] + "\n" + UTC_HELPER + "\n" + text[i:], 1
    return UTC_HELPER + "\n" + text, 1

def patch_seed_propagation(text: str) -> Tuple[str, int]:
    # Best-effort: if code writes a summary dict under key voidmark, ensure it includes seed_effective
    n = 0
    # pattern: summary["full_chain"]["voidmark"] = {...}
    # We cannot safely restructure arbitrary code, so only patch if we see a dict literal that lacks seed fields.
    # This is intentionally conservative.
    if "full_chain" in text and "voidmark" in text and "seed_effective" not in text:
        # If mark json uses key "seed", copy it into seed_effective in summary when constructing dict
        # heuristic: add line after a line containing '"voidmark":' in a dict literal by injecting '"seed_effective": seed,'
        text2, c = re.subn(r'("voidmark"\s*:\s*\{\s*)', r'\1\n            "seed_effective": seed,', text)
        n += c
        return text2, n
    return text, 0

def main() -> int:
    root = Path(".").resolve()
    py_files = find_py_files(root)
    touched = 0
    for p in py_files:
        raw = p.read_text(encoding="utf-8", errors="ignore")
        if "fluxguard" not in raw and "voidmark" not in raw and "generated_at_utc" not in raw:
            continue

        new = raw
        changed = 0

        new, c0 = ensure_helper(new)
        changed += c0

        new, c1 = patch_timestamp(new)
        changed += c1

        new, c2 = patch_seed_propagation(new)
        changed += c2

        if changed > 0 and new != raw:
            backup(p)
            p.write_text(new, encoding="utf-8")
            touched += 1
            print(f"patched: {p} (changes={changed})")

    print(f"done. files patched: {touched}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
