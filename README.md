# FluxGuard

Recommandations immédiates incluses dans `.github/workflows/blank.yml`:
- runner épinglé sur `ubuntu-22.04`
- retry automatique via `nick-fields/retry@v3`
- debug runner state (RAM, disque, top, ImageOS, runner-version)
- matrix Python 3.11 / 3.12
- timeout 20 minutes

Option monitoring:
- tu peux rendre le smoke non bloquant en mettant `continue-on-error: true` sur l'étape "Smoke test (retry)".
