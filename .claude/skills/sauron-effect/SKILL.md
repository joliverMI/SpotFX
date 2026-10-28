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
   rainbow (chromatic span > 180°, Pulse's own test) gets the RADIAL
   mapping (tune-up 1, 2026-10-11, his "too messy" on a heat-mapped
   rainbow): the set cold → warm walked outward-in through the eye's own
   shape (`radial_coord` — lens-shaped against the slit, round at the
   iris rim, following the hexagon outside), heat only sets brightness;
   everything else dark → bright along the heat. The resolved mapping is
   stored WITH the curve (`mapping()` calls `_assert_gradient` first), so
   a journey that carries a set across the rainbow line switches mapping
   in step with its colours. `angle` (Eye's rule) and `warm` (the old
   rainbow heat map) are still choices. KNOWN, TO WATCH AT THE GATE: the colour
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

## Tune-up 1 (2026-10-11): the slit floor and the perimeter ring

The Admiral, after tuning it live: the slit and the perimeter ring "don't
resolve quite right as they move because of the nature of the hex
pattern". Two constants govern the fix — never per-pixel tuning knobs:

- **`SLIT_MIN_DARK_PX` (3)** — the slit's fully dark core is never
  narrower than this many RENDERED pixels: a lattice row holds a real cell
  every second column, so a 2-px band can miss a row as the eye moves; his
  "one pixel more" cannot. A rounded column unioned with the lens, stopped
  `SLIT_MIN_TIP` half-widths short of the tips, scaled back up by the
  eyeball turn's sideways squeeze. `last_slit_core` is its instrument.
- **`RING_WIDTH` (0.11, was 0.05) + `RING_FADE`/`RING_FADE_ROUGH`** — the
  ring is ~2 px each side of the iris edge and fades into the flames,
  SCREENED with them (not a max), so there is no step where they meet.

No param changed meaning, so his tuned Sauron scene needed no migration.

## The lull is UPSIDE DOWN (2026-10-11), Eye's change made here too

His word: "upside down. it's a simple 180 degree rotation" (the plan's
revision 3 had turned the lids a quarter turn; that reading is withdrawn).
`_draw_lids` evaluates the copied lid geometry at (-dx, -dy) about the eye
and swaps the panel edges, so the lids meet just above the eye's centre and
curve the other way; `_step_lid`, the travel curve and the lid colour (the
set's hottest) are unchanged. `_lids_rotated` is set when a lull starts
(`lull_lids_upside_down`, registered, default True) and held through the
drop until the lids are open, so the drop opens them the same way round.
Same code as Eye (eye-effect skill); proof
`tests/test_eye_lull_lids_upside_down.py`.

## Background

No `no_background_color` flag: an authored set background reaches the wire
and `get_pixels()` paints it once for unlit cells. The effect never paints
`_bg_color` itself; the lids are literal black (AGENTS.md "A colour set's
background MODE lands in ONE place"). With `sky` > 0 almost no real cell
inside the hex is unlit.

## The drop Shockwave and the breath-hold (2026-10-11, transitions-drop plan phase 1)

This effect is a member of `fx.device_model.DROP_SHOCK_EFFECTS`. Its drop
gets the shared Shockwave painted by `Twod.render` AFTER its own `draw()`
(`fx/effects/phase_grammar.py` is the binding statement): a rim bloom, ONE
wavefront born on the iris rim as drawn this frame (`_last_iris`), debris (burning out as flame licks) and a wall splash, all in the
colour set's own colours, max-composed, never white (his ruling), with this
effect's own frame held dark ahead of the front (`drop_reveal`). The effect
calls `self._shock_begin()` exactly where its own drop payoff fires — never
on a silent watchdog release — and `shock_rim()` names its eye.
Eleven registered settings (`drop_shock` 0 = off, `drop_bloom_ms`,
`drop_color_lean`, `drop_ring_speed`, `drop_ring_width`, `drop_wake`,
`drop_debris_n`, `drop_debris_speed`, `drop_afterglow_beats`,
`drop_reveal`, `drop_shock_scale_min`) are first guesses pending his eye;
Sonic reaches them with `set_scene_entry_param`. The drop arm tells this
effect `drop_intensity`, which scales the debris count and the front's life.
The lull arm also tells it the BREATH-HOLD (`lull_breath_at_s`,
`lull_breath_s`, from the room's `lull_breath_hold_s`, 0.4 s default, always
inside the lull's dark rule): the base render takes the frame to true black
for that window. Help topics `drop-shockwave`, `lull-dark-cap` (the breath-hold is folded into it); proof
`scripts/check_drop_shockwave.py` / `tests/test_phase_grammar.py`.

WHETHER A DROP PAINTS IT AT ALL (2026-10-12, his "toggled per scene, as
well as globally, as well as a global setting for minimum energy"): the drop
arm also tells this effect `drop_shock_on` — the room's `drop_shock_enabled`,
the showing scene's own `drop_shock_enabled`, and the top bar's Energy
(`bridge.intensity(look_ahead=True)`, ENERGY since 2026-10-28 — `spectra/services/energy.py`; the 0.7 is re-set by `scripts/energy_parity.py`) against the room's `drop_shock_min_energy` (0.7),
decided by `phase_grammar.shock_allowed`. False = no painter at all: the
frame is this effect's own drop byte for byte (no reveal hold-back either).
Untold reads True. It is an overlay, so nothing in this effect's own drop
changes; `drop_shock` (the per-effect strength) is a separate knob. Help
`drop-shockwave-switches`; proof `tests/test_drop_shock_switches.py`.

## THE PRE-DROP — the dimmed glare (2026-10-27)

The plan's 3.5: "the lids part to a narrow glare on the slit pupil in the
new colours, flames held down, brightening slowly until the drop opens them
fully" — and it ships "at a dimmer setting" (his "do all recs"). Sauron is
in `fx.device_model.PRE_DROP_EFFECTS` since predrop step 8, one look for
both kinds ("glare"), ahead of the Sauron scene, which still waits on his
tuning session. The PRE_DROP block beside the surge constants is the look.
Four invariants not visible cold:

- **WHERE THE LIDS PART TO.** PRE_DROP_LID_OPEN_TO (0.62) sits in Eye's lid
  pause (LID_PAUSE_START..END): the lids rest on the iris's edge, so the
  eye's own band shows and the panel above and below stays covered — the
  prototype's glare exactly (its comment said "40% open"; it is the iris's
  edge). They part over PRE_DROP_PART_S from shut; the lull's own close is
  measured to the pre-drop and the breath holds the panel black before it.
- **HELD DOWN, NOT REWRITTEN.** The flames' reach is multiplied in
  `_flames(held=)` and the ember sky skipped while the glare shows — no
  config write (the prototype wrote `flames`/`sky` and restored them).
  Measured: about 460 flame cells through the approach, about 80 in the
  glare.
- **DIMMER, AND THE DROP NEVER SLAMS.** PRE_DROP_GLARE 0.20 -> 0.36 (the
  prototype's 0.35 -> 0.60): the lull's light is below today's at every gap
  (-2% at a 0.8 s spike, -38% at 2 s, -4% at a 3.3 s vocal intro), the gap
  about 1.85x today's lid line (the prototype's 2.7x). A drop landing on
  half-open lids slams them shut first (`_drop_slam`); after the glare
  (`_pd_glare`) it does not: the eruption fires on the mark and the lids
  open from the glare.
- **UNTOLD IS TODAY'S** frame for frame (proven against the module at the
  step-8 base; the rig reseeds `noise` and `_wander_seed`, which Sauron
  draws from an unseeded generator at construction).

## Sonic reach

Every registered param through `set_scene_entry_param` (registry-driven,
including `palette_sort`); the `sauron_surge` kind through
`set_flare_kind`. Help topics: `sauron-effect`, `sauron-surge`.

## Executable proofs

`scripts/check_sauron.py` (real pipeline, real crystal mask: slit
continuous on the lattice — and across a moving-gaze sweep at rest, under
a full charge and at the narrowest Slit Width, the floor off as red
control — rim hottest, the ring's crest on a real cell in every direction
every frame and its fade into the flames, reach, surge erupt/reset/decay,
beat dilation, palette sort, angle mode, the radial mapping following the
slit and breaking a rainbow into far fewer patches than the heat map, a
60 s soak, frame cost ~2.9 ms p50 here) — run by `tests/test_sauron.py`, which also covers the registry,
the device-model sets, the flare kind, the engine write (incl. flares-off),
the preview ruler and Sonic's enum. Offline GIFs:
`scripts/render_sauron.py` -> `docs/evidence/sauron/`; tune-up 1's
before/after (the merged effect read out of git beside the working tree,
his scene's own values, the eye moving): `scripts/render_sauron_tuneup.py`
-> `docs/evidence/sauron-tuneup-1/`.

## Flame Lick / Ignition (2026-10-11, transitions-drop plan phase 4)

- **FLAME LICK** (Sauron -> Black Hole / Orbits / Fish / Squiggles /
  Fireworks): the program reads the eye's last picture; `explode_frac`
  (room `transition_explode_frac`, his "say half for now") of its lit cells
  fly out as shards in the SET colour nearest each cell (never white), the
  rest collapse into the black; the eye dissolves over 0.3 s.
- **IGNITION** (those -> Sauron): `program_rim` (eye centre + iris radius in
  px, written each draw) is where the vortex lands; `_lens_gain` (1.0 outside
  a program) multiplies the slit's width so it opens from a hairline; the
  program reveals the eye from the rim by ONE fill, so the ring never pops in.
- **THE HANDED BRIGHTNESS**: a snapshot carrying `body_gain` sets where the
  body fades up FROM — `_infall["g0"]` for an adoption with particles,
  `_fade_up` for an empty program hand-off; 0.25 (the old fixed start) when
  none is handed, byte-identical. Eye has the same three hooks.
`fx/effects/transition_cloud.py`'s docstring is the binding statement for phase 4's programs; `tests/test_transition_programs_phase4.py` measures them on the real pipeline.
