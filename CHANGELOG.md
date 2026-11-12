# Changelog

## Unreleased

- `docs/GENERATE.md`: the generate.py contract, six rules, and a copy-paste prompt for writing the script with an
  AI assistant from an existing challenge file
- `tools/try_generate.py` runs a script locally or in the sandbox image and warns when the flag is visible in the output
- `examples/forensics_layers.py`: a harder, standard-library-only example with a per-team key
- Pull request template, Dependabot for Actions, protected `main` with required CI

## 1.1.0 (2026-11-11)

- The sandbox image is published as `ghcr.io/rj-karan/flagprint-generator`; the plugin uses it by default, then a
  locally built `flagprint/generator`, then plain Python
- Fixed: with several workers, the first flags issued could be computed with different secrets. The secret is now
  created once at startup and every worker reads the same row
- Fixed: per-team files could be downloaded before the challenge's prerequisites were solved
- Fixed: downloading from a flag-only or variants challenge returned 500 instead of 404
- Fixed: "Null Pointers's" in share alerts
- Faster admin monitor: one account lookup per team per page instead of per row
- Clean README with screenshots, a demo, and a comparison with other options; CONTRIBUTING, SECURITY and
  code of conduct; a docker-compose override for script delivery

## 1.0.0 (2026-11-11)

First public release.

- Per-team flags from an HMAC of challenge and team; no flag table to manage
- Per-team files: Replace (sample flag swapped in any file, including zip members) and Script (`generate.py` in a Docker sandbox)
- Variants for fixed-answer challenges
- Shared-flag detection with live admin alerts
- Admin monitor: alerts, submissions, flag lookup, shared IPs, Hall of Shame
- Team flags panel with per-team file preview and flag regeneration
- Hooks for other plugins that issue per-team flags
