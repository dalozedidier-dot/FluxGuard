FluxGuard Audit Postprocess Bundle v2

But
- Corriger les anomalies d'audit dans les artefacts FluxGuard, sans dépendre d'une modification précise du code interne.
- Fixer generated_at_utc (plus de 1970) et propager une "seed effective" unique dans le summary.
- Optionnel: quantifier les floats (par défaut 12 décimales) pour neutraliser les micro-écarts inter-OS/Python.

Principe
- On post-traite un dossier _ci_out (ou full/) après génération, puis on ré-écrit:
  - fluxguard_summary.json (et éventuellement voidmark_mark.json si demandé)

Scripts
- scripts/fluxguard_postprocess_audit.py
  Usage:
    python scripts/fluxguard_postprocess_audit.py _ci_out/full
    python scripts/fluxguard_postprocess_audit.py _ci_out/full --write-mark
    python scripts/fluxguard_postprocess_audit.py _ci_out --recursive

  Ce que ça fait:
  - Remplace generated_at_utc par un vrai UTC ISO (sans microsecondes).
  - Cherche voidmark_mark.json et récupère la seed.
  - Injecte dans fluxguard_summary.json:
      full_chain.voidmark.seed_effective = <seed lue dans mark>
  - Optionnel: quantifie les floats du summary et du mark.

Snippets
- snippets/postprocess_step.yml : step GitHub Actions à insérer après la génération.

Notes
- Ce bundle n'essaie pas de recalculer des hashes "manifest" car FluxGuard ne semble pas les référencer
  dans fluxguard_summary.json. Si vous avez un manifest externe, il faudra le mettre à jour après postprocess.
