# fix: remove BGN ccy

Fixes #1517

Removed BGN currency code from ISO 4217 validation list as Bulgaria will adopt EUR in 2026.

Tests
- Verified existing tests still pass with updated currency codes

Notes
- This change is backwards compatible as it only removes a currency code, not adding any new functionality
