# FluxGuard audit + determinism fixes (bundle v1)

This bundle contains:
- audit scripts to compare two FluxGuard output folders or ZIPs
- a best-effort patcher that updates FluxGuard code to:
  - set generated_at_utc correctly (no 1970 default)
  - propagate a single seed_effective consistently
  - optionally quantize floats in JSON output to reduce cross-platform micro diffs

Nothing here assumes a specific repo layout. The patcher searches for likely files and patterns
and makes .bak backups before editing.

## 1) Audit: compare two ZIPs
python scripts/fluxguard_compare_zips.py /path/to/fluxguard-ci-3.11.zip /path/to/fluxguard-ci-3.12.zip

It will:
- compare internal file lists
- compare SHA256 per file
- if JSON differs, compute numeric diffs for floats

## 2) Audit: check summary invariants inside a ZIP
python scripts/fluxguard_audit_summary.py /path/to/fluxguard-ci-3.12.zip

Checks:
- generated_at_utc not equal to 1970-01-01T00:00:00Z
- seed fields presence and consistency between summary and voidmark_mark.json
- reports missing expected keys

## 3) Best-effort patcher for code
Run this from the repo root:
python scripts/patch_fluxguard_seed_timestamp.py

What it tries to do:
- add utc_now_iso() helper
- replace generated_at_utc assignments that look like epoch defaults
- ensure summary contains seed_effective matching voidmark mark seed
- ensure voidmark_mark.json includes seed_effective too
- optional: wrap json payloads with float quantization (12 decimals)

If patterns are not detected, the patcher will not change anything.

## 4) Notes on strict determinism
- Keep a single seed_base, derive seed_effective per run deterministically, store it everywhere.
- For multi-worker runs, either set workers=1 for reproducibility or seed per worker deterministically.
- If you need bit-for-bit identical JSON across Python versions, quantize floats at write time.
