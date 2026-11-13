# fx/ vendored pipeline and per-effect mechanics

Moved from AGENTS.md during the 2026-11-09 trim (PR fm/spotfx-trim-agents-md).
Content below is verbatim from the prior AGENTS.md; see AGENTS.md's routing table
for when to read this file.

---

## SPECTRA fx/ (vendored LedFX render pipeline, Stage 1)

`fx/` is the LedFX render pipeline vendored from the fork at commit
`149f4470` — provenance, inventory, and the complete deviation list live in
`fx/VENDOR.md` (keep vendored files verbatim; re-diff against that commit
when updating). The in-process switch is `settings.fx_in_process` (default
OFF; production runs HTTP) at the `api/ledfx_client._request()` choke point —
the public client functions are the seam; don't fork per-transport logic in
callers. Offline dummy-device harness: `fx/headless.py` +
`tests/test_fx_headless.py` (deterministic frame-stepping under a fake
clock; `silence_audio()` is mandatory in any fx test — fx must never open or
enumerate audio devices). Stage 2 shared audio ingest: `fx/audio_ingest.py`
(fan-out hub + hub-fed melbank source; design rationale in its docstring) +
`api/audio_ingest_adapters.py` + `tests/test_audio_ingest.py` — DARK, nothing
in main.py references it; production still runs its own capture streams until
a later wiring stage. The Hue-DTLS / DDP single-sender exclusivity with the
running LedFX service is resolved by the S3 ownership gate: the facade
reaches live hardware only through the handover (see the S3 section above).

## A WRITE NEVER STARTS A HOST (`fx_seam.facade_host_ready`)

