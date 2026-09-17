---
name: fish-effect
description: >
  fx/effects/fish.py (Matrix, crystal-mapper) — a schooling/steering fish
  effect behind the Fish scene, built as a wholesale copy of Orbits V2's
  bands/kinds but with completely different kinematics. Load before
  touching swim speed, avoidance, the camera window, wake/trail rendering,
  dispersal, or the swim-burst flare — every one of these has a shipped
  invariant that isn't visible from reading the code cold.
---

# Fish

Matrix effect renders to `crystal-mapper` — load `crystal-hex-grid` first.
Fish shares Orbits V2's scene data (bands, flare kinds, weightings,
curves — see `scripts/seed_fish_scene.py`) but reuses NONE of Orbits'
motion; treat "Orbits semantics" as a false friend here.

## The speed dial is his ESCAPE HATCH back to smooth motion — not a
   redundant knob, and the defaults are DERIVED, not tuned by eye

`min_drift_speed` (floor, fraction of the old continuous target) +
`stroke_speed_cap` (pulse cap synced to the flap phase) together replace a
single smooth speed target with surge-and-coast thrust. Setting
`min_drift_speed=1, stroke_speed_cap=0` reduces the formula to EXACTLY the
old smooth target, bit for bit (`scripts/check_fish_camera.py` §1b proves
swimming KINEMATICS match the pinned pre-thrust `THRUST_BASELINE_REF` at
that setting) — that's the dial's whole
purpose: a way back to the old feel without touching code.
**The shipped defaults (`min_drift_speed=0.85`, `stroke_speed_cap=0.4`)
are SOLVED, not picked**: a pulse must redistribute speed in time without
changing the average speed across a stroke cycle, so they satisfy
`min_drift_speed + stroke_speed_cap * PULSE_SHAPE_CYCLE_MEAN(0.375) == 1.0`
algebraically. **Changing either shipped default requires re-solving this
equation for the other value**, or you silently reintroduce a mean-speed
regression exactly like the one caught live 2026-09-17 (a rebase surfaced
a 23% slowdown from defaults that hadn't been re-solved). See the THRUST
comment block in `fish.py` itself before touching either number.

## The "Fish Swim Burst" flare kind ships at `trigger_offset_ms = 0` —
   his own ruling, and per-kind timing has since made a pre-fire SAFE

The flare KIND is named **"Fish Swim Burst"**
(`scripts/add_fish_swim_burst_flare.py`); `swim_burst` is the EFFECT PARAM
it spikes (a momentary toggle, `hold_ms=300`). He first asked for the burst
to start 100ms before the trigger, then corrected himself — "no, dont pull
the band forward, just dont add the 100ms pre-fire" — so it fires ON the
trigger. That ruling is the reason it sits at 0, not a mechanical limit.

The mechanical limit that motivated it is CLOSED: PER-FLARE TRIGGER MOMENT
has shipped (`scene_response._band_anchor_ms`, `PendingKindBatch`; AGENTS.md
"PER-FLARE TRIGGER MOMENT"). A band's anchor is the min over every
declared, enabled kind's offset, zero included; on a trigger-relocated fire
the whole band starts at that anchor and each kind then waits
`max(0, kind.trigger_offset_ms - anchor_ms)`. So giving this kind -100ms
would start the burst 100ms early while every sibling left at 0 still fires
exactly on the mark. Two caveats before doing it: a bridge-classified
flare, `on_update` or `POST /api/engine/event` fires the band ATOMICALLY
(no offset honoured there at all), and the automatic lead
(`_response_switch_lead_ms`) stays band-wide. Adding the pre-fire is a
change to his authored behaviour — ask him, don't "fix" it.

## The trail must be fed the UNGAINED body — a scatter/crossfade gain must
   never be deposited into a PERSISTENT decaying buffer

The outgoing-crossfade body gain (up to ~3.33x, `TRANSITION_GAIN_FLOOR`)
compensates for the virtual's additive blend so a departing fish doesn't
visibly dim — but depositing that GAINED value into `self.trail` (a
decaying buffer with MEMORY) compounds: he reported trails "3x too long"
and "50% too big" the same night this shipped. Fix shape: draw the body
ONCE at TRUE brightness into the trail (every future frame's decay/
diffusion governed by that alone), and only while scattering, a SECOND
time at gained brightness maxed against the trail for THAT FRAME's
composited output ONLY — never stored. Generalizes: any effect with a
persistent trail/wake buffer must never let a transient render-time gain
leak into what gets stored for the next frame.

## The trails are two things, not one — his 2026-09-17 word trimmed both 25%

"The trails" his eye sees are `self.trail` (the fish's own persistent
smear, `trail_decay` -> `half_life = 0.02 + trail_decay * 0.5`) AND
`self.wake` (the Orbits-style trail laid at the tail, `ripple_life` for
duration, `ripple_width` for size). His ask, verbatim: "turn down the size
and duration of the trails by 25%." Shipped defaults (also the schema/
registry defaults, so a fresh instance already lands here):
`trail_decay` 0.4 -> 0.29 (half-life 0.22s -> 0.165s, -25% — 0.75x0.4=0.3
would only be -23% because of the 0.02s floor), `ripple_life` 0.9 -> 0.675,
`ripple_width` 1.3 -> 0.975. `ripple_spread`/`ripple_amount`/`blob_size`/
colour were deliberately untouched — this is a trail-only change.
`fx/effects/fish.py`'s vol schema is the default source actually in force
for a fresh instance on his virtual (voluptuous fills a missing key from
`CONFIG_SCHEMA` at `_apply_config`'s `schema()(config)` call) — NOT
`config/effect_params.json`'s `trail_decay` entry (0.15 there, never
matched his live 0.4, so it was already not the source), though that
registry's `ripple_life`/`ripple_width` entries DID match and were updated
alongside. A currently-running instance needs `scripts/
trim_fish_trails_25.py --apply` (edits `storage/spectra/fx-live/config.json`
directly — no generic live effects-config HTTP route exists) plus a
`spectra.service` restart to pick the new values up; a defaults change
alone only reaches the NEXT fresh Fish instance.

