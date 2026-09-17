---
name: blackhole-effect
description: >
  fx/effects/blackhole.py (Matrix, crystal-mapper) and fx/effects/
  blackhole1d.py (Strips) — the particle-infall/explosion effect behind
  the Black Hole V2 and Black Hole V2 UI scenes. Load before touching
  either module, before tuning reverse/charge/lull/drop behaviour on this
  effect, or before reasoning about a "black hole isn't exploding on time"
  / "the star freezes on every flare" style report that turns out to be
  this effect via a shared param (spin_sign).
---

# Blackhole / Blackhole1d

Matrix effect renders to `crystal-mapper` — **load the `crystal-hex-grid`
skill first** for anything about spawn radius, coverage, or "is this
visible" on this device; blackhole's own spawn-radius/hex-fill fixes are
downstream of that geometry, not independent tuning.

## Params that mean something other than their name suggests

- `reverse` (toggle, default True on Matrix / True on Strips): NOT "run
  backwards right now" — it's a SPAWN-SIDE flag that picks the sign of new
  particles' motion. Nothing reverses a particle already in flight. A
  `False→True` edge that used to snap the whole outbound population now
  ARMS a real turnaround (`_reverse_edge`/`_arm_reverse_fallback`,
  `REVERSE_FALLBACK_TURN_S`) that merges onto the speed curve with no
  visible step. **Do not "fix" a horizon captive by releasing it** — that
  was tried (PR #179) and reverted the same day: release evicts blobs the
  flare never moved and makes them immortal. The real fix pins a captive
  to the ring only while it's AT the ring (`REVERSE_FALLBACK_RING_TOL`).
- `swirl`, `spawn_rate`, `beat_burst`, `spawn_audio`, `speed_audio`: these
  are AUDIO GAINS (aspect: reactivity in the registry), not fixed
  speeds/counts — the live signal they multiply idles near 0 during quiet
  passages, so a "healthy" value can visibly read as frozen. See the
  radial-effect skill's audio-idle note for the general shape of this
  trap; it applies here too via the shared audio callback.
- `horizon_scale` / `HEX_FILL_RADIUS` (0.2..0.8, default 0.19-0.25): the
  lull's fill stops at the crystal's own real-cell boundary
  (`HEX_FILL_RADIUS ≈ 1.128` normalized-r), NOT at the addressable
  rectangle's corner (`r_max ≈ 1.49`) — growth past the hex covers dead
  cells only. Measure "is the panel dark?" over real cells (device
  profile mask), never the dummy rectangle.
- `horizon_color`: an ACCENT param (`config/effect_params.json`
  `blackhole.params.horizon_color.accent = true`) — forced black by
  `scene_compiler._entry_config` on every compile unless the scene entry
  itself authored a value. Don't assume a scene's stored value here is
  what he tuned; check `accent_param_for` if a scene shows white/wrong
  sparks.
- `background_color`/`background_brightness`: `blackhole` has NO
  `no_background_color` flag (unlike `radial`/`pacman`), and an authored
  black `bg_color` on a colour set is LOAD-BEARING here in Hybrid mode —
  it's what resets the background to black on every fire. Never strip it
  as "redundant" (AGENTS.md §72 has the full colour-bleed proof).

## Particle-flag vocabulary (don't conflate these two)

- `p_nocap` = "spawned past `max_blobs`" (drop payoff, blob rush, charge's
  forced formation) — read this for density-cap arithmetic.
- `p_is_burst` = "a drop-payoff particle specifically" — read THIS for
  anything measuring the explosion (`PHASE_BURST_SPEED_MULT` keys off it).
  A blob population is Little's Law (`rate × dwell time`), not the
  integral of the spawn rate — measure counts on rendered frames, never
  derive them from the rate curve. A drop's TOTAL visible peak is
  `PHASE_BURST_N` plus whatever the charge/lull just fed the horizon
  (`p_cap < 0`, captured), not the payoff alone — anchor any target ratio
  on `p_is_burst`, never on the total (`fx/VENDOR.md` #38).

## The three-anchor rule for THIS effect specifically

A drop/explosion anchors its START to the trigger mark (never its ramp's
end) — `_response_switch_lead_ms` short-circuits `lead=0` for
`event_class=="drop"` unconditionally. The burst payoff in this module
fires unconditionally on the phase's first rendered frame (the old
`phase_progress ≈ 0.995` gate is gone) to make that lead land visibly.
`DROP_FALLBACK_S` is dead code — nothing waits on `phase_progress`
reaching anything anymore.

## An orphan watchdog crash class lives here

`_phase_step`'s "drop" branch resolves `burst_t` out of a `None` sentinel
— any early `return` inside `_phase_step` (e.g. the charge/lull orphan
watchdog path) MUST happen only after that sentinel is resolved, or
`draw()`'s next call divides `None` and kills the render thread silently
(fixed once, `tests/test_blackhole_orphan_drop_none_crash.py` — the
general pattern to check before touching `squiggles.py`/`eye.py` too).

## Sonic reach

Sonic cannot edit these params directly (device/effect editing is out of
scope for the settings/scene console by design — see AGENTS.md's SPECTRA
settings console section). A param here becomes Sonic-tunable only
through an existing `FlareKind.params` target already wired on the
Black Hole scenes — Sonic edits the KIND (`set_flare_kind`), never the
Initial Set entry.

## Executable proofs

`scripts/check_blackhole_charge_lull.py`, `check_blackhole_charge_target.py`,
`check_blackhole_explosion_and_gap.py`, `check_blackhole_explosion_speed.py`,
`check_blackhole_hex_spawn.py`, `check_blackhole_reverse_fallback.py` +
matching `tests/test_blackhole_*.py`. Full history: `AGENTS.md`'s "Black
Hole" section and `fx/VENDOR.md` deviations #12, #14, #18, #19, #20, #38.
