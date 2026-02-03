# FluxGuard

## Badges (CI "réaliste")

Remplace `OWNER/REPO` par ton dépôt.

- Badge **push**: reflète le CI bloquant (push sur `main`).
- Badge **schedule**: reflète le monitoring (peut être non bloquant).

```md
[![CI (push)](https://github.com/OWNER/REPO/actions/workflows/blank.yml/badge.svg?branch=main&event=push)](https://github.com/OWNER/REPO/actions/workflows/blank.yml?query=branch%3Amain)
[![CI (schedule)](https://github.com/OWNER/REPO/actions/workflows/blank.yml/badge.svg?branch=main&event=schedule)](https://github.com/OWNER/REPO/actions/workflows/blank.yml?query=event%3Aschedule)
```

Astuce: sur GitHub, va dans **Actions** → ouvre le workflow → menu (⋯) → **Create status badge** pour copier le Markdown exact.

## Workflows quick-wins

Dans `.github/workflows/blank.yml`:
- `runs-on: ubuntu-22.04`
- retry automatique `nick-fields/retry@v3` (3 tentatives)
- libération disque via `jlumbroso/free-disk-space` (pinné sur le SHA de `v1.3.1`)
- debug avant/après (df, free, ImageOS, runner-version)
- en `schedule`: `continue-on-error: true` (monitoring non bloquant)
- en `push/PR`: `continue-on-error: false` (badge et PRs réalistes)
