# FluxGuard

CLI unique, modulaire, léger, déterministe, sans dépendances externes.

## Exécution (local)

Depuis `fluxguard/` :

```bash
python fluxguard.py nulltrace --runs 10 --output-dir _ci_out/nulltrace
python fluxguard.py riftlens --input datasets/example.csv --output-dir _ci_out/riftlens
python fluxguard.py voidmark --input datasets/example.csv --runs 50 --output-dir _ci_out/voidmark
python fluxguard.py all --shadow-prev datasets/example.csv --shadow-curr datasets/example.csv --output-dir _ci_out/full
```

## CI

Le workflow CI est dans `.github/workflows/blank.yml`:
- runner épinglé sur `ubuntu-22.04`
- matrix Python 3.11 / 3.12
- retry (3 tentatives) sur la suite smoke
