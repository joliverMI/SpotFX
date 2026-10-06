---
name: pulse-effect
description: >
  fx/effects/pulse.py (registry id `pulse`) — the Singles' one-colour light
  that pulses on hits, built to replace Power on the 17 Hue bulbs, the porch
  rail and the dining table (single-led-power plan, phases 1-3; phase 4,
  moving his scenes over, waits for his tuning). Bound today only in the
  tuning scene "Pulse Test (Orbits V2)". Load before touching hit
  detection, the flash budget or its output guard, charge/lull/drop on the
  Singles, the rainbow walk, the pulse_flash / pulse_flip flares or a flare
  kind's min_intensity, or a "the singles flash too much / don't move /
  went white" report.
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
  held) easing back to exactly 0 at `flip_beats` — never an RGB lerp,
  which passes through grey and shows as WHITE on Hue (the test carries
  that as its red control).
- **Flare pokes** follow the burst_rockets pattern (`fx/VENDOR.md` #15):
  edge-detected in `config_updated`, consumed in `render`, self-reset to 0;
  `_init_state` zeroes a stale persisted value. `flash`/`flip` are NOT in
  the registry; the sizes/timings they produce (`flash_size`, `flash_ms`,
  `flip_degrees`, `flip_beats`) ARE, so he tunes them on the Initial Set tab.
- **min_intensity** (`FlareKind`, any type; pulse_flip defaults to 0.4) is
  STRICT: fires only above. Below it a kind leaves its lane pool like a
  disabled one (`resolve_lane_picks`), and `fire_kind` (the ▶ Preview)
  returns `below_min_intensity`.

## Sonic reach

Effect params: none directly. Flares: `set_flare_kind` creates/updates
`pulse_flash` / `pulse_flip` and `min_intensity` (omit-means-keep).
Declaring both on the test scene: `scripts/add_pulse_flares.py` (dry run
default; refuses any scene with no Pulse entry).

## Proofs

`tests/test_pulse_effect.py` (phase 1), `tests/test_pulse_engine_wiring.py`
(phase 2), `tests/test_pulse_rainbow_flares.py` (phase 3: walk, flares,
gating, real pipeline + device preview, his songs),
`scripts/check_pulse_effect.py` (fixtures from his WAVs). Not yet measured:
the Singles' real gamma and delay (`scripts/measure_singles_response.py`,
blocked on a camera pose that can see them).
