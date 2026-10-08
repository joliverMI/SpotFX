# SPECTRA responses — the real charge/lull/drop grammar, per effect family

The build/suspend/release choreography for charges, lulls, and drops does
not live in SPECTRA: it lives in the vendored render pipeline, inside the
particle-based effects, DANCERS, and EYE — written there for the original
SpotFX program and carried verbatim into `fx/effects/`. SPECTRA's response
engine (`spectra/services/scene_response.py`) DRIVES that machinery; it
does not re-invent it.

## The universal contract (all twelve phase-capable effects)

Every effect in `fx/device_model.PHASE_EFFECTS` — `blackhole`,
`blackhole1d`, `orbits`, `orbits1d`, `radial`, `fireworks`, `fireworks1d`,
`squiggles`, `dancer`, `eye`, `fish`, `pulse` — carries two config params:

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
   the edge re-fire). EXCEPTION: a one-colour effect (Pulse,
   `fx.device_model.ONE_COLOUR_EFFECTS`) is skipped — and NAMED as
   `withheld` in the surge record — while a house mode's resting look owns
   the room (`house.scene_deferral`), because a lull's true black is only
   right during a music show; every other phase-capable virtual arms as
   before.
2. **Ramp**: a glide of `phase_progress → 1.0` over the class's duration.
   Charge/lull DYNAMICALLY STRETCH to ~90% of `gap_ms` — the real distance
   to where the build ends: a charge's own next lull or drop, a lull's own
   next drop, whatever flare or scene change sits between, else the next
   trigger this song will actually fire (`TriggerEngine.
   _phase_partner_gap_ms`, `spectra/services/phase_partner.py`) — hanging the remaining ~10% at
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

- **Charge** — up to `school_count` (18, +50% from his original 12,
  2026-09-16, watching it live) fish swim in on an even spread and
  steer onto ONE shared heading, each offset by a little `school_variation`
  so the school is near-identical but never lockstep; a separation steer
  (`SCHOOL_SPACING_W`) keeps them from clumping. The view travels with the
  school by `camera_follow`. Once the school has gathered (45% of the ramp,
  `CHARGE_FILL_AT`), every beat picks a new shared heading, never closer
  together than `turn_min_time` (his 400ms floor); the whole school banks
  onto it through a real arc, because nothing can out-turn the turn radius.
- **Lull** (REWORKED 2026-10-08, his own reversal of his 2026-08-28 "no
  lone fish" ruling, on his own word) — the school breaks into its chaotic
  SWIRL round the centre of view exactly as before, and every fish but
  `lull_keep` (told by the LULL HAND-OFF HOOK, `fx/effects/lull_handoff.py`;
  default 1) leaks out of it, furthest first, gone by the lull's HALF-WAY
  mark (in seconds when told the real gap, else `phase_progress` 0.5). The
  kept fish never leak, swirl, count toward the population, or get followed
  by the camera window — from the half until the drop they SEARCH: a slow
  leg to one side, a pause with its head swinging, a leg to the other side,
  and so on; the lull is never dark. Told `lull_keep = 0`, this is
  byte-identical to his original 2026-08-28 clock: thirds of
  `phase_progress`, school swirls and leaks out entirely by 1/3,
  ripples-only to 2/3, DARK after — no fish survives.
- **Drop** — Orbits' own payoff: 2x population of ballistic ejecta bolt
  straight off the panel, swim speed boosted and decaying over
  `DROP_SETTLE_S`. On top of it, a rush of `rush_count` (20) fish — plus any
  kept searcher, rejoining — pours in from every side (a centre burst
  stands in only when `rush_count` is 0), swirls round the centre of view
  for the drop, and at the settle exactly `particle_count` stay behind
  while the rest DISPERSE off the panel; the phase self-resets so an
  identical later drop edges again. REWORKED 2026-10-08: when told the
  fire's intensity (`drop_intensity`), the settle horizon, the boost and
  the rush's entry speed all scale by `lull_handoff.drop_scale` — the
  automatic ceiling (0.75) is this fixed drop exactly, a marked track
  (1.0) runs 20% longer, a quiet song shrinks toward `drop_scale_min`.
  Not told: the fixed constants, unscaled.

Full mechanism (the keeper's search, several keepers riding together for a
drop that lands on another effect, the hand-off hook's resolver contract):
AGENTS.md's Fish section (item 10) and the `fish-effect`/`drop-detection`
skills — not restated here.

A fish leaving for any reason — the lull, the settle, the population
shrinking, an outgoing crossfade into an effect with no blobs of its own —
DISPERSES off the panel rather than fading; only the drop's ejecta fade.
The mechanism is `fx/effects/fish.py`'s dispersal block (`fx/VENDOR.md` #39).

THE CAP: the charge's school and the drop's rush are the ONLY two moments a
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

### Pulse (`pulse.py`, the Singles — a one-colour effect, not a particle
one; single-led-power plan phase 2, 2026-10-06)

- **Charge** — the resting level climbs to `charge_top` (smoothstep of
  progress) while hits keep landing on top (never shallower than
  `CHARGE_MIN_DEPTH`); fades shorten by `CHARGE_FADE_X`.
- **Lull** — the level held at lull entry is multiplied by
  `1 - smoothstep(progress)`, reaching true black exactly when the ramp
  completes — the same clock the crystal and strips use.
- **Drop** — begins ON its first frame at `drop_burst`, whitened by
  `drop_white`, settling over `drop_settle_beats`; the phase then
  self-resets so an identical later drop edges again. A charge or lull
  that ends without a drop eases back over `EXIT_BLEND_S` instead of
  snapping.

Unlike every other family above, Pulse's choreography is WITHHELD (see
the Arm step's exception) while a house mode's resting look owns the
room — true black is only right during a music show.

Pulse also answers two flare kinds of its own (phase 3): **pulse_flash**
(the level jumps by `flash_size` x a strength of 0.4 + 0.6 x intensity and
falls back to a tenth in `flash_ms`, spent from the flash budget; inside a
lull it is scaled by the lull's fade, so the lull still lands black) and
**pulse_flip** (the hue turns `flip_degrees`, holds for `flip_hold_s`
(0.5s), then swings back round the wheel over `flip_fade_s` (1.0s); fires
only above intensity 0.4 by default —
`FlareKind.min_intensity`). Both are instant, self-resetting pokes with no
lead, carry or release.

Fish answers one flare kind of its own (2026-10-08): **big_fish** — one
really large fish crosses the panel behind the ordinary fish, its speed
following the fire's intensity (`big_fish_cross_slow_s` at 0 to
`big_fish_cross_fast_s` at 1, speed linear) and its colour the gradient's
centre turned 120 degrees (intensity 0.2 or less) to 180 (0.5 or more), at
`big_fish_brightness` (0.6). The same instant, self-resetting poke shape:
no lead (it enters on the mark), no carry, no release. The ordinary fish do
not avoid it yet (phase 2).

## Where SPECTRA proves it

- `scripts/check_spectra.py` — the drive: arm + ramp writes per class with
  the right durations, non-phase effects untouched, `phase_only` result,
  track-change release.
- `tests/test_spectra_engine.py` — frame-level fidelity on the headless
  harness: the real vendored effect enters the phase, `phase_progress`
  interpolates across render frames, and the drop self-resets to
  `"none"` — the actual state machine, end to end, no lights.
