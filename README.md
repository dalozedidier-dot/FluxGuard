FluxGuard CI Stabilization Bundle v2

Objectif
- Stabiliser immédiatement la CI en pinant ubuntu-22.04 et en activant le cache pip.
- Fournir un workflow exemple compatible Ubuntu 24.04 (ubuntu-latest) via virtualenv, en continue-on-error.
- Ajouter un step de debug conditionnel en cas d'échec (exemple fourni).

Contenu
- scripts/patch_fluxguard_ci_v2.py
  - Remplace runs-on: ubuntu-latest par runs-on: ubuntu-22.04 dans .github/workflows/*.yml|*.yaml
  - Ajoute cache: 'pip' dans les steps actions/setup-python@v5 quand absent
  - Option --rename-blank pour renommer blank.yml -> smoke-tests.yml
- workflows/smoke-tests.yml.example
  - Job principal sur ubuntu-22.04 (stable)
  - Job monitoring sur ubuntu-24.04 (continue-on-error) avec virtualenv
  - Step Debug env (on failure)

Usage
1) Dézipper à la racine du repo FluxGuard
2) Lancer:
   python scripts/patch_fluxguard_ci_v2.py
   ou:
   python scripts/patch_fluxguard_ci_v2.py --rename-blank

3) Vérifier:
   git diff

4) Commit et push

Notes
- Le patcher est volontairement conservateur: il modifie uniquement runs-on et le cache pip.
- Pour une migration ubuntu-24.04 propre, prendre le workflow exemple et l'adapter au repo (venv et install).
