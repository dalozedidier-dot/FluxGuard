FluxGuard – High Performance CI Update (v1)

Objectifs (PR CI)
- Passer le job principal sur ubuntu-latest (Ubuntu 24.04), plus rapide une fois stabilisé.
- Garder un garde-fou ubuntu-22.04 en continue-on-error (à supprimer après 20+ runs verts).
- Virtualenv obligatoire + cache pip.
- Réduire le scope smoke (nulltrace: 3 runs, voidmark: 5 runs).
- Sous-échantillonnage déterministe du dataset example.csv (par défaut ~10%).

Contenu
- .github/workflows/smoke-tests.yml
  PR/Push: job principal ubuntu-latest (py 3.11/3.12) + garde-fou ubuntu-22.04 (py 3.12, continue-on-error)
- .github/workflows/nightly-soak.yml
  Nightly: soak plus long (voidmark runs=200) sur ubuntu-latest (py 3.12)
- fluxguard/tools/make_smoke_sample.py
  Génère datasets/example_smoke.csv à partir de datasets/example.csv (sampling déterministe)

Application
1) Copier les fichiers du ZIP dans le repo (respecter les chemins).
2) Si vous avez déjà .github/workflows/blank.yml, renommez-le en smoke-tests.yml ou supprimez-le
   si vous adoptez directement smoke-tests.yml.
3) Ajuster la commande de tests si besoin (pytest vs fluxguard.py déjà en place).

Retrait du garde-fou 22.04
- Quand ubuntu-latest est vert sur 20+ runs: supprimer le job "smoke-22" dans smoke-tests.yml.
