---
name: pulse-effect
description: >
  fx/effects/pulse.py (registry id `pulse`) — the Singles' one-colour light
  that pulses on hits, built to replace Power on the 17 Hue bulbs, the porch
  rail and the dining table (single-led-power plan, phases 1-4). Tuned on
  "Pulse Test (Orbits V2)"; phase 4 (scripts/migrate_singles_to_pulse.py, run
  at deploy) moves every Power Singles scene onto it. Load before touching hit
  detection, the flash budget or its output guard, charge/lull/drop on the
  Singles, the rainbow walk, the pulse_flash / pulse_flip flares or a flare
  kind's min_intensity, or a "the singles flash too much / don't move / went
  white" report.
---

# Pulse

The module docstring is the binding statement; this is the cold-start map.
Plan: `/home/javi/fleet-spotfx/data/single-led-power-plan/report.md`.

## What drives it

- **Hits come from live audio inside the effect** (`ingest_signal`, audio
  thread) — measured against the music's OWN recent level, so calm songs
  still pulse. Everything else is engine-pushed config: `energy`/`beat_ms`
  (`spectra/services/pulse_feed.py`, at section edges), `phase`/
  `phase_progress` (it is in `fx.device_model.PHASE_EFFECTS`), and the two
  flare pokes `flash`/`flip`.
- **Two clocks.** Hits are logged on the audio clock (`_audio_t`); the
  flash budget, the output guard and rainbow-step spacing run on the RENDER
  clock (`_render_t`), so a flare flash lands and the window expires even
  when no audio arrives. Harness tests: `tests/pulse_song_harness.py` steps
  audio-then-render per frame.

## Invariants not visible from a cold read

- **The flash budget has two layers.** Predictive: each hit/flash books
  its rise in delivered light when it starts and is shrunk to what is left
  (`_budget_cap`, `_land_flash`). Backstop: `_guard_output` sums the rises
  ACTUALLY sent per second and clamps a frame that would overspend — needed
  because through the bulb curve a hit's attack under a decaying flash
  delivers more than either booked (measured: 3.02-3.37 on his songs with
  dense flares before the guard). The drop's landing frame is exempt (never
  shrunk) but spends the window. On his four fixture songs WITHOUT flares
  the guard never engages (`guarded_frames == 0`) — keep it that way or say
  why. Measure on the OUTPUT (`h.max_rise_per_second`), never the booking.
- **True black only during a music show**: phases are withheld from Pulse
  while a house mode rests (`scene_response._drive_phase`). A flash during
  a lull is scaled by the lull's own fade, so the lull still lands black.
