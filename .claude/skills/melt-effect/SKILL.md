---
name: melt-effect
description: >
  fx/effects/melt.py (Strips, `Atmospheric` category) — a plain HSV melt
  effect, currently the STAR scene's Strips entry. Load before touching
  STAR's strip behaviour or before re-running the "always melt" migration
  — a superseded seeder for this same virtual still exists and must NOT
  be re-run.
---

# Melt

A simple, mostly stock LedFX `Atmospheric` effect (`speed`, `reactivity` —
two params, no Matrix/crystal-mapper geometry involved; this is a Strips
effect). The invariant worth knowing lives OUTSIDE the effect module
itself, in how STAR's strips got wired to it:

## Two seeders exist for STAR's Strips — only ONE is current, and running
   the wrong one silently reverts his ruling

`scripts/seed_star_strips.py --apply` originally set up STAR's Strips with
an intensity-stepped `effect_steps` binding: base `melt` below ⚡0.7 (the
fallback, always melt) and a `power` STEP at/above ⚡0.7 (`bass_decay_rate
0.6` — the `star-fold-entry-growth` decision). **That seeder is now SUPERSEDED and must NOT be re-run**: his
2026-08-25 ruling "always do melt" removed STAR's Strips power step via
`scripts/star_strips_always_melt.py`, and re-running the OLD seeder would
silently put the power step back. Melt was never replaced — only the
power overlay on top of it was removed. The underlying intensity-stepped-effect
mechanism itself is unchanged and still used elsewhere — only STAR's own
Strips entry was pinned to melt unconditionally. Before touching STAR's
Strips config, check which of the two scripts is the one to run.

## Sonic reach

No direct param edit — reachable only through an already-attached
`FlareKind` on STAR, if one targets `speed`/`reactivity` (check the STAR
scene skill for what's actually attached).

## Executable proofs

No dedicated `check_melt_*.py`/`test_melt_*.py` exists — a named gap. The
"always do melt" migration and its test (`scripts/star_strips_always_melt.py`,
`tests/test_star_strips_always_melt.py`) prove STAR's scene data and belong
to the star-scene skill. History: AGENTS.md's "SPECTRA app" section, "always
do melt" ruling (search "star_strips_always_melt" in AGENTS.md for the full
quote and the superseded-seeder warning).
