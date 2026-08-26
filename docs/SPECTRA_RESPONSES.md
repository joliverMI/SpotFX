# SPECTRA responses — the real charge/lull/drop grammar, per effect family

The build/suspend/release choreography for charges, lulls, and drops does
not live in SPECTRA: it lives in the vendored render pipeline, inside the
particle-based effects, DANCERS, and EYE — written there for the original
SpotFX program and carried verbatim into `fx/effects/`. SPECTRA's response
engine (`spectra/services/scene_response.py`) DRIVES that machinery; it
does not re-invent it.

## The universal contract (all eleven phase-capable effects)

Every effect in `fx/device_model.PHASE_EFFECTS` — `blackhole`,
`blackhole1d`, `orbits`, `orbits1d`, `radial`, `fireworks`, `fireworks1d`,
`squiggles`, `dancer`, `eye`, `fish` — carries two config params:

- `phase`: `"none" | "charge" | "lull" | "drop"` — edge-detected in
  `config_updated` (a stale persisted value never edge-fires on a fresh
  instance; the pending edge is consumed in `draw()`).
- `phase_progress`: `0.0 → 1.0` — the ramp SpotFX drives. Choreography is
  progress-driven once the ramp moves (hand-scrubbable in the LedFX UI),
  with a wall-clock fallback that only runs while progress sits at 0, so a
  lost tween still animates.

Shared pieces (read them, they are the ground truth):

- Orphan watchdog: `fx/effects/particle_handoff.py` `phase_release_due` —
  a charge/lull whose payoff never arrives self-releases 12 s after the
  build completes, 60 s absolute cap. Most families release as a *silent
  drop* (the exit choreography without the burst).
- Self-reset: at the end of every drop the effect writes
  `{"phase": "none", "phase_progress": 0.0}` to itself through the
  sanctioned in-render config path, so an identical later drop write edges
  again.

## How SPECTRA's response classes drive it

`ResponseEngine.on_event("charge"|"lull"|"drop", intensity, gap_ms=None)` —
exactly the drive the original program used (`services/trigger_engine.py`
`_fire_phase`):

1. **Arm**: an instant `{"phase": <class>, "phase_progress": 0.0}` jump to
   every virtual whose live effect is phase-capable (the `0.0` reset makes
   the edge re-fire).
2. **Ramp**: a glide of `phase_progress → 1.0` over the class's duration.
   Charge/lull DYNAMICALLY STRETCH to ~90% of `gap_ms` — the real distance
   to the next trigger this song will actually fire
   (`TriggerEngine._next_trigger_gap_ms`) — hanging the remaining ~10% at
   `phase_progress=1.0` for free (nothing writes it again before the next
   phase event); his verbatim spec (2026-08-20, "fix the lull ramp"): "the
   single blob waiting in lull should reach the center just and hang for
   just a moment, maybe 10% of the lull time, before the explosion." An
   UNKNOWN gap (no trigger-schedule context — a bridge-classified legacy
   flare, or a manual test-fire) falls back to the tuned flat default:
   charge **4000 ms**, lull **2500 ms** (`scene_response.PHASE_RAMP_MS`,
   the original program's tuned defaults). Drop is never stretched — it
   stays **400 ms** ("drop stays short — it's the snap") regardless of
   `gap_ms`. See `scene_response._phase_ramp_ms`.
3. The drive fires for **every** charge/lull/drop event — band or no band —
   exactly as the original fired the phase machinery for every phase
   event. The scene's declared band rides **on top** as the scene's
   colouring, firing its NAMED FLARE KINDS at their scales (item-8 model:
   drift-jump / momentary / permanent — `spectra/models/scene.py`
   `FlareKind`): phase builds the arc, the response class colours it. A
   surge record with result `phase_only` means the arc ran with no band
   extras.
4. **Lifecycle guard**: a track change releases any armed charge/lull with
   an instant `phase "none"` write (`release_phases`) — a build must never
   linger into the next song. The watchdog remains the safety net, not the
   mechanism.

Phase keys ride ONLY these dedicated writes: they are deliberately absent
from `config/effect_params.json`, so the editor never offers them and the
band-patch registry gate drops them — a cached `"charge"` re-sent inside an
ordinary write would spuriously re-fire the choreography with no drop
coming (the same hazard the original program's `_strip_stale_phase`
guarded).

## Per-family grammar (what the room actually does)

### Black Hole (`blackhole.py`, strip translation `blackhole1d.py`)

- **Charge** — infall is forced (`reverse` saved and overridden to False,
  restored at the payoff); the event horizon quadratically swallows the
  panel while a glowing capture ring (`_phase_halo`) outruns the black
  disc, so the build reads even in silence. Ambient spawning pauses once
  the horizon covers the panel.
- **Lull** — held full-screen black: the room's screen is *gone*, only the
  halo's memory. (1D: mask fully closed with a lingering phosphor dot at
  the strip middle.)
