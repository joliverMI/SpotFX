---
name: dancer-effect
description: >
  fx/effects/dancer.py + fx/effects/dancer_flames.py + fx/effects/
  dancer_moves.py (Matrix, crystal-mapper) — the GIF-driven dancing-figure
  effect behind Dancers V2. Load before touching flame bursts, any
  audio-gated threshold on this effect, or GIF pose/style authoring (for
  the asset side specifically, use the led-gif-assets skill instead —
  this skill covers the effect's Python behaviour, not asset creation).
---

# Dancer

Matrix effect renders to `crystal-mapper` — load `crystal-hex-grid` first.
For creating/editing GIF poses or dance styles, use the `led-gif-assets`
skill; this one is about the effect module's own runtime behaviour.

## `burst_threshold` was a `>=` comparison against a signal that SATURATES
   at exactly 1.0 — this bit the Dancer's flames specifically

Every audio power in this pipeline is clipped to exactly 1.0 upstream
(`fx/effects/audio.py::_update_freq_power`), and an `ExpFilter` over it
converges to EXACTLY 1.0 in float within ~9 audio frames (~150ms at 60Hz).
A Range-max-1.0 threshold whose whole meaning is "never" therefore FIRED
on any loud passage the instant the comparison was `>=`. Fixed at
`fx/effects/dancer.py:1149` by excluding the top of the range
(`thr < 1.0 and sig >= thr`), NOT by switching to strict `>` (that also
changes exact-equality behaviour at every OTHER threshold in this
pipeline, most of which correctly use `>=` for [0,1] never-saturating
signals). Before adding or editing ANY audio-gated threshold anywhere in
`fx/effects/`, check whether the signal is `[0,1]`-clamped and saturates —
if it does, `min_volume`/`burst_threshold`-shaped comparisons at
`dancer.py:393`, `keybeat2d.py:479` have the SAME unfixed defect (reported,
not fixed — captain's call).

## A threshold gates only SOME of the flame sources — check the emitter
   count before promising a knob turns something off

Dancer has FOUR flame sources: beat bursts + ember trickle (both gated by
`burst_threshold`), the flourish payoff burst, and the six
`_impact_flames` stunt moments — the LATTER TWO are ungated. No threshold
value silences them; `burst_size = 0` is the other half of "off". Before
claiming a knob turns flames off, enumerate every CALLER of the flame
emitter, not just the one the knob's name suggests.

## Sonic reach

No direct param edit — reachable only through an already-attached
`FlareKind` on Dancers V2.

## Executable proofs

`scripts/check_dancer_flames_off.py`, `scripts/smoke_dancer_params.py`,
`tests/test_dancer_flames_off.py`. History: AGENTS.md's "A saturating
signal meeting >= makes a 'never' threshold fire" section, `fx/VENDOR.md`
#31.
