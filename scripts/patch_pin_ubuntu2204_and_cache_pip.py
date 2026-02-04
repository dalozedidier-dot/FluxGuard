#!/usr/bin/env python3
"""
Patch workflows GitHub Actions "best effort" pour FluxGuard.

Actions :
1) Remplacer "runs-on: ubuntu-latest" par "runs-on: ubuntu-22.04"
2) Ajouter "cache: 'pip'" sous "with:" des steps actions/setup-python@v5 si absent.

Usage :
  python scripts/patch_pin_ubuntu2204_and_cache_pip.py

Le script modifie les fichiers en place et crée des sauvegardes .bak à côté.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import sys

ROOT = pathlib.Path(".").resolve()
WF_DIR = ROOT / ".github" / "workflows"

RUNS_ON_RE = re.compile(r"^(\s*runs-on:\s*)ubuntu-latest(\s*)$", re.MULTILINE)

def patch_runs_on(text: str) -> tuple[str, int]:
    new_text, n = RUNS_ON_RE.subn(r"\1ubuntu-22.04\2", text)
    return new_text, n

def patch_setup_python_cache(text: str) -> tuple[str, int]:
    """
    Heuristique :
    - détecte les blocs de step contenant "uses: actions/setup-python@v5"
    - cherche "with:" puis "python-version:"
    - si aucune ligne "cache:" n'existe dans le mapping with:, insère "cache: 'pip'"
    """
    lines = text.splitlines(True)
    out = []
    i = 0
    changes = 0

    while i < len(lines):
        line = lines[i]
        out.append(line)

        if "uses:" in line and "actions/setup-python@v5" in line:
            # Cherche le bloc "with:" juste après, en conservant l'indentation
            j = i + 1
            # capture indentation base du step
            step_indent = re.match(r"^(\s*)", line).group(1)
            # balayage jusqu'à prochain step "-" au même niveau, ou fin
            # on va repérer with: et son indent, puis python-version: et cache:
            with_idx = None
            with_indent = None
            block_end = j
            while block_end < len(lines):
                # fin de step : "- name:" ou "- uses:" au même indent que step_indent + "- "
                if re.match(rf"^{re.escape(step_indent)}-\s+", lines[block_end]):
                    break
                block_end += 1

            # Analyse du bloc [i+1:block_end)
            block = lines[i+1:block_end]
            for k, bl in enumerate(block):
                m = re.match(r"^(\s*)with:\s*$", bl)
                if m:
                    with_idx = i + 1 + k
                    with_indent = m.group(1)
                    break

            if with_idx is not None:
                # mapping with: indent attendu
                map_indent = with_indent + "  "
                # détecter présence python-version et cache
                has_cache = False
                pv_line_idx = None
                scan_end = block_end
                for t in range(with_idx+1, scan_end):
                    l = lines[t]
                    # stop when indentation returns to with_indent or less (le mapping se termine)
                    if re.match(rf"^{re.escape(with_indent)}\S", l):
                        break
                    if re.match(rf"^{re.escape(map_indent)}cache\s*:", l):
                        has_cache = True
                    if re.match(rf"^{re.escape(map_indent)}python-version\s*:", l):
                        pv_line_idx = t

                if (not has_cache) and (pv_line_idx is not None):
                    insert_at = pv_line_idx + 1
                    cache_line = f"{map_indent}cache: 'pip'\n"
                    lines.insert(insert_at, cache_line)
                    changes += 1
                    # ajuster out: on ne peut pas recalculer out facilement ici, on va reprendre un modèle plus simple
                    # Solution : redémarrer la boucle en re-splittant après patch global en fin. Ici on a modifié lines,
                    # donc il faut mettre à jour le texte final après la boucle.
            i = block_end
            continue

        i += 1

    return "".join(lines), changes

def main() -> int:
    if not WF_DIR.exists():
        print(f"ERREUR: dossier introuvable: {WF_DIR}")
        return 2

    targets = sorted(list(WF_DIR.glob("*.yml")) + list(WF_DIR.glob("*.yaml")))
    if not targets:
        print("Aucun workflow .yml/.yaml trouvé.")
        return 0

    total_files = 0
    total_changes = 0

    for path in targets:
        original = path.read_text(encoding="utf-8")
        text = original

        text, n1 = patch_runs_on(text)
        text, n2 = patch_setup_python_cache(text)

        n = n1 + n2
        if n > 0 and text != original:
            backup = path.with_suffix(path.suffix + ".bak")
            if not backup.exists():
                shutil.copy2(path, backup)
            path.write_text(text, encoding="utf-8")
            total_files += 1
            total_changes += n
            print(f"PATCH: {path.relative_to(ROOT)} (changes={n}, runs-on={n1}, cache={n2})")
        else:
            print(f"OK:    {path.relative_to(ROOT)} (no change)")

    print(f"Résultat: fichiers modifiés={total_files}, changements={total_changes}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
