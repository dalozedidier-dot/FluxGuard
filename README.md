FluxGuard CI fix bundle v1

Objectif
- Stabiliser les workflows GitHub Actions en supprimant la dépendance à ubuntu-latest (Ubuntu 24.04 en 2026).
- Pinner explicitement ubuntu-22.04 sur les jobs "smoke" (solution immédiate).
- Ajouter le cache pip via actions/setup-python (gain de temps et stabilité).

Contenu
- scripts/patch_pin_ubuntu2204_and_cache_pip.py
  Patcher "best effort" qui :
  1) remplace runs-on: ubuntu-latest par runs-on: ubuntu-22.04
  2) ajoute cache: 'pip' aux steps actions/setup-python@v5 si absent

- workflows/blank.yml.example
  Exemple de workflow corrigé, avec :
  - ubuntu-22.04
  - cache pip
  - option virtualenv (recommandée si vous voulez rester compatible ubuntu-24.04)
  - job de monitoring ubuntu-24.04 en continue-on-error (optionnel)

Mode d'emploi
1) Dézipper ce bundle à la racine du repo FluxGuard.
2) Lancer :
   python scripts/patch_pin_ubuntu2204_and_cache_pip.py

3) Vérifier le diff :
   git diff

4) Ajuster manuellement si besoin (workflow non standard), puis commit/push.

Notes
- Le patcher est volontairement conservateur. Il ne restructure pas les steps pour forcer un venv.
- Si vous souhaitez rendre ubuntu-24.04 stable, utilisez le bloc virtualenv de l'exemple blank.yml.example.
