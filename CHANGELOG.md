# Changelog

## 1.0.0 (2026-11-11)

First public release.

- Per-team flags from an HMAC of challenge and team; no flag table to manage
- Per-team files: Replace (sample flag swapped in any file, including zip members) and Script (`generate.py` in a Docker sandbox)
- Variants for fixed-answer challenges
- Shared-flag detection with live admin alerts
- Admin monitor: alerts, submissions, flag lookup, shared IPs, Hall of Shame
- Team flags panel with per-team file preview and flag regeneration
- Hooks for other plugins that issue per-team flags
