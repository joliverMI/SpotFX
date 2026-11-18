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
has shipped (`scene_response._band_anchor_ms`, `PendingKindBatch`; docs/agents/sonic-and-colour.md
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
(`bridge.intensity(look_ahead=True)`, ENERGY since 2026-10-28 — `spectra/services/energy.py`; the 0.7 is re-set by `scripts/energy_parity.py`) against the room's `drop_shock_min_energy` (0.7),
decided by `phase_grammar.shock_allowed`. False = no painter at all: the
frame is this effect's own drop byte for byte (no reveal hold-back either).
Untold reads True. It is an overlay, so nothing in this effect's own drop
changes; `drop_shock` (the per-effect strength) is a separate knob. Help
`drop-shockwave-switches`; proof `tests/test_drop_shock_switches.py`.

## THE PRE-DROP — the searcher darts to the centre and waits there (2026-10-27)

The plan's 3.5 (his approval, 2026-10-26: "do all recs"): "the searching
fish darts to the centre on the pre-drop, then waits there poised, its head
quivering, until the drop." The Fish is in `fx.device_model.
PRE_DROP_EFFECTS` since predrop step 8, one look for both kinds ("dart",
`pre_drop_looks` in config/effect_params.json). `fx/effects/pre_drop.py` is
the binding statement for the told keys; the PRE_DROP block beside the
searching lull's constants for the look. Four invariants not visible cold:

- **THE SEARCHING LULL IS MEASURED TO THE PRE-DROP.** Told one,
  `_lull_clock` ends the lull on it: the half-way keep mark is half the way
  to it and the search's legs end on it — the rule the engine already
  applies to every member's ramp, dark point and breath — so the lone
  searcher is there to go. (Untold, a 2 s spike in a 3.2 s lull would land
  0.4 s before the mark, with the others still leaving.)
- **THE DART AND THE COIL ARE THE KEEPERS' OWN STEERING.** `_pre_drop_dart`
  overwrites `self._keep` — the dart to each keeper's place at the centre of
  view (its row offset kept), then a tight coil round it, the head's `look`
  quivering harder toward the drop — and carries `turn` (PRE_DROP_TURN),
  which draw() divides the keepers' turn clamp by; nothing writes config.
  The numbers are the plan's prototype's (its contact sheet is exactly this
  curl). On his settings the searcher sits about a body length from the
  centre, so the dart is short and the coil is the energy; on a gap longer
  than the prototype's 0.8 s the loops swing wider (mean 7-10 px from the
  centre, up to ~16 px, still inside the lit hex) because the steering's
  proportional turn lags a 2.2 rev/s target. A slower settle barely
  tightens it; the first loop's rate (`PRE_DROP_COIL_REV[0]`) does.
- **NEVER DARK.** The Fish takes no breath (BREATH_HOLD False, his
  2026-10-12 word), so a told breath is a no-op and every lull frame is
  lit. Its light over the lull is at or below today's (-5% at a 0.8 s
  spike, -29% at 2 s, -0% at a 3.3 s vocal intro) — inside the plan's own
  named +4%.
- **UNTOLD IS TODAY'S.** `_pre_drop_step` clears the clock on every frame
  of a lull not told one, so the lull is today's frame for frame (proven
  against the module at the step-8 base).

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
and the scaled drop's `drop_scale_min` — and the word shape's
`word_shape_size`/`word_shape_few` (but NOT its minimum form, which lives
in `fx.device_model.WORD_SHAPE_FORM_MIN_S` and is deliberately not
Sonic-tellable) — and the big fish's
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
History: docs/agents/fx-effects.md's "Fish (fx/effects/fish.py) — Orbits' twin" section —
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

## WORD SHAPES (2026-11-15, plan row W1.4) — a PROCESSION along the
   outline; untold, nothing here exists

His words for the row: *"Fish: similar to orbits ... they need to smoothly
accelerate and not have sudden velocity shifts"*, and on the first design:
*"the fish didn't seem to be sufficiently making the outline. We may need to
boost the trail brightness and lower decay briefly to get it to show
better. They also may need to more tightly flow."* P2 A, approved: with FEW
fish the water keeps a trace of the loop while the fish swim it.

A sung word that reaches a shape fires the showing scene's Words response;
the `word_shape` kind writes `fx/effects/word_shape_keys.py`'s six told keys
in ONE jump; the fish turn onto the outline nose to tail, circle it for the
phrase and peel away. **Load `.claude/skills/word-shapes` first** — it is
the binding statement for the library, the keys, the envelope and the engine
contract. The module's own WORD SHAPES block is the binding statement for
everything below; what is not visible cold:

- **IT IS A BLEND ON THE REST GEOMETRY, NOT A MODE.** A shaped fish is an
  ordinary swimmer (mode < 2) with the loop's steer summed into the same
  desired-heading vector every other term lands in, bounded by the same
  turn clamp — so the two fish laws still hold structurally. Every shape
  block in `draw()` is gated on `_word_shape_step` returning non-None, so
  **untold is byte-identical to the pinned pre-change module** over both
  real-audio arcs (`scripts/check_fish_word_shape.py` §1).
- **THE ENVELOPE IS THE SPEED, NEVER THE AIM.** `m`
  (`word_shape_keys.envelope`) paces how hard the loop pulls and how fast a
  fish runs; a fish heads for its entry from the FIRST frame of the form.
  `word_shape_grip` is the loop's own authority — 1 from that frame, let go
  over the first HALF of the release (`WS_RELEASE_GRIP`), so the fish return
  to wandering with heading and speed intact while the trail is still
  fading. A second word mid-shape restarts the form FROM the fraction
  standing (`word_shape_restart_t`, the closed-form inverse smoothstep) and
  a clearing write releases from it (`word_shape_release_t`) — never a snap.
- **THE ENTRY RULE** (`word_shape_entries`): each fish's entry is the
  outline point on its OWN bearing from the centre of view, so no two cross
  on the way in; no two entries are within `WS_ENTRY_MIN_GAP / n` of the
  loop; and over `WS_SPACE_EASE_S` they ease to EVEN spacing, each fish
  keeping its order. The minimum gap is opened EXACTLY (pool-adjacent
  violators, then a compression if the wrap is short) — **not by
  relaxation**: a relaxation pass halves the deficit, so a clump of eight
  fish on one bearing was still 0.3% short of the gap after twelve passes
  and the proof went red. The bearing is read in the fish's own NORMALIZED
  space, which is the shape's own space up to one scale per axis (`sx` and
  `sy` both carry `radius_scale`), so the two angles are literally the same
  angle and no panel geometry is involved.
- **HOLDING STATION IS SPLIT IN TWO, and that split is the clarity bar.**
  The lag between a fish and its own place on the loop has a COMMON-MODE
  part (the line marched while the fish swam in; a fish's path round a
  corner is longer than the arc) and a DIFFERENTIAL part (out of step with
  its neighbours). The line's own PHASE follows the fish
  (`WS_PHASE_GAIN` — the procession is where the fish are, which is also
  what the water trace should be drawing) and each fish's SPEED fixes only
  its spacing (`WS_SPACING_GAIN`). Correcting both with speed meant every
  fish sprinting after an absolute phase it could never reach, since a fish
  and its place move at the same pace — exactly the velocity shift his note
  rules out.
- **THE TARGET IS ANCHORED TO THE FISH, NOT TO ITS STATION** (`WS_REACH`).
  The one thing that keeps a fish on a corner: anchored to the time-marched
  station, a fish a tenth of the loop behind aimed at a point right across
  the heart's cleft and swam the CHORD — measured 11 px (5.6 cell pitches)
  inside the outline. Anchored a short arc ahead of its own place, the
  chord is always a few px long and it follows the line round.
- **THE TURN ARC TIGHTENS** (`WS_TURN_X`, scaled by `m`) — his "more tightly
  flow". **ROW W5.5 took it to 0.10 and measured that it is NOT what bound
  the corners** (the gain and the aim were); read that section before
  trusting the "only way the bar is reachable" reading below. Measured, the
  outline turns 249 degrees (the heart's cleft), 154 (a star's notch) and
  114 (the diamond's tip) inside ONE of his own turn radii
  (`orbit_radius` 0.14 = 4.5 px), so a fish on its ordinary circle rounds
  those 5 cell pitches wide of the line. The mechanism is the pre-drop's own
  (`PRE_DROP_TURN`, `kst["turn"]` dividing `omega_max`): the clamp still
  bounds every steering term, it is simply a tighter circle while a shape
  runs, and at `m = 0` it is his circle to the bit. **A fish-motion bar
  measured against "the ordinary turn clamp" has to read the clamp IN
  FORCE** — `check_fish_word_shape.py` §3 prints both.
- **A FEED-FORWARD OF THE LOOP'S OWN CURVATURE WAS BUILT AND IS NOT
  SHIPPED.** Turning each fish at the outline's curvature times its speed
  is the textbook fix for a proportional steer's lag, and it measured
  WORSE (medians 1.3/1.8/1.0 → 4.3/3.2/1.1 cell pitches): the projection a
  fish off the line reads is poor exactly where the curvature is largest,
  and a cusp's curvature saturates the clamp into a spin. Do not re-add it
  without re-running §4.
- **HIS NOTE'S TWO NUMBERS.** The trail's half-life eases from
  `trail_decay`'s own value up to its end of `WS_TRAIL_HALF_LIFE_S` — the
  **(few 0.6 s, many 1.0 s) PAIR**, chosen by the latched mode — and SINCE
  ROW W5.5 the pair is **(0.6, 0.6)**, divided by the lap's own speed-up, so
  it is one smear LENGTH rather than two durations (that section's table) —
  and its
  deposit brightness up to `WS_TRAIL_GAIN` (1.6), both by `m`, both through
  `_trail_half_life()` / `_trail_gain()`. **The pair, and why it is a pair
  rather than one number, is the half-life table further down this
  section**: the trade only exists with MANY fish, because with FEW the
  water trace already carries the line. The boost goes in through
  `_clip_body_layer`'s WHOLE-pixel ceiling — the scatter's own
  hue-preserving one — so a brighter smear is never a whiter one. **It asks
  for that by a FLAG, `_ws_gain_clip`, not an argument**: two check scripts
  substitute or wrap that method by its one-positional-argument signature
  (`check_fish_big_fish_avoid.py`'s `_Bodies` spy,
  `check_fish_disperse.py`'s per-channel control) and a new keyword broke
  both — `tests/test_fish_tail_drive.py` is what caught it. **`trail_decay`
  and `ripple_life` are NEVER written**: the scaling is the quantity they
  drive, so the release's end restores his values exactly and no new param
  exists. Re-measure sections 4 AND 5 together before moving either end of
  the pair — they pull against each other, and the first answer here was
  wrong because it was read off a metric that saturates (see the table).
- **THE WATER TRACE (P2 A) IS FEW-FISH ONLY.** With `n <= word_shape_few`
  the wake takes one deposit per fish per frame at the loop point its own
  place has reached (the loop, not the fish, so the line glows while a fish
  is still swimming onto it) and `ripple_life` eases up to
  `WS_RIPPLE_LIFE_S`. Scoped to few deliberately: with many, the bodies and
  trails already light the outline and a longer-lived busy wake is where
  white comes from (the WAKE COLOUR block). The mode is LATCHED at the edge,
  so a population change mid-shape cannot switch it.
- **THE PAUSES.** The wall's authority, the big fish, a swim burst and the
  pond rest are held while a shape runs and resume after; one already in
  flight finishes. The wall is faded by `m` exactly the way a big fish's
  threat already relaxes it — **except where it is late turning a fish back
  from a wall it is heading into**: "the pond gives way, the wall does not"
  (the BIG_AVOID block) is what keeps a fish on the panel and a shape is not
  allowed to spend it. The lunge, the solo burst and every speed moment need
  no gate of their own: they multiply the ORDINARY target, which the blend
  fades out. The tail drive hands over per fish through an ARRAY weight —
  the only thing that makes `_tail_drive_step`/`_tail_drive_flap` take a
  non-scalar `weight`, and an untold frame never reaches it.
- **WHAT WRONG LOOKS LIKE.** P3 A means a shape is never TOLD while a
  charge, lull or drop is armed, but one can ARRIVE mid-shape. Then the
  phase wins: a formed school, a rush, ejecta, keepers and dispersing fish
  are not on the loop at all, so the procession empties while the told clock
  keeps running, and the trail and wake still restore at the release's end.
  On the panel that reads as the shape dissolving into the charge's school,
  which is the right answer — his authored moment is the bigger one.
- **CREATION BASELINE** (`_ws_seen`): a fresh instance built from a
  persisted config carrying a stale SEQ must NOT fire — the fireworks
  `burst_rockets` rule. `prime()` is deliberately NOT called: this effect
  reads only `at()`, and `prime()` would build the ~200 ms `sdf_fast` grid
  it never looks at.
- **THE SETTINGS**: `word_shape_size` (0.62) and `word_shape_few` (3) are
  registered (help topic `word-shapes`), so Sonic reaches them per scene
  entry for free. The MINIMUM FORM is **not** a param:
  `fx.device_model.WORD_SHAPE_FORM_MIN_S["fish"] = 2.0`, because SpotFX's
  planner needs it before it has asked any effect anything (it decides the
  lead) — `docs/SPECTRA_TIMING_CONVENTIONS.md` carries the row.

**THE CLARITY BARS, measured** (`scripts/check_fish_word_shape.py`, his
real mask at SIZE 0.62, 20 seeds per row for the distances and 8 for the
white, his live music Fish with the tail drive and the pond rest on).
**ROW W5.5's numbers supersede every figure in this subsection** — it is
kept as W1.4's own record, the way Orbits' skill keeps W1.3's.

**THE WATER TRACE (P2 A) IS FEW-FISH ONLY** and `WS_RIPPLE_LIFE_S` is
likewise read as a length since row W5.5.

**"IS THE OUTLINE LIT" HAS TO MEAN CONTRAST HERE, and this row shipped a
vacuous metric once.** The first check counted a band cell lit at ANY value
above zero — and the fish's own wake already lights 74-98% of that band on
the SAME FRAME UNTOLD, so "100% lit" said nothing at all. The squadron
leader caught it (PR 532 review). It is now the share of the band ABOVE A
LIGHT THRESHOLD (64 and 128 of 255) plus the band-to-rest luminance ratio,
each read beside the same seed's frame UNTOLD — `band_contrast`. Anything
measured on an "above zero" share of this effect is worthless; the wake
washes everything.

| mode | shape | word | mid-hold | band>64 told/untold | band>128 | band/rest |
|---|---|---|---|---|---|---|
| few | heart | 0.7 | 0.9 | 100 / 14% | 87 / 7% | 4.3 / 1.7x |
| few | star | 1.1 | 1.0 | 99 / 11% | 85 / 6% | 4.2 / 1.4x |
| few | diamond | 0.4 | 0.2 | 100 / 8% | 97 / 4% | 6.4 / 1.2x |
| many | heart | 1.1 | 1.4 | 93 / 25% | 79 / 12% | 4.6 / 1.8x |
| many | star | 1.4 | 1.8 | 91 / 18% | 67 / 7% | 3.4 / 1.2x |
| many | diamond | 0.5 | 0.3 | 98 / 19% | 86 / 7% | 6.6 / 1.4x |

Distances in CELL PITCHES, medians of 20 seeds; the share of fish-instants
beyond the 2-pitch bar is 0-10.3%. The bars are 60% (few) / 70% (many) of
the band above 64, a ratio of at least 2.5x, and at least 1.4x the untold
ratio on the same seed.

**THERE IS NO ENERGY AXIS**, and claiming one double-counted: this effect
never reads `word_shape_level`, so every figure came out identical at
Energy 0.2 and 0.8. On HIS scene (copied from Orbits V2) Energy drives
`particle_count`, so FEW and MANY *are* the Energy axis.

**THE HALF-LIFE IS A (FEW, MANY) PAIR** because the trade only exists with
many fish — re-measured on the contrast metric, since the first answer here
was read off the saturated one:

| mode shape | half-life 0.6 / 1.0 / 1.35 s | band>128 | white (today's worst) |
|---|---|---|---|
| many heart | | 61.3 / 71.4 / 78.0% | 18.7 / 21.3 / 22.7% (28.3%) |
| many star | | 51.4 / 68.2 / 72.7% | 23.6 / 26.8 / 28.28% (28.3%) |
| few heart | | 82.4 / 82.4 / 83.6% | flat |
| few star | | 75.0 / 77.6 / 78.4% | flat |

So MANY takes 1.0 s — 10 to 17 points of real light for 2.6 to 3.2 of
white, with 1.5 points of headroom; 1.35 s leaves 0.02 points and drops the
ratio to 2.7x. FEW is FLAT at all three (the water trace already carries
it) and stays at 0.6 s.

**TWO STATISTICS, AND WHICH BAR IS HELD ON WHICH.** The word bar (4 cells)
is held on the WORST fish of 20 seeds; the mid-hold bar (2 cells) on the
MEDIAN, because that is what the plan's own one-number-per-row figures are.
The worst instant and the share of fish-instants beyond 2 pitches are
printed beside it, and the worst is pinned (`HOLD_DIST_MAX_SEEN`).
**MANY-STAR IS MARGINAL**: its median is 1.8-2.4 depending on the seed
count, and a star's notch bound on the shaped circle is 2.0-3.4 pitches, so
many fish at a notch cannot meet 2 cells by geometry. Both distance bars
are read off the fish the TURN-CIRCLE LAW allows on the line (the plan's
own parenthetical), with the threshold and the window derived from the law.

**THE WHITE TAIL IS AN OPEN EXCEEDANCE, not a pass.** Across 8 seeds the
shaped worst is 23.9-33.8% against this effect's own worst busy frame today
(few 26.0%, many 24.5%), so five of six rows exceed the plan's bar in the
TAIL; the medians are 12-26%. A shape packs the shoal onto one small loop
and each fish carries its own place in the gradient, so overlapping bodies
sum two hues — the same arithmetic as his 2026-10-26 report, which option A
fixed for the WAKE only. Attributed: his x1.6 trail boost costs 0.5-2
points and buys 14 points of band light, so it stays; the FEW water trace
owns the rest of the FEW tail and is also the whole reason FEW reads (-8
points of white, -45 of band if removed), and **its amplitude is
NON-MONOTONIC** — dimming it can RAISE white, because a dimmer single-hue
trace stops winning `lighten`'s max over the whiter body sum. The root fix
is to narrow the gradient span a procession draws from (his own option-A
vocabulary, one colour for one drawn shape), which is a change to his
authored colour behaviour and so his call. **His ruling, 2026-11-17:
option A, ship as built, his to judge by eye** — no further tuning, this
stays as measured in the W3 room deploy. The script pins the measured
worst and median and prints the bar's status per row.

**Proofs**: `scripts/check_fish_word_shape.py` (TEN sections since row
W5.5, the whole acceptance list) and `tests/test_fish_word_shape.py` (the
contract, the floor through the real engine, the envelope's inverses, the
entry rule, and one real effect for the baseline / restore / pauses).

## ROW W5.5 (2026-11-18) — THE LOOP IS RUN, AND THE CORNERS ARE CORNERS

His second room verdict, verbatim: *"Oribits is really good at showing
shape, we need to get Fish to behave similarly. Ask me questions if it's
hard to implement, but you might need to override some min turn radii to
match the effect, especially on the star."* (With W4's framing underneath
it: *"Start with orbits and when we get that dialed in, we will do fish. I
think fish are going to have to override some of the motion rules to move
sharply enough to form corners, like on the star."*) Everything in the
W1.4 section above still describes the mechanism; what moved is below, and
where the two disagree on a NUMBER this section wins.

**FIVE LEVERS, and only two of them were the ones expected.** The row's
own sweep (`scripts/check_fish_word_shape.py --only sweep`: loop x turn,
then trail, then gain, then aim) is what chose each, and re-running it is
how a later change re-chooses them.

| lever | was | is | what it buys |
|---|---|---|---|
| `word_shape_speed_x` (REGISTERED, 1-6) | — | **3.0** | the lap: 5.5 s -> 1.83 s (FEW), 7.0 -> 2.33 (MANY) |
| `WS_TURN_X` | 0.25 | **0.10** | the shaped circle 1.13 px -> 0.45 px (0.23-0.39 cell pitches) |
| `WS_TURN_GAIN_X` | 2.0 | **12.0** | a star's worst corner 3.88 -> 0.99 cell pitches |
| `WS_TARGET_LEAD` / `WS_REACH` | 0.015 each | **0.008** each | 0.99 -> 0.37 |
| `WS_WALL_TURN_X` | 2.0 | **1 / WS_TURN_X**, and the wall's FLOOR relaxed with it | the wall cannot re-widen the circle at a corner near the pond's edge |

- **SPEED IS THE FIRST LEVER, and the arithmetic is the revisit gap against
  the trail's own half-life** (Orbits' W4.4 finding, reproduced here). At
  x1, three fish on the heart's 168-cell outline revisit a point every
  `WS_LOOP_S_FEW / 3` = 1.83 s against a 0.6 s trail half-life, so each
  smear is down to 12% of itself before the next fish arrives; at x3 the
  gap is 0.61 s — one half-life, 49%. `_word_shape_speed_x` is the binding
  statement and names the FOUR quantities that take the multiplier
  together: the line's own `march`, the procession's `pace`, the DASH CAP
  (absolute px/s — left alone it binds at x3, the heart's pace going 21 ->
  64 px/s against a 44 px/s cap, and the fish would chase a line it can
  never catch) and the PHASE EASE. `WS_SPACING_GAIN` needs nothing: it is
  already a multiplier ON the pace.
- **THE TURN CIRCLE IS NOT WHAT BOUND THE CORNERS, and that is the row's
  first finding.** His instruction said to override it and it was overridden
  — but measured on the corner bar, moving `WS_TURN_X` from 0.25 to 0.08 at
  x1 took a star's worst corner from 5.39 cell pitches to 5.45, which is no
  movement at all. What bound it was the AIM:
  * **the heading GAIN.** A proportional steer needs a heading error to
    command a rate, and the lag that error stands for gets worse the
    faster the line runs — and this row runs it three times faster. At x3
    on the shaped circle: 3.88 cell pitches at the shipped x2, 1.40 at x6,
    **0.99 at x12**, 1.27 at x24 (over-steer coming back), with the
    per-instant median distance 1.31 -> 0.10 and the p90 2.92 -> 0.50.
    **AND IT WAS LOAD-BEARING FOR THE CONTRAST BAR TOO**, which the row did
    not expect: at the gain this effect shipped with, the worst row's share
    of the band over 64/255 reads **59%** — under its own 60% FEW bar — and
    93% at x12. It is the same mechanism (a fish that lags the line is not
    ON the band), and it is why no amount of speed or trail alone ever got
    this effect's band share where his eye wanted it.
  * **the pursuit LEAD.** A steer aimed `L` of arc ahead has a chord that
    passes a corner of exterior angle theta at `(L / 2) sin(theta / 2)`,
    whatever it can turn — 1.7 px at the heart's cleft on the old 0.030 of
    the loop, which is 0.9-1.5 cell pitches of a 1.0-pitch bar spent before
    the circle is ever consulted. Halved, it is 0.57-0.59 pitches on the
    heart and the star and 0.31 on the diamond. Swept: 0.99 cell pitches of
    worst corner at 0.030, 0.79 at 0.024, **0.37 at 0.016** and 0.24 at
    0.010 — but 0.010 drops the worst band row to 83%, so 0.016 is where it
    bottoms out without paying for it.
  **THE CLAMP IS WHAT MAKES A HIGH GAIN SAFE**, which is why the two move
  together: at x12 the heading settles in about two frames and every frame
  of it is still bounded by the tightened circle, so the structural
  guarantee is the same single `np.clip(omega, -omega_max, omega_max)` it
  always was — section 3 reads the clamp IN FORCE and measures 100.0% of
  it (saturated at the cusps) and 1000% of the untightened circle, by
  design.
- **THE WALL'S FLOOR HAD TO GO WITH IT.** `_glance_radius` floored its arc
  at the fish's OWN turn radius, and the wall is the one authority that
  still OVERRIDES the loop's steer while it runs — so near the pond's edge
  a glance planned on a 4.54 px circle rounds a star's notch wide of the
  line however tight the shape's circle is. `_ws_wall` is now a THREE-tuple
  (look-ahead, arc divisor, floor divisor) and the floor is the same
  `1 - (1 - WS_TURN_X) * m` the clamp in `draw()` uses. **`own_floor=True`
  keeps the fish's own radius for the two callers that are not steering**:
  `_landing`'s corner rounding (how a long BODY rounds a panel corner —
  geometry, and a per-frame rho would thrash `_landing_field`'s cache) and
  `_wall_steer`'s probe reach (only ever safer the wider it is).
  **BOTH HALVES EARN THEIR PLACE, measured** — and the one thing that
  matters is measured on the right line: the LANDING LINE is the glance's
  own target, pulled `WALL_GRAZE` half-widths inside the lit edge with its
  corners rounded, so an ordinary fish crosses it routinely (untold over
  his real-audio arcs: 1.77 px FEW, 1.78 MANY). The LIT SILHOUETTE is
  whether a middle is actually off the panel, and no configuration puts one
  there:

| wall under a full shape | worst corner | past the landing line | past the LIT edge |
|---|---|---|---|
| **arc / 10 (= 1 / `WS_TURN_X`), floor relaxed — as shipped** | **0.49 p** | 2.77 px | 0.48 px INSIDE |
| arc / 2 (W1.4's own), floor relaxed | 0.80 p | 2.75 px | 0.96 px inside |
| arc / 2, floor NOT relaxed | 0.80 p | 3.19 px | 0.15 px inside |

  So the ARC DIVISOR is what buys the corner (0.80 -> 0.49 cell pitches)
  and the FLOOR is what buys the recovery (3.19 -> 2.75 px of overshoot,
  because a glance that can command the full shaped clamp comes back
  sooner). The shape costs about a pixel more than this effect's own untold
  worst AT THE LANDING LINE and nothing at all at the lit edge. Section 9
  prints both, beside the same seed untold, and pins both.
- **W1.4's TWO HALF-LIVES ARE NOW SMEAR LENGTHS, NOT DURATIONS.** Each is
  DIVIDED BY THE LAP'S OWN SPEED-UP in `_trail_half_life` /
  `_wake_half_life`, so the smear a fish lays keeps the LENGTH W1.4
  measured instead of three times it. **The division goes on the BLENDED
  value, not on the target**: blending toward `want / x` makes the
  half-life non-monotonic in `m` (it peaks 0.233 s around m = 0.5 against
  0.200 s at the hold, because the target falls faster than the blend
  climbs), while blending first and dividing after makes the smear LENGTH
  follow W1.4's own ramp exactly — `(h + m (F - h)) / x`, times the pace,
  IS that ramp. `WS_RIPPLE_LIFE_S` is untouched at 3.0 (0.42 s of wake
  half-life at x3, still covering the 0.61 s a point waits between two of
  three fish).
- **AND THE PAIR'S OWN REASON MEASURED AWAY, so `WS_TRAIL_HALF_LIFE_S` is
  (0.6, 0.6).** The pair existed because "the trade is only real with many
  fish" — with FEW the water trace carried the line, with MANY the trail
  WAS how the band between the fish stayed lit. At x3 that is no longer
  true: MANY clears its 70% band bar by 16 to 30 points at the FEW end too
  (its revisit gap is 7.0 / (6 x 3) = 0.39 s), while the longer end costs 4
  to 5 points of white on exactly the three rows where white is the open
  exceedance. That is the row's own instruction — speed first, the trail
  only as far as the bar needs — applied to his own standing concern. Kept
  as a TUPLE because the mode latch is still the thing that would re-open
  it.

| `WS_TRAIL_HALF_LIFE_S`'s own ends | worst band>64 | worst corner | worst white |
|---|---|---|---|
| **0.6 (= 0.20 s effective, as shipped)** | **93%** | 0.37 p | **26.2%** |
| 1.0 (W1.4's MANY end) | 95% | 0.37 p | 31.5% |
| 1.4 | 98% | 0.37 p | **36.7%** |

  Two points of band for five of white, on a bar already met by 33 points.
  (The same trade read on EFFECTIVE half-lives before the pair collapsed:
  0.20 s 86% / 33.0% white, 0.30 s 89% / 33.3%, 0.45 s 98% / 37.8%, 0.60 s
  99% / 40.8%.)

  AND THE LAP AND THE CIRCLE, from the same sweep — x4 is where the band
  COLLAPSES, so his own estimate of 3 was right, and 0.10 is where the turn
  column plateaus:

| lap (turn 0.25 -> 0.08) | x | worst band>64 | worst corner | white |
|---|---|---|---|---|
| 5.50 s | 1.0 | 74 -> 87% | **5.09 -> 5.47 p** | 31-32% |
| 2.75 s | 2.0 | 89 -> 90% | 2.55 -> 0.77 p | 30% |
| **1.83 s** | **3.0** | 92 -> **92%** | 0.50 -> **0.40 p** | **26%** |
| 1.38 s | 4.0 | 81 -> **65%** | 0.32 p | 30% |

  The trace's own life behaves the same way (at effective trail 0.30:
  1.0 s -> 33.3% white, 1.5 -> 33.3%, 2.0 -> 38.5%), and it is also what
  owns the FEW tail exactly as W1.4 said. `WS_TRAIL_GAIN` STAYS AT 1.6:
  lowering it costs band light and RAISES white, the non-monotonicity W1.4
  recorded (a dimmer single-hue trace stops winning `lighten`'s max against
  the whiter body sum underneath). **This also moves two assertions**: the
  trail and the wake still rise while a shape holds — his "lower decay
  briefly" — but by less than the x3 the slow lap needed, so the proof and
  the test assert the ARITHMETIC (`pair / x`) rather than a loose multiple.
- **THE CORNER MEASURE IS NEW (section 9) and it is the row's own bar**:
  the distance from each outline VERTEX to the nearest fish PATH through
  the hold, in cell pitches, printed per corner. A path and not an instant,
  because a corner is drawn by a fish going round it at some point in the
  hold and smeared there for a trail half-life afterwards. The vertex
  detector is VERIFIED rather than trusted — the signed turn over one cell
  pitch of arc, clustered — against the corners he names: the heart's point
  and cleft (2), a star's five points and five notches (10), the diamond's
  four tips (4). **The turn circle's own minimal-arc depth is printed
  beside it as a REFERENCE, never asserted**: a fish can come in either
  side of it, wider when its aim cuts the corner and CLOSER when it
  overshoots into a cusp and comes back (measured at the heart's cleft, a
  1.52-pitch arc depth against 0.02-0.09 pitches of real path).
- **AND THE STATISTIC IS PER SEED, NEVER POOLED ACROSS THEM.** The first
  version of this measure took each corner's BEST reading over the seeds
  and then the worst corner, which mixes runs that never happened together
  and reads optimistically: 0.32 cell pitches pooled against **0.49** per
  seed, on the same three seeds. A shape fires once, on one seed, so the
  bar is held on the worst corner of the WORST seed and the median seed is
  printed beside it. The squadron leader's review of this row caught the
  two numbers disagreeing across the docs; the disagreement was the
  pooling, not the labelling.
- **THE CONTRAST BAR IS NOW OVER-SATISFIED, which is the honest reading of
  his verdict.** At the shipped levers the band over 64/255 reads 86-100%
  against bars of 60% (FEW) / 70% (MANY), band/rest 3.6-8.0x against 2.5x,
  every hold frame — where W1.4 measured 91-100% on a *vacuous* denominator
  and his eye still called it unclear. The corner bar is met on every
  corner of every shape in both modes (worst **0.49** cell pitches against
  1.0, on the star, median seed 0.31), and the per-instant distance medians fall from 1.31 to 0.10 cell
  pitches.
- **THE WHITE TAIL IS STILL THE OPEN EXCEEDANCE, and it is still HIS
  CALL.** Measured at the shipped levers it sits where his 2026-11-17
  ruling left it (option A, ship as built, his to judge by eye) rather than
  better: a tighter procession puts more bodies on the same cells, and
  overlapping bodies sum two gradient hues. The root fix is unchanged —
  narrow the gradient span a procession draws from, one colour for one
  drawn shape — and it is a change to his authored colour behaviour, so it
  is not a build row's to make. Section 5 prints the number and names the
  bar it exceeds.

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

## ROW W6.1 (2026-11-18) — THE NOSE STOPS WAGGING, AND THE RIG MOVES TO HIS
   OWN 30 fps

His THIRD room verdict, verbatim: *"Only thing left is the fish needs a
little more tuning. Everything else was good. The shape outline needs to
reach at least a moment where it is either filled with fish or trail. Right
now, the fish seem to jitter out of the outline and so it isn't distinct
enough. Also, if we did a highlight of the shape in orbits, do it on
fish."* Everything the W1.4 and W5.5 sections above describe still stands;
where this section and those disagree on a NUMBER, this one wins.

**THE ROW'S FIRST ACT WAS TO MOVE THE RIG, AND THREE OF ITS FOUR FINDINGS
ONLY EXIST AT 30 fps.** His crystal's `refresh_rate` is 30 and a virtual
renders at its slowest device (`.claude/skills/radial-effect`'s own note;
`fx/virtuals.py`), while `scripts/check_fish_word_shape.py` had `DT = 1 /
60`. So EVERY W5.5 number — the corner bar, the smoothness bars, the sweep
that chose x12 — was read at twice the live rate, and three separate things
in this effect's shaped steering are functions of `dt`:

| read at his own 30 fps, on master | 60 fps (what W5.5 measured) |
|---|---|
| nose WAGS 18.57-27.71 per fish-second | 3.38-12.11 |
| the HEAD's p95 from the band 2.75-8.18 cell pitches | 2.37-2.97 |
| a middle's p95 0.29-**7.44** | 0.18-1.12 |
| worst corner 0.72 p (bar 1.0, still met) | 0.49 p |
| **fish up to 14.5 px OFF THE LIT PANEL** (0.00 untold) | 0.00 px |
| the band FILLED (over 128/255) at the best hold frame 44.0-88.2% | — |
| smoothness: worst lit-cell change 3.18%, speed 9.7% of its own max | 2.14% / 8.3% |

The smoothness bars HOLD at 30 fps (3.18% against 8%, 9.7% against 100%),
and so does the corner bar. What does not hold is everything about the
NOSE — and the wall, which nobody had measured at his rate.

**FOUR CAUSES, each arithmetic rather than a guess, each measured before it
was changed.**

1. **THE PROPORTIONAL STEER OVERSHOOTS.** `omega = d_hd * turn_gain` then
   `hd += omega * dt` corrects `turn_gain * dt` of the heading error per
   frame: at the shaped 39 /s that is 0.65 at 60 fps and **1.30 at 30** —
   past the target, with the error alternating sign. The step is now the
   exact first-order form, `k = 1 - exp(-gain_ws * dt)` of the error
   commanded as `d_hd * k / dt`, BLENDED by `m_fish` so that `m = 0` is
   `TURN_GAIN * 1.0 + (...) * 0.0` — his own expression in IEEE arithmetic,
   not just in algebra. 0.73 of the error at 30 fps, 0.48 at 60, never more
   than the error at ANY rate. `WS_TURN_GAIN_X` therefore names a SETTLING
   TIME now rather than a per-frame fraction, which is what makes x24 safe.
2. **THE CLAMP STOPPED MEANING AN ARC.** `omega_max = speed /
   turn_radius_px / WS_TURN_X` is the right angular RATE for a 0.45 px
   circle; what a drawn frame gets is `omega_max * dt`, and at the x3 pace
   that is **4.7 to 7.2 RADIANS** — more than a full turn. Measured: a fish
   on the loop with the wall's glance saturating the clamp (urgency 1.00,
   omega 190-214 rad/s) corkscrewed a complete circle every frame and
   travelled **20.5 px off the lit panel**, against 0.00 on the same seed
   untold. The guarantee's own sentence ("an about-face is always an arc
   and never a flip") was simply false. `WS_TURN_MAX_RAD_FRAME` (pi / 2) is
   a per-RENDERED-FRAME ceiling on the bound — STAR's
   `ROTATION_CAP_DEG_FRAME` precedent — and it is still the one `np.clip`.
   It cannot bind at `m = 0` by arithmetic: the ordinary clamp would need a
   fish at 214 px/s and this effect's own fastest is 4.2x cruise.
3. **THE AIM WAS SHORTER THAN A FRAME'S TRAVEL, and this is the one that
   owns the WAG.** The aim is an ARC (`WS_REACH + WS_TARGET_LEAD`, 0.016 of
   the loop = 0.2-1.1 px) and a frame's travel is a LENGTH (1.5-2.4 px at
   30 fps). Measured frame by frame on the diamond — whose own tangent
   never reverses, so every reversal read there is the effect's: at a
   corner the aim point jumps from one side of it to the other WITHIN one
   frame, the error arrives as 90 degrees in a single step, and the next
   three frames bring the fish back (-9, -13, -7 deg). `WS_AIM_STEP_X`
   (1.5) floors the aim arc at that many of the fish's OWN frame steps, per
   fish, read from its own speed. At 60 fps it barely binds (one step is
   0.7 px against the 0.96 px the aim already was), which is why W5.5 never
   saw it.
4. **THE WANDER WAS THE ONE UNGATED STEERING TERM.** `WANDER_W` 1.0 against
   the loop's `WS_SEEK_W` 14 moved the DESIRED heading about 0.7 degrees
   every frame, which the shaped gain then chased. It now eases out by `m`
   exactly as the swirl and the beat's kicks already did — the loop IS the
   current while a shape runs.

**AND WHAT HIS "HIGHLIGHT" ACTUALLY NAMES IS PERSISTENCE.** `fx/effects/
orbits.py` carries exactly four `WORD_SHAPE_*` constants (`FEW`, `MANY`,
`TRAIL_S` 1.8, `SPEED_X` 4.0) and **no shape-time brightness, glow or line
lift at all** — W4.4's option B was framed and never built; he settled
option A, as built. What makes Orbits' outline read whole is its trail
OUTLIVING THE REVISIT GAP at x4 (`WORD_SHAPE_TRAIL_S` as a DURATION add-on,
0.9 -> 1.8 s). W5.5 had done the OPPOSITE here, reading both half-lives as
smear LENGTHS divided by the pace: 0.20 s of trail against a 0.61 s gap
(FEW heart) or 0.39 s (MANY), so each smear sat at 12% of itself when the
next fish arrived. `WS_TRAIL_GAP_X` (1.0) floors both the body trail's
half-life and the FEW water trace's at the revisit gap
(`_word_shape_revisit_gap`, the LATCHED lap over the LATCHED count, ramped
by `m` so the form's first frame is still his own value).
`tests/test_fish_word_shape.py::test_the_port_from_orbits_is_persistence_and_not_a_highlight`
is what keeps this straight for the next row.

**THE LEVERS, re-swept at 30 fps** (`--only sweep`'s own four new tables;
each figure the worst of 6 (mode, shape) rows, 2 seeds):

| lever | was | is | what it buys |
|---|---|---|---|
| the heading STEP | `d_hd * gain` | `d_hd * (1 - exp(-gain dt)) / dt` | no overshoot at any frame rate |
| `WS_TURN_GAIN_X` | 12.0 | **24.0** | worst corner 1.04 -> 0.79 p, band filled 75.6 -> 77.8% |
| `WS_TURN_X` | 0.10 | **0.10**, measured and KEPT | 0.15 gave 0.75 p against 0.79 — inside two seeds' noise, and would have broken his pinned "under half a cell pitch" |
| `WS_TURN_MAX_RAD_FRAME` | — | **pi / 2** | 20.5 px off the lit panel -> 0.00; wags 8.86 -> 6.14/s, band FILLED 60 -> 78%, worst corner 0.87 -> 0.70 p |
| `WS_AIM_STEP_X` | — | **1.5** | wags 12.00 -> 6.14/s; costs the corner 0.33 -> 0.70 p |
| the WANDER under a shape | ungated | `* (1 - m)` | part of the same overshoot |
| `WS_TRAIL_GAP_X` | — | **1.0** | band FILLED 36 -> 78%, band>64 61 -> 94%, white 19.6 -> 31.0% |
| `WS_WAKE_FADE` | 1.0 | **0.0** | ratio 8.1 -> 10.5x and white 33.8 -> 31.0%, for NO band cost |
| `WS_FLAP_X` | — | **None**, measured and refused | 1 glide size: ratio 10.5 -> 14.6x but band FILLED 78 -> 74% and white 31.0 -> 35.4% |
| `WS_TRACE_MANY` | (few only) | **False**, measured and refused | extending the trace to MANY moved the band FILLED 0 points (78 -> 78%) and cost 5 of white; brighter too, 82% for 39.2% white |

**THE TWO REFUSALS ARE RE-MEASURABLE FROM THE SHIPPED SCRIPT**, not just
recorded here: `--only sweep`'s own OFF-BAND table runs the flap at one and
three glide sizes, the ordinary wake as W1.4 had it, and the trace extended
to MANY (plain and brighter) against the shipped configuration, so a later
row overturns either with one command.

**THE AIM AND THE CORNER PULL AGAINST EACH OTHER, and that is the row's own
trade.** A longer aim moves the target continuously through a corner (fewer
reversals) and cuts the corner by `(L / 2) sin(theta / 2)`:

Section 10's own aim table, at the shipped gain, cap and gap:

| `WS_AIM_STEP_X` | wags/fish-s | worst corner | band>64 | band FILLED | white |
|---|---|---|---|---|---|
| 0.0 (W5.5's) | 12.00 | **0.39 p** | 96% | 79% | 32.0% |
| 1.0 | 7.14 | 0.33 | 95% | 76% | 30.5% |
| **1.5 (shipped)** | **6.14** | 0.70 | 94% | 78% | 31.0% |
| 2.0 | 5.14 | 1.46 — OVER the bar | 95% | 74% | 32.3% |

The corner bar of 1.0 is what bounds it at 1.5, and section 9's own
three-seed figure at that setting is 0.79. (An earlier pass of this sweep,
at the W5.5 gain of x12, read 11.43 -> 6.00 -> 4.86 wags down the same axis
with the corner going 0.50 -> 1.04 -> 1.51 — the same trade, one gain
lower.)

And the clamp's own ceiling, which is the axis nothing else could reach:

| `WS_TURN_MAX_RAD_FRAME` | wags/fish-s | worst corner | band>64 | band FILLED | band/off |
|---|---|---|---|---|---|
| 180 deg (no ceiling) | 8.86 | 0.87 p | 80% | 60% | 11.0x |
| **90 deg (shipped)** | **6.14** | **0.70** | **94%** | **78%** | 10.5x |
| 60 deg | 5.57 | 0.82 | 94% | 77% | 7.5x |
| 45 deg | 5.71 | 1.82 — OVER the bar | 90% | 66% | 5.7x |

The 180-degree row is the one that walks a fish 20.5 px off the lit panel
(section 9's own two depths), so its corner figure is not the whole cost.

**THE GAIN IS NOT THE WAG'S LEVER, which the row did not expect.** The
re-sweep of `WS_TURN_GAIN_X` x `WS_TURN_X` at 30 fps moves the corner (3.28
cell pitches at x6, 0.79-1.04 at x12 and x24) and moves the wag HARDLY AT
ALL — 4.86 to 7.43 per fish-second across all nine combinations. x6 is pure
lag and costs the band (61.9% filled) and the white (40.2%) as well as the
corner.

**A ONE-POLE ON THE TURN COMMAND WAS BUILT AND IS NOT SHIPPED** — this
row's version of W1.4's curvature feed-forward, and recorded for the same
reason. STAR's `_govern_rotation` smooths that effect's jerk with a
unity-DC-gain one-pole on the per-frame advance, so the same filter on the
shaped turn command (state `p_om`, in RENDERED frames) is the textbook
answer. Swept over 0, 1, 1.5, 2.5 and 4 frames it barely touched the wag
(6.00 -> 4.86) and destroyed everything the row is for: worst corner 1.04
-> **10.73** cell pitches, band filled 75.6 -> **29.2%**, white 33.1 ->
43.8%. A fish that cannot spend its turn WHEN the corner arrives does not
round the corner at all.

**THE TWO NEW SECTIONS, and the one honest miss.**

**Section 11, THE OUTLINE IS WHOLE FOR A MOMENT** — his own bar. The hold
frame that MAXIMISES the band's share over 128/255 ("filled", not "lit"),
and at THAT frame the OFF-band light: every real cell outside the band and
outside a ONE-CELL MARGIN around it, because a body is a cell wide and its
own width is not jitter. Bars: 95% of the band filled AND band/off-band
20x, on every seed of three, both modes, all three shapes. **It is a
different, tighter question than section 4's** (93-100% over 64/255 and
3.6-8.0x at mid-hold) and it is the one he asked.

Section 10's own OFF-BAND table is the one those three rows are read off,
worst of its six (mode, shape) rows at 30 fps:

| configuration | band>64 | FILLED | band/off | white | corner |
|---|---|---|---|---|---|
| **as shipped** (flap his own, wake eased out, trace FEW) | 94% | **78%** | **10.5x** | **31.0%** | 0.70 p |
| the FLAP eased to 1 glide size | 92% | 74% | 14.6x | 35.4% | 0.70 |
| the FLAP eased to 3 glide sizes | 92% | 74% | 14.6x | 35.3% | 0.70 |
| the ORDINARY WAKE left as W1.4 had it | 95% | 78% | 8.1x | 33.8% | 0.70 |
| the TRACE extended to MANY too | 95% | 78% | 10.4x | 36.0% | 0.70 |
| the TRACE to MANY and brighter (amp x1.4) | 99% | 82% | 9.6x | 39.2% | 0.70 |

Nothing down this axis moves the CORNER at all, which is the same clean
separation the gap axis shows: the trail, the water and the steering are
three independent defects in this effect and the row treated them as such.

Section 11 also ATTRIBUTES the off-band light between the BODY layer
(`eff.trail`) and the WATER layer (`eff.wake`), which is how this row chose
between its two candidate levers instead of guessing: at the moment, FEW
reads 15.2 body / 14.4 water and MANY 13.8 / 7.7. Both are real, and the
water's half is free to remove while the body's half is not.

**Section 12, THE NOSE DOES NOT WAG.** Per fish per frame of the hold, the
signed heading change; a WAG is a sign reversal between consecutive frames
with both `|d_hd|` past 2 degrees, counted per fish-SECOND so the two frame
rates compare. The HEAD is the point `_draw_bodies` really draws — the
middle extrapolated HALF A BODY along `p_hd` (`SPINE_U[0] = 0`, and
`SPINE_THROW = SPINE_U ** 1.6` is ZERO at the nose, so this is a heading
measure and not a flap one) — and not the middle section 4 reads.

**BOTH OF SECTION 12's BARS HAVE A DERIVED GEOMETRIC FLOOR UNDER THEM, and
one of them is unreachable.** The floors are printed beside every number
and the ASSERTED figures are the measured worsts, PINNED — section 5's own
shape for the white tail it exceeds:

| mode shape | wags/fish-s | its floor | head p95 | its floor | middle p95 |
|---|---|---|---|---|---|
| few heart | 6.00 | 1.64 | 3.04 p | 1.32 p | 1.43 p |
| few star | 2.00 | 0.00 | 3.40 | 2.14 | 1.33 |
| few diamond | 0.86 | 0.00 | 2.15 | 2.07 | 0.15 |
| many heart | 6.57 | 1.29 | 2.99 | 1.32 | 1.22 |
| many star | 1.00 | 0.00 | 2.95 | 2.14 | 0.99 |
| many diamond | **0.43** | 0.00 | **2.07** | 2.07 | 0.10 |

- **THE WAG'S FLOOR** is the OUTLINE's own tangent reversals for a point
  walking it at the procession's pace at the rate being measured. The
  heart's cleft turns IN and back OUT, so its floor is 1.29-1.64 per second
  — already past the plan's 0.5 bar. The star's and the diamond's are 0.00.
  **many-diamond MEETS the plan's bar outright (0.43)**; the heart is the
  outlier at 4x its own floor, and its cleft is a cusp.
- **THE HEAD'S FLOOR** is where the nose of a fish exactly ON the line
  pointing exactly along its TANGENT actually lands. His fish is **4.33
  cell pitches long** and the nose is half of that ahead, so on a curve it
  leaves the band by construction: p95 1.32 (heart), 2.14 (star), 2.07
  (diamond). **The plan's 1.0-pitch bar is therefore unreachable at his own
  `blob_size`** — arithmetic, not tuning, the same reading W5.5 gave
  many-star's 2-cell bar. Both diamond rows now sit AT their floor (2.07
  and 2.15 against 2.07).

Row W6.1 took the wag from **18.57-27.71** per fish-second to **0.43-6.57**
and the head's p95 from **2.75-8.18** cell pitches to **2.07-3.40**, at his
own frame rate. The plan's 0.5 bar is missed on five rows of six and is
reported; it is not moved.

**AND THE WALL IS FIXED AT HIS RATE, which is the row's quietest win.**
Past the landing line 0.46-0.50 px told (his own untold worst over the real
arcs is 1.78) and **0.00 px past the LIT silhouette**, against 20.65 px and
13.76 px on master at 30 fps. No fish leaves the panel any more.

**WHITE IS REPORTED, under his standing option A** (2026-11-17: ship as
built, his to judge by eye). The whole-outline moment costs white — the
trail floor is a longer smear and overlapping bodies sum two gradient hues,
his 2026-10-26 arithmetic unchanged — and the ordinary wake's removal pays
some of it back. The root fix is still to narrow the gradient span a
procession draws from, which is his authored colour behaviour and not a
build row's to change. Section 5 prints the number and names the bar.

**Proofs**: `scripts/check_fish_word_shape.py` (TWELVE sections now, at 30
fps with `--fps 60` as the cross-check; section 1 reads IDENTICAL against
the pinned module at BOTH rates) and `tests/test_fish_word_shape.py` (its
own laws at 30 fps: the first-order step at 15, 30 and 60 fps, the clamp's
per-frame ceiling, the aim's floor, the revisit gap, the hand-overs, and
that there is no highlight in Orbits to port).
