---
name: orbits-effect
description: >
  fx/effects/orbits.py (Matrix, crystal-mapper) and fx/effects/orbits1d.py
  (Strips) — orbiting-particle effect behind Orbits V2, and the strip
  effect several OTHER scenes' Strips entries reuse (Squiggles V2,
  Dancers V2, Pacman V2). Load before touching either module, before
  tuning drop-ejecta persistence, or before assuming Fish's kinematics —
  Fish is a wholesale copy of this scene's params/bands but moves
  completely differently; see the fish-effect skill for the split.
---

# Orbits / Orbits1d

Matrix effect renders to `crystal-mapper` — load `crystal-hex-grid` first
for anything about coverage/spawn radius on this device.

**Orbits1d is load-bearing for scenes that aren't "Orbits" at all** —
Squiggles V2, Dancers V2 and Pacman V2 all use `orbits1d` for their Strips
entry (their own Matrix effect is something else). A change here can move
four scenes at once; check `EFFECT_SCENE_MAP.json`'s scene entries before
assuming a fix is Orbits-only.

## Params worth knowing before tuning

- `orbit_radius` (0.02..0.8): a real geometric radius, degeneracy-guarded —
  `drift_conductor._registry_range()` intersects any drift declaration's
  lo/hi against this param's OWN legal range at Mechanism construction, so
  an authored profile built for a different param (e.g. a [0,1]-ish
  default) can't silently wander below the effect's own floor and get
  rejected by the config schema while the conductor's model keeps moving.
- `reverse` (toggle, default False): spawn-side direction flag, same
  semantics as blackhole's — see that skill's note; it does NOT reverse a
  particle already in flight.
- `spin` (0..1): current swirl amount, an ordinary numeric here (unlike
  radial's `spin`, which is squared and audio-driven — don't cross-apply
  that mental model).
- `speed_jump`/`speed_jog`/`brightness_audio`/`size_audio`: audio gains —
  idle near their floor during quiet passages; see the audio-idle trap
  documented on the radial-effect skill.
- `implode_fade`/`implode_reach`/`bounce_chance`/`overlap_blend`
  (orbits1d only): strip-specific shape/collision params with no Matrix
  analogue — don't assume parity between the two modules' schemas.

## Drop-ejecta persistence is a Little's-Law order statistic

His ask was "3 seconds" for how long ballistic drop ejecta lingers after a
drop. The burst COUNT (`DROP_EJECTA_X=2`, i.e. 3x the configured
population) is explicitly NOT to be touched — it already matches his
stated number. `particle_count` feeds the ejecta count
(`DROP_EJECTA_X * particle_count`), and "time until the last one is gone"
is an order statistic over that count — a higher `particle_count`
mechanically produces a longer worst-case straggler even with an
UNCHANGED per-particle speed distribution. Measure over several RNG seeds
and average; a single run is noisy (`scripts/
check_orbits_drop_burst_and_persistence.py`).

## Sonic reach

Same rule as every effect here: no direct param edit. Sonic reaches these
params only through an existing `FlareKind` on whichever scene binds this
effect.

## Executable proofs

`scripts/check_orbits_drop_burst_and_persistence.py`,
`scripts/smoke_orbits_params.py`, `tests/test_orbits_drop_persistence.py`.
History: AGENTS.md's "Fish" section (the comparison table for orbits vs.
fish motion) and the drop-timing-reference withdrawal note
(`data/drops-still-fire-early-star-does-not-explode/`).
