---
name: fish-effect
description: >
  fx/effects/fish.py (Matrix, crystal-mapper) — a schooling/steering fish
  effect behind the Fish scene, built as a wholesale copy of Orbits V2's
  bands/kinds but with completely different kinematics. Load before
  touching swim speed, avoidance, the camera window, wake/trail rendering,
  dispersal, the lull's searching keeper / the intensity-scaled drop, the
  swim-burst flare, the big-fish flare, the tail drive or the pond rest —
  every one of these has a shipped invariant that isn't visible from
  reading the code cold.
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

## THE TAIL DRIVE (2026-10-26) — the tail is the engine; `tail_drive = 0`
   is the old motion bit for bit

His ask: "a slow moving fish, or barely moving fish, would show it's tail
swimming and that motion would visually propel the fish ... so we still get
the good reactive movement"; the plan he approved: "tail-driven swimming
with beats as strong as today". The module's TAIL DRIVE block is the
binding statement (`fx/VENDOR.md` #84); what is not visible cold:

- **The music sets an EFFORT, the tail makes the speed.** The effort is
  the target the speed section always computed, WITHOUT the thrust pulse
  (`want_tail`), carried through the same big-fish flee / swim burst /
  solo burst multipliers. `_tail_drive_step` decides stroke or glide,
  eases the tail toward the stroke that effort asks for, then pushes with
  the tail's CURRENT motion (thrust `K (A f)^2 2cos^2(tail tip)`, drag
  `d v^2 + l v`, `K flap_rate^2 = d + l`). `_tail_drive_flap` draws exactly
  that A and f: what is drawn IS what pushes.
- **The escape hatch is structural**: at `tail_drive = 0` neither method
  is entered (`want_tail` is None), so nothing it computes reaches a fish;
  `scripts/check_fish_tail_drive.py` §1 proves kinematics AND frames bit
  for bit against the pinned `TAIL_BASELINE_REF` over two real-audio
  arcs. Values between 0 and 1 blend the speed and the drawn flap; the
  thrust dial above fades out as it rises. **A proof that compares fish
  motion against a pinned pre-change module must hold `tail_drive = 0`**
  (the default, so only a config copied from his live music Fish entry,
  which the scene script turns on, needs it said).
- **Burst and glide only engages below `glide_below`** (an effort, x
  cruise). The ordinary target never asks for less than cruise, so in
  ordinary music the tail strokes continuously and the visible change is
  the speed rising and falling with each stroke, the tail moving first
  at a beat. The pond rest (below) is what asks for less.
- **The QUICK MOMENTS stay quick** (`TAIL_STIFF_MAX`'s block). The swim
  burst, a solo burst and a big-fish flee each shorten the old speed ease
  (`BURST_SPEED_TAU`, `SOLO_SPEED_TAU`, `BIG_FLEE_TAU`); the water's own
  response, 1/(2 d v + l), is far slower near cruise. Without this the
  dash covered a third less in its 300 ms, started 50 ms late, and one fish
  failed to get out of the big fish's way. While a moment has shortened the
  ease, thrust and drag scale together to answer within it (same speed),
  and the push is the stroke's cycle mean (the next mid-sweep can be
  ~50 ms away). A beat does not shorten the ease.
- **Scope = the thrust pulse's**: mode < 2, not cap-exempt, no school. The
  beat envelope `p_tkick` arms where the lunge arms and forces a stroke;
  it decays for every fish so one rejoining after a school carries none —
  `_decay_tail_kick` runs even on a frame with no eligible fish at all (a
  formed school, i.e. the whole charge/lull/drop), via the standalone call
  beside `tail_w`, or a kick armed just before a charge would freeze and
  force an extra stroke on the fish that resumes ordinary swimming after
  the drop. No random numbers are drawn, so the shared generator is
  untouched.
