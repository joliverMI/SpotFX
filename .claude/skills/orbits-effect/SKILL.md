---
name: orbits-effect
description: >
  fx/effects/orbits.py (Matrix, crystal-mapper) and fx/effects/orbits1d.py
  (Strips) — orbiting-particle effect behind Orbits V2, and the strip
  effect three OTHER scenes' Strips entries reuse (Squiggles V2,
  Dancers V2, Pacman V2). NOT Fish — Fish's own Strips entry is
  `fireworks1d` (live data, see the fish-scene skill), even though its
  Matrix entry is a wholesale copy of this scene's params/bands and moves
  completely differently; see the fish-effect skill for that split.
---

# Orbits / Orbits1d

Matrix effect renders to `crystal-mapper` — load `crystal-hex-grid` first
for anything about coverage/spawn radius on this device.

**Orbits1d is load-bearing for scenes that aren't "Orbits" at all** —
Squiggles V2, Dancers V2 and Pacman V2 all use `orbits1d` for their Strips
entry (their own Matrix effect is something else). A change here can move
four scenes at once (Orbits V2 plus those three); check the live scenes
(`GET /spectra/api/scenes`) before assuming a fix is Orbits-only. **Fish is
NOT one of them** — despite being a wholesale copy of this scene's own
Matrix params/bands, its Strips entry is `fireworks1d` (see the fish-scene
skill's own note on the divergence from its seed script).

## Params worth knowing before tuning

- `orbit_radius` (0.02..0.8): a real geometric radius, degeneracy-guarded —
  `drift_conductor._registry_range()` intersects any drift declaration's
  lo/hi against this param's OWN legal range at Mechanism construction, so
  an authored profile built for a different param (e.g. a [0,1]-ish
  default) can't silently wander below the effect's own floor and get
  rejected by the config schema while the conductor's model keeps moving.
- `reverse` (toggle, "Reverse Spin", default False): read LIVE on every
  frame in `draw()` (`direction = -1.0 if self.reverse else 1.0`), so it
  flips the rotation of EVERY particle AND the tether ring continuously,
  including ones already in flight (`orbits1d`: the oscillation and the
  ring). This is the OPPOSITE of blackhole's spawn-side `reverse` — never
  port a blackhole reverse fix here, or an orbits one there.
- `spin` ("Ring Spin", 0..1, registry aspect `reactivity`): the tether
  RING's rotation speed as a fraction of `base_speed`, boosted by the audio
  impulse (`ring_phase += spin * base_speed * direction * (1 + 0.5 *
  speed_jump * impulse) * dt`). Not a swirl amount — that is Fish's
  meaning for its own `spin` — and not radial's squared audio gain either.
- `speed_jump`/`speed_jog`/`brightness_audio`/`size_audio`: audio gains —
  idle near their floor during quiet passages; see the audio-idle trap
  documented on the radial-effect skill.
- `implode_fade`/`implode_reach`/`bounce_chance`/`overlap_blend`
  (orbits1d only): strip-specific shape/collision params with no Matrix
  analogue — don't assume parity between the two modules' schemas.

## Drop-ejecta persistence is a Little's-Law order statistic

His ask was "3 seconds" for how long ballistic drop ejecta lingers after a
drop. The burst COUNT (`DROP_EJECTA_X=2`, i.e. 3x the configured
population) is explicitly NOT to be touched — it already matches his
stated number. `particle_count` feeds the ejecta count
(`DROP_EJECTA_X * particle_count`), and "time until the last one is gone"
is an order statistic over that count — a higher `particle_count`
mechanically produces a longer worst-case straggler even with an
UNCHANGED per-particle speed distribution. Measure over several RNG seeds
and average; a single run is noisy (`scripts/
check_orbits_drop_burst_and_persistence.py`).

## The lull can be TOLD to keep N blobs (2026-10-08, the fireworks melds)

Orbits joined `fx.device_model.LULL_HANDOFF_EFFECTS` (`fx/effects/
lull_handoff.py`; `fx/VENDOR.md` #64) for the drop-led switch's keepers
meld: a lull leading into Fireworks is told `lull_keep = 3`. Told N > 1,
the lull keeps N blobs (the shortfall flies in from off-panel), the
geometry falls only to `LULL_KEEP_RING` of itself and each blob's own
orbit shrinks to `LULL_KEEP_ORBIT` (`_orbit_scale`), so the N sit on an
evenly spaced ring — distinct origins for Fireworks to explode. Told
`lull_next` another effect, `_handoff_snapshot` flags them (`"keepers"`).
**Told 1 (the default) or untold, the lull is byte-identical to before** —
proven frame for frame against the pinned pre-change module; told 0, it
keeps its one blob anyway (it has no dark lull to fall back to). Orbits'
own drop ejecta burst (`_spawn_drop_ejecta`, `DROP_EJECTA_X *
particle_count`) still does not scale with `drop_intensity` — only the
Shockwave does (below): Orbits is now IN `DROP_INTENSITY_EFFECTS`, widened
2026-10-11 to every `DROP_SHOCK_EFFECTS` member so the Shockwave's own
debris/front-life can scale, but `orbits.py` itself never reads
`drop_intensity`.

## The drop Shockwave and the breath-hold (2026-10-11, transitions-drop plan phase 1)

This effect is a member of `fx.device_model.DROP_SHOCK_EFFECTS`. Its drop
gets the shared Shockwave painted by `Twod.render` AFTER its own `draw()`
(`fx/effects/phase_grammar.py` is the binding statement): a rim bloom, ONE
wavefront born on the tether ring at its resting radius (`horizon_scale` x `radius_scale`), debris (curving back onto the ring) and a wall splash, all in the
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
The lull arm also tells it the BREATH-HOLD (`lull_breath_at_s`,
`lull_breath_s`, from the room's `lull_breath_hold_s`, 0.4 s default, always
inside the lull's dark rule). **On Orbits it is NOT true black** (2026-10-12,
the Admiral: "I want orbits and fish to specifically not go dark completely
on the crystal or the strips" / "orbits should keep at least one dim blob"):
`BREATH_FLOOR = BREATH_FLOOR_DIM` (0.25) makes the base render dim the frame
to that share instead, so the lull's one blob stays, dim, through the
breath (`phase_grammar.breath_gain(..., floor=)`). Do not set it back to 0.
Help topics `drop-shockwave`, `lull-dark-cap` (the breath-hold is folded into it); proof
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

## The STRIP (`orbits1d`) draws its phases through the strip phase layer

Since 2026-10-11 (strip phase plan phase 3; `fx/effects/strip_phase.py` is
the binding statement, `fx/VENDOR.md` #74) the strip's charge/lull/drop
LOOK — hue-kept colour gain, set-colour fill, the drop's set-colour
shockwave, the lull's fade to black at the room's dark point, the white
guard — comes from the shared layer, and so does its phase PLUMBING (edge
detection, the orphan watchdog, the drop's self-reset after
`DROP_SETTLE_S`): the module keeps only `_strip_phase_enter` and its
per-frame `_phase_step`. The phase is `self._sp_phase`. What it owns:

- **Swell and HOLD** (his call 2): the charge swells to `CHARGE_PEAK_N`
  (16, `particle_count`'s own max) over `CHARGE_PEAK_AT` of progress and
  holds there to the drop. It used to shed back to ONE blob by the
  charge's end — do not bring the shed back.
- The lull's one blob collapses to the middle on the layer's OWN lull
  timing (`_strip_phase_lull()`), landing as the strip reaches its dark
  point — and STAYS, dim (2026-10-12, "orbits should keep at least one dim
  blob"): the strip's own `lull_ember` default is `LULL_EMBER` (0.2,
  `STRIP_PHASE_DEFAULTS`, spliced into the schema and the registry like the
  Fireworks strip's 0.12), so the layer fades it to 20%, never black. This
  is every scene that uses `orbits1d` (Orbits, Squiggles, Dancers, Pacman
  V2). Proof `tests/test_particle_strip_phase.py`,
  `scripts/check_particle_strip_phase.py`.
- The strip's drop SHOCKWAVE obeys the crystal Shockwave's switches (the
  room, the scene, the 0.7 top-bar Energy floor — told `drop_shock_on`);
  skipped, only the wave and flood go (`tests/test_drop_feedback_1012.py`).
- The drop re-adds all 16 (each erupting through its implosion), the
  fly-out on its own clock (`_fly`), and sheds back to the scene's own
  `particle_count` on the "none" edge.
- A flare punch in the dark springs the collapsed blob back out (size and
  position follow `_strip_phase_punch()`) with an implosion burst in the
  blob's OWN colour — the lull has no white guard.
- On a phase the implosion pair comes from the SET (the set rotated by a
  third, `_phase_fragment_colours`), never the hue wheel's ±120°, which
  reaches hues the set does not have. Off-phase it is the ±120° pair, and
  every off-phase frame is byte-identical to before.
- ACTIVITY (`STRIP_PHASE_ACTIVITY`): `base_speed` and `spin`, 0.5 each —
  never the count, which is the swell's.

The 2-D Matrix `orbits.py` is untouched by all of this.

## Thematic transitions (2026-10-11, transitions-drop plan phase 3)

The Black Hole's ERUPTION implodes onto Orbits' LIVE blobs (his comment:
"implode into the orbits like the shoaling"): `_formation_points()` gives
every tracked blob's pixel position each frame, and each ejecta lands ON
one with its velocity. Orbits also FEEDS an Infall into the Black Hole:
`_handoff_snapshot` now carries `vx`/`vy` (px/s, from `p_vx`/`p_vy` — SoA
arrays set every frame from the drawn displacement, render byte-identical)
and `gesture: "orbit"`. An incoming Orbits starts FRESH under a program
(the program owns the outgoing particles). `fx/effects/transition_program.py`'s docstring is the binding statement; `tests/test_transition_programs.py` measures it on the real pipeline.

## Sonic reach

Same rule as every effect here: no direct param edit. Sonic reaches these
params only through an existing `FlareKind` on whichever scene binds this
effect — except that a registered param's current value on one scene
entry is reachable through `set_scene_entry_param`, which includes the
strip's strip-phase tunables (`charge_fill` … `flare_punch_glow`,
registered on `orbits1d`).

## Executable proofs

`scripts/check_orbits_drop_burst_and_persistence.py`,
`scripts/smoke_orbits_params.py`, `tests/test_orbits_drop_persistence.py`,
`tests/test_fireworks_melds.py` (keep-N ring, the keepers flag, untold
byte-identity), `tests/test_lull_handoff.py`. The strip on the strip phase
layer: `scripts/check_particle_strip_phase.py` (before/after on his own
Orbits V2 strip entry, the pinned pre-change module as red control) +
`tests/test_particle_strip_phase.py`, `scripts/check_strip_phase.py`.
History: AGENTS.md's "Fish (`fx/effects/fish.py`) — Orbits' twin,
different kinematics" section (how Fish reuses Orbits' patterns but not its
motion) and the drop-timing-reference withdrawal note
(`data/drops-still-fire-early-star-does-not-explode/`).

## Phase 4 transitions (2026-10-11): Shoaling, Shoal Break, Unravel, Flame Lick

- **`p_om`** (SoA, exported as the snapshot's `om`): each blob's heading RATE,
  rad/s in pixel space, smoothed over `OM_TAU_S` from consecutive velocities.
  Render-inert. The SHOALING (Orbits -> Fish) peel reads it: every fish starts
  on its blob turning at the blob's own rate (fish.PEEL_S).
- Orbits RECEIVES Shoal Break (fish dots), Unravel (a chain's dots), Flame
  Lick (the eye's shards) onto its live `_formation_points()`, the same
  Hermite FORM as the Eruption; Orbits -> Squiggles is UNRAVEL (the blobs
  thread onto the chain heads).
`fx/effects/transition_cloud.py`'s docstring is the binding statement for phase 4's programs; `tests/test_transition_programs_phase4.py` measures them on the real pipeline.

## THE HOST FRAME: born matched, with a velocity graft (2026-10-17)

The shoal-burst plan (`/home/javi/fleet-spotfx/data/shoal-burst-plan/
report.md`; `fx/effects/transition_cloud.py`'s `HostFormer` is the binding
statement) made Orbits a form a transition program can be BORN INTO, so the
cloud leaving the old effect rides the new blobs instead of flying to them.
Three things on this effect:

- **`_program_birth(snap)` / `_program_hosts(pids)`** — one blob per
  released object, AT its position, carrying the id the program's cloud
  follows it by (`p_pid`). It is NOT part of `_adopt_handoff`, deliberately:
  the crossfade adoption path is byte-identical and the birth is an opt-in
  capability. `_program_hosts` answers NaN for a retired pid, and those
  pieces fall back to a constant-turn continuation.
- **THE VELOCITY GRAFT** (`p_resx`/`p_resy`/`p_resage`, applied in `draw()`
  after the entering/leaving blend has settled `x, y`). Orbits is
  POSITION-driven — a tether on a spinning ring, a blob orbiting the tether
  — so there is no velocity state to set. Instead
  `drawn(t) = model(t) + v_res . t . e^(-t/tau)` with
  `v_res = v_inherited - v_model(0)`: the graft's own velocity at birth is
  exactly `v_res`, so the blob leaves on the velocity it inherited; the
  displacement peaks at `v_res.tau/e` and returns to zero, so the model is
  never permanently displaced and NOTHING IS SOLVED BACKWARDS (no inverse
  kinematics for slot/phase/radius). `v_model(0)` is MEASURED on the first
  frame after birth, never guessed. `tau` is `transition_graft_ms`.
- **RING ORDER IS CHOSEN, not left to chance**: `_manage_population` hands
  slots out in array order, so the birth orders the born blobs by their own
  angle and rotates that to the ring, which is what keeps each glide into
  orbit short instead of sending a blob across the panel for a slot it never
  had to have. `_count_hold` holds the matched count (3 fish -> 3 orbits)
  until `transition_count_hold_ms` after the program ends, then the
  authored `particle_count` wins and `_manage_population` flies the
  difference in or out exactly as it does for any live change.

Proofs: `tests/test_shoal_burst.py` (every number, with a `git archive` of
the merge-base as the before), `tests/shoal_burst_harness.py` (the rig).
