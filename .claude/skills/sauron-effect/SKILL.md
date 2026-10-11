---
name: sauron-effect
description: >
  fx/effects/sauron.py (Matrix, crystal-mapper) — the Eye of Sauron: a copy
  of Eye with a vertical slit pupil, a white-hot rim, a heat-mapped iris of
  fire streaks, noise-field flames reaching toward the crystal's hex edge,
  an ember sky, a `palette_sort` switch and the `sauron_surge` flare poke.
  Load before touching the slit, the flames' reach, the palette sort, the
  surge flare, or anything Sauron inherited from Eye (gaze, hand-off,
  charge/lull/drop).
---

# Sauron

Matrix effect on `crystal-mapper` — load `crystal-hex-grid` first. The
module docstring is the binding statement; the approved plan is
`/home/javi/fleet-spotfx/data/sauron-eye-plan/report.md` (v2, "go with all
recs, approved", 2026-10-10). Phase 1 (this effect) and phase 2 (the scene
copy script, NOT run) are built; the strips (`sauron1d`), a Sauron-own
charge/lull/drop choreography and the B-style ember garnish on a surge are
later phases — do not build them without his word.

## What is COPIED from Eye, and the one departure

The gaze model, the 3D foreshortening, the particle hand-off (src
`"sauron"`) and Eye's charge/lull/drop state machine (iris grows / slit
narrows / flames run inward on a charge; lids on a lull; eruption on a
drop) are Eye's, copied — NOT shared. Eye stays byte-for-byte untouched.
The one departure: `snap_threshold`'s saturating `>=` is FIXED here
(`thr < 1.0 and imp >= thr`, dancer.py's shape) — Eye still has it.

Every effect that special-cases an `"eye"` snapshot was taught to treat
`"sauron"` the same (radial's src gate, dancer's reveal hold, fish's
TRANSITION_ADOPTERS, spectra/services/transition_phases.py's pairs). A NEW
effect that special-cases `"eye"` must name `"sauron"` too.

## Four things that bite

1. **`pupil_size` keeps Eye's NAME, not its meaning**: here it is the
   SLIT's height as a fraction of the iris radius (Eye: a round pupil's
   radius as a fraction of the panel). `iris_size`/`gaze_radius` keep their
   meanings but the plan settled bigger/closer defaults (0.62 / 0.36). The
   seeder drops those static Eye values for exactly this reason.
2. **Reach is a FRACTION of each pixel's own gap to the hex edge**, ray-cast
   from the eye through blackhole.py's measured hex faces — never a scalar
   radius. MEASURED (scripts/check_sauron.py §3, shipped Flames 0.55):
   mean lick reach ~0.2 of the gap at rest, ~0.45-0.5 at full bass, the
   longest licks to ~0.9-0.98 (within 15% of the edge in most full-bass
   frames). "Flames" is the knob if he wants them to fill more.
3. **The palette sort runs only when GradientEffect regenerates its curve**
   (`_generate_gradient_curve` override — on a config change, never per
   frame) and rewrites only the curve THIS effect samples. Under `auto` a
   rainbow (chromatic span > 180°, Pulse's own test) sorts cold → warm,
   everything else dark → bright. KNOWN, TO WATCH AT THE GATE: the colour
   journey rotates a set's hues, and a re-ordering is discrete — as a
   rotation carries one colour past another in warmth/brightness, those two
   swap places along the heat (a step, not a glide). Measured nowhere yet.
4. **The `surge` poke is unregistered and self-resetting** (the
   firework_burst / pulse_flash / big_fish shape): edge-detected in
   `config_updated`, a creation baseline so a stale persisted poke never
   erupts, reset to 0 in `draw()` under the effect lock. The envelope rises
   to the poke at once and decays exp(-t / SURGE_TAU); `surge_visible_s` is
   what the preview ruler draws. A drop/radial eruption (`_burst`) burns
   like a full surge.

## Background

No `no_background_color` flag: an authored set background reaches the wire
and `get_pixels()` paints it once for unlit cells. The effect never paints
`_bg_color` itself; the lids are literal black (AGENTS.md "A colour set's
background MODE lands in ONE place"). With `sky` > 0 almost no real cell
inside the hex is unlit.

## Sonic reach

Every registered param through `set_scene_entry_param` (registry-driven,
including `palette_sort`); the `sauron_surge` kind through
`set_flare_kind`. Help topics: `sauron-effect`, `sauron-surge`.

## Executable proofs

`scripts/check_sauron.py` (real pipeline, real crystal mask: slit
continuous on the lattice, rim hottest, reach, surge erupt/reset/decay,
beat dilation, palette sort, angle mode, a 60 s soak, frame cost ~2.8 ms
p50 here) — run by `tests/test_sauron.py`, which also covers the registry,
the device-model sets, the flare kind, the engine write (incl. flares-off),
the preview ruler and Sonic's enum. Offline GIFs:
`scripts/render_sauron.py` -> `docs/evidence/sauron/`.
