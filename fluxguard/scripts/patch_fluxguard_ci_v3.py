#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

RUNS_ON_RE = re.compile(r"^(\s*runs-on:\s*)(['\"]?)(ubuntu-latest)\2\s*$", re.IGNORECASE)

def patch_runs_on(text: str) -> tuple[str, int]:
    n = 0
    out = []
    for line in text.splitlines(True):
        m = RUNS_ON_RE.match(line)
        if m:
            out.append(f"{m.group(1)}ubuntu-22.04\n")
            n += 1
        else:
            out.append(line)
    return "".join(out), n

def patch_setup_python_cache(text: str) -> tuple[str, int]:
    '''
    Add cache: 'pip' under with: of actions/setup-python@v5 if missing.
    Conservative text patch, targets common indentation patterns.
    '''
    lines = text.splitlines(True)
    n = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.search(r"^\s*uses:\s*actions/setup-python@v5\s*$", line):
            j = i + 1
            with_idx = None
            uses_indent = len(line) - len(line.lstrip(" "))
            while j < len(lines):
                l = lines[j]
                if (len(l) - len(l.lstrip(" "))) <= uses_indent and re.match(r"^\s*-\s+", l):
                    break
                if re.match(r"^\s*with:\s*$", l):
                    with_idx = j
                    break
                j += 1
            if with_idx is None:
                i += 1
                continue

            with_indent = len(lines[with_idx]) - len(lines[with_idx].lstrip(" "))
            k = with_idx + 1
            has_cache = False
            insert_at = None
            child_indent_min = None
            while k < len(lines):
                l = lines[k]
                indent = len(l) - len(l.lstrip(" "))
                if indent <= with_indent:
                    if insert_at is None:
                        insert_at = k
                    break
                if child_indent_min is None and l.strip():
                    child_indent_min = indent
                if re.match(r"^\s*cache:\s*['\"]?pip['\"]?\s*$", l):
                    has_cache = True
                if insert_at is None and re.match(r"^\s*python-version:\s*", l):
                    insert_at = k + 1
                k += 1
            if insert_at is None:
                insert_at = k
            if not has_cache:
                ins_indent = child_indent_min if child_indent_min is not None else (with_indent + 2)
                lines.insert(insert_at, " " * ins_indent + "cache: 'pip'\n")
                n += 1
                i = insert_at + 1
                continue
        i += 1
    return "".join(lines), n

def write_template(wf_dir: Path, template_path: Path, target_name: str) -> None:
    target = wf_dir / target_name
    if target.exists():
        print(f"Skip template install, already exists: {target}")
        return
    target.write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Installed template: {target}")

def replace_with_template(wf_dir: Path, template_path: Path, target_name: str) -> None:
    target = wf_dir / target_name
    if not target.exists():
        raise SystemExit(f"Target workflow not found: {target}")
    bak = target.with_suffix(target.suffix + ".bak")
    if not bak.exists():
        bak.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    target.write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Replaced with template: {target} (backup: {bak.name})")

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".", help="Repository root (default: .)")
    ap.add_argument("--rename-blank", action="store_true", help="Rename .github/workflows/blank.yml to smoke-tests.yml (content unchanged).")
    ap.add_argument("--install-smoke-template", action="store_true", help="Install smoke-tests.yml from bundled template if absent.")
    ap.add_argument("--replace-blank-with-template", action="store_true", help="Replace blank.yml with bundled template (creates .bak).")
    args = ap.parse_args()

    root = Path(args.repo_root).resolve()
    wf_dir = root / ".github" / "workflows"
    if not wf_dir.exists():
        raise SystemExit(f"Workflows directory not found: {wf_dir}")

    template_path = Path(__file__).resolve().parent.parent / "workflows" / "smoke-tests.yml.template"
    if not template_path.exists():
        raise SystemExit(f"Bundled template not found: {template_path}")

    if args.rename_blank:
        blank = wf_dir / "blank.yml"
        if blank.exists():
            target = wf_dir / "smoke-tests.yml"
            if target.exists():
                print(f"Skip rename, target already exists: {target}")
            else:
                blank.rename(target)
                print("Renamed blank.yml to smoke-tests.yml")
        else:
            print("No blank.yml found, skip rename.")

    if args.install_smoke_template:
        write_template(wf_dir, template_path, "smoke-tests.yml")

    if args.replace_blank_with_template:
        replace_with_template(wf_dir, template_path, "blank.yml")

    changed_files = 0
    total_runs_on = 0
    total_cache = 0

    for p in sorted(list(wf_dir.glob("*.yml")) + list(wf_dir.glob("*.yaml"))):
        original = p.read_text(encoding="utf-8")
        text, n1 = patch_runs_on(original)
        text, n2 = patch_setup_python_cache(text)

        if text != original:
            bak = p.with_suffix(p.suffix + ".bak")
            if not bak.exists():
                bak.write_text(original, encoding="utf-8")
            p.write_text(text, encoding="utf-8")
            changed_files += 1
        total_runs_on += n1
        total_cache += n2

    print(f"Patched files: {changed_files}")
    print(f"runs-on replacements: {total_runs_on}")
    print(f"cache insertions: {total_cache}")
    print("Done.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