- **Rainbow walk**: Pulse walks only when its `gradient` spans > 180° of
  hue (`chromatic_span_deg`, the colour journey's own test). The compiler
  (`scene_compiler.set_entries_for`) hands it the STRIPS' WHOLE gradient in
  a rainbow set (marked `is_rainbow` or spanning > 180°); a set marked
  rainbow whose strips span less shows the first colour, no walk. Steps
  1/7 on hits stronger than 0.35, at most one per 0.45 beat; drift 2% a
  bar; 70 ms glide. Samples the same RGB gradient curve the strips render.
- **Colour flip is a HUE rotation** (`rotate_hue`, saturation and value
  held), HELD at full angle for `flip_hold_s` (fixed seconds, not beats —
  tuning feedback 2026-10-06, his report: "way too fast... at least half a
  second and then fade out"), then eased back to exactly 0 over
  `flip_fade_s` — never an RGB lerp, which passes through grey and shows
  as WHITE on Hue (the test carries that as its red control).
- **Flare pokes** follow the burst_rockets pattern (`fx/VENDOR.md` #15):
  edge-detected in `config_updated`, consumed in `render`, self-reset to 0;
  `_init_state` zeroes a stale persisted value. `flash`/`flip` are NOT in
  the registry; the sizes/timings they produce (`flash_size`, `flash_ms`,
  `flip_degrees`, `flip_hold_s`, `flip_fade_s`) ARE, so he tunes them on
  the Initial Set tab.
- **Hit source** (`hit_source`, three options): "kick and bass" (default,
  tuning feedback 2026-10-06 — weights `beat_power`/`bass_power` near full
  and `mids_power`/`high_power` falling off above ~250 Hz, so hats/cymbals
  move it far less than kicks/bass); "bass weighted" (the original default,
  `lows_power + 2 x melbank mean`); "bass only" (`lows_power` alone).
  Regenerating `tests/fixtures/pulse/` after any change to the hit signal
  needs the new per-band arrays `scripts/check_pulse_effect.py` captures
  (`beat`/`bass`/`mids`/`high`, alongside the original `lows`/`bmean`).
- **min_intensity** (`FlareKind`, any type; pulse_flip defaults to 0.4) is
  STRICT: fires only above. Below it a kind leaves its lane pool like a
  disabled one (`resolve_lane_picks`), and `fire_kind` (the ▶ Preview)
  returns `below_min_intensity`.

## The lull's dark point is the SHARED rule, not a constant here

Since 2026-10-07 (the Admiral: "set a max time for that portion to 3
seconds ... 17 seconds of expansion and 3 seconds of dark") this effect's
lull goes dark at the dark point of `fx/effects/lull_dark.py` — dark for
half the lull, never longer than the room's `lull_dark_max_s` (3 s by
default, Sonic-editable via `set_setting`). SpotFX pushes `lull_ramp_s` /
`lull_dark_s` on the lull arm (`scene_response._drive_phase`, only to
`fx.device_model.LULL_DARK_EFFECTS`), and the effect measures the lull on
its OWN seconds-in-phase, never `phase_progress` — a long lull's dark
point sits inside the progress hang, where only a clock can find it. (A
lull after a completed charge used to start its progress at 1.0 and be
released by the orphan watchdog 12 s in; that is fixed for every phase
effect in the shared tween engine, `fx/VENDOR.md` #58, and the watchdog
reads plain progress again.) A write WITHOUT the two keys falls
back to the end of the ramp (`LULL_LEGACY_DARK_AT`, 1.0), byte-identical
to Pulse's own pre-rule fade. Told, Pulse now reaches pitch black at the
SAME dark point as the crystal (`keep = 1 - smooth(approach)`) — earlier
than before on a short lull (half of it, matching the crystal), and a
20 s lull is pitch black for exactly its last 3 s. Read lull_dark.py's
docstring before changing anything about when this lull goes dark.

## Sonic reach

Effect params: YES, as of the 2026-10-06 Sonic coverage audit build —
`get_scene_entry_params`/`set_scene_entry_param` (spectra/services/
scene_console.py) read and write any of the 27 Pulse settings' current
value on one scene's one device entry (e.g. "set Resting Level (calm) to
0.3 on Pulse Test's Singles entry"). A value held by a ⚡ binding is
replaced, named as such. Flares: `set_flare_kind` creates/updates
`pulse_flash` / `pulse_flip` and `min_intensity` (omit-means-keep).
Declaring both on the test scene: `scripts/add_pulse_flares.py` (dry run
default; refuses any scene with no Pulse entry). Putting Pulse on a
scene's Singles entry, or choosing its colour mode, is still NOT Sonic's
(the Initial Set tab's job) — only copy_scene_device_entry reaches that,
and only by copying a whole entry from another scene.

## The Light Show's hand on Pulse (2026-10-08)

Three Light Show actions reach this effect WITHOUT writing its config
(a config write would fight scene fires, the Pulse feed and the param
watchdog): `pulse_reactivity` and `pulse_brightness` push per-VIRTUAL
values into `fx/pulse_modulation.py`, which `render()` reads once a frame
(`self._mod`; None = no entry = byte-identical). Reactivity multiplies
`_react()` — the hit term (`_pulse`, the charge's `env * d2`) and the
rainbow walk's hit STEP — and nothing else, by the Admiral's choice
(option A): rest level, slow drift, flash/flip flares and charge/lull/drop
are untouched. Floor/ceiling clamp the final eye-scale level before the
output guard, and the floor is re-asserted after it (the guard only slows
rises); crossed, the ceiling wins. Holds on DIFFERENT targets stack
(reactivities multiply, highest floor / lowest ceiling) in
`spectra/services/show_mods.py`; re-firing the same action on the exact
same target RESTARTS the matching hold instead of stacking a duplicate
(his 2026-10-08 report of two "Flares off" entries from one re-fire). The
third action, `flares` off, stops every flare kind AND charge/lull/drop on
its virtuals (ResponseEngine `_flare_states`) — for this effect that means
no flash, no flip, no lull darkness and no drop burst on the Hues.
Sonic: `set_pulse_reactivity` / `set_pulse_brightness` / `set_flares` /
`end_effect_hold` (show_console). Spec: `tests/test_pulse_modulation.py`,
`tests/test_show_flares_off.py`.

## Phase 4 — moving his scenes over

`scripts/migrate_singles_to_pulse.py` (dry run default, `--apply`,
`--revert` from the manifest it writes beside its backup) switches every
scene whose Singles category entry runs `power` to `pulse`. It READS what
travels off the live tuning scene at run time, never a typed copy: the
Singles params (today `{}` — his tuning is the schema defaults, PR 359)
and every pulse_flash/pulse_flip kind verbatim with its attachment (every
flare band, x1.0, no lane) — his trigger timing included (Flash -92 ms,
Colour Flip -355 ms when written; seeded 0). A Pulse kind already on a
scene (matched by TYPE) is retimed only from the seed 0; any other value
is his per-scene timing and is kept. The colour flip's -355 ms becomes the
band ANCHOR (min over every declared, enabled kind, min_intensity-gated
ones included), so each flare band now starts 355 ms early and every other
kind waits to its own moment (per-flare trigger moment) — exactly as on
Pulse Test. Spec: `tests/test_migrate_singles_to_pulse.py`.

## Proofs

`tests/test_lull_dark.py` (the dark-point rule and this effect's lull on
the real pipeline).
`tests/test_pulse_effect.py` (phase 1), `tests/test_pulse_engine_wiring.py`
(phase 2), `tests/test_pulse_rainbow_flares.py` (phase 3: walk, flares,
gating, real pipeline + device preview, his songs),
`scripts/check_pulse_effect.py` (fixtures from his WAVs),
`scripts/check_pulse_hit_source_bands.py` (the 2026-10-06 tuning
feedback's reactivity evidence: old vs new `hit_source` default against
his songs' own bass vs snare/other onset marks). Not yet measured:
the Singles' real gamma and delay (`scripts/measure_singles_response.py`,
blocked on a camera pose that can see them). That script's `NEVER_STREAM`
guard refuses `hue-lights` because its stream is the whole ten-bulb Music
Group, far more than this protocol's two-fixture isolation needs — never
because any of its bulbs (the Loft Ceiling Uplight and the three Ledge
bulbs included) are treated differently; see AGENTS.md "THE FOUR BULBS ARE
ORDINARY" (2026-10-06).