Found 2026-10-06 when a deploy restart came back with 0 of 5 virtuals up:
`fx.facade.handle()` lazily STARTS a fresh `FxHost` on the default config dir
(`storage/fx`, 0 devices) whenever no host is installed — right for
spot-effects' in-process switch, fatal in SPECTRA. A resume/take assembles
the live stack for ~17 s before `facade.set_host` runs; a trigger crossing
on the playing song in that window sent a scene write through the facade,
the facade started an EMPTY host, and the real stack then loaded every
virtual against an empty device registry ("segment schema rejected the
stored segments ... data[0]" for all of them). So with SPECTRA owning, every
in-process write path asks `fx_seam.facade_host_ready()` first (facade host
installed AND `live.assembling` False): `fx_seam`'s primitives refuse with
`HostNotReady` (a `HandoverInProgress`, so existing handlers treat it the
same), `FacadeExecutor` models the write and sends nothing, and
`device_console` refuses a live edit (its list answers from the stored
config). Logged once per episode. **A new module that calls
`fx.facade.handle` from `spectra/` must make the same check.** Spec:
`tests/test_no_lazy_host_on_write.py` (a trigger fired mid start-up, with a
red control that reproduces the empty host).

## A CONFIG LOAD IS AN ORDERED PROGRAM — a virtual's restore can undo its neighbour's

Found live 2026-09-01 (`fx/VENDOR.md` #29, PR fm/tvmapper-cold-load-fix): his
`tv-mapper` came up DARK after every SPECTRA restart, deterministically, and
nothing above INFO said so. Three things generalize past this one virtual:

- **Activating a virtual is not a private act.** It registers segments on
  each backing device, and `fx/devices/__init__.py::Device.add_segments_batch`
  deactivates every EXTERNAL virtual streaming to a device whose OWN
  device-virtual is activating (and vice versa). So a virtual's restore can
  silently undo one that already came up. `Virtuals.create_from_config` used
  to restore a stored effect through `set_effect()`, which unconditionally
  activated — even for a virtual stored `active: false`, which the loop then
  set back two statements later. A no-op on itself; permanent on its
  neighbours. `set_effect(..., activate=False)` is the fix, and the STORED
  `active` FLAG now decides. **Before adding anything to a config-load loop,
  ask what it does to virtuals ALREADY loaded — config order is the program,
  and his real ordering (tv-mapper idx 14, both sconces idx 22/27) is what
  made this deterministic rather than a race.**
- **Read the end state back; a step that looked fine when it ran proves
  nothing.** `Virtuals._audit_restored_effects` runs after the whole config
  is loaded and names every virtual the stored config says should be driving
  and isn't — it does not need to know HOW one was stopped, which is exactly
  why it catches this class. `_record_restore_failure` logs at ERROR with the
  virtual, the STORED EFFECT TYPE and the real reason, and
  `Virtuals.restore_failures` carries it to `live_host.activation_gaps` —
  which previously GUESSED "effect restore failed silently at config load"
  and was wrong about this very defect. **A status surface that invents a
  cause is worse than one that says "unknown".**
- **A repair that lies is worse than a failure that is loud** (the captain's
  own ruling). An evicted virtual still HOLDS its effect object; it just runs
  no render thread. So a same-type effects PUT took `facade._effects_put`'s
  `use_tween` / in-place `update_config` branch, which never touches
  `virtual.active`, and returned success: real glide writes in
  `executor.recent_writes`, operator satisfied, fixture dark. Only a
  TYPE-SWITCH write appeared to fix it, because that branch calls
  `set_effect()` — and that asymmetry was the best diagnostic clue.
  `facade._verify_effect_took` now reads the LIVE INSTANCE back on every
  effects PUT (object exists, not a `DummyEffect`, right type, virtual
  actually active), attempts one honest repair, and 500s by name otherwise.
  **A write call returning is never evidence that the write took.**

**How a latent ordering bug became live, and the mapping feature's part in
it:** a device virtual with NO stored `effect` key never enters the restore
branch, so it never activated and never evicted anything. His three
(`tv-backlight`, `sconce-kitchen-left`, `sconce-kitchen-right`) each now hold
`singleColor` at `#000000` brightness 0.0 — `room_mapping.MAP_EFFECT_TYPE` +
`BLACK` verbatim — with `pixelRange`/`pixelPattern` in their stored `effects`
history, lamps that exist nowhere else. `activate_for_capture` writes an
effect and raises the active flag through `fx_seam`, i.e. the facade's
`_effects_post` + `_virtual_put_active`, and BOTH call `save_config()`: a
capture run PERSISTS a stored effect onto a device virtual that had none.
Those values are his own runs' genuine residue, not corruption — the load
path was what was wrong to act on them — so nothing in his config was
rewritten. The ACTIVE-flag half of that residue (an interrupted run leaving
a device-virtual stored activatable), and the one-time repair for a config
already carrying it, is deviation #37 — see the Rooms section's own bullet
above (`room_mapping.transient_activate`,
`scripts/repair_copy_carrier_active_flags.py`). **Anything that borrows a
virtual and puts it back should know it is writing his stored config, not
just the live host.**

Proofs: `tests/test_cold_load_effect_restore.py` (cold start in a FRESH
INTERPRETER per the light-mode cold-start precedent — a warm pytest process
cannot speak honestly about config load order; 5 of its 7 tests verified RED
against the unfixed code, the lying repair reproducing as literal
`200`/`success` with the virtual still dark) and
`scripts/check_cold_load_effect_restore.py`, which cold-loads HIS OWN
`storage/spectra/fx-live/config.json` READ-ONLY with every device swapped for
a dummy of the same pixel count: unfixed, exactly one virtual comes up dark
and it is `tv-mapper`; fixed, all five declared-active virtuals drive. **That
dummy-swap is the general recipe for proving anything about his real config
offline** — it is the only change made, so ordering, segments and pixel
counts are all his.

## A colour set's background MODE lands in ONE place: `Effect.get_pixels()`

The Admiral's 2026-10-07 report ("the fish effect seems to not obey
overwrite from colors. it may be same with other effects") was right and
was never in `fish.py`: `Twod.render()` pre-filled the Matrix canvas with
the background in overwrite mode, so every effect that paints ONTO that
canvas (Fish, Orbits, Fireworks, Black Hole, Dancer, Eye) composed
body + background and the base layer then doubled it on every dark pixel
(`fx/VENDOR.md` #60, the canvas now always starts black); Black Hole's
horizon disc and Eye's lids ALSO painted `_bg_color` themselves and were
the one region still doubled after that (#61 — they paint black now).
**The rule: an effect never paints `self._bg_color` into its own canvas.**
Black is "shows the background" once `get_pixels()` has run — in BOTH
modes, exactly once. `radial.py`'s explosion-fade bg term is the one
deliberate self-painter (#62: it switches `bg_color_use` off while it
paints, so the base layer never doubles it; bg-blocked in the registry
anyway) and `pulse.py` opts out of backgrounds entirely. Before
reasoning about any "effect X ignores overwrite/additive" report, run
`.venv/bin/python scripts/check_effect_background_mode.py [effect]` — it
renders every registered effect in both modes on the real pipeline and
reads the lit-pixel blue against each mode's own curve;
`tests/test_effect_background_mode.py` holds the same contract over every
effect, with red controls for both defect shapes.

## Black Hole (`fx/effects/blackhole.py`) — four things that bite

Everything below is recorded in `fx/VENDOR.md` (#12, #14, #18, #19, #20,
#38)
with the mechanism detail; this is the short list of traps.

1. **`reverse` is a SPAWN-SIDE flag that also picks the sign of every live
   blob's motion.** Nothing reverses a particle already in flight, which is
   why flipping it back used to snap the whole outbound population around
   in one frame. Since 2026-08-24 the True→False edge arms a real
   turnaround (`_reverse_edge` → `_arm_reverse_fallback`, `p_turn`/`p_vr`,
   `REVERSE_FALLBACK_TURN_S`) that merges back onto the speed curve with no
   step at either seam; the outward eject stays instant by his own ask.
   **Do not "fix" a horizon captive by releasing it** — PR #179 did exactly
   that and was reverted the same day (#181, no reason recorded): a release
   also evicts blobs the flare never moved AND makes them immortal (the
   infall alive-test retires captives by their hold clock and never
   free-fallers). The shipped fix instead pins a captive to the ring only
   while it is AT the ring (`REVERSE_FALLBACK_RING_TOL`).
2. **Two particle flags, not one.** `p_nocap` = "spawned past max_blobs"
   (the drop payoff, the blob rush, the charge's forced formation) and is
   what the density-cap arithmetic reads; `p_is_burst` = "a drop-payoff
   particle" specifically, and additionally drives
   `PHASE_BURST_SPEED_MULT`. Anything measuring the explosion filters on
   `p_is_burst`; anything about the cap uses `p_nocap`. Conflating them
   silently changes what the explosion measurements report.
3. **The charge no longer swallows the panel, and the lull's fill stops at
   the HEX bound, not `r_max`.** `HEX_FILL_RADIUS` (1.128, computed from
   the measured `HEX_SPAWN_VERTS`) is where every real cell is already
   covered; `r_max` (~1.49) is the addressable RECTANGLE's corner and every
   pixel of growth past the hex covers dead cells — that gap was his "it
   currently expands too far". Any "is the panel dark?" measurement on this
   device must be taken over the REAL cells (the device profile's mask), not
   the dummy rectangle a headless harness renders — see
   `scripts/check_blackhole_charge_lull.py` for the instrument and
   `.claude/skills/crystal-hex-grid/SKILL.md` for why.
4. **A BLOB POPULATION IS LITTLE'S LAW, so a spawn RATE is not a blob
   COUNT.** Blobs are captured by the horizon and retire, so the live
   population is `rate × how long a blob stays visible` — and the charge's
   own `_phase_speed_mult` keeps shortening that time as it ramps. Raising
   `CHARGE_SPAWN_RATE_MAX` from 12 to 45 moved the measured count from 19
   to 41; integrating the rate would have predicted nearly four times the
   blobs. **Measure the count on rendered frames; never derive it.** Two
   companion traps, both of which have already cost a wrong answer here:
   a VISIBLE blob means `p_cap < 0` (a captive is pinned on the ring and
   blending to the horizon colour — it is "in the event horizon") AND
   `r <= HEX_FILL_RADIUS` (past that his crystal has no real cells, so a
   particle parked there is not on screen); and the drop's TOTAL visible
   peak is NOT its payoff — `_phase_step` releases every captive on entry
   (`p_cap = -1`), so the total is `PHASE_BURST_N` plus whatever the
   charge/lull just fed the horizon, and it therefore GROWS with the charge
   (81-118 → 148-199 across one calibration). Anchor a ratio on
   `p_is_burst`, never on the total, or the target is a divergent fixed
   point. `fx/VENDOR.md` #38 is the binding statement; the instrument is
   `scripts/check_blackhole_charge_target.py`.
5. **`max_blobs` gates INFALLING blobs only, not every captive too
   (2026-10-17, bh-infall-plan, option D — the Admiral: "just do option
   D").** Before this, `_spawn`'s density check counted every ambient
   (non-no-cap) blob — horizon captives included — against `max_blobs`,
   so under busy music the captive QUEUE ALONE (spawn rate × its
   `horizon_hold + HORIZON_FADE_S` ≈ 3.6s hold+fade) filled the cap and
   fresh infall stalled to ZERO for seconds — worst right after a scene
   transition INTO Black Hole, which lands the whole outgoing cloud onto
   the ring as captives in one frame (the transition programs' own
   `INFALL`/`ERUPTION` hand-off, see "TRANSITION PROGRAMS" above). `_spawn`
   now counts only `p_cap < 0` (not yet captured) and not `p_nocap` against
   `max_blobs`; `CAP` (1024) still bounds the hard buffer regardless, and
   with `max_blobs` well under it a full captive queue plus a full
   `max_blobs` of infalling can never approach that limit — no separate
   captive budget was built (his own call, accepted trade-off: a denser
   ring under busy music — 58 vs 43 measured captives in the plan's own
   rig — not a busier field). C (muting the Black Hole's own picture
   under the program) and A (a seeded starting population) were proposed
   in the same plan and NOT built; B (split the cloud, let some fall
   instead of all landing on the ring) was measured worse than today and
   rejected. Spec: `tests/test_blackhole_infall_through_transition.py`
   (a real Orbits→Black Hole transition and a steady-state run, both
   proven RED against the pre-fix accounting restored inline as the
   control).

## A SATURATING SIGNAL MEETING `>=` MAKES A "never" THRESHOLD FIRE

Found 2026-09-02 turning the Dancer's flames off (`fx/VENDOR.md` #31,
PR fm/dancer-flames-off). Every audio power in this pipeline is CLIPPED
to exactly 1.0 upstream (`fx/effects/audio.py::_update_freq_power`'s
`np.minimum(freq_power_raw, 1)`), and an `ExpFilter` over it converges to
EXACTLY 1.0 in float within ~9 audio frames (~150 ms at 60 Hz). So a
user threshold whose Range max is 1.0 — the setting whose whole meaning
is "never" — FIRES on any loud passage the moment the comparison is
`>=`. It is not an overshoot past 1.0, so **clamping the signal fixes
nothing**; the comparison is what has to exclude the top of the range.
Prefer `thr < 1.0 and sig >= thr` over switching to a strict `>`: `>`
also changes the exact-equality case at every OTHER threshold, and a
saturating signal reaches exact equality routinely, so an existing
setting can no longer be claimed bit-identical.

Known instances of this shape, checked not assumed (only the first is
fixed; the rest are reported, and the captain decides):
`fx/effects/dancer.py:1149` `burst_threshold` (FIXED),
`fx/effects/eye.py:574` `snap_threshold` (same defect, unfixed),
`fx/effects/dancer.py:393` + `fx/effects/keybeat2d.py:479`
`min_volume` compared `>=` against a [0,1]-clamped volume — while
`fx/effects/audio.py:1173` and `fx/effects/melbank.py:540` compare the
SAME setting with strict `>`, where 1.0 genuinely does mean never. When
adding any audio gate, check which side of that split you are on.

**And a gate is rarely the only source.** The Dancer has FOUR flame
sources and `burst_threshold` gates only two (beat bursts, the ember
trickle); the flourish payoff burst and the six `_impact_flames` stunt
moments are ungated, so no threshold value can silence them —
`burst_size = 0` is the other half of "off". Before promising a knob
turns something off, enumerate every caller of the emitter, not just the
one the knob's name suggests. Proofs (harness + pinned pre-change
baseline, offline on `fx.headless`):
`tests/test_dancer_flames_off.py`, `scripts/check_dancer_flames_off.py`.

## Fish (`fx/effects/fish.py`) — Orbits' twin, different kinematics

A new Matrix effect + a Fish scene that is a WHOLESALE COPY of his Orbits V2
(flare kinds, bands, initial params, weightings, curves, labels — see
`scripts/seed_fish_scene.py`, dry-run default, and `docs/SPECTRA_SPEC.md`
§94). Eight things to know before touching it:

1. **It reuses Orbits' patterns, not its motion.** Each fish has its own
   position, speed and SCREEN-space heading; the thin oval's head is laid
   out along that heading (never in normalized space — that would shear it
   by the panel's aspect; the rear half follows the recorded path, see 8).
   A real turn RADIUS (`orbit_radius`, re-read) caps the turn rate, so an
   about-face is structurally an arc. Several shared param keys keep their
   names but mean something else on a fish (`orbit_radius` → turn radius,
   `spin` → current swirl, `horizon_scale` → home ring, `base_speed` → swim
   speed, decoupled from the turn radius) — the registry `note` on each says
   so; read it before assuming Orbits semantics.
2. **The population-cap bypass is scoped to two moments**, by his own
   decision: the charge's school and the DROP's rush, via `p_nocap` (the
   rush was the lull's until 2026-08-28 — see 6 below). A cap-exempt fish
   never survives the moment it was granted for, and ordinary swimming
   always obeys `particle_count`. Don't widen this.
3. **Mutual avoidance is STEERING ONLY** (`avoid_strength`, 2026-08-28 —
   his own 2026-08-25 deferral un-parked). It adds one more weighted term
   to the desired-heading sum and is bounded by the SAME turn-rate clamp as
   every other steer, which is what makes both fish laws structural rather
   than best-effort. Three things not to undo: only neighbours in the
   FORWARD arc count and the answer is a lateral swerve (a point-away
   vector asks for a 180 and measurably made crossings WORSE); the
   separation radius is DERIVED from body length, never a second knob; and
   it is off during the charge's school and the drop's rush, which are
   authored choreography, not crowds to fix. Sweep + tuned default:
   `scripts/check_fish_avoidance.py`.

4. **A strong beat LUNGES** (`LUNGE_*`, 2026-08-28) — his live diagnosis:
   the ripple scales off real speed and flap correctly, but the beat speed
   boost used to decay within tens of ms, so big ripples rode tiny travel.
   The envelope holds the boost near full for `LUNGE_HOLD_S` so a beat
   covers several body lengths. Motion side only; the wake was deliberately
   NOT touched (it self-heals once the travel widens). It rides
   `speed_jump` x the existing spike signal and adds NO knob, and arms only
   above `LUNGE_SPIKE_MIN` so quiet swimming stays byte-identical. Sweep:
   `scripts/check_fish_lunge.py`.

5. **Positions are a WORLD FRAME and the panel is a WINDOW onto it**
   (`camera_follow`, 2026-08-28): the render subtracts a camera origin
   (screen = world - cam), and AT REST THAT MAPPING IS THE IDENTITY — which
   is why `camera_follow=0` is byte-identical to the pre-window effect, not
   merely close (`tests/test_fish_camera.py` proves it against the
   PRE-CAMERA BASELINE's own module, loaded out of git as a second
   registered effect — reuse that trick for any future byte-identity claim
   in `fx/`). That baseline ref is PINNED, and imported from
   `scripts/check_fish_camera.py::BASELINE_REF` rather than copied: it was
   originally the moving ref `master`, which silently retired the whole
   proof to `pytest.skip` the moment the camera merged. **A false alarm is
   loud and gets fixed; a permanent skip is silent and reads as green** —
   when an instrument's reference moves out from under it, pin the
   reference, never silence the instrument. What the knob
   actually does is UNDO A CLAMP: the charge already held the school on
   screen by subtracting the school's own velocity from every swimming fish
   — a window locked rigidly to the shoal — so `camera_follow` is the
   fraction of that travel handed back to the fish, with the window
   following at its own lagging, speed-capped pace. Three things not to
   undo: the window moves ONLY during the charge and the lull; it follows
   only fish it can currently SEE (which is what makes "the school is never
   lost" structural rather than tuned, and what stops a rush stayer
   converted far off-window from dragging it away); and ripples are stored
   in WORLD px so they are left behind in the water, with anything far
   off-window CULLED, never wrapped. Everything naming the visible water —
   pond bound, home ring, "inward", the lull's centre pull, where arrivals
   and the drop's burst appear — is measured from the window, not a fixed
   world point, or the school would just circle a stationary pond. The lull's
   own centre pull is deliberately left WHOLE (it is what holds his "stays in
   the centre of view" to 4px); relaxing it with `camera_follow` is a design
   fork, not taken. Measured basis for the 0.8 default, and the honest
   surprise that the CHARGE's wake already streamed on master (so the gain
   there is the shoal moving, not the water starting to):
   `scripts/check_fish_camera.py`.

6. **THE WAKE, THE CHARGE'S SPREAD AND THE LULL CLOCK were all replaced
   2026-08-28** (`fm/fish-ripples-charge-lull-rework`), on his word. Do not
   restore any of the three out of loyalty to what was there before.
   * **The wake is Orbits' trail, plus expansion.** One persistent
     accumulation buffer (`self.wake`) decayed exponentially AND diffused
     outward every frame; deposits are soft FILLED splats at the tail, laid
     every frame through the same `_splat_many` each body segment uses.
     There is no ripple ring buffer, no radius, no outline — his objection
     was the visible circle line. Energy still rides speed x flap, never a
     beat value. It is SCREEN space but WORLD anchored: rolled each frame
     by exactly the displacement the world->screen mapping moved, with the
     sub-pixel remainder carried; what rolls off an edge is dropped, never
     wrapped. **Its colour rule is stated in the module and read off the
     RESOLVED gradient curve, never the config string** — a solid palette
     gives it substantially less brightness (`WAKE_SOLID_DIM`); a real
     gradient gives it `wake_hue`'s colour. **His 2026-10-26 option A
     reversed the gradient half** (the opposite colour ADDED onto the
     bodies was what washed rainbow scenes out to white): the default is
     the fish's own colour, met by `wake_blend = lighten` in `_composite`,
     the matrix's ONE writer; `opposite` + `add` is the old render bit for
     bit, and a pinned PIXEL proof must hold it there. Measured proofs:
     `scripts/check_fish_wake.py`, `scripts/check_fish_wake_blend.py`; the
     fish-effect skill has the rest.
   * **The charge spreads.** An even (low-discrepancy) spawn plus an
     omnidirectional separation steer (`SCHOOL_SPACING_W`), weighted well
     under `SCHOOL_W` so the shared heading still governs the unison
     arrival. `avoid_strength`'s forward-arc dodge is still OFF in a
     school; these are different terms. Before/after against the merge-base:
     `scripts/check_fish_charge_spread.py`.
   * **The lull is a CLOCK in thirds of its own (dynamic) duration**: every
     fish gone by 1/3 — no lone fish, no survivor, with a hard backstop, not
     just a schedule; ripples only to 2/3; fully dark after (the wake is
     RAMPED to zero, because a half-life never reaches it). The window eases
     home once there is nothing left to follow — since 7 below, from the
     lull's first frame, because every fish is dispersing from the moment
     the swirl starts. **The lull's rush MOVED INTO
     THE DROP** (his addendum): it rushes in at the drop instant, swirls for
     the drop's duration (`RUSH_SWIRL_W`), and `particle_count` of them stay
     behind — read ONCE at the settle, after which the ordinary
     intensity-driven count owns the population again through the normal
     entry/exit paths (`_settle_rush`'s docstring is the binding statement).
     With `rush_count` at 0 the drop is exactly what it was.
   * **`scripts/check_fish_camera.py::BASELINE_REF` moved forward** to that
     PR's merge-base, because the old "camera_follow=0 IS the pre-camera
     commit, bit for bit" claim needs a reference differing ONLY by the
     camera, and the wake changes the render at knob zero. What it asserts
     now: the window origin is EXACTLY zero at knob 0 across the whole arc.
     Its ordinary-swimming comparison (1b) has since moved to its own pin,
     `THRUST_BASELINE_REF` — see 8.

7. **A FISH NEVER FADES OUT — IT DISPERSES (2026-09-16,
   `fm/spotfx-fish-disperse-and-speed-flare`, his words: "the fish shouldn't
   fade out, they should disperse off the screen").** Every exit — the
   population trim, the lull, `_settle_rush`/`_release_nocap`, and an
   OUTGOING crossfade into an effect with no blobs of its own — is ONE mode, DISPERSING
   (`p_mode == 4`): full brightness, steered out of the window under the
   same turn clamp, retired only once the whole body is off the panel. Mode
   2 (a linear fade) now belongs to the drop's ejecta ALONE. Three things
   not to undo: (1) a dispersing fish carries a DEADLINE (`p_dl`, effect
   clock), and its speed is DERIVED every frame from the distance still to
   cover (`_disperse_speed`, measured along its heading, bounded by the
   outward line plus a half turn) — never a tuned speed, which is what lets
   a 900 ms lull and a 6 s one both land; (2) the lull CLOCK is his
   2026-08-28 thirds, unchanged — only the manner moved (school → swirl →
   rank-ordered leak, `LULL_LEAK_*`, with `LULL_EXIT_MIN_S` meant to make a
   lull too short to swirl in scatter straight out rather than be retired
   on the panel by the backstop. fm/spotfx-fish-body-trails-head-tail-
   thrust found that margin thin: at his tightest tested gap, 0.9s, 3 of 60
   seed/gap combinations left one straggler still on the panel the instant
   the hard backstop empties the population, which pops at full brightness
   with no fade — exactly the visible defect this whole mechanism exists to
   prevent. `DISPERSE_TAU` 0.07 -> 0.05 (0 of 60 fail) is a MITIGATION, NOT
   A STRUCTURAL FIX: it widens a sampled margin. At a 0.9s gap the ramp is
   ~0.81s, the third lands at ~0.27s and the exit aim
   (`LULL_GONE_AT * LULL_EXIT_BY`) at ~0.248s, leaving ~22ms (~1.3 frames,
   shorter than the dispersal ease itself) before `_lull_step`'s
   unconditional instant `_compact` — a pre-lull state the check does not
   sample (another song, population, no charge first, real dt jitter) can
   still leave a fish there. Known, accepted, follow-up-worthy: make the
   backstop disperse rather than pop, or state the exit margin in absolute
   time. `scripts/check_fish_disperse.py` §1 keeps the check strict over the
   states it samples; (3) the crossfade scatter is SKIPPED when the
   incoming effect adopts the fish as its own particles
   (`TRANSITION_ADOPTERS`, keyed by module basename: blackhole, orbits,
   fireworks, squiggles, eye, dancer, fish — measured, each reads the live
   fish snapshot and spawns from it; scattering too would show the shoal
   twice), radial keeps its collapse, and everything else (pacman included —
   it has no adopt path) scatters. The scatter's body gain (`1 / (1 -
   weight)`, floored) compensates only an ADDITIVE blend and only the
   bodies, and reads the weight ONE FRAME AHEAD (the virtual advances its
   counter right after rendering the outgoing effect) — but it CANNOT keep a
   fish at full brightness: the virtual clips the outgoing frame at 255
   before weighting it by `(1 - weight)`, so a saturated core dims anyway.
   A named, accepted limit, measured on rendered pixels in
   `check_fish_disperse.py` section 2 (the numbers are in the comment beside
   `TRANSITION_GAIN_FLOOR`); lifting it needs a change to the virtual's
   blend, not to the effect. A gained body clips HUE-PRESERVING
   (`_clip_body_layer`, scatter only — ordinary swimming keeps its exact
   per-channel clip), or a saturated colour washes toward yellow-white on its
   way out; section 2b reads the rendered chromaticity of lone fish and puts
   the per-channel clip back as its red control. Scope: `fish.py` only — the Fish scene's Strips
   entry is still `orbits1d`, which still fades.
   **The swim burst is an ordinary momentary TOGGLE flare** (`swim_burst`,
   registry-declared so `_compute_param_moves` lands a real bool): the
   effect owns only a level, the flare kind owns ALL the timing (`hold_ms`
   = length, 300; `trigger_offset_ms` = start, authored 0 — it fires ON the
   trigger, by his own correction; an early start is deferred to per-flare
   trigger-moment work, because a kind's offset moves its whole band).
   Sonic's `set_flare_kind` carries `trigger_offset_ms` for it, and on an
   update `trigger_offset_ms`, `hold_ms`, `params`, `gain` and `jump` are all
   omit-means-keep like `enabled` — "make it 400ms" is `hold_ms` alone — each
   carried only where the requested type accepts it. `scripts/add_fish_swim_burst_flare.py`
   pools it in a pick-one "Shape" lane with the band's MOMENTARY shape
   flares (so Reverse fires half as often) and refuses a band where a
   "Shape" lane already exists. Proof + red controls:
   `scripts/check_fish_disperse.py`, `tests/test_fish_disperse.py`.

8. **THE BODY IS THE HEAD'S OWN RECENT PATH, and speed is REAL TAIL-STROKE
   THRUST, not a smooth target (2026-09-16, `fm/spotfx-fish-body-trails-
   head-tail-thrust`)**. His complaint: "their bodies don't seem to bend
   naturally as they turn in a radius... facing the tangent but should be
   facing the curvature." His ruling: body-trails-the-head over a literal
   bend model, "the tail flipping is what drives the speed."
   * **Backbone**: the front half of the spine (`SPINE_U<=0.5`, the head)
     still points the CURRENT heading by straight extrapolation — a fish's
     nose really does lead. The trailing half is walked back along a per-
     fish recorded path instead (`p_trail_x`/`p_trail_y`, `BODY_TRAIL_LEN`
     x `BODY_TRAIL_STEP_PX` of screen-px arc length, pushed by REAL travel
     distance every frame — never time-sampled, so the trail always covers
     roughly the same physical distance regardless of current speed).
     EVERY moving fish records, drop ejecta included, and each sample is
     laid at the exact crossing point (several per frame when travel
     needs it), so `p_trail_acc` IS the path distance back to trail[0] —
     rear nodes are placed at `acc + (k-1)*STEP`, never a whole sample per
     index, which made the tail collapse and regrow after every push. The
     path is recorded IN THE WATER: travel is the fish's UNCLAMPED swim
     velocity, and whatever the charge's school clamp took out of its world
     travel (`_flow_px`/`_flow_py`, the wake's own carry) moves its stored
     samples too — recorded in the world alone, `camera_follow=0` folded a
     schooling fish's tail forward over its head.
     `_draw_bodies(..., use_trail=False)` keeps the old all-heading layout
     for the one caller with no recorded path of its own (the outgoing
     radial collapse, which overwrites position/heading into a synthetic
     spiral every frame). A straight run's trail IS that straight line, so
     the backbone reduces to exactly the old rigid stick there; a real turn
     bends through the arc actually swum.
   * **Thrust**: `min_drift_speed` (a floor, fraction of the plain
     continuous target this effect always computed) plus a pulse synced to
     the SAME `p_flap` phase the visual flap already runs on, capped by
     `stroke_speed_cap` (a fraction of that same target) — one pulse per
     flap cycle. THE DIAL IS HIS ESCAPE HATCH, not two redundant knobs:
     `min_drift_speed=1, stroke_speed_cap=0` reduces `want`/`tau` to
     exactly the old formula (bit for bit — proven both in
     `tests/test_fish.py` and against the real pre-thrust merge-base in
     `scripts/check_fish_camera.py` section 1b, which is why THAT script
     carries its own separate `THRUST_BASELINE_REF` rather than moving the
     shared `BASELINE_REF` — see that constant's own comment on why moving
     it broke `check_fish_charge_spread.py`'s unrelated before/after).
     Lowering the floor and opening the cap gives pure surge-and-coast.
     "More jerky in slow music" (a separate, earlier ask) falls out of this
     for free: quiet audio lowers the continuous target, which lowers
     `speed_norm`, which lowers `flap_freq`, spacing pulses further apart —
     no bolt-on jitter.
   * **THE SHIPPED DEFAULTS MUST PRESERVE THE OLD MEAN SPEED — found live
     2026-09-17, when a rebase onto #279's swim-burst boundary brake
     surfaced it.** The first-shipped defaults (`min_drift_speed=0.6`,
     `stroke_speed_cap=0.45`) averaged only ~0.77x the old continuous
     target over a full stroke cycle — a real, unasked-for 23% slowdown
     (measured: 13.39 vs 17.50 px/s at a fixed test config) that #279's own
     regression test caught: its unbraked-burst negative control stopped
     overshooting at all, because the burst's fixed 3.2x multiplier now
     rode an already-smaller baseline. His correction and the governing
     principle: **a pulse redistributes speed in time, it must not reduce
     the average** — within one stroke cycle a fish surges and coasts, but
     across a whole cycle it covers the same ground the old smooth target
     did. The shipped defaults (`min_drift_speed=0.85`,
     `stroke_speed_cap=0.4`) are DERIVED, not tuned by eye: `pulse_shape`'s
     own cycle mean is `PULSE_SHAPE_CYCLE_MEAN=0.375` (an algebraic fact of
     the shaping curve, not a measurement), so `want`'s cycle mean is
     approximately `min_drift_speed + stroke_speed_cap*0.375`, solved for
     `==1.0`. FIRST-ORDER, not exact: `flap_freq` rises with speed, so the
     stroke runs faster through the surge and the measured mean lands
     slightly low — a bias that grows with `stroke_speed_cap`.
     Measured on the real pipeline: mean speed at the new defaults is
     17.4681 px/s against 17.4960 px/s at the dial's neutral setting
     (0.16% low, held within 1% by `tests/test_fish.py::
     test_default_dial_preserves_the_old_mean_speed`), and #279's negative
     control passes again unmodified (unbraked overshoot ~3px both seeds,
     matching master's own 3-5px). **The two sliders stay fully
     independent** (his own requirement) — this constraint binds only the
     two DEFAULT values together, never the runtime relationship between
     them; moving either off its default is still free to raise or lower
     the mean, same as always. Changing either shipped default number
     requires re-solving this equation for the other (see the THRUST
     comment block in `fish.py` and `config/effect_params.json`'s matching
     defaults), or the defaults will silently reintroduce a mean-speed
     drift exactly like this one.
   * **SCOPED to the ordinary population only** (`mode<2`, `p_nocap==0`,
     AND not while `_school_on`) — the charge's school and the drop's
     rush are authored choreography, not ordinary swimmers, the same
     reasoning (and the same `_school_on` flag) that already keeps mutual
     avoidance off during a school; a pulsing speed there measurably
     perturbed `SCHOOL_SPACING_W`'s own tuned spread and had to be
     excluded, not re-tuned. `p_nocap` alone misses half the school: the
     charge counts and steers the fish already swimming as school members.
   * **A body-shape ("goldfish") change was asked for, then explicitly
     withdrawn same-session** ("just disregard the goldfish thing") — if a
     future ask revives thicker/rounder fish bodies, it is a fresh ask, not
     something this PR quietly shipped and someone forgot to mention.
   * **Sonic-adjustable**: both dial fields are ordinary `CONFIG_SCHEMA`
     entries AND registered in `config/effect_params.json` (Sonic's param
     discovery reads type/range from the registry), so once deployed they
     are tunable without another deploy. Help: `fish-effect`.
   * **THE TAIL DRIVE (2026-10-26) goes the rest of the way and fades this
     dial out** (`tail_drive`, the module's TAIL DRIVE block, his "would
     show it's tail swimming and that motion would visually propel the
     fish"): the music sets an EFFORT and the tail's own drawn stroke makes
     the thrust, so the tail moves first and the fish surges after it.
     `tail_drive = 0` (the schema default) runs none of it — the old motion
     bit for bit — and only the music Fish scene turns it on
     (`scripts/set_fish_tail_drive.py`, a deploy step). Proof:
     `scripts/check_fish_tail_drive.py`; the fish-effect skill has the
     rest.
   * **THE POND REST (2026-10-26)** (`quiet_rest`, the module's POND REST
     block, his "the fish should almost come to a rest, with very sporadic
     short motions, like real fish in a pond"): it hears `volume()`, the
     ABSOLUTE level (the band powers are auto-gained and read a quiet
     passage as loud within ~2 s), and is held at 0 through every charge,
     lull, drop, school, rush and crossfade. It rests only the ORDINARY
     share of the speed target, after the flee / swim burst / solo dash
     have multiplied it, so a new speed moment must multiply in before
     `_pond_rest_step` or the rest squashes it. `quiet_rest = 0` runs none of
     it and never reads `volume()`; a proof comparing against a pinned
     pre-change fish with an audio stub that HAS `volume()` must hold it at
     0. Only the music Fish turns it on (`scripts/set_fish_pond_rest.py`,
     a deploy step). Proof: `scripts/check_fish_pond_rest.py`; the
     fish-effect skill has the rest.
   * **THE WAKE NOW SITS UNDER THE SCHOOL DURING A CHARGE OR LULL — a
     visible change he did not ask for, shipped with this branch.** The
     wake buffer is SCREEN space, and the old deposit
     (`cx + p_x*sx - cos(hd)*len/2`) never subtracted the window origin the
     body is drawn with, so whenever the view had moved (every charge and
     lull at `camera_follow` > 0) the whole wake was laid tens of px off to
     one side of its fish. The deposit now reads `_trail_tail_point`, which
     shares `_trail_points` with `_draw_bodies`' rear spine — one definition
     of where the tail is, in the body's own world->screen mapping. What
     `scripts/check_fish_wake.py` measures on this branch is the corrected,
     window-relative deposit, not the old offset.
   Proof: `tests/test_fish.py` (both dial endpoints, the trail on straight
   and turning paths, the rear body holding its length on swimmers, ejecta
   and a clamped school, birth backfill, the shipped default's mean-speed
   preservation), `scripts/check_fish_camera.py` section 1b +
   `tests/test_fish_camera.py` (KINEMATICS, not rendered pixels, match
   `THRUST_BASELINE_REF` at the dial's neutral setting, with the shipped
   default as the negative control — the trail is always live, so rendered
   frames never return to bit-identical). `scripts/check_fish.py`'s
   flap-bounds check carries a float32 tolerance for a real, legitimate
   boundary landing (see its own comment); `scripts/check_fish_disperse.py`'s
   lull check STAYS STRICT (`== 0`) — its one real violation was traced to
   `DISPERSE_TAU` and mitigated there, not by loosening the check — the
   ~22ms residual slack at a 0.9s gap remains (see the dispersal item above
   and `DISPERSE_TAU`'s own comment in `fish.py`).

**A GAINED BODY MUST NEVER BE DEPOSITED INTO THE TRAIL** (hotfix,
2026-09-16, his live report the same night #274 shipped: trails "at least
3 times too long" and "about 50% too big"). The outgoing-crossfade body
gain (up to 1/`TRANSITION_GAIN_FLOOR` = 3.33x, see the crossfade block
above) was being fed straight into `self.trail` — a PERSISTENT, DECAYING
buffer — so a departing fish's smear started from up to 3.33x its true
peak and took proportionally longer to decay below any visible floor (his
"3x"), reading wider once diffused (his "50%"). Fixed at the render step
in `draw()`: the body is drawn ONCE at its TRUE brightness into
`self.trail` (so every future frame's decay and diffusion is governed by
that alone, exactly as before the crossfade/scatter feature existed), and,
only while scattering, a SECOND time at the gained brightness, maxed
against the trail for THIS FRAME's composited output only — the boosted
value is never stored, so it cannot compound. `TRANSITION_GAIN_FLOOR` and
the wake half-life were deliberately left untouched (tuning either would
mask the leak, not fix it, and cost the anti-dimming or his trails
generally). One pre-existing check's own threshold
(`scripts/check_fish_disperse.py` section 2, "median on-panel body peak
stays >= X through weight 0.2") had to be re-measured down from 0.8 to
0.65 — that number turns out to have been partly propped up by the very
over-persistence bug this fixes (a fish's trail-memory of its own past
over-bright frames was quietly boosting the reading); 0.65 is the
compensation's honest floor with margin, not a masking retune. Falsifier,
his own ask ("compare against 27b1eeb"): `self.trail` is now proven
BIT-IDENTICAL regardless of the scatter gain, and the decay/diffusion
formula itself is proven unchanged against `BASELINE_REF` (this repo's own
precise pre-scatter checkpoint, predating 27b1eeb) — see
`tests/test_fish_disperse.py::
test_scattering_trail_is_fed_true_brightness_not_the_crossfade_gain`'s own
docstring for why BASELINE_REF is used in place of the literal commit he
named.

**THE SWIM BURST STAYS ON SCREEN, and the charge's school is +50% (both
2026-09-16, same night he first watched it live).** His words: "it seems
like they always fly off the screen, but they should stay on the screen."
Root cause, found by instrumenting the real pipeline (not assumed from the
turn-radius math, which is speed-invariant by construction and does NOT
predict this): the boundary steer's heading correction converges on a
FIXED TIME constant (`TURN_GAIN`'s own proportional gain), never a fixed
distance, so a burst-speed fish travels proportionally further during that
same correction time before its heading catches up, and can clear the
panel edge before the steer finishes turning it back. Fixed with a
boundary SPEED BRAKE (`BOUND_BRAKE_AT`/`BOUND_BRAKE_TAU`, near `BOUND_W` at
the top of `fx/effects/fish.py`) that takes speed back toward cruise once
boundary avoidance is genuinely near full effect — **live only while
`self._burst`/`self._burst_tail` is**, so ordinary swimming (a lunge, plain
jiggle variance wandering near the pond edge) is completely untouched.
While live it takes back ANY excess above cruise, but only on a fish heading
OUTWARD, never speeds up a sub-cruise fish, and compounds per unit time
(`(1 - brake) ** (dt / BOUND_BRAKE_TAU)`, frame-rate independent and exactly
the tuned brake at 60 Hz) — a linear `min(1, dt/tau)` ease at 0.05 s was
measured letting 7.9px of overshoot back in. **"Outward" is the pond
ellipse's own ray term (`bb > 0`), not "away from the centre"**: the pond
is ~2:1, and the centre-pointing test (`cos(hd - inward) < 0`) was measured
leaving ~4px of the overshoot in, from fish pointed at the centre while
crossing the top edge. Ordinary swimming untouched is
proven by `test_fish_camera.py`'s own byte-identity guard, which this fix
had to earn a second time after an earlier draft widened the boundary
steer's own trigger distance and leaked into ordinary swimming (reverted;
only the speed brake survived). The steer itself
(`need`/`ahead_px`/`w_bound`, and everything about `turn_radius_px`/
`omega_max`) is UNCHANGED. `school_count`'s schema default moved 12 → 18
(his ask, a plain +50%, well inside `MAX_SCHOOL`'s existing 24 headroom —
no `CAP`/`p_nocap` change needed, that exemption already covers the whole
school). **A default bump that isn't pinned in a check script's own config
silently changes what that check measures** — `scripts/
check_fish_charge_spread.py` compares a BEFORE (`BASELINE_REF`'s own
historical default) against an AFTER that read the SCHEMA default rather
than an explicit value, so raising it made "cells per on-panel fish"
regress for a completely unrelated reason (more fish crowded into the
same panel, not worse spacing) — fixed by pinning `school_count=12`
explicitly in that script's own config, matching its own printed
assumption and isolating the spacing algorithm it actually tests from
population size. The same bump had to land in `config/effect_params.json`
twice (`params.school_count.default` AND the `defaults` blob): the Initial
Set tab and `backfill_param_defaults.py` read the registry, and nothing
checks it against the schema. Proof: `scripts/check_fish_burst_bounds.py`,
`tests/test_fish.py::test_swim_burst_stays_on_screen`.

9. **THE WALL IS THE PANEL'S REAL LIT SHAPE, AND THE FISH GLANCE OFF IT
   SIDE-ON (2026-10-06, his ask: "anticipate the wall and start turning
   away ... on both fish scenes"; reworked 2026-10-07 after the first build
   left them "stuck in the middle": "go right up to the edge of the wall
   ... sides touch the walls, more than their heads ... okay for light to
   bleed"). The WALL block in `fish.py` and `.claude/skills/fish-effect`
   are the binding statements.** A fish swims on until the arc that lands
   it PARALLEL to the wall with its flank over the last lit cells has
   shrunk to the arc its nose allows, flies that arc in, and peels away —
   never "keep clear water ahead", which on a 37 px panel was the
   middle-crowding bug. The shape is READ off the virtual's own segments
   (`is_gap_device`, through Twod's own flips) — on the crystal, the
   hexagon, corners rounded to a curve a long fish can follow; the pond
   (`roam_scale`) still bounds the middle and is glanced the same way.
   **The measured limit, stated not hidden**: a straight-drawn head cannot
   put the side on a short edge before the nose from a steep approach, so
   some nose-first contact at corners is structural — three stricter
   designs were built, measured and rejected in `fish-effect`'s skill
   (they kept the fish off the wall). `wall_lookahead` (seconds of its own
   swimming: widens the arc for a fast fish) and `wall_turn_strength`
   (divides the arc) are registered (Sonic reaches them per scene entry);
   `wall_lookahead = 0` is the old pond-edge steer, kinematics bit for bit
   against the pinned merge-base. Ordinary swimmers only — the charge's
   school keeps the old edge. **A proof of some OTHER fish mechanism that
   compares kinematics or positions against a pinned ref must hold
   `wall_lookahead = 0`** (camera 1b, the clump, burst-brake and
   avoidance-mechanism tests and disperse §2b already do). A rig that
   should see a hex-corner bug needs `fx.headless`'s `real_mask` (his
   crystal's real/gap segments) — a plain rectangle never shows one.
   `scripts/check_fish_wall.py` compares old edge / PR 361 / new against a
   lit edge it computes itself. The House Fish scene's occasional SOLO
   BURST (`solo_burst_*`, default off) is that scene's own data:
   `scripts/add_house_fish_solo_burst.py`.

10. **THE LULL LEAVES ONE FISH THAT SEARCHES, AND THE DROP FOLLOWS THE
   MUSIC (2026-10-08, fish-lull plan; the Admiral: "have all the fish
   leave over time except for one, so one is left at the half way mark
   ... move to one side, pause, then move to the other ... make the
   length of the drop and how fast the fish swirl depend on the
   intensity")** — this REVERSES item 7's "every fish gone by 1/3, dark
   after" on his own word. The module's 2026-10-08 LULL block and the
   `fish-effect` skill are the binding statements. Keepers are a new mode
   (5): never counted, swirled, retired or followed by the window, and they
   RIDE the window's ease-home so they hold their place on screen. The
   number kept is TOLD by the lull hand-off hook ("THE LULL HAND-OFF HOOK"
   section below; default 1). **Told `lull_keep = 0`, the lull is item
   7's clock bit for bit**, proven against the pinned pre-change module —
   so a proof of any OTHER fish mechanism that compares against a pinned
   pre-2026-10-08 fish through a lull must tell it `lull_keep = 0`
   (`scripts/check_fish_wall.py::HOLD_LULL`), exactly like
   `wall_lookahead = 0` above. The drop scales by `lull_handoff.drop_scale`
   (0.75 intensity = the old drop exactly); untold = the fixed constants.

11. **THE BIG FISH FLARE IS A BACKGROUND LAYER, NOT A PARTICLE (2026-10-08,
   `big_fish` flare kind; phase 2, 2026-10-09: the ordinary fish steer out
   of its way — item 12).** The module's BIG FISH block, `fx/VENDOR.md` #65 and the
   `fish-effect` skill are the binding statements. It lives in `self._big`
   (screen space, no SoA slot) and `_big_fish_layer` composites it behind
   the ordinary fish — **every path that writes `self.matrix` must call it
   once a frame** (draw, `_fade_only`, `_draw_collapse` today) or a big
   fish freezes there. Its frequency on the Fish scene is weighted by DATA,
   not code: a lane picks evenly among member NAMES, so
   `scripts/add_fish_big_fish_flare.py` pools TWO identical kinds ("Big
   Fish", "Big Fish 2") in the "Shape" lane with its two other shape
   flares — a big fish on half the flares. Edit both copies together.
   **Its BODY IS AN ORDINARY FISH, SCALED** (reworked the same day, his
   word on the first build: "the fish looks all wrong. it should be the
   same as the other fish in the effect, just bigger, in the background,
   and dimmer, with a dim but large ripple"): it goes through the ordinary
   fish's own `_spine_wave`/`_splat_spines` (factored out of
   `_draw_bodies`, ordinary frames proven bit for bit unchanged), with each
   splat's whole reach — size plus `_splat_many`'s +0.5 px — scaled and
   the same spine resampled densely, because a literal six-splat scale-up
   falls apart into six beads. It lays its own wake into the shared buffer
   (`big_fish_ripple`, `big_fish_ripple_size`). A bespoke silhouette for it
   is what he rejected; do not go back to one.

12. **THE OTHER FISH AVOID THE BIG FISH, AND THE WALL STILL WINS
   (2026-10-09, his approval of the look: "Big fish looks right: build
   step 2 - the other fish steer around the big fish while it crosses").**
   The module's BIG_AVOID block and the `fish-effect` skill are the
   binding statements. Three things learned the hard way: the body to keep
   clear of is the splat's LIT CORE (`BIG_AVOID_CORE`), not its reach — the
   reach needs more room than the panel has; the way out is a SEARCH for a
   reachable spot inside the lit panel, because at the hexagon's two points
   the big fish fills the whole lit height and "turn off its line" drives a
   fish into the wall; and the wall keeps any fish it is late turning back
   (handing those to the threat put fish up to 13 px past the lit edge).
   The soft pond gives way for a threatened fish (`_wall_landing(free=)`).
   Measured with `scripts/check_fish_big_fish_avoid.py`: in the middle
   columns no fish's middle is ever on it; at the points some brushing
   remains — that is the honest limit, not a bug to tune away. With no big
   fish (or `big_fish_avoid` 0) every frame is the pre-avoidance module's.

Every new fish knob is a first guess pending his eye; the effect ships
tunable, not tuned. Proof: `scripts/check_fish.py`,
`scripts/check_fish_avoidance.py`, `scripts/check_fish_lunge.py`,
`scripts/check_fish_camera.py`, `scripts/check_fish_wake.py`,
`scripts/check_fish_charge_spread.py`, `scripts/check_fish_burst_bounds.py`,
`scripts/check_fish_disperse.py`, `scripts/check_fish_wall.py`,
`scripts/check_fish_big_fish_avoid.py`,
`tests/test_fish.py`, `tests/test_fish_camera.py`,
`tests/test_fish_disperse.py`, `tests/test_fish_wall.py`,
`tests/test_fish_lull_searcher.py`, `tests/test_fish_big_fish_avoid.py`.

## Sauron (`fx/effects/sauron.py`) — the Eye of Sauron, a COPY of Eye (phases 1-2 built)

Plan: `/home/javi/fleet-spotfx/data/sauron-eye-plan/report.md` (v2, "go
with all recs, approved", 2026-10-10). The module docstring and the
`sauron-effect` / `sauron-scene` skills are the binding statements. Four
things:

- **A COPY, NOT A SHARE**: Eye's gaze, foreshortening, hand-off (src
  `"sauron"`) and charge/lull/drop are copied verbatim; `eye.py` is
  untouched. Every effect that special-cases an `"eye"` hand-off snapshot
  (radial, dancer, fish's `TRANSITION_ADOPTERS`, spectra
  `transition_phases`) names `"sauron"` too — a new one must as well. The
  copied `snap_threshold` saturating `>=` is fixed here only.
- **`palette_sort`** (default `auto`: dark -> bright, or `radial` for a
  set spanning > 180° of hue — tune-up 1, 2026-10-11, replacing a
  heat-mapped `warm`; see the skill's own "Tune-up 1" section) re-orders
  the curve THIS effect samples, in a `_generate_gradient_curve`
  override — on a config change, never per frame, never his colour-set
  data.
- **`sauron_surge`** is the tenth FlareKind type, the firework_burst /
  pulse_flash / big_fish shape (`SAURON_SURGE_EFFECTS`, unregistered
  self-resetting `surge` poke, no lead/carry/release), written over
  `_flare_states()` so a Light Show flares-off target gets none.
- **THE SCENE IS NOT SEEDED**: `scripts/seed_sauron_scene.py` (a copy of
  Eye V2, dry-run default) waits for his live tuning session
  (docs/ADDING_EFFECTS.md's gate); his values go into its `MATRIX_TUNED`
  and the registry first. The strips (`sauron1d`) and a Sauron-own
  charge/lull/drop are later phases. Proof: `scripts/check_sauron.py`
  (run by `tests/test_sauron.py`); GIFs `scripts/render_sauron.py` ->
  `docs/evidence/sauron/`.

## Pulse (`fx/effects/pulse.py`) — the Singles' one-colour effect, phases 1-4 built

The single-led-power plan (`/home/javi/fleet-spotfx/data/single-led-power-plan/
report.md`, approved by the Admiral "with all recommendations") replaces
Power on the Singles in four phases: (1) the effect offline + a camera
measurement, (2) engine wiring + a test scene and HIS TUNING GATE, (3)
rainbow walk + two flare kinds, (4) scene migration — `scripts/
migrate_singles_to_pulse.py` (dry run default, `--apply` at deploy,
`--revert` from its own manifest) switches every Power Singles scene at
once, on the Admiral's 2026-10-07 word ("push to the rest of the scenes"),
carrying Pulse Test's own tuned Singles params and its two Pulse flare
kinds along with his trigger timing changes — a per-scene timing he had
already set is kept. Power stays installed throughout. **The module
docstring is the binding statement** (hit detector, rise/fade, rest/depth,
smallest pulse, `gamma`, no background, the flash budget, the hooks, the
rainbow walk, the flare pokes); `.claude/skills/pulse-effect/SKILL.md` is
the cold-start map, with its own "Phase 4" section for the migration
detail. Eleven things:

- **WIRED (phase 2) THROUGH TWO SETS IN `fx/device_model`.** `pulse` is in
  `PHASE_EFFECTS` (charge/lull/drop on the shared ramp — a lull reaches black
  at the shared lull dark point, see "THE LULL'S DARK POINT" below) and in
  `ONE_COLOUR_EFFECTS`, which
  keys exactly three things: the feed, the colour fill and the house guard
  below. Its tunable params are in `config/effect_params.json` (help topic
  `pulse-effect`); `energy`/`beat_ms`/`phase`/`phase_progress` are
  deliberately NOT, like every phase effect's phase keys (nor the flare
  pokes `flash`/`flip`).
- **THE FEED** (`spectra/services/pulse_feed.py`, binding statement):
  `energy` = the section's Energy (`spectra/services/energy.py` — see
  "ENERGY" below — `energy.normalize` then `energy.mark_math`, so it obeys
  his 0.75 automatic ceiling and reaches 1.0 only on a marked track), `beat_ms` from
  the analysed tempo. Pushed only when it changes (a section edge, a song)
  by its own engine loop on `bridge.effective_position_ms` — no A/V lead, so
  not a second application point — and carried in the scene fire that
  installs Pulse (`engine.pulse_fire_overlay`). Every push moves the
  conductor's `param_baseline` (`on_surge`), which is what keeps the param
  watchdog from "restoring" a pushed value.
- **ONE PLACE PICKS A SET'S ENTRY PER VIRTUAL**: `scene_compiler.
  set_entries_for` (compile, the conductor's set landing, the flare colour
  jump, the colour-set Preview). A one-colour virtual keeps his own Singles
  colour; with none it takes the strips' FIRST colour; in a rainbow set
  (`is_rainbow`, or the strips' gradient spans >180°) it takes the strips'
  WHOLE gradient, which Pulse walks (phase 3: a seventh per solid hit, 2% a
  bar — it walks only a gradient spanning >180°, the same test). A new
  set-landing path must use it, not `_set_entry_by_virtual`, or Pulse goes
  unfilled there.
- **TRUE BLACK ONLY DURING A MUSIC SHOW**: `_drive_phase` withholds phases
  from one-colour virtuals while `house.scene_deferral()` names a reason
  (`withheld` in the record). House levels, Hue Hold and off rules sit
  downstream of every effect and apply regardless.
- **THE TEST SCENE** (`scripts/seed_pulse_test_scene.py`, dry run default,
  `--apply`, `--remove`): "Pulse Test (Orbits V2)" — Orbits V2 with Pulse on
  the Singles, params empty so he tunes from the defaults, NO sequencer
  entry so it is never drawn automatically. Not run by the build: a deploy
  step. Spec: `tests/test_pulse_engine_wiring.py`.
- **ONE COLOUR, NO BACKGROUND, structurally** — `_refresh_bg_render_state`
  switches the base background layer off, so a colour set's Singles
  background (42 of his sets carry one) can never paint under it.
- **THE FLASH BUDGET IS LUMINANCE, not a count**: the delivered-light rises
  of all hits in any second may not sum past `max_flash_rate` (3); a drop is
  never shrunk but spends it. Not WCAG's stricter count of every >=10% flash.
  It runs on the RENDER clock, and since phase 3 an OUTPUT GUARD
  (`_guard_output`) holds it on the light actually delivered too: booking is
  predictive, and a hit's attack under a decaying flash delivers more through
  the bulb curve than either booked (3.02-3.37/s measured on his songs with
  dense flares before it). It never engages on his fixture songs without
  flares; keep that true.
- **TWO PULSE FLARE KINDS AND A GENERIC MINIMUM INTENSITY (phase 3).**
  `pulse_flash` / `pulse_flip` (`spectra/models/scene.py`, `scene_response.
  _pulse_flash`/`_pulse_flip`) write unregistered, self-resetting pokes to
  `fx.device_model.PULSE_FLARE_EFFECTS` — the firework_burst shape: no
  knobs on the kind (size/angle/timing are Pulse's registered settings), no
  lead, no carry, no release queue. The flip is a HUE rotation back round the
  wheel, never an RGB return (grey, which Hue shows as white).
  `FlareKind.min_intensity` (any type; pulse_flip defaults to 0.4) is STRICT
  (fires only above), gated in `resolve_lane_picks` (a gated kind leaves its
  pool like a disabled one, named `below_min_intensity`), again on the run
  list, and in `fire_kind` (the ▶ Preview reports it). Sonic's
  `set_flare_kind` takes both types and `min_intensity` (omit-means-keep).
  `scripts/add_pulse_flares.py` (dry run default) declares and attaches both
  on the test scene and REFUSES a scene with no Pulse entry — moving a real
  scene is phase 4. Help: `pulse-rainbow-walk`, `pulse-flares`,
  `flare-min-intensity`. Spec: `tests/test_pulse_rainbow_flares.py` (incl.
  the real pipeline into the device preview's encoders).
- **HIS SONGS ARE FIXTURES, AND THE FIXTURES ARE PROVEN**:
  `tests/fixtures/pulse/` is the effect's own audio input recorded through
  the real pipeline from his WAVs; `scripts/check_pulse_effect.py
  [--write-fixtures]` reruns the whole pipeline and fails if the fixture-
  driven run (the pytest path, `tests/pulse_song_harness.py`) lands on a
  different light. Regenerate after any change to the hit signal — the
  fixture carries the per-band arrays (`beat`/`bass`/`mids`/`high`,
  alongside the original `lows`/`bmean`) that any new `hit_source` needs.
- **HIS FIRST LIVE TUNING FEEDBACK, THREE CHANGES (2026-10-06, same day):**
  (1) `hit_source` gained a third, now-DEFAULT option, "kick and bass" —
  weights `AudioAnalysisSource`'s own beat/bass bands near full and its
  mids/high bands falling off above ~250 Hz (his report: "too reactive to
  higher frequencies and not reactive enough at low frequencies"); "bass
  weighted" (the original default, `lows_power + 2 x melbank mean` — the
  melbank mean leans toward the virtual's upper listening band, i.e.
  hats/cymbals) and "bass only" stay selectable. (2) `fade_beats_calm`/
  `fade_beats_intense` defaults raised 4x (1.6->6.4, 0.5->2.0 — "too
  strobey... longer decays by about four times"); `max_flash_rate`
  untouched. (3) the colour flip's `flip_beats` (tempo-scaled) is RETIRED
  for `flip_hold_s` (0.5s default) + `flip_fade_s` (1.0s default) — FIXED
  SECONDS, never beat-scaled, so a fast song can't strobe the flip short
  ("way too fast... at least half a second and then fade out"); held flat,
  then eased (smoothstep) to exactly 0, never a snap. The test scene's
  Pulse entry and its two flare kinds all store empty `params`/`{}` (he
  tunes from schema defaults, by the seeder's own design) — nothing was
  migrated because nothing was stored. `spectra/services/flare_preview.py`'s
  `pulse_effect_ms` dropped its tempo lookup for the flip (no longer
  needed — fixed seconds). Proof: `tests/test_pulse_effect.py`,
  `tests/test_pulse_rainbow_flares.py`, `scripts/check_pulse_effect.py`,
  `scripts/check_pulse_hit_source_bands.py` (reactivity evidence — hits
  classified against his songs' own bass vs snare/other onset marks,
  old default vs new).
- **THE CAMERA MEASUREMENT DRIVES REAL FIXTURES** —
  `scripts/measure_singles_response.py` (dry run by default, `--simulate`
  proves the analysis against known answers) holds `porch-rail`,
  `dining-table`, `dining-hues` through Light Show device holds, reads the
  capture frame tap, and frees `dining-hues` from the house mode's Hue hold
  by editing ONLY that area's look (restored in a `finally`, from a record
  written first). **A Hue area is streamed whole**: `hue-lights` is the
  full ten-bulb Music Group (Loft Ceiling Uplight and the three Ledge
  bulbs included — ordinary Spectra bulbs, just far more than this
  measurement needs), so it is refused outright as out of scope for a
  two-fixture isolation, never because any of its bulbs are treated
  differently. `--apply` only with firstmate's go, and only 08:30-22:30. **Its first live
  run (2026-10-06 08:45) measured nothing: the kitchen-kiosk camera pose sees
  none of the three Singles fixtures at full white** — the measurement stays
  pending until a different pose or a light sensor; gamma ships at 2.2.

## THE LULL'S DARK POINT — one rule, opted into per effect (`fx/effects/lull_dark.py`)

2026-10-07, the Admiral: a lull effect goes fully dark for HALF the lull,
never longer than `RoomControlState.lull_dark_max_s` (3 s default,
Sonic-editable through the generic `set_setting`; Scenes panel field, help
topic `lull-dark-cap`) — a 20 s lull is 17 s of approach + 3 s dark, a 4 s
lull still 2 + 2. `fx/effects/lull_dark.py`'s docstring is the binding
statement, including the three-step OPT-IN for an existing or future lull
effect (schema fields, `fx.device_model.LULL_DARK_EFFECTS`, one
`lull_timing()` call where the effect had a fixed dark fraction). Opted in
at the time: Black Hole, Squiggles, Pulse only (his "just these 3 for
now"). **Since 2026-10-11 every strip phase member (Melt, Power and
Black Hole's own strip `blackhole1d` — see "THE STRIP PHASE LAYER" below)
is opted in too**, via the shared strip layer reading this same rule.
**Star (radial) joined 2026-10-13** (the star plan, his "lull b") — its
own fall-into-the-core mechanism is the radial-effect skill's, not a
second copy of this rule. Three things:

- **SpotFX tells, the effect measures.** `scene_response._drive_phase` adds
  `lull_ramp_s`/`lull_dark_s` to the lull ARM write, only for
  `LULL_DARK_EFFECTS` virtuals (`_lull_dark_keys`); a write without them
  (tests, LedFX UI scrubs) falls back to each effect's legacy progress
  fraction, byte-identical.
- **A JUMP IS NOT UNDONE BY THE GLIDE WRITTEN RIGHT AFTER IT**
  (`fx/VENDOR.md` #58, fixed at its root 2026-10-07). The phase arm is a
  1 ms `JUMP_MS` tween to `phase_progress` 0 then a glide to 1; the tween
  engine used to retarget the glide from the jump's CURRENT value (still
  its start, no frame rendered), so a lull after a completed charge — and a
  drop after a completed lull — glided 1.0 -> 1.0 on EVERY phase effect and
  the orphan watchdog released a long lull 12 s in. `start_param_
  transitions` now retargets a tween that would land by the next frame
  from its TARGET. The told effects still read the lull on their own clock
  — not as a workaround but because a lull over ten times the cap has its
  dark point inside the progress hang. Spec:
  `tests/test_lull_after_charge.py` (every `PHASE_EFFECTS` member, with the
  pre-fix retarget as its red control).
- **Squiggles' lull THINS OUT on a schedule** (2026-10-11, his pick "A"
  on the transitions/drop plan, replacing the CRT switch-off): spawning
  eases out over `lull_entry_s`, then chains fizzle one at a time to a
  population schedule ending before the dark point, head-on booms held
  back so a long lull's walled-in chains do not collide themselves out
  within ~8 s. The squiggles-effect skill is the binding statement. Spec:
  `tests/test_lull_dark.py` (rule, arm write, and all three effects on the
  real pipeline through a 20 s lull after a completed charge),
  `tests/test_squiggles_lull_thinning.py`.

## THE STRIP PHASE LAYER — charge, lull and drop on the 1-D strips (`fx/effects/strip_phase.py`)

2026-10-11, strip phase plan phase 1 (`/home/javi/fleet-spotfx/data/
strip-phase-plan/report.md`, revision 3). The Admiral: brighter and busier
on a charge, relax to black in a lull, a big explosion on the drop — and,
binding, "i don't want to raise the white in the charge, or on the drop".
The module docstring is the binding statement (the curves, THE ORDER of the
output stage, HOW AN EFFECT JOINS). Eight things:

- **ONE LAYER, ONE LINE TO JOIN**: put `StripPhase` first in a 1-D effect's
  bases and add it to `fx.device_model.STRIP_PHASE_EFFECTS` (unioned into
  PHASE/LULL_DARK/DROP_INTENSITY, so SpotFX tells it with no SpotFX change),
  then register `strip_phase.registry_params()` in `config/
  effect_params.json` (Sonic reaches them via `set_scene_entry_param`).
  Members: Melt, Power, the Black Hole strip (plan phase 2), the Orbits
  and Fireworks strips (plan phase 3). `tests/test_strip_phase.py`'s guard
  fails on a registered 1-D effect that neither joins nor is named in
  `STRIP_PHASE_EXCEPTIONS`.
- **AN EFFECT WITH ITS OWN PHASE CHOREOGRAPHY KEEPS NO PHASE PLUMBING**
  (plan phase 3 folded the three particle strips' copies into the layer —
  the module docstring's THE PARTICLE STRIPS' PLUMBING): the layer edge-
  detects the phase key (every phase write is PASSIVE, so an effect's own
  `config_updated` never sees it), runs the orphan watchdog, and resets
  the key after the effect's own `STRIP_PHASE_DROP_S`; the effect starts
  its choreography in `_strip_phase_enter(phase, prev, released)` (called
  once per edge, before render) and reads the phase as `self._sp_phase` —
  never a second copy of its own. Its `config_updated` must NOT call
  `super()`, because `_apply_config` already calls every direct base's own
  hook and a second `StripPhase` pass on a creation write turns a stale
  persisted phase into a false edge. Its content must read the layer's
  dark point (`_strip_phase_lull()`), never a progress fraction of its
  own; its drawn phase looks are retired in favour of the layer's; it may
  answer a flare punch (`_strip_phase_on_punch`, `_strip_phase_punch()`),
  and carry its own tunable defaults (`STRIP_PHASE_DEFAULTS` — the
  Fireworks strip's 12% `lull_ember`; the Orbits strip's own 20%, since
  2026-10-12, is the other — neither strip lull goes fully black). The
  Black Hole strip keeps its blob formation and drop/punch bursts; the
  Orbits strip swells to 16 and HOLDS (his call 2), re-adds 16 on the drop
  and draws its phase implosions from the set; the Fireworks strip stopped
  slowing on the charge and adds an uncapped launch rate past his density
  cap.
- **NO ADDED WHITE, STRUCTURALLY**: a hue-kept colour gain (a pixel scales
  whole and stops at full), a fill and a drop shockwave sampled from the
  effect's own gradient (the shockwave paints OVER, brighter-wins, never
  adds hues), and a WHITE GUARD on charge and drop that pulls any pixel
  back to the set's own grey share at its hue — and does the device's
  per-channel 255 clip itself, hue-kept, since that clip is what whitens
  an over-full colour. Proof measures whiteness with code independent of
  the layer and carries a red control.
- **NON-MEMBERS ARE BYTE-IDENTICAL**: the base `Effect` gained three call
  sites (`_render`, `get_pixels`, `_apply_config`), each guarded by the
  class flag `_strip_phase` / an empty `PASSIVE_CONFIG_KEYS`.
  `PASSIVE_CONFIG_KEYS` exists because a phase ramp tweens
  `phase_progress` every frame and a gradient effect's full config_updated
  chain resets its audio filters and snaps its gradient roll; a write
  carrying ONLY layer-owned keys merges and calls `_passive_config_updated`.
- **THE ROOM MASTER `strip_phase_strength`** (RoomControlState, 0..1.5,
  Sonic `set_setting`, Scenes panel) is pushed on every strip arm write;
  0 reproduces Melt and Power exactly as before (proven through a whole
  cycle); on the Black Hole strip 0 switches the layer's drawing off but
  not its own (reworked) blob choreography — the retired white flood is
  not a rollback target.
- **A FLARE IN THE LULL'S DARK PUNCHES THROUGH** (his answer 5):
  `ResponseEngine._run_kinds` collects every virtual the batch actually
  wrote to (`_jump`/`_glide` — every write in scene_response goes through
  them — into a ContextVar) and, while a lull is armed, pokes the
  `fx.device_model.FLARE_PUNCH_EFFECTS` virtuals the lull reached
  (`_lull_vids`) with `flare_punch` + `flare_punch_hold_s`. The envelope
  AND its runtime are `lull_dark.punch_envelope` / `lull_dark.FlarePunch`
  — one definition (read lull_dark.py's "HOW A LULL EFFECT TAKES THE
  PUNCH"). Since plan phase 5 the crystal's Black Hole and Squiggles and
  the Pulse singles are members too ("a flare in a dark room lights
  everything together"): Black Hole holds its horizon back and keeps what
  the lull swallowed on the lull's ring, Squiggles brings tagged chains
  the thinning never touches, Pulse shows max(lull fade, punch x its
  ordinary look) — each shows its ORDINARY look under a punch, never the
  phase's (measured: `scripts/check_flare_punch_crystal.py`; byte-identical
  without a punch, `tests/test_flare_punch_crystal.py`). A charge/lull/drop
  event's own band never punches (`_PUNCH_OK`, carried on a
  PendingKindBatch). The poke key is `flare_punch`; the tunable is
  `flare_punch_strength` — they collided once, and a collision silently
  zeroes the strength on the poke's self-reset.
- **HELD BACK UNDER A HOUSE MODE** (his call 4):
  `scene_response.HOUSE_HELD_PHASE_EFFECTS` = one-colour ∪ strip members,
  read by `_drive_phase` and `rearm_phase`.
- **THE STRIP STAR READS SKIPS ITS LULL** (2026-10-14, his Q5: "The strip
  used by the radial effect shouldn't do the lull"): Radial stamps its
  source strip every frame (`strip_phase.mark_radial_source`); a lull edge
  on a stamped strip tells the effect "none" and only eases the charge back
  (`_sp_skip`), the key tracked apart in `_sp_seen` so it never re-edges.
  Charge and drop unchanged; Star darkens its own lull. Proof:
  `tests/test_star_strip_lull.py`.
- **EVERY MEMBER IS A PRE-DROP MEMBER** (2026-10-27, predrop plan step 9;
  `fx.device_model.PRE_DROP_EFFECTS` includes `STRIP_PHASE_EFFECTS`): the
  pre-drop's keys and the breath told with them are PUSHED keys (the lull
  arm stays passive), and the layer draws the TWINKLE from the pre-drop to
  the drop — the module docstring's THE PRE-DROP. A new member must declare
  a look in `config/effect_params.json` (`pre_drop_looks`: the twinkle, or
  one of its own drawn through `_strip_phase_pre_drop()`, as the Fireworks
  strip's rockets are), or `tests/test_pre_drop_arm_identity.py` fails.
Proofs: `tests/test_strip_phase.py` (harness `tests/strip_phase_harness.py`:
the real pipeline + production ResponseEngine/FacadeExecutor, fake clock
behind `time.time_ns` too, since Melt reads it), `scripts/
check_strip_phase.py` (the measured cycle and the stage cost: ~0.1 µs
off-phase, ~230-245 µs a frame during a charge/drop at 560 px); the Black
Hole strip's before/after on his own entry, with the pinned pre-change
module as red control: `scripts/check_blackhole_strip_phase.py` +
`tests/test_blackhole_strip_phase.py`; the Orbits and Fireworks strips'
(and the plumbing fold's) the same way: `scripts/
check_particle_strip_phase.py` + `tests/test_particle_strip_phase.py`. The
harness seeds each particle strip's own `_rng` (np.random.seed does not
reach it). Help topic `strip-phases`; `fx/VENDOR.md` #68, #72, #74.

## THE LULL HAND-OFF HOOK — how a lull is told what to leave for its drop (`fx/effects/lull_handoff.py`)

2026-10-08 (fish-lull plan phase 1), lull_dark's sibling and built the same
way. **It is the ONE interface between an effect's lull/drop choreography
and whatever knows what the drop will be — the drop-scene-variety work
(drop-led switching, the fireworks melds) plugs a RESOLVER into it and must
not build a second.** `fx/effects/lull_handoff.py` (the keys and the
opt-in) and `scene_response`'s "THE LULL HAND-OFF HOOK" docstring section
(the resolver contract) are the binding statements. Four things:

- Every lull arm tells each `fx.device_model.LULL_HANDOFF_EFFECTS` virtual
  `lull_keep`/`lull_next`/`lull_s` (every key, every arm, even at the
  default, so a previous lull's request is forgotten); every drop arm tells
  each `DROP_INTENSITY_EFFECTS` virtual `drop_intensity` (the fire's
  intensity, floored at 0.01 so 0 always means "not told"). Fish is the
  first and only member. Phase-write keys only — never in the registry.
- The RESOLVER (`LullContext` -> `LullHandoff`) is installed ONCE,
  process-wide, with `scene_response.install_lull_handoff_resolver(fn)`
  from `spectra/services/engine.py` — process-wide so the drop-sequence
  preview's scratch responders ask the same one. With none installed every
  lull keeps 1. A resolver must be pure and cheap and never raises into the
  fire (a failure is logged and the default used, named in the record).
- `LullContext` carries the scene, the fire's intensity, the gap, every
  virtual's current effect and the live song/position (`song_position`,
  wired from the bridge in engine.py). The phase record names what was
  told (`lull_handoff`, `drop_intensity`), so the fire log and the
  sequence preview can say why a lull kept three fish.
- An effect that is in BOTH this set and `LULL_DARK_EFFECTS` goes dark at
  its dark point only when told `keep == 0` (none is, today).
Spec: `tests/test_lull_handoff.py`.

## THE DROP SHOCKWAVE + THE BREATH-HOLD (`fx/effects/phase_grammar.py`)

2026-10-11, the transitions-drop plan's phase 1 (crystal only; strips are
separate work). `phase_grammar.py`'s docstring is the binding statement,
including how an effect opts in. Four things:

- **ONE SHARED PAINTER, IN THE BASE RENDER.** `Twod.render` calls
  `_phase_grammar_post()` after `draw()` for a class with `DROP_SHOCK = True`
  (`fx.device_model.DROP_SHOCK_EFFECTS`: Black Hole, Orbits, Sauron, Eye,
  Fish — NEVER Fireworks, his word); a test holds the set equal to the
  opted-in classes. The member names its eye (`shock_rim()`, render pixels)
  and calls `_shock_begin()` where its own payoff fires — never on a silent
  watchdog release. Not opted in, `drop_shock: 0`, the switches below
  saying no, or no breath told: the frame is never touched.
- **SET COLOURS ONLY, MAX-COMPOSED — NEVER WHITE** (his ruling: brighter
  means more colour and more activity). Every layer is a set colour scaled;
  the front's lean toward the brightest stop moves the GRADIENT POSITION,
  never an RGB mix. Measure with `phase_grammar.white_cells` before adding
  any layer.
- **THE BREATH-HOLD** (`RoomControlState.lull_breath_hold_s`, 0.4 s,
  Sonic-editable, 0 = off) rides the lull arm of every
  `fx.device_model.BREATH_HOLD_EFFECTS` member as
  `lull_breath_at_s`/`lull_breath_s`, always inside `lull_dark.dark_hold_s`,
  0 when the gap is unknowable; it ends on the drop's edge or
  `BREATH_OVERRUN_S` after it was due. Since 2026-10-12 (the Admiral: "I
  want orbits and fish to specifically not go dark completely ... I do want
  it on pulse effect"; "orbits should keep at least one dim blob") that set
  is the Shockwave members WITHOUT the Fish (`Twod.BREATH_HOLD = False`)
  plus Pulse (true black, punch and flash included), and Orbits breathes
  only to its `BREATH_FLOOR` (one dim blob); the Orbits strip keeps one
  dim blob through its lull's dark (its own `lull_ember`, 0.2). Star
  (radial) joined 2026-10-13 too (the star plan) — like Pulse it takes
  the breath in its own draw, true black (the radial-effect skill). Spec
  `tests/test_drop_feedback_1012.py`.
- `DROP_INTENSITY_EFFECTS` widened to every member: the drop scales the
  debris and the front's life; Black Hole's own burst grows on a loud told
  drop and is exactly `PHASE_BURST_N` untold. The eleven `drop_*` settings
  are registered per member (`phase_grammar.registry_params()` is the one
  shape) — schema keys may not contain "colour" (`fx/utils.py` refuses it).
  Proof: `scripts/check_drop_shockwave.py`, `tests/test_phase_grammar.py`;
  help `drop-shockwave`; the breath-hold's own help folded into
  `lull-dark-cap`'s topic 2026-10-15 when Settings grouped the two
  fields under one link (Scenes & drops' "Lull" row).
- **THREE SWITCHES DECIDE WHETHER A DROP PAINTS IT** (2026-10-12, the
  Admiral): `RoomControlState.drop_shock_enabled` (room, default on), the
  showing scene's `SceneV2.drop_shock_enabled` (default on; the Fish scene
  ships OFF via `scripts/set_fish_drop_shock_off.py`, a deploy step), and
  `drop_shock_min_energy` reads Energy at the drop WITH THE LOOK-AHEAD
  (`ResponseEngine(drop_energy=)` → `bridge.intensity(look_ahead=True)`),
  the same number the drop fires at — its 0.7 was set on the old raw
  top-bar scale, and the Energy plan's D5 parity re-set (`scripts/
  energy_parity.py`) moves it to the share-matched Energy value (0.32 on
  his data at build time); an unknown energy is never gated).
  `scene_response._drop_shock_keys` decides once per drop arm with
  `phase_grammar.shock_allowed` and tells every member `drop_shock_on`
  (record key `drop_shock`); told False the base render builds no painter,
  so the frame is the effect's own drop byte for byte. Since 2026-10-12
  ("stip shockwave, yes") every strip phase member is told the same verdict
  (`DROP_SHOCK_TOLD_EFFECTS`) and skips only its wave and flood; its colour
  and activity burst still run. Star (radial) joined `DROP_SHOCK_TOLD_
  EFFECTS` too (2026-10-13, the star plan's drop D3) — it is never a
  Shockwave member (its own bands-snap-back is its drop), but told False
  that snap is withheld and the drop is the plain bloom (the radial-effect
  skill). The Pulse FLASH flare has its own floor on
  the same top-bar Energy (`pulse_flash_min_energy`, 0.8,
  `scene_response.pulse_flash_allowed`). Spec
  `tests/test_drop_shock_switches.py`, `tests/test_drop_feedback_1012.py`;
  help `drop-shockwave-switches`, `pulse-flash-energy`.

## Radial (STAR) rotation is audio-lows-driven — a healthy `spin` can read as parked

`fx/effects/radial.py`'s ONLY motion source is the audio callback:
`spin_total += lows_impulse * spin_cfg²/10 * ROTATION_SPEED_SCALE` per
60 Hz callback, i.e. **rev/s = 4.8 × lows_impulse × spin²**
(`ROTATION_SPEED_SCALE=0.8`, the Admiral's 2026-10-06 20% cut — see "THE
MAXIMUM ROTATION SPEED WAS CUT 20%" below for the full before/after across
every rotation source) — `spin` is a gain on the LIVE captured lows power
(snapcast.monitor melbank), NOT a motor speed, and NOT the bridge's
"intensity" (that's stored librosa file analysis; the two diverge freely).
During bass-light passages the lows impulse idles ~0.01, so a healthy spin
0.55 turns ~5°/s — reads as frozen while rendering fine.
Diagnosed live 2026-08-21 (his "star is not moving at any speed" — his own
binding edit and #168's flip port both ruled out with evidence):
`docs/spectra-star-motion-audio-idle.md`. Executable proof, real pipeline,
no live access: `scripts/check_star_spin_motion.py`. Before diagnosing any
"effect X ignores its speed/reactivity param" report, check whether the
param is an audio gain (`aspect: reactivity` in `config/effect_params.json`)
and measure the live impulse before blaming the param value or the writer.

**Since 2026-08-25 radial has a second, differently-scaled rotation control
— don't confuse the two** (his ask, PR fm/radial-base-rotation; `fx/VENDOR.md`
deviation #22): `base_rotation` is a QUIET FLOOR in plain REVOLUTIONS PER
SECOND — LINEAR and absolute, never squared, never multiplied by audio —
while `spin`/Speed stays exactly the squared audio gain above. They combine
as `effective rev/s = max(base_rotation, reactive rev/s)`: a FLOOR, not a
sum, so a base never adds anything at a peak and the existing reactivity is
byte-identical wherever the music's own drive is faster (the named
alternative, a sum, is a one-line change in `_base_rotation_step`). It
advances on the RENDER clock (`draw` → `_base_rotation_step(self.passed)`),
NOT in `audio_data_updated` — a base term there would stall in exactly the
quiet case it exists for. Default `0.0`, so every pre-existing scene renders
byte-identically until he sets one (asserted, not claimed). Proofs:
`scripts/check_radial_base_rotation.py`, `tests/test_radial_base_rotation.py`.
Registry-declared param help (`"help_topic"` on an entry in
`config/effect_params.json` → a `HelpLink` on that param's row in
`InitialSetTab.tsx`) is new with this change and is the general way to
deep-link a param to a help topic; note such a topic id lives in the JSON
registry, so the AGENTS.md orphan-audit grep over `.tsx`/`.ts` will not see
it.

**THE MAXIMUM ROTATION SPEED WAS CUT 20% (2026-10-06, Admiral order
verbatim: "reduce the maximum speed of rotation of Star by 20 percent").**
`fx/effects/radial.py`'s `ROTATION_SPEED_SCALE = 0.8` is the ONE constant
applied to every source above that contributes to rotation speed, so the
*ceiling* drops uniformly rather than just a default: the reactive
ceiling (spin at its own unchanged max 1.0, full audio impulse) was
6 rev/s, now 4.8 (`self.spin`'s own `/10.0` divisor gained the scale, so
`spin`'s input range stays `[-1, 1]` — a binding already set to `spin`'s
"max" reaches the new, lower ceiling automatically, nothing about how a
binding reaches max changed); `CHARGE_SPIN_REV_S` (charge-phase spin-up)
was 0.9 rev/s, now 0.72; `base_rotation`'s own schema/registry ceiling was
2.0 rev/s, now 1.6 (`config/effect_params.json`'s `base_rotation.max`
mirrors the schema literal — keep both in sync by hand, there is no
shared source across the JSON/Python boundary). A stored scene or flare
kind authored above the new `base_rotation` ceiling is CLAMPED ON LOAD
(`spectra/models/scene.py`'s `_clamp_radial_base_rotation`, called from
`SceneV2`'s `_flare_bands_shim` before-validator) rather than silently
dropped — `fx`'s own `_apply_config(validate=True)` drops the WHOLE write
on a schema mismatch, never just the one offending field (see the
`spin_sign` entry above), so an un-clamped out-of-range value would have
reverted the entry's whole config on its next fire, not just capped the
speed. The clamp covers plain scalars, `ValueBinding` map-mode
out_min/out_max/fallback, `ValueBinding` steps values, and a flare kind's
absolute/random `ParamTarget` on this param name; an `offset`-mode
`ParamTarget` is left alone (a signed delta off a runtime-carried
baseline, not evaluable at load time). Unverified against his live room
(standing order 35, no live test without his word) — specs:
`tests/test_radial_base_rotation.py`'s rotation-speed-cap cases,
`scripts/check_radial_base_rotation.py`.

## Radial (STAR) — the star improve plan (2026-11-12): ease-in, the 70% cap, the star wave, Edge Morph

The radial-effect skill's "THE STAR IMPROVE PLAN" section is the binding
statement; `data/star-improve-plan/plan.md` the plan he approved. In one
line each: the "dead on entry" was a FIRE-TIME defect (a `random_sign`
binding on a 0..1 param flipped then clamped to 0 — `binding_resolver.
_maybe_flip_sign` now skips any param with `lo >= 0`); `_govern_rotation`
eases the first `spin_ease_in_s` seconds (STAR 1.0, effect default 0) and
clamps every frame's TOTAL advance (shipped at `ROTATION_CAP_REV_S` 3.36
rev/s; since the spin smooth plan below `ROTATION_CAP_DEG_FRAME` 18 deg per
rendered frame);
`_star_wave_step` sways `star` between `star_wave_lo`/`_hi` (STAR −0.2..
+0.4, through flat = 0 — flat is 0, not 0.5) at a pace set by the pushed
`energy` (the pulse feed now feeds radial, energy only); "Edge Morph" is a
`ParamTarget` mode `random_other` on `edges` 3..6, permanent, on STAR's two
upper flare bands; Melt's `dark_floor` (VENDOR.md #92) and the TV's
`pixel_map` (#93, `docs/agents/devices-and-ownership.md`) are the strip
half. Proofs: `tests/test_star_improve.py`; rig: `scripts/
render_star_improve_*.py`.

## Radial (STAR) — the spin smooth plan (2026-11-12): the per-frame clamp and the energy-paced release

The radial-effect skill's "THE SPIN SMOOTH PLAN" section is the binding
statement; `data/star-spin-smooth/plan.md` the plan, `report.md` the
measured evidence. In one line each: the crystal renders at 30 fps (its
WLED `refresh_rate`; a virtual renders at its slowest device) while audio
callbacks run at 60 Hz, so the 3.36 rev/s cap was 40 deg per rendered frame
— past the 180/edges deg at which a 6-point star's turn reads backwards,
his "hard to tell it moved"; the cap is now `ROTATION_CAP_DEG_FRAME` = 18
deg per rendered frame, any dt; the jerk was the lows filter's ~6-frame
burst shape squared by `spin`, not the cap, so `_govern_rotation` now runs
a unity-gain one-pole on the per-frame ADVANCE (total turn and mean speed
preserved) whose time runs `spin_release_low_s` (STAR 0.45) at pushed
`energy` 0 to `spin_release_high_s` (STAR 0.2) at 1, linear, never a step;
effect default 0/0 is today to the frame. `scripts/star_spin_smooth_
scene_data.py` writes the two STAR params (DJ, at deploy). Proofs:
`tests/test_star_spin_smooth.py`. Per-frame STAR reasoning uses dt = 1/30;
`tests/star_harness.py` steps at 1/60.

## `crystal-mapper` (the hex Matrix virtual) — read the skill before touching it

Load `.claude/skills/crystal-hex-grid/SKILL.md` before changing any effect
targeting the Matrix category (`config/effect_params.json`
`categories.Matrix.effects` — 11 of them, not just Blackhole), before
writing anything that reads `storage/device_profiles/`, or before trusting
any coverage/brightness/"is this visible" measurement on that virtual. Short
version: only 976 of the addressable 72x37=2664 cells are real light
(36.6%), forming a hexagon — real-cell density is a flat 50% out to
`r<=0.85` (normalized radius, r=1 = the panel's own rectangular edge) and a
hard 0% past `r≈1.2`, a cliff, not a gradient. The effect-layer render
pipeline (`fx/effects/twod.py`) has zero awareness of this — `r_width`/
`r_height` are always the full rectangle. Found and fixed 2026-08-17
(`fx/effects/blackhole.py`'s infall spawn annulus landed almost entirely on
the dead corner band — `fx/VENDOR.md` deviation #12, `docs/SPECTRA_SPEC.md`
§76) after repeated prior agent confusion about this device's geometry; the
skill exists so that doesn't happen again. **The boundary is
direction-dependent, not a single radius** — its distance from center is
~0.87 normalized-r at a flat edge's own midpoint-normal vs. ~1.13 at a
corner vertex, so a scalar spawn radius can only coincide with the true
edge at a handful of angles (found the hard way 2026-08-18, same §76: a
hit-rate-maximizing scalar annulus read as spawning "several pixels" inside
the visible edge everywhere except the tight end of that range).
`fx/effects/blackhole.py`'s `HEX_SPAWN_VERTS`/`_hex_spawn_edge_radius`
compute the boundary per spawn angle instead — see the skill's own new
section for the derivation and why a hexagon's inradius is NOT "tangent at
the edge and outside near the corners" (it's inside the polygon everywhere
but the 6 tangent points, by definition).

