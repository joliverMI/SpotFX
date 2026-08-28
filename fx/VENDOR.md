# fx/ — vendored LedFX render pipeline

Source: the SpotFX LedFX fork at `/home/javi/ledfx-src`,
branch `wip/matrix-dancers-snapshot-20260812`, commit `149f4470`
("WIP snapshot: dancer/eye/shapemap/lattice matrix work as of 2026-08-12").
License: GPL-3.0 (`fx/LICENSE`, copied from the fork's `LICENSE.txt`).

This is Stage 1 of the approved Option C merge
(`/home/javi/fleet-spotfx/data/spotfx-ledfx-merge-scout/report.md` §3,
`decision-merge-architecture-choice.md`): the subset of `ledfx/` that
production actually uses, imported as `fx.*` inside SpotFX. The fork stays
installed and untouched; nothing here runs unless the in-process facade is
switched on (`settings.fx_in_process`, default off).

## What is vendored (verbatim except the deviations below)

- Core: `color.py`, `config.py`, `consts.py`, `events.py`, `shapemap.py`,
  `transitions.py`, `utils.py`, `virtuals.py`, `scenes.py`, `assets.py`
- Effects plumbing: `effects/__init__.py` (effect base + server-side tween
  engine), `twod.py`, `audio.py`, `melbank.py`, `mel.py`, `math.py`,
  `gradient.py`, `hsv_effect.py`, `modulate.py`, `temporal.py`, `gifbase.py`,
  `particle_handoff.py`, `lattice.py`, `oneshots/oneshot.py`,
  `utils/logsec_helper.py`, `utils/get_info.py`
- The effects production uses (the 19 in `config/effect_params.json` plus
  `singleColor`; `dancer` brings `dancer_moves` + `dancer_flames`):
  blackhole, blackhole1d, blender, concentric, dancer, equalizer2d, eye,
  fireworks, fireworks1d, gifplayer, keybeat2d, melt, noise2d, orbits,
  orbits1d, pacman, power, radial, squiggles, singleColor
- Devices: registry (`devices/__init__.py`), the three production driver
  families — `ddp.py`/`wled.py` (plus `e131.py`, `udp.py`, `packets.py` which
  `wled.py` imports), `hue.py` (the fork's hardened Hue entertainment driver,
  as-is), `dummy.py` — and nothing else (the other ~20 drivers are dropped)
- Support pulled by `utils.py`/`assets.py`: `libraries/cache.py`,
  `utilities/{gradient_extraction,image_utils,security_utils}.py`

Dropped entirely (per report Option C): `core.py`, the aiohttp server and
`ledfx/api/*`, the LedFX frontend, zeroconf/mDNS, integrations, sentry, tray
icon, sendspin, nowplaying, presets library, playlists.

`effects/oneshots/` and `effects/utils/` have no `__init__.py` in the fork
(namespace packages); that is preserved here.

## Import rewrite

Mechanical rewrite in every vendored file — import statements only, plus the
three registry package-name strings (`"ledfx.effects"` → `"fx.effects"`,
`"ledfx.devices"` → `"fx.devices"`, `"ledfx.virtuals"` → `"fx.virtuals"`) and
`ledfx.api.websocket.` attribute references in `effects/audio.py`. Local
variables named `ledfx` (the core object handle) are untouched.

## Deviations from verbatim (complete list)

1. `effects/audio.py`: `import sounddevice as sd` →
   `from fx.compat_sounddevice import sd`. Importing sounddevice initializes
   PortAudio and scans audio hardware at import time; the proxy defers that
   to first use. See `fx/compat_sounddevice.py`.
2. `effects/utils/get_info.py`: module-scope `import aiohttp` moved into the
   two functions that use it. aiohttp belongs to the dropped web stack and is
   not a SpotFX dependency; the helper only runs in logsec diag mode.
3. `consts.py`: `import ledfx_assets` → `import fx.assets_builtin as
   ledfx_assets`. The fork's `ledfx_assets/` is 23 MB of media; the shim
   keeps `LEDFX_ASSETS_PATH` resolvable (builtin:// lookups find nothing —
   production GIFs live in the user asset store under the fx config dir).
4. New SpotFX-authored boundary stubs (not fork code): `api/websocket.py`
   (WEB_AUDIO_CLIENTS / WebAudioStream / ACTIVE_AUDIO_STREAM),
   `sendspin/{__init__,config,stream}.py` (SENDSPIN_AVAILABLE = False),
   `assets_builtin/`, `compat_sounddevice.py`.
5. `device_model.py` — SpotFX-authored (not fork code): the shared device
   model (categories/virtual topology, effect-param registry, scope
   resolution) the architecture decision places in the shared library.
   SPECTRA imports it; spot-effects keeps its own services until replaced.
6. `effects/blackhole.py`: the event-horizon glow and charge/drop halo no
   longer default to hardcoded `horizon_color` white — `horizon_follow_blobs`
   (new config key, default `True`) samples the live blob gradient each
   frame instead (`fx.effects.blackhole.Blackhole2d.draw`); set it `False`
   to restore the original literal-`horizon_color` behavior byte-for-byte.
   Not yet ported back to the fork source at `/home/javi/ledfx-src` — the
   fork and this file have drifted on this one effect until that happens.
7. `virtuals.py`: two `except` clauses broadened to `except Exception`
   (report gate "the crystal lazy-activation class", two-writers incident
   2026-08-13) — `Virtuals.create_from_config`'s per-virtual effect-restore
   (was `except (RuntimeError, ValueError)`) and `Virtual.activate`'s
   `activate_segments` call (was `except ValueError`). Any other exception
   type (a Hue handshake failure, a socket error) escaped both uncaught and
   could abort the whole per-virtual activation loop, stranding every
   virtual still to come in config order — the crystal-mapper darkfault.
   Behavior otherwise unchanged: still logged, still non-fatal to the
   virtual itself.

8. `utils.py`: new `WLED.get_info()` method (json/info GET, same
   `_wled_request` pattern as `get_state()`). Not in the fork — added so
   SPECTRA's device-liveness verification (`spectra/services/
   live_host.py::device_gaps()`) can read WLED's realtime "live" flag,
   which the device reports only under json/info, never under json/state
   (get_state()'s endpoint carries on/bri/ps/seg but no "live" key —
   verified against real WLED devices, 2026-08-14).
9. `devices/__init__.py`, `devices/hue.py`, `devices/wled.py`, and
   `fx/host.py` (SpotFX-authored, not vendored): stop-at-teardown fix
   (BEHAVIOUR CHANGE — spectra-hue-bridge/report.md, PR
   fm/spectra-hue-stop-fix). `Device.deactivate()` is synchronous and, on
   Hue/WLED, fires an unawaited device-stop coroutine
   (`async_fire_and_forget` — the bridge's `action: stop` PUT / WLED's
   `{"live": false}`) so it never blocks callers that must stay
   synchronous (render-thread/event-loop callers via `set_effect`,
   `check_and_deactivate_devices`, etc.). `FxHost.shutdown()` used to call
   that plain `deactivate()` and then immediately shut its
   `ThreadPoolExecutor` down with no intervening `await` — the scheduled
   stop coroutine never even started before its executor was gone
   (`RuntimeError: cannot schedule new futures after shutdown`, 100%
   reproducible on every SPECTRA↔spot-effects ownership handover quiesce).
   The Hue bridge, never told the entertainment session ended, held it
   open until its own idle timeout lapsed, and the *next* activation ate
   that as a DTLS handshake timeout — the intermittent "DTLS handshake to
   Hue bridge timed out" failures, worse on the second bridge in
   activation order (Dining Hues).

   Fix: `Device.deactivate()`'s subclasses (Hue, WLED) now dispatch their
   stop/release coroutine via `Device._dispatch_teardown_task()`, which
   remembers the resulting `Task` on the instance instead of letting it
   float free. `Device.async_deactivate()` (new; default no-op wrapper
   around `deactivate()` for device types with nothing pending) awaits
   that remembered task if one is pending; `Devices.
   async_deactivate_devices()` calls it per device; `FxHost.shutdown()`
   awaits that before shutting the executor down, on every deactivation
   path (handover quiesce, release, rollback, process shutdown). Tracking
   the task on the instance (rather than assuming the teardown-path
   deactivate() call is the one that dispatches it) matters because a
   virtual's own `check_and_deactivate_devices()` and the vendored
   `LEDFX_SHUTDOWN` event listener (`Devices.__init__`'s `on_shutdown`,
   itself deferred via `call_soon_threadsafe`) can each independently call
   plain `deactivate()` on the same device during one teardown — whichever
   runs first dispatches and is tracked; `Device._teardown_dispatched`
   (reset by `activate()`) makes every later `deactivate()` call this
   cycle a no-op instead of re-dispatching (and re-scheduling a callback
   that could itself land after the executor is gone). `FxHost.shutdown()`
   also now fires `LedFxShutdownEvent` (which triggers that listener)
   AFTER its own device teardown pass, not before, so the listener's
   redundant call always lands on an already-guarded device. Every other
   `deactivate()` caller is unchanged (still synchronous, still
   fire-and-forget) — only the teardown path that was provably dropping
   the stop was touched. Not yet ported back to the fork source at
   `/home/javi/ledfx-src`.

10. `effects/__init__.py`: `Effect.start_param_transitions` fix (BEHAVIOUR
    CHANGE — spectra-room-fault-diagnosis/report.md, PR
    fm/spectra-room-fault-fix). Retargeting a param key's in-flight tween
    from a gradient value to a colour/numeric value (or vice versa) before
    it completes raised `KeyError: 'current'`: the numeric/color branches
    (line ~699/705) unconditionally read `prior["current"]`, but a
    gradient-kind `prior` stores its progress under `current_curve`/
    `target_curve` instead, never `"current"`. This dropped SPECTRA's
    flare-driven colour-set jump mid-application (`scene_response.py.
    _color_jump`, reached via `bridge.py`'s per-message handler, which only
    logs and moves on — the whole event was silently lost). Fix: reuse
    `prior["current"]` only when `prior.get("kind") != "gradient"`,
    mirroring the existing `prior.get("kind") == "gradient"` guard already
    present in the gradient branch just below. Not yet ported back to the
    fork source at `/home/javi/ledfx-src`.

11. `devices/hue.py`: new read-only `frozen` property (SpotFX-authored, not
    fork code) exposing the existing private `_frozen` flag —
    `spectra/services/ambient.py`'s per-group ambient reconcile (Hue
    entertainment-area selection, PR fm/spectra-hue-entertainment-areas)
    needs to tell an already-frozen device from one ambient never touched,
    to avoid calling `set_frozen(False)` (which reconnects the entertainment
    stream, `_trigger_reconnect()`) on a device that was never frozen in the
    first place. No behaviour change — a plain accessor.

12. `effects/blackhole.py`: the infall-mode (`reverse=False`) spawn location
    (BEHAVIOUR CHANGE, two rounds).

    Round 1 (PR fm/spectra-blackhole-hex-spawn, 2026-08-17): moved from a
    fixed `(0.90, 1.05)` to a fixed `SPAWN_ANNULUS_MIN/MAX = (0.70, 0.85)`,
    in the same normalized-r units as `radius_scale` (r=1 = the panel's own
    rectangular edge). The effect has no knowledge of which addressable
    cells are real light vs a gap-mapped dummy device — it spawns purely in
    (r, theta) space and lets fx/virtuals.py's segment routing decide per
    pixel. On a hex-lattice matrix virtual (his real `crystal-mapper`:
    72x37 addressable, only 976/2664 = 36.6% real —
    `storage/device_profiles/crystal-mapper.json`) real-pixel density is a
    flat 50% out to r<=0.85 and collapses to ~20% by r=1.0, 0% past r=1.2 —
    the old annulus spawned almost entirely in that near-zero-density corner
    band, so a fresh blob was invisible until it had fallen most of the way
    to the horizon.

    Round 2 (PR fm/spectra-blackhole-spawn-at-edge, 2026-08-18): the round-1
    fix maximized real-pixel hit rate, which is a different objective from
    what he actually asked for — his live report was that blobs now spawn
    "several pixels" inside the visible edge instead of arriving from it.
    The hex silhouette's distance from center genuinely depends on
    direction (~0.87 normalized-r at a flat edge's own midpoint-normal,
    ~1.13 at a corner vertex — see `.claude/skills/crystal-hex-grid/
    SKILL.md`), so no single scalar can sit "at the boundary" in more than a
    few directions. `SPAWN_ANNULUS_MIN/MAX` are retired; the infall branch
    now computes the boundary per spawn angle via `HEX_SPAWN_VERTS` (the
    silhouette's true vertices, measured off the same device profile) and
    `_hex_spawn_edge_radius(theta)` (a closed-form convex-polygon support
    function, checked against the boundary measured directly off the
    profile to within ±0.06 normalized-r), then adds a small outward margin
    (`SPAWN_EDGE_MARGIN_MIN/MAX = 0.02-0.12`). Real-pixel hit rate for this
    mechanism (~5%) is LOWER than round 1's (~50%) by design — a spawn just
    past the true boundary starts dark and lights up the instant it falls
    back across its own local edge on the next inbound step, which is the
    arriving-from-outside look he asked for.

    Both rounds leave `radius_scale`/`sx`/`sy` (the effect's overall
    panel-filling scale, and the fall/travel distance from spawn to
    horizon/center) untouched — only where blobs *start* moved, not how
    much of the panel the effect uses. Evidence:
    `scripts/check_blackhole_hex_spawn.py` (real-density-by-radius, the
    per-angle formula checked against the device profile, and all three
    historical mechanisms' hit rates); frame-level proof:
    `tests/test_blackhole_spawn_radius.py`. Not yet ported back to the fork
    source at `/home/javi/ledfx-src` — this whole mechanism is tuned
    specifically against `crystal-mapper`'s measured hex silhouette and has
    no meaning for a genuinely full-rectangle matrix virtual, which SpotFX
    doesn't have one of today; revisit if one is ever added.

13. `effects/__init__.py`: `hue_tween_fields()` achromatic-endpoint fix
    (BEHAVIOUR CHANGE — docs/SPECTRA_SPEC.md §83/§84, PR
    fm/spectra-achromatic-saturation-fix). The function's own docstring
    already stated its intent: for an achromatic (black/grey/white)
    endpoint, adopt the OTHER end's hue "so the blend fades saturation in
    place instead of sweeping through arbitrary red." It did adopt the
    other end's hue, but still ramped SATURATION from 0 to the target's own
    value (`sat(t) = t * target_sat`) — producing a dim-AND-desaturated
    (grey) midpoint the plain RGB path it replaced never produced (`mix_colors`
    scales an RGB vector, which leaves its saturation ratio unchanged). Fix:
    also adopt the other end's SATURATION for an achromatic endpoint, the
    same way hue already is, so only VALUE ramps — verified byte-identical
    to the plain RGB path in both directions (fade in from black, fade out
    to black) on real pairs from his library. Colour-to-colour crossings
    (neither endpoint achromatic) are untouched by construction — same
    formula as before for that branch, proven bit-identical, including the
    separately-filed muddy cream→blue crossing
    (`data/spectra-grey-midpoint-transition/brief.md`), whose own dip lives
    in `mix_colors` (the plain RGB path), not this function. Evidence:
    `scripts/check_hue_blend_achromatic_desaturation.py`; tests:
    `tests/test_hue_tween_achromatic_saturation.py`. Not yet ported back to
    the fork source at `/home/javi/ledfx-src`.

14. `effects/blackhole.py`: `_phase_burst()`/`draw()` — the drop-payoff
    explosion (BEHAVIOUR CHANGE, PR fm/spectra-blackhole-explosion-twice-as-
    fast). His ask, verbatim: "the timing is good on black hole, but the
    speed of the explosion after the implosion needs to be 2 times faster."
    New constant `PHASE_BURST_SPEED_MULT = 2.0` doubles the outward velocity
    of ONLY the drop-payoff burst's own particles (tagged `p_is_burst`) in
    `draw()`'s `out_mask` branch, paired with `_phase_burst()` halving those
    same particles' `p_out` outward-flight duration — same reach, half the
    time, not a bigger burst. `_erupt_burst`'s cross-effect handoff
    eruptions share the `out_mask`/`p_out` mechanism but are never tagged
    `p_is_burst`, so they are untouched. The pinch (implosion) and the
    post-burst horizon ease-back (`DROP_RESET_S`) are both untouched, so the
    burst still fires on the exact same frame relative to the trigger as
    before — evidence: `scripts/check_blackhole_explosion_speed.py`, tests:
    `tests/test_blackhole_explosion_speed.py`. Not yet ported back to the
    fork source at `/home/javi/ledfx-src`.

15. `effects/fireworks.py` + `effects/fireworks1d.py`: flare-driven payoff
    burst (NEW MECHANISM, PR fm/fireworks-burst-flare). New `burst_rockets`
    config key (int, 0–12, default 0, ADVANCED) on both effects — SpotFX's
    `firework_burst` flare kind writes an instant "explode N payoff rockets
    NOW" count; the effect edge-detects it in `config_updated` exactly like
    the phase key (a stale persisted value never fires on a fresh
    instance), consumes it in the next draw, and self-resets the key to 0
    via the same sanctioned in-render `_apply_config(validate=False,
    fire_event=False)` path the drop's own phase auto-reset uses, so an
    identical later write edges again. The spawn itself is the drop
    payoff's OWN shape, factored into `_payoff_burst_at()` and called by
    both `_rocket_payoff()` (unchanged behaviour) and the new
    `_flare_burst()`: fireworks1d's two staggered pairs per origin
    (PAYOFF_SPEED + the 0.6x stagger, PAYOFF_LIFE, bright 1.0,
    ignore_cap); fireworks' one giant burst per origin (burst_size*2.5
    min 24 particles, PAYOFF_SPEED, PAYOFF_LIFE, bright 1.0, ignore_cap)
    at the payoff's own near-center origin spread. Purely additive — live
    particles, lull rockets, and the phase machinery are untouched, and
    the burst deliberately still lands during a lull, exactly as the drop
    payoff itself does. Tests: `tests/test_firework_burst.py`. Not in the
    fork source at `/home/javi/ledfx-src` (SpotFX-authored mechanism).

16. `effects/fireworks.py`: drop/lull rockets launch RADIALLY EQUIDISTANT
    (owner ask, 2026-08-21, PR fm/fireworks-rocket-angles). `_launch_rockets`
    used to draw each of the LULL_ROCKETS start angles independently
    (`rng.uniform(0, 2*pi, k)`), so the six rockets clumped; the new
    `_rocket_start_angles(k)` is the ONE angular plan — even `2*pi/k`
    spacing, the whole ring randomly rotated per launch, each rocket
    nudged by at most `LULL_ROCKET_WIGGLE_FRAC` (1/6 of the step, +/-10
    degrees at six rockets — small enough that the ring still reads as a
    ring and no two rockets can ever swap order). `end_r` (0.36–0.76 past
    centre), the +/-0.5 rad end-angle jitter and LULL_ROCKETS=6 are
    deliberately unchanged (he praised them). `fireworks1d` needs no change:
    its two rockets leave from the fixed strip ends, equidistant by
    construction. Tests: `tests/test_fireworks_rocket_angles.py`. Not in
    the fork source at `/home/javi/ledfx-src`.

17. `effects/fireworks.py` + `effects/fireworks1d.py`: the DROP TAIL
    (BEHAVIOUR CHANGE, PR fm/fireworks-drop-tail; #16 is the concurrent
    rocket-angles PR). His ask, verbatim: "On the fireworks drop there need
    to be fireworks spawning continuously after the first big burst." Two
    mechanisms, both effects identically: (a) new constants `DROP_TAIL_RATE`
    (8 launches/s) / `DROP_TAIL_S` (2.5 s) beside the other choreography
    constants — after `_rocket_payoff()` fires on the drop edge, `_drop_
    tail_step()` runs a shower of ORDINARY fireworks (ordinary size/speed/
    life, never the payoff's PAYOFF_* shape) at a rate easing linearly
    from DROP_TAIL_RATE to 0 over DROP_TAIL_S — the charge's own linear
    ramp, mirrored on the way out — on its OWN clock (`_tail_t`), because
    the drop phase still self-resets at the untouched `DROP_SETTLE_S`
    (0.9 s) and the tail must outlive it. It is a launch RATE, not a
    `_pspawn` multiplier: his real Fireworks V2 entries run `spawn_rate=0`
    (beat bursts only), where any spawn_rate multiplier — including the
    charge's CHARGE_SPAWN_X — is inert. Tail launches pass `ignore_cap`
    like the payoff. (b) particles spawned past the density cap (payoff,
    flare burst, tail, lull rockets) are flagged `p_nocap`/`f_nocap` (new
    SoA member, compacted with the rest, carried in the native handoff
    snapshot) and NO LONGER OCCUPY `max_blobs`: `_capacity()` /
    `_spawn_firework`'s room count them out, so the ordinary show keeps
    launching underneath the payoff's afterglow. Measured pre-fix on the
    real pipeline: the payoff's ignore_cap particles held the live count
    over max_blobs for PAYOFF_LIFE x burst_life (~2.6 s at his crystal's
    burst_life 1.9, ~1.5 s at defaults) and EVERY ordinary launch — his
    beat bursts — was swallowed for that long; the firework_burst flare
    (#15) did the same after each flare. That silence, then the ordinary
    show popping back, was the cliff. LULL_ROCKETS, end_r, PAYOFF_*, the
    flare's counts, and DROP_SETTLE_S are unchanged. Evidence:
    `scripts/check_fireworks_drop_tail.py` (incl. his real spawn_rate=0 /
    beat-burst config), tests: `tests/test_fireworks_drop_tail.py`. Not
    in the fork source at `/home/javi/ledfx-src`.

18. `effects/blackhole.py`: the reverse RELEASE fall-back (BEHAVIOUR
    CHANGE, PR fm/blackhole-drop-suite). His ask, verbatim: "I like how on
    reverse, the event horizon immediately ejects blobs, but when it
    reverses back to normal, currently the blobs immediately change
    direction. I want them to accelerate back to the black hole, but not
    immediately change direction. Just start falling back using the
    acceleration value we have... The current setting is too jerky."
    `reverse` is a spawn-side flag that ALSO picks the sign in draw()'s
    `new_r = r ± v·dt`, so the momentary flare's release flipped the whole
    outbound population's direction in one frame. New per-particle SoA
    members `p_turn`/`p_vr` (compacted and carried in the native handoff
    snapshot like every other member) plus `REVERSE_FALLBACK_TURN_S = 0.5`:
    on the reverse True→False EDGE (`_reverse_edge`, armed in
    `config_updated` exactly like the phase key — never on an ordinary
    config write) every live blob enters a turnaround carrying the exact
    outward speed it already had, decelerates at 2·v(r)/TURN_S — the
    effect's OWN speed curve, so the turn takes TURN_S regardless of
    base_speed, radius or the live audio boost — passes continuously
    through zero and MERGES into ordinary infall the instant its velocity
    equals the curve's own speed for its radius (no step at either seam:
    unlike `p_out`'s expiry, which stalls to zero and hands the particle
    full-speed infall on the next frame). The False→True eject is
    deliberately untouched and still instant — his liked half. Second,
    smaller change in the same mechanism: a horizon captive is now PINNED
    to the ring only while it is within `REVERSE_FALLBACK_RING_TOL` (0.02)
    of it, so a captive the outflow carried off the ring falls back under
    ordinary physics instead of being teleported onto the ring on the
    flip-back frame — inert in ordinary infall, where a pinned orbiter sits
    exactly at `rh`. That teleport is the defect PR #179 correctly
    diagnosed and fixed by RELEASING every captive on every reversed frame;
    #179 was reverted the same day (#181, no reason recorded) and is NOT
    relanded here — releasing also evicts blobs the flare never moved
    (restarting their hold clock and horizon colour blend) and makes them
    immortal, since the infall alive-test retires captives by their hold
    clock and never free-fallers. Nothing is released by this change.
    `blackhole1d.py` is deliberately NOT mirrored: it has no capture
    mechanism, and his Strips entry authors `reverse: true` as its own
    baseline, so the flare's absolute `reverse=True` write is a no-op
    there. Evidence: `scripts/check_blackhole_reverse_fallback.py`; tests:
    `tests/test_blackhole_reverse_fallback.py`. Not in the fork source at
    `/home/javi/ledfx-src`.

19. `effects/blackhole.py`: the BLOB RUSH (NEW MECHANISM, PR
    fm/blackhole-rush-and-charge-lull). His ask, verbatim: "add a new
    effect that runs as a shape flare that randomly chooses between the
    momentary reverse and this one. This one is called 'blob rush' and it
    just generates 12 blobs all at once spread out fairly evenly. Override
    any max blob counts for this generation if that's easy, or remove the
    ones in the event horizon." New `blob_rush` config key (int, 0-64,
    default 0, ADVANCED) — SpotFX's `blob_rush` flare kind writes an
    instant "spawn this many blobs NOW" count; the effect edge-detects it
    in `config_updated` exactly like the phase key and fireworks'
    `burst_rockets` (#15) — a stale persisted value never fires on a fresh
    instance — consumes it in the next draw, and self-resets the key to 0
    via the same sanctioned in-render `_apply_config(validate=False,
    fire_event=False)` path. `_blob_rush()` places the blobs at even
    `2*pi/k` angles, the whole ring randomly rotated per rush, each nudged
    by at most `BLOB_RUSH_WIGGLE_FRAC` (1/6, fireworks' own wiggle from
    #16) of one step; `_spawn()` grew `theta=`/`ignore_cap=` keyword
    arguments so the rush reuses the ordinary spawn's own colour/placement
    logic — arriving just past the true per-direction hex boundary in
    infall (#12) and from the horizon ring in reverse — while bypassing
    `max_blobs` via the existing `p_is_burst` no-cap tag. His first
    override option was taken and his second ("remove the ones in the
    event horizon") deliberately was NOT: nothing already on screen is
    touched. Purely additive: no carry, no release, no lead. Deliberately
    NOT mirrored to `blackhole1d` — it is a 1px ring view with no hex
    boundary to arrive from, and his ask named Black Hole's own event
    horizon and max blob counts. Evidence: `scripts/check_blob_rush.py`
    (his real Black Hole V2 scene, read-only, at his crystal's 72x37
    shape); tests: `tests/test_blob_rush.py`. Not in the fork source at
    `/home/javi/ledfx-src` (SpotFX-authored mechanism).

20. `effects/blackhole.py` + `effects/blackhole1d.py`: the CHARGE/LULL
    rework (BEHAVIOUR CHANGE, PR fm/blackhole-rush-and-charge-lull; the
    DROP is deliberately untouched by it). His ask, verbatim: "on the drop
    sequence, for charge: instead of the black hole expanding, accelerate
    the number of blobs forming (up to 12/second, but not all at once),
    ignore max counts, accelerate their fall speed, and increase the
    thickness of the event horizon slowly. Then, on the lull, continue the
    fast blob falling but expand the event horizon until it fills the hex
    (i think it currently expands too far) at half way through the duration
    of the lull. So half of the lull should be dark. Then the drop can stay
    the same as it is now."

    CHARGE: `_horizon_radius` now returns the plain audio baseline for the
    whole build — the quadratic swallow to `r_max` is gone, and with it the
    black disc that trailed it by `CHARGE_HALO_LEAD` (retired; `_disc_radius`
    is now always the horizon itself). What builds instead: `_phase_halo`'s
    ring half-thickness grows `CHARGE_HALO_W_MIN`→`_MAX` (0.05→0.34);
    `_phase_spawn_rate()` forces blobs into being at
    `CHARGE_SPAWN_RATE_MAX * p**CHARGE_SPAWN_CURVE` (12/s at p=1, quadratic
    so it accelerates in rather than stepping up) through a per-frame
    accumulator, additive to the ordinary spawn and past `max_blobs` via
    `_spawn(ignore_cap=True)`; `_phase_speed_mult()` scales infall speed
    1.0→`CHARGE_FALL_SPEED_MAX` (2.0) linearly in p.

    LULL: the horizon expands from the baseline to `HEX_FILL_RADIUS`
    (+`LULL_FILL_MARGIN`) at `LULL_FILL_PROGRESS` (0.5) and HOLDS, and the
    halo stops painting once filled, so every REAL cell of his hex panel is
    black for the second half. `HEX_FILL_RADIUS` is the measured hex
    silhouette's own furthest vertex (1.128, computed from
    `HEX_SPAWN_VERTS` — see deviation #12 and `.claude/skills/
    crystal-hex-grid/SKILL.md`), NOT `r_max` (1.49 on his crystal, the
    addressable RECTANGLE's corner): that difference is his "it currently
    expands too far" — past the hex every further pixel of growth covers
    dead cells. The forced formation and the fast fall CONTINUE through the
    lull's first half; `_phase_spawn_paused` now pauses spawning only after
    the fill, never from lull entry, and no longer has a charge clause at
    all.

    A SECOND PARTICLE FLAG: `p_nocap` (compacted and carried in the native
    handoff snapshot like every other member) is now what the density-cap
    arithmetic reads. `p_is_burst` keeps its narrower meaning — "a
    drop-payoff particle", which additionally drives
    `PHASE_BURST_SPEED_MULT` — so the charge/lull's forced blobs and the
    blob rush (#19) bypass the cap without being mistaken for payoff
    particles by anything that measures the explosion. Same split
    `fireworks` made for the same reason (#17).

    `blackhole1d` mirrors exactly the two halves that translate: the
    accelerating formation (its own `_phase_spawn_rate`/`_phase_speed_mult`
    and an `ignore_cap` on `_spawn`) and the half-way-dark lull ("fills the
    hex" becomes "covers the strip" — it is a 1px ring view with no hex
    silhouette of its own), with its charge halo thickening in place on the
    sample ring instead of sweeping the strip away. Its pre-existing lull
    phosphor dot is kept, and its drop is untouched. TIMING HONESTY: SpotFX
    ramps `phase_progress` over ~90% of the real gap and then hangs at 1.0
    (`scene_response._phase_ramp_ms`), so p=0.5 lands at ~45% of the lull's
    true wall-clock duration — the closest an effect can get without being
    told the duration. Evidence:
    `scripts/check_blackhole_charge_lull.py` (darkness measured over
    crystal-mapper's REAL cells, not the dummy rectangle); tests:
    `tests/test_blackhole_charge_lull.py`, with
    `scripts/check_drop_visible_onset.py` and
    `tests/test_blackhole_orphan_drop_none_crash.py` re-run green for the
    untouched drop. Not in the fork source at `/home/javi/ledfx-src`.

21. `effects/fish.py`: an ENTIRELY NEW, SpotFX-authored effect (PR
    fm/fish-effect-and-scene, his ask 2026-08-25). Not in the fork source at
    `/home/javi/ledfx-src` and not derived from any fork effect line by
    line: it is Orbits' visual language (SoA particles, enter/leave
    lifecycle, audio impulse plumbing, trail buffer, the twod projection,
    the phase-key state machine, the particle-handoff protocol) carrying
    completely different kinematics — per-fish position/velocity/heading, a
    rate-limited turn built from a real turn RADIUS, a flapping spine
    rendered as a chain of splats along the heading, and an expanding
    ripple wake composited straight to the output instead of through the
    trail buffer. Orbits itself is UNTOUCHED.

    Mutual avoidance (`avoid_strength`, added 2026-08-28, PR
    fm/fish-collision-avoidance — his own deferral un-parked: "add the
    collision") is STEERING ONLY, by construction: it contributes one more
    weighted term to the desired-heading vector sum and is then bounded by
    the same turn-rate clamp as every other steer, so neither fish law can
    be broken — no reverse on the spot, no turn tighter than the radius, and
    never a written position. Only neighbours inside the forward arc count
    and the answer is a lateral SWERVE, not a point-away vector (pointing
    away from a fish dead ahead asks for a 180 the clamp then spends a whole
    arc serving, while the crossing happens anyway — measured: the
    point-away form RAISED crossings and clamp saturation). The separation
    radius is DERIVED from body length (`AVOID_SEP_BODIES`), never a second
    knob. Off entirely while a school is formed, and rushing fish neither
    steer nor count as neighbours: the charge's school moves "almost
    identically" and the lull's rush is deliberately chaotic — authored
    choreography, not crowds to fix. `avoid_strength=0` is byte-identical to
    the pre-feature effect (asserted, not claimed). Default 0.45, tuned at
    HIS live state (jiggle 0.5, roam_scale 0.75) —
    `scripts/check_fish_avoidance.py` prints the sweep.

    Two one-line supporting edits, both purely additive: `effects/radial.py`
    adds `"fish"` to the src whitelist its `_adopt_handoff` gate uses (no
    existing source's behaviour changes), and `fx/device_model.py`'s
    `PHASE_EFFECTS` gains `"fish"` so charge/lull/drop reach it. SPECTRA's
    own `services/transition_phases.py` adds fish to `_PARTICLES`; the
    legacy twin (`services/transition_phases.py` at the repo root) is
    deliberately NOT changed, because fish exists only in this vendored
    pipeline and never in the LedFX service that registry describes.

    THE POPULATION CAP: the `p_nocap` tag (the same flag #17/#20 established
    for fireworks and blackhole) is granted at exactly two scripted moments
    — the charge's school and the lull's rush — and never survives them.
    `CAP` is sized so both plus a full drop explosion fit at once
    (`tests/test_fish.py::test_buffer_headroom_holds_school_rush_and_explosion_at_once`).
    THE LUNGE (`LUNGE_*`, 2026-08-28, same PR — his own live diagnosis):
    the ripple correctly scales off real speed and flap, but the beat speed
    boost decayed within tens of milliseconds, so a big ring rode a tiny
    travel. A spike at or above `LUNGE_SPIKE_MIN` now arms a per-fish
    envelope that HOLDS the boost near full for `LUNGE_HOLD_S` (0.6 s)
    before releasing on `LUNGE_FALL_S`. Motion side ONLY — the wake is
    untouched and self-heals once the travel widens. Magnitude keeps riding
    `speed_jump` x the existing spike signal, so the menu gains no knob, and
    below the threshold nothing arms and nothing decays: quiet swimming is
    byte-identical (asserted). Measured, 4 seeds, distance covered in the
    1 s after a strong beat under a real music envelope: 2.98 -> 5.55 body
    lengths (+86%); the hold is what does it (hold 0 s -> 4.82).
    `scripts/check_fish_lunge.py` prints the sweep.

    Evidence: `scripts/check_fish.py` (eight measured sections on the real
    pipeline), `scripts/check_fish_avoidance.py`,
    `scripts/check_fish_lunge.py`, `tests/test_fish.py`.

22. `effects/radial.py`: a QUIET BASE ROTATION FLOOR (NEW PARAM +
    BEHAVIOUR, PR fm/radial-base-rotation). His ask, verbatim: "i like the
    current reactivity speed of the radial effect in the star scene, but I
    want there to be some minimum absolute value for the base speed the
    pattern rotates at. The Speed parameter in the scene definition seems
    to be related to reactive speed (like the current settings). I want to
    be able to define the quiet base speed of rotation as well." His
    reading of `spin`/Speed is exactly right and already documented:
    `docs/spectra-star-motion-audio-idle.md` — the vendored effect's ONLY
    motion source is `audio_data_updated`'s `spin_total += impulse * spin`,
    where `spin = nonlinear_log(spin_cfg, 2)/10` is a SQUARED GAIN on the
    live captured lows power. A gain can never produce motion in silence at
    any value; an additive term is the only thing that can.

    New config key `base_rotation` (float, `[0.0, 2.0]`, default **0.0** —
    every existing scene, his STAR included, renders byte-identically until
    he sets it; `scripts/check_radial_base_rotation.py` §1 asserts the
    frames match). It is declared on the EFFECT, not on one scene's
    instance, so any radial entry can carry it. UNITS ARE DELIBERATELY
    UNLIKE `spin`: `base_rotation` is LINEAR and ABSOLUTE, in REVOLUTIONS
    PER SECOND (0.05 = one turn per 20s), where `spin` is squared and then
    multiplied by live audio. `config/effect_params.json`'s own note and
    help topic `radial-base-rotation` both say so in as many words.

    SEMANTICS ARE A FLOOR, NOT A SUM — firstmate's pick, named rather than
    silent: `effective rev/s = max(base_rotation, reactive rev/s)`, so a
    base never adds anything at a peak and the existing reactivity is
    preserved exactly wherever the music's own drive is faster. (The
    alternative, a SUM, would speed every peak up slightly; the knob's
    semantics make either a one-line change in `_base_rotation_step`.)

    WHERE IT ADVANCES is load-bearing: the base rides the RENDER clock
    (`draw` → `_base_rotation_step(dt)`, `dt = self.passed`), never the
    audio callback. Audio callbacks stop entirely when the capture pipeline
    stalls or the effect is unsubscribed — a base term living there would
    stall in exactly the quiet case it exists for. `audio_data_updated`
    additionally accumulates its own advance into `_reactive_advance`,
    which `_base_rotation_step` drains (unconditionally, so it can never
    carry a stale frame across a base=0 stretch) to know how much of this
    frame's revolutions the audio already paid for.

    INTERACTIONS PRESERVED: direction comes from the same sign ladder the
    charge phase already used — `sign(spin)` (which is what the
    `spin_sign`/Flip sign-control write sets), else `sign(twist)`, else
    clockwise — so the base always follows the current direction and never
    fights a reverse flare; `spin_total` still stays in `[0, 1)` (the `%
    1.0` is applied on the base write too, and Python's float modulo
    returns a positive result for a negative operand); the charge phase's
    own `CHARGE_SPIN_REV_S` boost is unchanged and additive on top (the
    floor is measured against the AUDIO drive only — a deliberate,
    documented scope, since the charge is a brief authored accelerator, not
    the quiet case); and the particle-handoff snapshot's `spin_sign` read
    is untouched.

    Evidence: `scripts/check_radial_base_rotation.py` (real `fx.headless`
    pipeline — byte-identical frames at base=0, the measured rate in
    silence, and the reactive rate at a peak proven identical with and
    without a base) and `tests/test_radial_base_rotation.py`. Not in the
    fork source at `/home/javi/ledfx-src` (SpotFX-authored mechanism).

Everything else is byte-identical to the fork at 149f4470 modulo the import
rewrite and the deviations above. When updating vendored files, re-diff
against that commit.
