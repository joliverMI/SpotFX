# SPECTRA responses — the real charge/lull/drop grammar, per effect family

The build/suspend/release choreography for charges, lulls, and drops does
not live in SPECTRA: it lives in the vendored render pipeline, inside the
particle-based effects, DANCERS, and EYE — written there for the original
SpotFX program and carried verbatim into `fx/effects/`. SPECTRA's response
engine (`spectra/services/scene_response.py`) DRIVES that machinery; it
does not re-invent it.

## The universal contract (all ten phase-capable effects)

Every effect in `fx/device_model.PHASE_EFFECTS` — `blackhole`,
`blackhole1d`, `orbits`, `orbits1d`, `radial`, `fireworks`, `fireworks1d`,
`squiggles`, `dancer`, `eye` — carries two config params:

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

`ResponseEngine.on_event("charge"|"lull"|"drop", intensity)` — exactly the
drive the original program used (`services/trigger_engine.py`
`_fire_phase`):

1. **Arm**: an instant `{"phase": <class>, "phase_progress": 0.0}` jump to
   every virtual whose live effect is phase-capable (the `0.0` reset makes
   the edge re-fire).
2. **Ramp**: a glide of `phase_progress → 1.0` over the class's duration —
   charge **4000 ms**, lull **2500 ms**, drop **400 ms** ("drop stays
   short — it's the snap"; `scene_response.PHASE_RAMP_MS`, the original
   program's tuned defaults).
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
  (1D: two staggered pairs per rocket — one fat layered burst.)

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