- **Drop** — the horizon pinches to a point, 24 full-bright blobs erupt
  from the center (`_phase_burst`, bypasses `max_blobs` — the explosion
  must always land), the saved config is restored, and the horizon eases
  back to baseline over 0.5 s.

### Orbits (`orbits.py`, strip translation `orbits1d.py`)

- **Charge** — the population swells from its current count to 10 blobs
  over the first 45% of the ramp, then sheds down to a single blob: the
  room gathers, then focuses.
- **Lull** — that last blob's whole orbit collapses smoothstep to the
  center (97% radius reduction, 40% slower spin), a tiny residual swirl
  instead of a frozen point.
- **Drop** — configured population restored with a center burst for the
  missing, plus 2× population of ballistic ejecta that blast straight off
  the panel; orbital speed boosted ×3.5 decaying over 2.4 s; survivors fly
  back to their orbits in 0.4 s.

### Fish (`fish.py`, no strip translation — the scene runs `orbits1d` there)

Orbits' twin as a scene, but the charge and the lull are his own
(2026-08-25, corr=6dd10a8c3c5bd72a) and are the reason the effect exists
separately at all.

- **Charge** — up to `school_count` (12) fish swim in and steer onto ONE
  shared heading, each offset by a little `school_variation` so the school
  is near-identical but never lockstep. The camera follows the school
  perfectly: the fish hold station on screen and the WATER streams past
  instead (the ripple wake is advected by minus the school's velocity).
  Once the school has gathered (45% of the ramp, `CHARGE_FILL_AT`), every
  beat picks a new shared heading, never closer together than
  `turn_min_time` (his 400ms floor); the whole school banks onto it through
  a real arc, because nothing can out-turn the turn radius.
- **Lull** — the school disperses, furthest first, on a rank schedule so
  everyone but ONE fish is gone by `LULL_DISPERSE_AT` (0.42). That fish —
  the one nearest centre when the lull began — keeps swimming while a
  ramping positional pull holds it in the middle of view, fully centred by
  `LULL_CENTER_PROGRESS` (0.5; TIMING HONESTY: SpotFX ramps
  `phase_progress` over ~90% of the real gap and then hangs at 1.0, so p=0.5
  lands at ~45% of the lull's true wall clock — the same convention
  `blackhole.py`'s `LULL_FILL_PROGRESS` records). At `LULL_RUSH_AT` (0.60)
  a rush of `rush_count` (20) fish pours in FROM THE DIRECTION that fish is
  heading and zooms past it with `rush_chaos` spread in heading and speed;
  after `rush_time` (1.0s) exactly `particle_count` fish are kept (the lone
  one counts) and the rest carry on off-panel.
- **Drop** — Orbits' own payoff, unchanged in spirit: configured population
  restored with a centre burst for the missing, plus 2x population of
  ballistic ejecta that bolt straight off the panel; swim speed boosted and
  decaying over `DROP_SETTLE_S`; the phase self-resets so an identical later
  drop edges again.

THE CAP: the charge's school and the lull's rush are the ONLY two moments a
fish scene exceeds `particle_count`, via the `p_nocap` tag. A cap-exempt
fish never survives the moment it was granted for — the rush's own settle
clears the tag on the keepers and departs the rest, the drop and a return to
`phase: none` both release any left over.

### Radial (`radial.py`)

- **Charge** — the spin accelerates in the pattern's apparent direction,
  ease-in so the spin-up peaks exactly at the ramp end.
- **Lull** — the whole pattern implodes to a held center point
  (`_phase_warp`), background fading with it.
- **Drop** — the pattern blooms back out over 0.5 s.

### Fireworks (`fireworks.py`, strip translation `fireworks1d.py`)

- **Charge** — launch rate climbs to 6× while every burst gets smaller
  (×0.4), slower (×0.45), and shorter-lived (×0.6): more and more, less
  and less — pure tension.
- **Lull** — launching stops; 3 guided rockets cross the dark panel from
  the edge to past-center, dimmed 75%, never aging out. (1D: rockets from
  both strip ends toward offset points past the middle.)
- **Drop** — every rocket explodes exactly where it is into a giant
  firework in its own gradient colour (×1.6 speed, ×1.35 life, cap
  ignored); with no rockets in flight, a spread of giant center bursts.
  (1D: two staggered pairs per rocket — one fat layered burst.) Then the
  **drop tail**: a shower of ordinary fireworks launches at
  `DROP_TAIL_RATE` (8/s) easing linearly to 0 over `DROP_TAIL_S` (2.5 s)
  — the charge's linear ramp mirrored on the way out — on its own clock,
  outliving the phase's own `DROP_SETTLE_S` (0.9 s) self-reset. It's a
  launch rate, not a `spawn_rate` multiplier (his real scene runs
  `spawn_rate=0`, beat bursts only, where a multiplier is inert). Payoff,
  burst-flare, tail and rocket particles never occupy `max_blobs`
  (`p_nocap`/`f_nocap`), so the scene's own launches keep coming
  underneath the afterglow instead of pausing for `PAYOFF_LIFE × burst_life`
  (`fx/VENDOR.md` #17, `scripts/check_fireworks_drop_tail.py`).

### Squiggles (`squiggles.py`)

- **Charge** — the silhouette's walls turn solid (`_bounce`: chains turn
  back inward instead of exiting) while spawn rate (+7 chains/s at full
  ramp) and `max_chains` (×2.6) climb: the figure fills with trapped,
  thickening scribble.
- **Lull** — an old-TV switch-off (`_phase_crt`): vertical squash to a
  bright line over the first 55% of the ramp, then a horizontal pinch into
  a single held white dot.
- **Drop** — once the drop ramp completes (gated on `phase_progress` the
  same way Blackhole gates its own payoff, not on the instant phase edge —
  fixed 2026-08-20, PR fm/spectra-squiggles-drop-timing-and-a-much-bigger-
  explosion: it used to burst at t=0 of the ramp, up to a full ramp EARLY
  vs. Blackhole on the same trigger), a 9-chain fan erupts from the center
  (cap bypassed) at 55% of normal speed so it lingers instead of flashing
  past, walls open, population returns to normal ~1 s after the burst.

### Dancers (`dancer.py` — state is `_cld_*`; `self._phase` there is the
beat clock, not this machinery)

- **Charge** — the dance itself intensifies: `dance_intensity` scales up
  to ×2 (capped 2.4) as the ramp builds, with a surge floor so the dancers
  visibly accelerate even in silence.
- **Lull** — every free dancer blends into a held squat (`_SQUAT` pose,
  override weight = ramp): the crew crouches, coiled.
- **Drop** — every dancer fires a `cld_drop` stunt (1.8 s, staggered
  0.08 s apart): coil for the first 15%, then a style picked per dancer —
  breakers (hip-hop/k-pop/robot/floss) freeze-spin with impact flames,
  splitters (ballet/tango/salsa/tai-chi) land a grand jeté into the floor,
  and any dancer may simply leap huge (25% chance).

### Eye (`eye.py`)

- **Charge** — the iris grows (+30%), the pupil constricts (×0.5), and
  the flames reverse to stream INWARD: the eye feeds. A flare recreation
  mid-charge continues the phase (it rides the native handoff snapshot).
- **Lull** — the lids close emoji-style (`_lid_travel`): fast ease-out to
  the iris edge, a near-still pause over the ramp's [0.50, 0.75], then the
  final close (completing at 0.93 so end-of-ramp jitter can't strand a
  slit-open lid); the gaze returns to center.
- **Drop** — if a short lull left the lids mid-close they SLAM shut first,
  then the eye explodes open (0.18 s), a flame burst with a randomness
  spike rides the opening, settling over 1.2 s.

## Where SPECTRA proves it

- `scripts/check_spectra.py` — the drive: arm + ramp writes per class with
  the right durations, non-phase effects untouched, `phase_only` result,
  track-change release.
- `tests/test_spectra_engine.py` — frame-level fidelity on the headless
  harness: the real vendored effect enters the phase, `phase_progress`
  interpolates across render frames, and the drop self-resets to
  `"none"` — the actual state machine, end to end, no lights.
