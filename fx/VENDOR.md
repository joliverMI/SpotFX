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

Everything else is byte-identical to the fork at 149f4470 modulo the import
rewrite and the deviations above. When updating vendored files, re-diff
against that commit.
