---
name: fireworks-effect
description: >
  fx/effects/fireworks.py (Matrix, crystal-mapper) and fx/effects/
  fireworks1d.py (Strips) — the rocket/burst effect behind Fireworks V2.
  Load before touching launch/burst/drop-tail timing, before tuning
  spawn_rate (at 0, beat bursts are the ONLY launch source and every
  spawn_rate multiplier is inert — verify the live value, it drifts), or
  before adding a firework_burst-style flare kind to another scene.
---

# Fireworks / Fireworks1d

Matrix effect renders to `crystal-mapper` — load `crystal-hex-grid` first.

## At `spawn_rate: 0`, beat bursts are the ONLY launch source — check the
   live value before promising a spawn-rate fix

The mechanism: with `spawn_rate` at 0, beat bursts (`beat_burst`) are the
ONLY ordinary launch source, and any `_pspawn`-style spawn_rate multiplier
(including the charge's `CHARGE_SPAWN_X`, `1 + X*p`) multiplies zero and is
INERT. Anything that must visibly add launches then has to be a launch RATE
or touch beat bursts directly — which is exactly why the drop tail is a
rate (`fx/VENDOR.md` #17, "Fireworks drop tail").

Which regime his scene is in is NOT a fixed fact: `seed_fireworks_scene.py`
and the drop-tail notes authored `spawn_rate: 0`, but a read of the live
store on 2026-09-16 showed 0.5 on both entries. **Verify against
`GET /spectra/api/scenes` — this drifts.**

## Density cap: `p_nocap`/`f_nocap` bypass, and why the "big burst then
   nothing" cliff existed

Particles spawned past `max_blobs` (payoff, `firework_burst` flare, drop
tail, beat-burst rockets past the cap) are flagged `p_nocap`/`f_nocap` and
DON'T occupy the cap slot. Before that flag, a payoff held the cap full
for `PAYOFF_LIFE × burst_life` (~2.6s on his crystal) and silenced every
beat burst — the "big burst then nothing" defect. Measure post-drop
density with `scripts/check_fireworks_drop_tail.py` before reasoning about
spawn pacing anywhere near a drop.

## Drop tail: an elevated launch rate that eases back, not a flat return

Right after the payoff an EXTRA launch rate is ADDED on top of the ordinary
show: `DROP_TAIL_RATE * (1 - t/DROP_TAIL_S)` launches/s — linear, additive,
`DROP_TAIL_RATE = 8.0`, `DROP_TAIL_S = 2.5` (`_drop_tail_step`; the same
`DROP_TAIL_S` in `fireworks.py` and `fireworks1d.py`, but the strip's RATE
is 12 since strip phase plan phase 3 — a heavier shower on the strip). It eases to exactly
baseline by `DROP_TAIL_S`, never overshooting below it, and runs on its own
clock (the drop phase itself self-resets earlier, at `DROP_SETTLE_S`). This
covers a drop with NO preceding lull too (no rockets still grows a tail).
An ordinary flare burst (`burst_rockets`) does NOT start a tail — the tail
belongs to the drop specifically; a flare stays the additive volley it
was authored as.

## The STRIP (`fireworks1d`) draws its phases through the strip phase layer

Since 2026-10-11 (strip phase plan phase 3; `fx/effects/strip_phase.py` is
the binding statement, `fx/VENDOR.md` #74) the strip's charge/lull/drop
LOOK comes from the shared layer, and so does its phase PLUMBING (edge
detection, the orphan watchdog, the self-reset after `DROP_SETTLE_S`) —
the module keeps `_strip_phase_enter` (a lull launches its rockets, a drop
explodes them and starts the tail, leaving a lull any other way burns them
out) and a per-frame `_phase_step`. The phase is `self._sp_phase`. Retuned:

- the charge no longer slows or shortens its fireworks (`CHARGE_SLOW`,
  `CHARGE_SHORT` 0);
- his scene's `max_blobs` 6 clipped the charge's launch multiplier to 3
  fireworks in flight, so the charge ADDS an uncapped launch rate rising
  0 -> `CHARGE_LAUNCH_RATE_MAX` (8/s) (the tail's own `ignore_cap` shape);
- the strip's drop tail is 12/s (the crystal's stays 8);
- the lull is the ONE strip lull that is not black (his call 3): this
  effect's own `lull_ember` default is `LULL_EMBER` (0.12, its schema via
  `strip_phase.tunable_fields`, its registry entry via
  `registry_params(STRIP_PHASE_DEFAULTS)`), so the rockets cross the dark
  as 12% embers. Their own dimming (`LULL_ROCKET_FADE`) is retired — the
  layer's fade is the one dimmer.
- ACTIVITY (`STRIP_PHASE_ACTIVITY`): spawn_rate, beat_burst, burst_speed
  (0.3) — never max_blobs, his density cap.

A Firework Burst flare in the lull's dark is its own punch; nothing else
answers it here. Off-phase frames are byte-identical to before. The 2-D
Matrix `fireworks.py` is untouched.

## `firework_burst` flare kind: it jumps a phase key, it does not schedule

`firework_burst` explodes an intensity-scaled rocket count (3 at intensity
0 → 6 at 1) IMMEDIATELY, by jumping the effect's own `burst_rockets` key
(edge-detected, self-resetting — a phase-key pattern, `fx/VENDOR.md` #15,
deliberately absent from the param registry, gated by
`fx.device_model.FIREWORK_BURST_EFFECTS`). It is deliberately NOT
`beat_burst` — that param only launches on the NEXT beat, so it can never
land on a trigger mark. It has NO release queue (nothing to schedule at
the four drain points) — particles simply age out inside the effect.

## THE KEEPERS MELD — a flagged keeper becomes a payoff rocket (2026-10-08)

The drop-led switch's fireworks melds (`spectra/services/drop_switch.py`,
drop-scene-variety plan phase 3, `fx/VENDOR.md` #64). A Fish/Orbits lull
TOLD it leads into Fireworks (`lull_handoff`'s `lull_next`) flags its
`lull_keep` (3) keepers in its snapshot (`"keepers"`); `_adopt_handoff`
turns each flagged one into a HELD, stationary rocket (`_import_keepers`:
`p_rocket` with no `_rocket_path`, `p_nocap`, at most
`KEEPER_ROCKETS_MAX`) and the drop arm that follows the cut makes
`_rocket_payoff` — the lull rockets' own payoff — explode every one where
it stands, in its own colour, instead of six random near-centre bursts.
Three things not visible cold:

- **No flag, no change**: an unflagged snapshot adopts byte-identically
  to before (proven against the pinned pre-change module). The flag only
  exists when the outgoing lull was told a DIFFERENT effect is coming.
- **Held keepers never hang**: no drop arm within `KEEPER_HOLD_S` (0.6 s)
  and each bursts as an ordinary firework where it stands
  (`_release_keepers`); a lull arriving meanwhile releases them first, so
  `_phase_rockets` (which guides the first N rockets) can never grab them.
- **Order**: `_adopt_handoff` runs before `_phase_step` in `draw()`, so a
  drop arm that lands before the first frame still finds the keepers.

Leaving Fireworks is spectra-side only (a cut 1 s after its own drop into
the Black Hole; on the next big analysed flare into the others) — the
incoming effects' generic adopts take the burst cloud; nothing here
changed for it.

## Thematic transitions (2026-10-11, transitions-drop plan phase 3)

Fireworks FEEDS the Infall into the Black Hole for now (`_handoff_snapshot`
carries `vx`/`vy` = `p_vx`/`p_vy` in px/s + `gesture: "spray"`); Lensing
replaces that row next task. Black Hole -> Fireworks has NO program (the
Fountain, next task) and keeps its own adopt. A DROP-led Fireworks -> Black
Hole switch is still the SWALLOWED meld, untouched. `fx/effects/transition_program.py`'s docstring is the binding statement; `tests/test_transition_programs.py` measures it on the real pipeline.

## Sonic reach

No direct param edit — same rule as every effect here; reachable only
through an already-attached `FlareKind` on Fireworks V2. The melds' two
room tunables (`drop_switch_swallow_delay_s`, `drop_switch_hit_threshold`)
are settings-registry keys.

## Executable proofs

`scripts/check_fireworks_drop_tail.py`, `scripts/check_firework_burst.py`,
`tests/test_fireworks_drop_tail.py`, `tests/test_fireworks_rocket_angles.py`,
`tests/test_firework_burst.py`, `scripts/check_particle_strip_phase.py`
+ `tests/test_particle_strip_phase.py` (the strip on the strip phase
layer, his own Fireworks V2 strip entry, the pinned pre-change module as
red control), `tests/test_fireworks_melds.py` (the
keepers meld on the real pipeline, the pinned-module byte-identity, the
swallow and implode adopts), `scripts/render_fireworks_melds.py` (offline
GIFs, committed under `docs/evidence/fireworks-melds/`). The scene
migration that attaches the kind, `scripts/add_fireworks_burst_flare.py`
(dry-run default), belongs to the fireworks-v2-scene skill. History:
`docs/SPECTRA_SPEC.md` §89 (also
referenced in AGENTS.md's own prose), `fx/VENDOR.md` #15, #17.
