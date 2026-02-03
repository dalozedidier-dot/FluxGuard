# FluxGuard

Objectif: tests intermédiaires rapides pour évaluer sensibilité à la dérive.

## Niveau 1: dérive intentionnelle (déjà prêt)
Deux datasets fournis:
- `datasets/example.csv`
- `datasets/example_drift.csv` (b augmente de 5% sur la fin, c change de signe sur la fin)

Exécuter:
```bash
cd fluxguard
python fluxguard.py all --shadow-prev datasets/example.csv --shadow-curr datasets/example_drift.csv --output-dir _ci_out/full_drift
```

## Augmentation des runs
VoidMark (standalone):
```bash
python fluxguard.py voidmark --input datasets/example.csv --runs 1000 --noise 0.05 --output-dir _ci_out/voidmark_big
```

VoidMark dans la chaîne:
```bash
python fluxguard.py all --shadow-prev datasets/example.csv --shadow-curr datasets/example_drift.csv \
  --void-runs 1000 --void-noise 0.05 --output-dir _ci_out/full_drift_big
```

NullTrace:
```bash
python fluxguard.py nulltrace --runs 500 --output-dir _ci_out/nulltrace_big
```

## Multi-seuils et seuils extrêmes
RiftLens (standalone):
```bash
python fluxguard.py riftlens --input datasets/example_drift.csv --thresholds 0.1 0.3 0.5 0.7 0.9 0.95 --output-dir _ci_out/riftlens_ext
```

Chaîne complète:
```bash
python fluxguard.py all --shadow-prev datasets/example.csv --shadow-curr datasets/example_drift.csv \
  --rift-thresholds 0.1 0.3 0.5 0.7 0.9 0.95 --output-dir _ci_out/full_ext
```

## Note importante
VoidMark n'est pas un détecteur de drift via l'entropie moyenne. Sa valeur ajoutée est l'intégrité:
- `base_sha256` change quand le target change
- l'entropie moyenne doit rester stable autour de ~4.9 bits (si elle saute, c'est un signal de non-uniformité ou d'artefact).
NullTrace, dans sa forme actuelle, ne lit pas le dataset. Il sert de soak déterministe.