- **Registered first guesses**: `glide_drag` (d + l, 1.6/s; cruise is held
  at any value) and `glide_below` (0.75); help topic `fish-tail-drive`.
  On for the music Fish scene only (the fish-scene skill's script).

## THE POND REST (2026-10-26) — they almost stop when the music goes
   quiet; `quiet_rest = 0` is the old motion bit for bit

His ask: "at really low music levels, like when it's almost or completely
quiet, the fish should almost come to a rest, with very sporadic short
motions, like real fish in a pond"; the plan he approved: "a quiet pond
rest with occasional darts", music Fish only, "'quiet' means the music's
own level". The module's POND REST block is the binding statement
(`fx/VENDOR.md` #85); what is not visible cold:

- **It hears `volume()`, never the band powers.** The melbank auto-gains
  (it divides by a slow max), so `lows_power` reads a quiet passage as
  loud within ~2 s. `volume()` is 1 + dB SPL / 100 (`fx/effects/audio.py`
  `pre_process_audio`, filtered at alpha 0.99) and is CLIPPED to [0, 1] on
  read: a fresh analysis filter starts at -90 dB, so a fresh process's
  first read is -0.9. His house volume (`snap_volume`) never reaches the
  capture client, so it does not calm them.
- **The detector is `rest_step`, a module function** (the library check
  runs the same one): a slow average (1.2 s) the rest ENTERS on, a fast one
  (0.12 s) that can only WAKE it, a smoothstep from `rest_calm_level` 0.66
  (-34 dB) to `rest_full_level` 0.52 (-48 dB), in over 2.2 s, out over
  0.15 s. No callback for `REST_SILENCE_S` (1 s) reads 0: the audio hub's
  own pause. An effect that has NEVER heard anything reads loud (0.8), so
  a stub with no `volume()` (every older check's) never rests.
- **The startle**: a spike strong enough to lunge cuts the level by its
  own size in the same frame, and the lunge's share of the target is never
  scaled (`target / (1 + lunge) * (keep + lunge)`), so the next song's
  first hit is a full burst (above 2x cruise 0.13-0.18 s after Dopamine's
  opening hit, measured).
- **A MOMENT's share is never rested either**: `_pond_rest_step` runs
  AFTER the big-fish flee, the swim burst and the solo dash have multiplied
  the target (`ordinary` is captured before them) and rests only the
  ordinary share (`ordinary / (1 + lunge) * (keep + lunge) + (target -
  ordinary)`); the brake skips a fish a moment drives too. Run before them,
  the rest squashed a swim burst at full rest to a 0.05 cruise-second dash
  (now 0.55; awake 0.81) and left resting fish in the big fish's path (219
  and 158 frames of a middle on it, now 0) — `check_fish_pond_rest.py` §4
  keeps that old rule as its red control. **A new speed moment must
  multiply the target BETWEEN the capture and the call**, or the rest will
  squash it.
- **The beat TRACKER's ticks are scaled by (1 - rest).** `bpm_beat_now()`
  predicts ticks with no drums at all; without the gate a drumless quiet
  passage twitches to the tempo grid. A real onset arrives through the
  impulse spike, which is never gated.
- **With the tail drive** the fins brake (`REST_BRAKE`), except on a fish
  a dart is pushing (`_dart_thrust`), and the low effort bursts and glides.
- **The darts**: `p_dart` is the push clock (> 0 pushing; it runs on BELOW
  0 through the glide while the turn continues, and is reset to 0 when
  the steer lets go), `p_dhd` the heading (NaN = no dart), `p_dnext` the
  next due time (effect clock). **A dart begins where `p_dart` turns
  POSITIVE** — a detector keyed on "it rose" double-counts every reset
  from below 0 (found building the check). A dart turns only as far as it
  travels (`omega_max = speed / turn_radius_px`), so the steer stays on
  through the glide until the fish faces the dart's heading (`DART_FACE`)
  or `DART_STEER_S` passes: measured a 0.28 s push to 0.68x cruise, 0.78
  body lengths, 38 degrees median against aims of 29-115. Do not get more
  turn by turning tighter — the turn radius is the shipped arc invariant;
  a dart aimed into the wall turns away from its aim, the wall winning.
- **Their own generator**: `self._rng.spawn(1)[0]`, made on the first
  dart step. A spawned child never draws from or advances the shared
  stream, and a seeded test reproduces the darts; in the room
  (`default_rng()`) each instance darts its own way.
- **Never during a moment** (`_rest_held`): a charge, lull or drop, a
  formed school, a rush (any mode 3), or a live crossfade on either side
  (`particle_handoff.transition_progress`) or a transition program running
  into it. Held = level 0 and every dart ends (`_end_darts`). The
  held-transition draw paths (`_fade_only`, `_draw_collapse`) zero
  `_rest_level` too, since nothing swims there.
- **The escape hatch is structural**: at 0, `_pond_rest_step` is never
  entered and `volume()` is never read; `scripts/check_fish_pond_rest.py`
  §1 proves frames AND kinematics bit for bit against the pinned
  `REST_BASELINE_REF` over both real-audio arcs at `tail_drive` 0 and 1,
  fed deep quiet. **A proof comparing fish motion against a pinned
  pre-change module, with an audio stub that HAS `volume()`, must hold
  `quiet_rest = 0`.** Switching it off live forgets the level and any dart
  in flight (`config_updated`; the arrays do not exist yet during
  `super().__init__`, hence its `hasattr`).
- **His library** (`tests/fixtures/fish_swim/library_volume.npz`, 126 of
  his songs' `volume()` per frame, re-recorded by the check's
  `--write-fixtures`): at rest 0.58% of song time, inside the music in 2
  songs (quiet stretches of Efecto and Hey Nineteen). The between-songs
  fixtures (Contra's outro, Dopamine's opening) carry `vol` beside the
  lows and beats; record one song per interpreter.
- **Registered first guesses**: `quiet_rest` (0..1), `rest_calm_level`,
  `rest_full_level`, `dart_every_s` (mean, 9 s); help topic
  `fish-pond-rest`. On for the music Fish scene only (the fish-scene
  skill's script); House Fish would rest almost all the time.

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

## The WAKE's colour and blend (2026-10-26) — his option A reversed the
   2026-08-28 colour rule

His report: "the fish scene gains a lot of white color, especially in
rainbow effects when there is a lot going on. My guess is that the
trails/ripples overlap and add to white." Measured (data/fish-swim-plan,
part 1): the 2026-08-28 rule ("a different color from the fish if there is
a gradient") put the OPPOSITE colour under every fish on a rainbow, and the
final mix ADDED the wake onto the bodies — complementary light summed is
white, worst in the busiest music, since rainbow sets are only picked above
`rainbow_select_limit` 0.9. His answer, verbatim: "I approve option A for
the wake." The module's WAKE COLOUR block is the binding statement
(`fx/VENDOR.md` #83); what is not visible cold:

- **Two settings, both registered** (help topic `fish-wake-colour`):
  `wake_hue` (`own` default / `neighbour` = an eighth along the gradient /
  `opposite` = the 2026-08-28 half turn) is read by `_wake_palette`
  through `WAKE_HUE_OFFSETS`; a SOLID palette ignores it and keeps the
  fish's own colour at `WAKE_SOLID_DIM`. `wake_blend` (`lighten` default /
  `under` / `add`) is read by `_composite`, the ONE writer of
  `self.matrix`: the draw, `_fade_only` and `_draw_collapse` all call it,
  each proven by driving a real swum fish through that exact path and
  checking what reached `_composite` against the blend's own formula
  (`tests/test_fish_wake_blend.py`, not an AST walk). A new compositing
  path calls `_composite`, never paints the matrix itself. The help topic
  is checked the same way — `scripts/check_fish_help_topics.mjs`
  parses the real `helpContent.ts` tree, not a substring match.
- **The WATER is the wake plus the big fish**, summed, then through
  `_hue_clip` (an over-bright pixel scaled down whole) before it meets
  the bodies. Lighten is per channel: it never makes a channel brighter
  than the brighter layer, and a fish over its own-colour wake shows
  exactly the fish. It does NOT stop two different hues meeting per
  channel — the own colour is what removes most of the white (own + add
  alone measured 12.5%; opposite + lighten alone 25.7%).
- **`opposite` + `add` is the pre-2026-10-26 render bit for bit**, proven
  over two real-audio arcs against the pinned `WAKE_BASELINE_REF`
  (`scripts/check_fish_wake_blend.py`). **A proof that compares fish
  PIXELS against a pinned pre-change module must hold the wake there**,
  the way the wall's proofs hold `wall_lookahead = 0`: today
  `test_fish_big_fish.py` (PR 381), `test_fish_big_fish_avoid.py`'s
  `_frames`, `test_fish_lull_searcher.py`'s bit-for-bit test and
  `tests/shoal_tier_b_driver.py`'s `HOLD` do. A pinned KINEMATICS proof
  needs nothing — the wake never steers a fish.
- **Measured** (his crystal's 976 real cells, his real audio,
  `tests/fixtures/fish_wake/`): busy rainbow arc white light 27.6% ->
  12.2%, near-white cells in the drop (p90) 30 -> 4, 90.6% of today's lit
  cells; calm arc 26.5% -> 8.0%; the mix costs +0.004 ms a frame.
  `_channel_peak` exists because numpy's `max(axis=-1)` over a 3-wide axis
  cost ~0.1 ms by itself.
- **Re-recording the fixtures** (`--write-fixtures`) runs one song per
  interpreter: the analysis carries process-wide state, and a song
  analysed after another does not reproduce itself.
- **Deploy**: both keys are new, so no stored config carries them and a
  restarted live Fish instance fills them from the schema defaults — the
  `trim_fish_trails_25.py` problem (a changed default never reaches a
  stored key) does not arise here. House Fish gets the change too; its
  wake is faint, so it moves less (15.5% -> 13.4% on a rainbow set).

## Fish never fade — they DISPERSE (steer off-panel), full brightness the
   whole way, on a DEADLINE

Every exit (population trim, lull, rush settle, an outgoing crossfade with
no adopting effect) is ONE mode: DISPERSING (`p_mode == 4`) — full
brightness, steered out under the ordinary turn-rate clamp, retired only
once the WHOLE body clears the panel. Speed is DERIVED every frame from
remaining distance-to-clear (never a tuned speed) — this is what lets a
900ms lull and a 6s one both work. Mode 2 (linear fade) now belongs ONLY
to the drop's ejecta. The lull's own duration is `phase_progress`'s real
gap to its own drop under the PHASE PARTNER rule (`spectra/services/
phase_partner.py`), else the next trigger with no drop ahead — see
`_lull_step`'s own docstring in `fish.py`.

## The lull leaves ONE fish that SEARCHES (2026-10-08) — and the drop
   follows the music. This reversed his 2026-08-28 "no lone fish" clock

His words: "have all the fish leave over time except for one, so one is
left at the half way mark. then have that last fish move slowly and look
like it's searching ... then on the drop, all the missing fish come back in
the rush we currently have. also, make the length of the drop and how fast
the fish swirl depend on the inensity of the music". The module's
2026-10-08 LULL block is the binding statement; six things not visible
cold:

- **The lull is TOLD how many to keep** through the LULL HAND-OFF HOOK
  (`fx/effects/lull_handoff.py`, `fish` is its first member): `lull_keep`
  (default 1), `lull_next`, `lull_s` on every lull arm, `drop_intensity` on
  every drop arm. **`lull_keep = 0` is his 2026-08-28 clock bit for bit**
  (gone by a third, dark after two thirds) — proven against the pinned
  pre-change module. Any OTHER proof that compares against a pinned
  pre-2026-10-08 fish through a lull must tell it `lull_keep = 0`
  (`scripts/check_fish_wall.py::HOLD_LULL` is the shape), the
  `wall_lookahead = 0` rule one mechanism over.
- **Keepers are mode 5**: never counted by the population, never swirled,
  never retired, never followed by the window. The `keep` fish nearest the
  centre of view are chosen at the lull's edge; a lull with fewer fish
  calls the shortfall in from off-panel (fading up like any arrival). Every
  other fish leaks out before the HALF (`KEEP_LEAK_*`, `KEEP_EXIT_BY`), a
  backstop at the half retires anything that is not a keeper. The half is
  SECONDS (`lull_s / 2`) when told, progress 0.5 when not.
- **The search** (`_keep_targets`/`_start_leg`): a short first leg to the
  side it already faces (`SEARCH_LEG_SHARE` of the time left), a PAUSE
  (hover at `SEARCH_PAUSE_X`, head swinging `SEARCH_LOOK_SWING` — drawing
  only, the travel heading never moves), then a leg to the other side, to
  `search_reach` of the pond, at `search_speed` x cruise. About-faces are
  arcs (the turn clamp); `KEEP_LEVEL_W` pulls a keeper back to mid-height so
  an about-face arcs away from the nearer top/bottom wall — keepers are kept
  OFF the wall glance on purpose (its authority took a turning keeper over
  and ran it along the wall).
- **Keepers RIDE THE WINDOW**: the window eases home after the charge at up
  to 1.4x cruise, faster than a searching fish — so keepers are shifted by
  the window's own step and hold their place on screen (the water slides
  under them). Without it a keeper was dragged off the panel.
- **Several keepers** (`lull_keep` N — 3 is what a Fireworks drop asks for)
  hold a loose ROW, spaced `KEEP_SPACING_BODIES` (wider,
  `KEEP_SPACING_NEXT_BODIES`, when `lull_next` names another effect, so an
  adopter gets distinct origins — `_handoff_snapshot` carries exactly the
  keepers), with a separation steer (`KEEP_SEP_W`) so an about-face cannot
  fold the row up. They rejoin the population (mode 0) on the frame the
  lull ends, however it ends.
- **The scaled drop**: `lull_handoff.drop_scale` (0.75 = the old drop
  exactly, 1.0 = 1.2x, quiet songs down to `drop_scale_min`) multiplies the
  settle horizon (the swirl follows), the boost and the rush's entry speed
  (by half). Untold (`drop_intensity` 0) = the fixed constants, expression
  for expression; the self-reset forgets a told intensity.

`search_speed`/`search_pause_s`/`search_reach`/`drop_scale_min` are
registered (help topic `fish-lull-search`) — FIRST GUESSES, pending his eye.

**THE KEEPERS MELD (2026-10-08, drop-scene-variety phase 3)**: a lull told
`lull_next` an effect other than fish flags its keepers in
`_handoff_snapshot` (`"keepers"` = mode 5), and Fireworks explodes each one
where it stands on the drop-led cut (`fx/effects/fireworks.py`'s KEEPERS
MELD, `fx/VENDOR.md` #64). Untold or told fish: no flag, every successor
adopts as before. Proof: `tests/test_fireworks_melds.py`.

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

## The WALL: a fish swims right up and turns in ALONGSIDE it — and
   `wall_lookahead = 0` is the old pond edge, bit for bit

Two rounds of his words. 2026-10-06: "the fish don't interact with the
'wall' naturally. Have them 'anticipate' the wall and start turning away."
2026-10-07, on the first build (PR 361): "The fish now get stuck in the
middle. I still want them to go right up to the edge of the wall, but i
want them to start turning so their bodies sides touch the walls, more than
their heads ... It's okay for light to bleed off the fixture, I'm more
interested in a natural look." The WALL block at the top of `fish.py` is
the binding statement; the traps:

- **Do not go back to "turn away" / "keep clear water ahead".** PR 361 kept
  a whole look-ahead + 25% of free water in front of every fish; for a
  21 px House Fish on a 37 px panel that is most of the panel, so the shoal
  balled up in the middle (middles over ~23% of the lit cells, flank on the
  wall 0% of the time). The glance lands the fish ALONGSIDE the wall: it
  turns on the one circular arc `R = f * cot(theta/2)` that ends parallel
  to the wall with its middle WALL_GRAZE (0.3) half-widths from the edge,
  starts that turn the frame R shrinks to the arc it wants
  (`_glance_radius`), then peels WALL_PEEL (12°) further and lets go.
- **The arc it wants is the nose rule**: the tightest that keeps the
  nose's light no deeper past the wall than its flank's ends up
  (`R_nose`, ~1.3 body lengths for a steep approach on body_aspect 3),
  never tighter than the turn radius or `wall_lookahead` seconds of its
  own swimming, divided by `wall_turn_strength`.
- **The honest limit, measured and stated in the PR**: a fish with a
  straight-drawn head cannot make its SIDE arrive before its nose from a
  steep approach to an edge shorter than its arc — and on the crystal the
  top edge is 34 px against a ~27 px House Fish arc, so steep approaches
  land at corners nose-first. Three alternatives were built and measured
  and are NOT shipped: a receding-horizon arc planner (constant-curvature
  rollouts are too conservative on this hex — fish turned early, back in
  the middle), a nose barrier (`db/ds >= -sqrt(2b/R)` on the nose's own
  distance — every contact side-on but the flank reached the wall only
  ~4% of the time) and a glance + barrier floor (same). He weighted
  reach and "natural" over a strict nose rule ("bleed is OK"), so the
  shipped balance is (his House Fish, `check_fish_wall.py` §2): flank on
  the wall ~57%, body alongside in ~3/4 of contacts, ~3% of time at the
  tightest turn (old edge ~14%), panel covered ~83% (PR 361: ~23%).
- **Corners are rounded** (`_landing_field`: the inset silhouette opened by
  a disc of the fish's glance radius, never past WALL_ROUND_FIT of the
  room): the 90° tips are tighter than a long fish's arc, and steered into
  one its nose leaves the panel. Cached by (wall, inset, radius) — the
  music Fish's blob_size is bound to trigger intensity, so a few fields get
  built per song (a few ms each).
- **The wall is READ, not assumed**: `_real_cell_mask` walks the virtual's
  own segments (a pixel on a `gap-` dummy, by `fx.utils.is_gap_device`, is
  dark) through Twod's own flip/mirror/rotate; `_silhouette` fills the
  lattice holes. `fx.headless.write_headless_config(real_mask=...)` builds
  his crystal's shape for any rig — a plain rectangle never shows a
  hex-corner bug.
- **The pond (`roam_scale`) still bounds the MIDDLE** and is glanced the
  same way. His music Fish scene stores roam_scale 0.75 (his own value,
  set in August) — its fish glance along an invisible ellipse three
  quarters of the panel across and never reach the real edge; raising it
  is his call, never a silent migration.
- **A crowd near the wall**: while the glance has authority, a neighbour's
  swerve is still applied (WALL_DODGE x) but only TOWARD THE WATER —
  allowed both ways, his House Fish were shoved up to 34 px off the panel.
  A fish that stops swimming (disperses, rushes, ejects) drops the wall's
  hold the same frame (`_wall_release`) or the crossfade scatter misses
  its deadline.
- **Scope: ordinary swimming only.** The charge's school keeps the old
  pond-edge steer; the rush, ejecta and dispersing fish are unbounded.
- **Proofs that hold an OTHER mechanism must hold the wall at its hatch**
  (`wall_lookahead = 0`): `check_fish_camera.py` §1b / `test_fish_camera.py`,
  `test_fish.py`'s clump, burst-brake and avoidance-mechanism tests, and
  `check_fish_disperse.py` §2b all do.
- **Measuring "side vs head"**: use the light, not the points — the nose
  splat is 0.45 half-widths, the flank 1. A nose POINT at the edge already
  lights the last cells. `scripts/check_fish_wall.py` measures against a
  sub-pixel edge it computes itself (upsampled EDT of the lit area), never
  the effect's own field.

## The SOLO BURST — one random fish dashes, now and then; default OFF

His ask: "In house fish scene, give individual ones an occasional burst of
speed." Not the Swim Burst flare (whole shoal, on a trigger). `solo_burst_
rate` (per MINUTE across the shoal, a Poisson clock), `solo_burst_speed`
(x its ordinary speed), `solo_burst_time` (hold, s); attack/hold/ease
envelope `p_sb`/`p_sb_t`, stroke rate up with it. **The schema default
rate is 0** — only House Fish turns it on, via its own params
(`scripts/add_house_fish_solo_burst.py` owns the values; the house seeder
imports them). Only an ordinary swimmer with the wall at most faintly in
its look-ahead is picked; a due burst waits for one; none during a
charge/lull/drop or an outgoing crossfade; a burst gives up its hold once
the wall presses hard.

## The BIG FISH flare (2026-10-08) — an ordinary fish, bigger, behind

His words: "a really large fish swims directly across the screen, in the
background of the others, and at 60% brightness (tuneable) ... The speed it
goes at is dependant on intensity. the color should be the 120 to 180
degree rotation of the central color of the scene". On the first build
(PR 381, a bespoke silhouette with a forked tail fin): "the fish looks all
wrong. it should be the same as the other fish in the effect, just bigger,
in the background, and dimmer, with a dim but large ripple". The BIG FISH
block at the top of `fish.py` is the binding statement; what is not
visible cold:

- **It is NOT a particle, but its BODY IS AN ORDINARY FISH.** No SoA slot,
  no steering, no wall, no camera: `self._big` is a short list of dicts
  swimming straight across in SCREEN space. But it is drawn through the
  ordinary fish's own `_spine_wave` / `_splat_spines` (factored out of
  `_draw_bodies` — `test_without_a_poke_every_frame_is_pr381s_exactly`
  holds ordinary frames bit for bit). **Do not bring back a bespoke
  silhouette — that is what he rejected.**
- **A literal scale-up beads.** Six soft splats blur into one body at an
  ordinary fish's few pixels; magnified five times they are six beads, and
  `_splat_many`'s +0.5 px reach does not scale. So `_big_fish_bodies`
  scales each splat's WHOLE reach (size + 0.5) by length / ordinary length
  and resamples the SAME spine (profile, throw, wave) every
  BIG_FISH_NODE_PX, each node weighted spacing / reach so the level along
  it is an ordinary fish's. `test_its_body_is_one_continuous_fish_not_
  beads` goes red at six nodes.
- **Its motion is read in BODY LENGTHS A SECOND** against an ordinary fish
  at cruise (`_big_fish_motion`): the ordinary flap rules then give a big
  slow fish a slow, gentle stroke, exactly what an ordinary fish crossing
  at that many body lengths a second would do. It also carries the
  ordinary audio brightness and size swell (no jiggle) and the ordinary
  `trail_decay` smear (its own buffer, `self._big_trail`).
- **"Background"**: its layer is hidden wherever the ordinary fish's body
  layer is lit (fully at `BIG_FISH_OCCLUDE_AT`), then added — so it must
  be composited at EVERY path that writes `self.matrix` (the main draw,
  `_fade_only`, `_draw_collapse`), each calling it exactly once a frame,
  and BEFORE `self.wake` is composited (it lays its wake there). A new
  compositing path needs the same call or a big fish freezes there.
- **"60%" is 60% of an ordinary fish of its colour**: drawn at the
  ordinary level, clipped to 255 KEEPING ITS COLOUR (so the 120-180 degree
  rule survives the bright middle), then `big_fish_brightness`.
- **Its wake** is the ordinary deposit rule (tail point, sized off body
  length and tail throw, "stronger when faster", pulsing with the tail) at
  its size, in its own colour, into the shared wake buffer, times the
  scene's `ripple_amount`. Large because the rule scales with the body;
  dim because "faster" is body lengths a second — measured peak about a
  fifth of its body, a quarter of the ordinary fish's wakes.
  `big_fish_ripple` (1 = that rule, 0 = none) and `big_fish_ripple_size`
  (1 = in proportion) tune it.
- **Colour is re-read every frame** from the gradient's centre (0.5,
  unrolled by `gradient_spin`), turned by `big_fish_hue_degrees` (120 at
  ≤0.2, 180 at ≥0.5, linear) in a coin-flipped direction. Hue only — an
  achromatic centre stays white/grey.
- **Speed is linear in SPEED, not time**: `big_fish_cross_s` interpolates
  1/T between `big_fish_cross_slow_s` (intensity 0) and `_fast_s`.
- **The poke** `big_fish` (the fire's intensity, floored at
  `BIG_FISH_POKE_FLOOR` so 0 still edges) is unregistered and self-resets,
  the fireworks `burst_rockets` shape; `BIG_FISH_MAX` (3) cross at once.
- **A test comparing two runs must give each its own virtual id** — the
  fish store a particle-handoff snapshot under it on shutdown, and a
  second run on the same id adopts the first run's shoal (`_cross`'s
  `_RUNS` counter). The store is PROCESS-WIDE, so the id must be unique
  across test FILES too: `test_fish_big_fish.py`'s bare `m3` once collided
  with `test_fish_camera.py`'s `m3` and failed its seed-3 run whenever the
  two files ran in one session — prefix ids with the file's own name.

## THE OTHER FISH AVOID IT (phase 2, 2026-10-09) — the wall still wins

His approval of the look: "Big fish looks right: build step 2 - the other
fish steer around the big fish while it crosses." The BIG_AVOID block
(beside `BIG_AVOID_W`) is the binding statement; what is not visible cold:

- **Its "body" is the LIT CORE, not the splat reach.** A splat's light
  falls off linearly to its reach; measured on the big fish's own
  cross-section, it is a quarter lit at `BIG_AVOID_CORE` (0.7) of it. With
  the full reach (±11.7 px at default size) the clearance needed is ~16 px
  either side of its line — more than the panel has, so no steering could
  meet it. The same core rule sizes the ordinary fish; the margin
  (`big_fish_avoid_margin`, px) goes on top.
- **The way out is a SEARCH, not "turn off its line".** His crystal is a
  hexagon: at its two points the big fish fills the whole lit height, so a
  vertical escape there drives a fish into the wall. `_big_fish_threat`
  scores spots around each threatened fish (inside the lit panel) by
  clearance from the big fish's MOVING body from arrival on AND along the
  way there; it was a rule-based side choice first and that measured
  worse at every step.
- **The pond gives way, the wall does not.** His music Fish's pond
  (roam_scale 0.75) is ~27 px tall: it cannot hold a fish beside a centred
  big fish, so a threatened fish glances off the lit panel only
  (`_wall_landing(free=)`, `self._pond_free` during `_wall_steer`). The
  wall keeps any fish it is LATE turning back from a wall it is heading
  into (`w_toward & w_urg >= WALL_LATE`); handing those to the threat too
  measured fish up to 4-13 px past the lit edge. Kept, that is 0.
- **A startled fish turns hard and the right way**: `BIG_TURN_BOOST`
  multiplies the turn gain (proportional TURN_GAIN 3/s took ~0.7 s for a
  120° dodge its turn circle allows in ~0.3 s), still clipped to the turn
  circle; a near-U-turn swings AWAY from the big fish's line, never the
  shorter way through it.
- **The honest limit**: at the hexagon's points a fish caught by the wall
  can brush it as it passes. Measured (`scripts/check_fish_big_fish_
  avoid.py`, 6 seeds): fish middles on its lit body in the middle columns
  103 → 0 (quiet) and 139 → 0 (loud); overlap pixels 4898 → ~2400 and
  3413 → ~650; past the lit edge 0 before and after; the turn circle never
  exceeded. Do not "fix" the residue by relaxing the wall.
- **Scope**: ordinary swimmers (the charge's school included) and the
  lull's keepers; never the rush, ejecta or dispersing fish. With no big
  fish, nothing runs — bit for bit the pre-avoidance module
  (`tests/test_fish_big_fish_avoid.py`, music / keepers-for-fireworks /
  House Fish with solo bursts), and `big_fish_avoid` 0 is the step-1
  crossing bit for bit.

## A `"sauron"` hand-off snapshot is treated exactly like `"eye"`

Sauron (fx/effects/sauron.py, 2026-10-10) is a copy of Eye with Eye's
hand-off choreography verbatim, so wherever this effect special-cases an
incoming `"eye"` snapshot it names `"sauron"` alongside it (`TRANSITION_ADOPTERS`: an incoming Sauron adopts the fish, so they do not disperse). Keep
the two together: a new `"eye"` special case here needs `"sauron"` too
(sauron-effect skill).

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

## The drop Shockwave and the breath-hold (2026-10-11, transitions-drop plan phase 1)

This effect is a member of `fx.device_model.DROP_SHOCK_EFFECTS`. Its drop
gets the shared Shockwave painted by `Twod.render` AFTER its own `draw()`
(`fx/effects/phase_grammar.py` is the binding statement): a rim bloom, ONE
wavefront born on the home ring (`horizon_scale`), centred on the window, debris (curving back to the home ring) and a wall splash, all in the
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
**NO BREATH-HOLD on the Fish** (2026-10-12, the Admiral: "I want orbits and
fish to specifically not go dark completely on the crystal or the strips"):
`BREATH_HOLD = False` on the class, and SpotFX no longer tells it the
breath keys (`fx.device_model.BREATH_HOLD_EFFECTS` leaves the Fish out), so
the lull's searcher swims straight through to the drop — no short black
before it. The schema still carries the two keys (a told one is a no-op).
The Fish scene's strip (`fireworks1d`) keeps its own 12% ember and is
unchanged. Help topics `drop-shockwave`, `lull-dark-cap` (the breath-hold is folded into it); proof
`scripts/check_drop_shockwave.py` (`breath_ok`) / `tests/test_phase_grammar.py`.

WHETHER A DROP PAINTS IT AT ALL (2026-10-12, his "toggled per scene, as
well as globally, as well as a global setting for minimum energy"): the drop
arm also tells this effect `drop_shock_on` — the room's `drop_shock_enabled`,
the showing scene's own `drop_shock_enabled`, and the top bar's Energy
(`bridge.intensity()`) against the room's `drop_shock_min_energy` (0.7),
decided by `phase_grammar.shock_allowed`. False = no painter at all: the
frame is this effect's own drop byte for byte (no reveal hold-back either).
Untold reads True. It is an overlay, so nothing in this effect's own drop
changes; `drop_shock` (the per-effect strength) is a separate knob. Help
`drop-shockwave-switches`; proof `tests/test_drop_shock_switches.py`.

## Thematic transitions + the Shoaling adoption fix (2026-10-11)

- **THE ADOPTION FIX**: the generic (cross-type) adopt keeps a predecessor's
  inherited heading and speed (`snap["vx"]`/`["vy"]`, clamped to 0.2-4x
  cruise) instead of re-heading every fish to the tangent of where it sat —
  that re-heading was a new direction and speed on the first real frame. A
  snapshot with no velocity keeps the tangent, as before.
- Fish receives the Black Hole's ERUPTION: `_formation_points()` (every
  ordinary fish's screen position, read live) — the ejecta implode onto
  swimming fish. Fish feeds an Infall: `_handoff_snapshot` carries `vx`/`vy`
  (heading x speed) and `gesture: "swim"`.
`fx/effects/transition_program.py`'s docstring is the binding statement; `tests/test_transition_programs.py` measures it on the real pipeline.

## Sonic reach

The "Fish Swim Burst" flare kind is Sonic-editable via `set_flare_kind`
(`trigger_offset_ms`, `hold_ms`, `params`, `gain` are all omit-means-keep).
**`set_flare_kind` looks kinds up BY NAME: pass `name="Fish Swim Burst"`,
never `name="swim_burst"`** — the latter is the effect param, and naming it
would CREATE a duplicate kind instead of editing the existing one.

Every REGISTERED fish param (`config/effect_params.json`) — the wall's
`wall_lookahead`/`wall_turn_strength` (the glance's speed widening and its
arc divisor) and the solo burst's three included —
— and the lull search's `search_speed`/`search_pause_s`/`search_reach`
and the scaled drop's `drop_scale_min` — and the big fish's
`big_fish_brightness`/`big_fish_size`/`big_fish_cross_slow_s`/
`big_fish_cross_fast_s`/`big_fish_ripple`/`big_fish_ripple_size` and the
avoidance's `big_fish_avoid`/`big_fish_avoid_margin` — and the wake's
`wake_hue`/`wake_blend` (enums, refused outside their options) —
is reachable per scene entry through `get_scene_entry_params` /
`set_scene_entry_param` (e.g. scene "House Fish", target "Matrix"),
validated against the registry's own range. A new fish param is only
Sonic-reachable once it is registered there.

## Executable proofs

`scripts/check_fish.py`, `check_fish_avoidance.py`, `check_fish_lunge.py`,
`check_fish_camera.py`, `check_fish_wake.py`, `check_fish_charge_spread.py`,
`check_fish_burst_bounds.py`, `check_fish_disperse.py`,
`check_fish_wake_blend.py` (the wake's colour and blend on two real-audio
arcs, with `test_fish_wake_blend.py`),
`check_fish_help_topics.mjs` (every help topic a fish param links is a
real `helpContent.ts` entry, not a substring match),
`check_fish_pond_rest.py` (the pond rest's acceptance list on his real
audio and library, with `test_fish_pond_rest.py`),
`check_fish_tail_drive.py` (the tail drive's acceptance list, with
`test_fish_tail_drive.py` — its own guards section re-runs
`check_fish_disperse.py`'s searching-lull dispersal measurement at
`tail_drive=1` too, alongside the wall, repeated bursts, mutual avoidance
and big-fish avoidance),
`check_fish_wall.py` (`--gifs DIR` writes old-edge / PR 361 / new GIFs and
track plots on his real crystal shape), `tests/test_fish.py`, `test_fish_camera.py`,
`test_fish_disperse.py`, `test_fish_wall.py`,
`test_fish_lull_searcher.py` (the searching lull, keep N, the scaled drop,
and keep 0 + an untold drop bit for bit against the pinned pre-change
module), `test_lull_handoff.py` (the hook); `scripts/
render_fish_lull_searcher.py` writes the before/after GIFs.
`test_fish_big_fish.py` (the big fish: both curves, crossing time, colour,
60% of the same fish, the ordinary body and no beads, its flap and wake,
behind the others, the lull dark, ordinary frames bit for bit against PR
381, the engine poke, the preview ruler, the migration script);
`scripts/render_fish_big_fish.py --out DIR` writes PR 381 | rework GIFs.
`test_fish_big_fish_avoid.py` (the other fish avoiding it, and nothing
changed without one); `scripts/check_fish_big_fish_avoid.py` measures it
before/after and `--gifs DIR` writes the before | avoiding GIFs.
History: AGENTS.md's "Fish (fx/effects/fish.py) — Orbits' twin" section —
read that in full before a non-trivial change; it documents ~8 more
PR-scoped fixes (lunge envelope, charge spread, camera window centring,
wake replacement) each with its own measured-not-assumed proof.

## Fish does NOT paint a background itself — "Fish ignores overwrite" (2026-10-07) was the Matrix pre-fill

His report that Fish does not obey a colour set's `overwrite` background
mode was true on master and was not in `fish.py`: `Twod.render()` pre-filled
the canvas with the background in overwrite mode and Fish composes its
bodies/trail/wake ON that canvas (`np.asarray(self.matrix) + body_out`), so
a lit fish carried the full background under it — additive by construction
— and `get_pixels()` then doubled it on every dark pixel. Fixed in `twod.py`
(fx/VENDOR.md #60, the canvas always starts black); nothing in `fish.py`
changed. If a background-mode report lands on this effect again, run
`scripts/check_effect_background_mode.py fish` before reading fish.py —
the probe measures the lit-pixel blue against each mode's own curve.

## Phase 4 transitions (2026-10-11): the PEEL, Shoal Break, Unravel

- **THE PEEL** (`PEEL_S`, `p_peel` SoA, `_peel_age`): a fish adopted from a
  snapshot carrying `om` (an orbit blob's turning rate) turns at that rate and
  eases into its own steering over 0.4 s — the heading RATE is continuous, not
  just the heading — and its backfilled body lies back along that curve, not a
  straight line. Applied after the turn-circle clip (the inherited rate is an
  arc already). A snapshot without `om` adopts exactly as before.
- Fish -> Orbits / Squiggles is SHOAL BREAK (each body shatters into dots that
  implode onto the moving targets); Orbits -> Fish is SHOALING (the real Fish
  adopts the blobs from the first frame — the program leaves the registry
  snapshot, `TAKE_REGISTRY = False`); Squiggles -> Fish is UNRAVEL; Sauron/Eye
  -> Fish is FLAME LICK onto `_formation_points()`.
`fx/effects/transition_cloud.py`'s docstring is the binding statement for phase 4's programs; `tests/test_transition_programs_phase4.py` measures them on the real pipeline.

## THE HOST FRAME: `om` published, born matched (2026-10-17)

The shoal-burst plan (`/home/javi/fleet-spotfx/data/shoal-burst-plan/
report.md`; `fx/effects/transition_cloud.py`'s `HostFormer` is the binding
statement). Fish needed almost nothing new — heading and speed ARE its
state and `PEEL_S` already eases an inherited turn rate into its own
steering, which is why the plan calls its `_adopt_handoff` the existence
proof for the whole design. Three things:

- **`p_om` is no longer thrown away.** Fish computed `omega` every frame and
  discarded it; it is now stored at the heading integration and PUBLISHED as
  the hand-off snapshot's `om`. That is what a cloud leaving a TURNING fish
  continues on (before this it flew dead straight out of a turn — measured
  0 degrees of cloud turn against 43 degrees of parent turn), and what a
  born orbit/fish keeps turning at.
- **`_program_birth(snap)` / `_program_hosts(pids)`** — one fish per
  released object, at its position, on its heading and speed, peeling at its
  inherited rate, carrying the id the cloud follows it by (`p_pid`). It is
  `_adopt_handoff`'s own cross-type block plus the count rule and that id,
  and deliberately NOT part of that method: the crossfade adoption path
  stays byte-identical.
- **`_count_hold`** holds the matched count (3 orbits -> 3 fish) until
  `transition_count_hold_ms` after the program ends, then the authored
  `particle_count` wins and `_manage_population` flies the difference in or
  out as it does for any live change.

Proofs: `tests/test_shoal_burst.py`, `tests/shoal_burst_harness.py`.
