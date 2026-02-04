FluxGuard CI Bundle v3

But
1) Immédiat: forcer ubuntu-22.04 partout pour supprimer les échecs liés à ubuntu-latest (Ubuntu 24.04).
2) Activer cache pip sur actions/setup-python@v5.
3) Fournir un workflow "smoke-tests" prêt, avec virtualenv, et un job de monitoring Ubuntu 24.04 en continue-on-error.

Contenu
- scripts/patch_fluxguard_ci_v3.py
  - Remplace runs-on: ubuntu-latest par runs-on: ubuntu-22.04 dans .github/workflows/*.yml|*.yaml
  - Ajoute cache: 'pip' dans les steps actions/setup-python@v5 quand absent
  - Option --rename-blank: renomme blank.yml en smoke-tests.yml (sans modifier son contenu)
  - Option --install-smoke-template: écrit un workflow complet smoke-tests.yml si absent
  - Option --replace-blank-with-template: remplace blank.yml par le template (en sauvegardant un .bak)

- workflows/smoke-tests.yml.template
  - Job smoke sur ubuntu-22.04, matrix Python 3.11 et 3.12
  - Virtualenv obligatoire
  - Cache pip activé
  - Debug automatique en cas d'échec
  - Job smoke-future sur ubuntu-24.04 en continue-on-error, même logique venv

Usage typique
A) Stabilisation immédiate sans toucher à la logique des tests
   python scripts/patch_fluxguard_ci_v3.py

B) Renommer blank.yml pour clarté
   python scripts/patch_fluxguard_ci_v3.py --rename-blank

C) Installer un workflow smoke-tests.yml prêt à l'emploi (sans modifier les autres)
   python scripts/patch_fluxguard_ci_v3.py --install-smoke-template

D) Remplacer blank.yml par le template (solution directe si blank.yml est la CI principale)
   python scripts/patch_fluxguard_ci_v3.py --replace-blank-with-template

Après patch
- Vérifier: git diff
- Commit et push
