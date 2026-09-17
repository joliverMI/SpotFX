---
name: squiggles-v2-scene
description: >
  The "Squiggles V2" SPECTRA scene — Matrix `squiggles`, Strips
  `orbits1d` (NOT a Squiggles-specific strip effect), Singles `power`.
  Load before editing this scene's flare bands/kinds or colour-set accept
  list. Load the squiggles-effect skill first for the underlying Matrix
  effect, and the orbits-effect skill for what its Strips entry actually
  runs.
---

# Squiggles V2 (scene)

Load `squiggles-effect` (Matrix) and `orbits-effect` (Strips — this
scene's Strips entry is `orbits1d`, not a squiggles-specific strip
effect) first.

`scripts/seed_squiggles_scene.py` is this scene's own seed script.
`scripts/widen_squiggles_colorset_accept.py` widened this scene's colour-
set accept list (`accept_all_sets=True`) — a change independent of, and
untouched by, the `no_background_color` flag's own back-and-forth (see
squiggles-effect skill's §85/§87 note); don't conflate the two when
reasoning about which sets this scene will draw from.

## A stuck-reversed momentary flare on this scene is the known
   never-authored-param trap, not a new bug

`orbits1d` registers `reverse` but Squiggles V2's own Strips entry never
sets it (same shape as Orbits V2/Squiggles V2 both having this on their
Strips per AGENTS.md's "reverse flare's ~2x dwell overrun" entry) — a
momentary spike on a param the scene entry never authored used to land
and never release, stranded until an effect-TYPE switch rebuilt the
instance. Fixed generically (`_resting_value` fallback to the effect's own
schema default) — if a "stuck in Reverse" report recurs on this scene's
strips specifically, check that fix is still live before assuming it's a
new defect.

## Sonic reach

Scene settings and flare kinds only via the scene console.

## Executable proofs

Shares the squiggles-effect skill's proof corpus
(`scripts/check_squiggles_drop_timing.py`,
`scripts/widen_squiggles_colorset_accept.py`,
`tests/test_squiggles_drop_timing.py`,
`tests/test_squiggles_colorset_widen.py`). Named gap: no check proves
THIS scene's actual band attachments end to end.
