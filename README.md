# FluxGuard v10 (data-aware, toujours minimaliste)

Objectif: conserver la philosophie deterministe et auditee, tout en ajoutant une couche data-awareness sans boite noire.

## Ce qui est ajoute
1) RiftLens
- Ruptures locales par fenetres en stdlib.
- Mode causal lite (lags, correlation dirigee) en stdlib.
- Si ruptures est installe, option d'utilisation (fallback automatique).

2) VoidMark
- Fingerprint statistique CSV (mean, std, quantiles, MAD, missingness).
- Comparaison a un baseline mark, KS test lite (approx) en stdlib.
- Historique de versions local (type DVC-lite): fichier JSON append-only.

3) NullTrace
- Mode data-aware: checks de qualite sur sous-echantillons deterministes.
- Mini moteur de regles: fichier texte rules.yml simple (cle: expression), evalue via AST safe.

## Execution (local)
```bash
cd fluxguard
python fluxguard.py all --shadow-prev datasets/example.csv --shadow-curr datasets/example_drift.csv --output-dir _ci_out/full --version-db _ci_out/full/voidmark_versions.json
python fluxguard.py riftlens --input datasets/example_drift.csv --local-ruptures --output-dir _ci_out/riftlens
python fluxguard.py riftlens --input datasets/example_drift.csv --mode causal --max-lag 3 --output-dir _ci_out/riftlens_causal
python fluxguard.py voidmark --input datasets/example_drift.csv --baseline-mark _ci_out/full/step2_voidmark/vault/voidmark_mark.json --output-dir _ci_out/voidmark --version-db _ci_out/voidmark_versions.json
python fluxguard.py nulltrace --runs 50 --data-aware --input datasets/example_drift.csv --rules ../rules.yml --output-dir _ci_out/nulltrace
```

## CI
Workflow inclus: .github/workflows/blank.yml en ubuntu-22.04, matrix 3.11/3.12, upload des artefacts.
