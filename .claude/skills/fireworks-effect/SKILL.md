---
name: fireworks-effect
description: >
  fx/effects/fireworks.py (Matrix, crystal-mapper) and fx/effects/
  fireworks1d.py (Strips) — the rocket/burst effect behind Fireworks V2.
  Load before touching launch/burst/drop-tail timing, before tuning
  spawn_rate (his real scene runs it at 0 — beat bursts are the ONLY
  launch source), or before adding a firework_burst-style flare kind to
  another scene.
---

# Fireworks / Fireworks1d

Matrix effect renders to `crystal-mapper` — load `crystal-hex-grid` first.

## His real scene runs `spawn_rate: 0` on BOTH effects

Beat bursts (`beat_burst`) are the ONLY ordinary launch source on his live
Fireworks V2 — any `_pspawn`-style spawn_rate multiplier (including the
charge's `CHARGE_SPAWN_X`) is INERT on his scene. Anything that must
visibly add launches has to be a launch RATE change or touch beat bursts
directly (`fx/VENDOR.md` #17, "Fireworks drop tail").

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

Right after the payoff the ordinary launch rate is ELEVATED
(`>= 1 + DROP_TAIL_X * (1 - t/DROP_TAIL_S)^2` of baseline) and eases to
exactly baseline by `DROP_TAIL_S`, never overshooting below it. This
covers a drop with NO preceding lull too (no rockets still grows a tail).
An ordinary flare burst (`burst_rockets`) does NOT start a tail — the tail
belongs to the drop specifically; a flare stays the additive volley it
was authored as.

## `firework_burst` flare kind: it jumps a phase key, it does not schedule

`firework_burst` explodes an intensity-scaled rocket count (3 at intensity
0 → 6 at 1) IMMEDIATELY, by jumping the effect's own `burst_rockets` key
(edge-detected, self-resetting — a phase-key pattern, `fx/VENDOR.md` #15,
deliberately absent from the param registry, gated by
`fx.device_model.FIREWORK_BURST_EFFECTS`). It is deliberately NOT
`beat_burst` — that param only launches on the NEXT beat, so it can never
land on a trigger mark. It has NO release queue (nothing to schedule at
the four drain points) — particles simply age out inside the effect.

## Sonic reach

No direct param edit — same rule as every effect here; reachable only
through an already-attached `FlareKind` on Fireworks V2.

## Executable proofs

`scripts/check_fireworks_drop_tail.py`, `scripts/
add_fireworks_burst_flare.py` (migration — dry-run default),
`tests/test_fireworks_drop_tail.py`, `tests/test_fireworks_rocket_angles.py`,
`tests/test_firework_burst.py`. History: AGENTS.md §89, `fx/VENDOR.md`
#15, #17.