## Fish never fade — they DISPERSE (steer off-panel), full brightness the
   whole way, on a DEADLINE

Every exit (population trim, lull, rush settle, an outgoing crossfade with
no adopting effect) is ONE mode: DISPERSING (`p_mode == 4`) — full
brightness, steered out under the ordinary turn-rate clamp, retired only
once the WHOLE body clears the panel. Speed is DERIVED every frame from
remaining distance-to-clear (never a tuned speed) — this is what lets a
900ms lull and a 6s one both work. Mode 2 (linear fade) now belongs ONLY
to the drop's ejecta.

## The swim burst can push a fish off-screen — a boundary SPEED BRAKE
   exists specifically for burst speed, and it's scoped tightly

The boundary steer converges on a FIXED TIME constant, so a burst-speed
fish can travel far enough during that correction time to clear the panel
edge before its heading catches up — this is NOT predicted by the
turn-radius math (speed-invariant by construction) and was only found by
instrumenting the real pipeline. The fix (`BOUND_BRAKE_AT`/
`BOUND_BRAKE_TAU`) is live ONLY while a swim-burst is active
(`self._burst`/`self._burst_tail`) and only for a fish heading OUTWARD —
ordinary swimming near the edge is completely untouched. Don't widen its
trigger condition without re-running `scripts/check_fish_burst_bounds.py`
and `scripts/check_fish_camera.py` §1b's ordinary-swimming kinematics
guard.

## Everything else worth knowing before a change

- **Body follows the RECORDED PATH, not a bend model**: the front half of
  the spine points the current heading; the rear half is walked back
  along a per-fish recorded path (world-space, pushed by real travel
  distance, never time-sampled) — a straight swim reduces to the old
  rigid stick exactly.
- **Mutual avoidance is STEERING ONLY**, forward-arc, bounded by the same
  turn-rate clamp as everything else, and OFF during the charge's school
  and the drop's rush (authored choreography, not crowds to fix).
- **`camera_follow` is a WINDOW, not a world remap** — at `camera_follow=0`
  the world→screen mapping is the identity. It is NO LONGER proven
  byte-identical to the pre-camera render (the wake rework changed the
  render at knob zero, so `BASELINE_REF` moved forward); `scripts/
  check_fish_camera.py` §1 now asserts two narrower things: **1a** the
  window origin never leaves zero across the whole arc (exact, against
  `BASELINE_REF`), and **1b** ordinary-swimming KINEMATICS — motion, not
  rendered pixels — match a SEPARATE pinned ref, `THRUST_BASELINE_REF`, at
  the thrust dial's neutral setting (`min_drift_speed=1,
  stroke_speed_cap=0`). Pin a NEW reference constant when a mechanic
  changes what a claim compares, never let a moving `master` ref silently
  retire the proof to a skip.
- **A pulse/thrust config disagreement between the effect's own docstring
  math and the shipped defaults is the class of bug to watch for** — the
  2026-09-17 mean-speed regression is the cautionary tale; re-derive, don't
  eyeball.
- **`p_nocap`/school/rush exemptions are scoped**, same shape as
  blackhole's — don't widen without a fresh ask.

## Sonic reach

The "Fish Swim Burst" flare kind IS Sonic-editable via `set_flare_kind`
(`trigger_offset_ms`, `hold_ms`, `params`, `gain` are all omit-means-keep)
— this is the one fish control Sonic can reach directly, because it's a
FlareKind, not a raw effect param. **`set_flare_kind` looks kinds up BY
NAME: pass `name="Fish Swim Burst"`, never `name="swim_burst"`** — the
latter is the effect param, and naming it would CREATE a duplicate kind
instead of editing the existing one. Every other param here follows the
usual rule: no direct edit, only through an attached FlareKind.

## Executable proofs

`scripts/check_fish.py`, `check_fish_avoidance.py`, `check_fish_lunge.py`,
`check_fish_camera.py`, `check_fish_wake.py`, `check_fish_charge_spread.py`,
`check_fish_burst_bounds.py`, `check_fish_disperse.py`,
`tests/test_fish.py`, `test_fish_camera.py`, `test_fish_disperse.py`.
History: AGENTS.md's "Fish (fx/effects/fish.py) — Orbits' twin" section —
read that in full before a non-trivial change; it documents ~8 more
PR-scoped fixes (lunge envelope, charge spread, camera window centring,
wake replacement) each with its own measured-not-assumed proof.
