---
name: orbits-effect
description: >
  fx/effects/orbits.py (Matrix, crystal-mapper) and fx/effects/orbits1d.py
  (Strips) — orbiting-particle effect behind Orbits V2, and the strip
  effect four OTHER scenes' Strips entries reuse (Squiggles V2,
  Dancers V2, Pacman V2, Fish). Load before touching either module, before
  tuning drop-ejecta persistence, or before assuming Fish's kinematics —
  Fish is a wholesale copy of this scene's params/bands but moves
  completely differently; see the fish-effect skill for the split.
---

# Orbits / Orbits1d

Matrix effect renders to `crystal-mapper` — load `crystal-hex-grid` first
for anything about coverage/spawn radius on this device.

**Orbits1d is load-bearing for scenes that aren't "Orbits" at all** —
Squiggles V2, Dancers V2, Pacman V2 and Fish all use `orbits1d` for their
Strips entry (their own Matrix effect is something else). A change here can
move five scenes at once (Orbits V2 plus those four); check the live scenes
(`GET /spectra/api/scenes`) before assuming a fix is Orbits-only.

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
inside the lull's dark rule): the base render takes the frame to true black
for that window. Help topics `drop-shockwave`, `drop-breath-hold`; proof
`scripts/check_drop_shockwave.py` / `tests/test_phase_grammar.py`.

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
effect.

## Executable proofs

`scripts/check_orbits_drop_burst_and_persistence.py`,
`scripts/smoke_orbits_params.py`, `tests/test_orbits_drop_persistence.py`,
`tests/test_fireworks_melds.py` (keep-N ring, the keepers flag, untold
byte-identity), `tests/test_lull_handoff.py`.
History: AGENTS.md's "Fish (`fx/effects/fish.py`) — Orbits' twin,
different kinematics" section (how Fish reuses Orbits' patterns but not its
motion) and the drop-timing-reference withdrawal note
(`data/drops-still-fire-early-star-does-not-explode/`).
