---
name: pacman-effect
description: >
  fx/effects/pacman.py (Matrix, crystal-mapper) — a mini Ms. Pac-Man game
  rendered as a music-reactive matrix effect, behind Pacman V2. Load
  before touching ghost AI, the `reverse` param (means "frighten the
  ghosts" here — `reverse` means something different on nearly every
  effect on this device), or the effect-switch crossfade morph.
---

# Pacman

Matrix effect renders to `crystal-mapper` — load `crystal-hex-grid` first.
`pacman` carries `no_background_color: true` in the registry (thin/sparse
canvas, same reasoning as radial — an authored background would wash the
maze).

## `reverse` DOES NOT MEAN "reverse direction" HERE — it means "frighten
   the ghosts"

`reverse` is one name for several unrelated behaviours on this device:
blackhole's picks outward flow vs. infall (spawn-side), orbits' flips the
live spin of every particle and the ring, squiggles' makes every chain
retrace its path, fireworks' implodes instead of exploding, fish's reverses
the current's swirl, and dancer's adds a mirrored PARTNER dancer. On Pacman
it is "force power-dot mode" (`game.forced_fright`), one of TWO ways to
frighten the ghosts (the other being eating a power dot): forcing it turns
every ghost blue and fleeing, hunted by her instead of hunting her. Do not
port a `reverse`-shaped fix from another effect skill onto this one without
re-reading what the flag actually does here.

## Game rules that are invariants, not tuning

A LONE ghost can never catch her — it stumbles and scrambles away when it
gets close. TWO chase ghosts cornering her simultaneously DO catch her
(death blink → respawn at start → ghosts return to the center house).
Ghosts (re)spawn from the house doors with a moment of invulnerability so
she can't camp the spawn point. These are game-design invariants baked
into the state machine, not parameters — `ghost_count`/`ghost_speed`/
`fright_time` tune the numbers around them, they don't change the rules.

## It participates in the SAME particle_handoff transition choreography
   as eye/blackhole

`pacman.py` imports `fx.effects.particle_handoff` (`_wipe_state`,
`draw()`). Two directions, two different mechanisms:

- **INTO Pacman** (role `"in"`): the crossfade is "a big chomping Pac-Man
  that wipes the old effect away", and the wipe front tracks
  `particle_handoff.transition_progress` CONTINUOUSLY (smoothstepped) —
  it is NOT gated on any threshold. The same continuous wipe runs in
  reverse (role `"out"`) when Pacman leaves for a non-particle effect.
- **OUT OF Pacman into a particle sibling** (`PARTICLE_SIBLINGS`:
  Blackhole, Orbits, Fireworks, Squiggles): the wipe is SKIPPED entirely.
  Below `PACMAN_MORPH_START` (0.45, the same constant `eye.py` and
  `spectra/services/transition_phases.py` use) the maze fades while the
  entities keep playing; at that constant the sibling adopts Pacman's
  entities as particles and Pacman stops drawing them.

See the eye-effect skill's particle_handoff note; the same caution about
touching transition timing applies here.

## `smooth_motion` (toggle, default True)

Not an audio gate — a rendering-quality flag (interpolated vs. stepped
grid motion). Don't confuse it with the audio-gain params on this effect
(`wall_audio`/`speed_audio`/`beat_jump`), which idle near their floor
during quiet passages the same way every reactivity-tagged param does
(see the radial-effect skill's audio-idle note for the general shape).

## Sonic reach

No direct param edit — reachable only through an already-attached
`FlareKind` on Pacman V2.

## Executable proofs

No dedicated `check_pacman_*.py`/`test_pacman_*.py` exists yet — a named
gap. The nearest shared-machinery proof is
`tests/test_lead_time_alignment.py` (the transition-anchor system
`particle_handoff` feeds) and AGENTS.md's own paragraph on `pacman`'s
`no_background_color` flag (search "pacman" in AGENTS.md for the colour-
set accept-list caveat before assuming a narrow list is arbitrary).
