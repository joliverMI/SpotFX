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

11. `virtuals.py` + `devices/__init__.py`: per-device flush cadence
    (BEHAVIOUR CHANGE — data/spectra-crystal-colour-lag/report.md, PR
    fm/spectra-per-device-cadence). `Virtual.refresh_rate` used to be BOTH
    the render loop's own clock (`thread_function`'s sleep interval) AND
    the per-device network-flush ceiling (via `Device.update_pixels`'s
    unconditional `self.flush(frame)` whenever called by the device's
    `priority_virtual`) — `min(device.max_refresh_rate for device in
    self._devices)`, so ANY virtual combining a deliberately slow device
    (a wifi/pixel-count-constrained unit, capped on purpose) with a faster
    sibling forced the WHOLE virtual, including the faster device, down to
    the slow one's cadence. Confirmed live and currently active on the
    `hues` virtual (`dining-hues` 30fps + `hue-lights` 62fps, both Hue) at
    diagnosis time; not currently live for `crystal` specifically because
    `Crystal-Mapper` happens to be a single-real-device virtual today — but
    the mechanism is real, in the vendored render engine, not topology
    luck, and the Admiral's ruling (`crystal`'s 30fps config stands,
    unconditionally) means the general case has to be fixed rather than
    worked around by keeping crystal permanently siloed.

    Fix, in two parts:
    - `Virtual.refresh_rate` (min) is UNCHANGED — still feeds
      `Device.refresh_rate`/`priority_virtual` exactly as before, zero
      regression risk to that reporting path. A NEW `Virtual.render_rate`
      (max across `self._devices`) drives the render thread's own sleep
      interval (`thread_function`) and the two transition-frame-count
      sizings (`set_effect`, `clear_effect`) — the loop now assembles and
      offers a frame often enough to serve the FASTEST member.
    - `Device.update_pixels()`'s real `self.flush(frame)` call (the only
      choke point all three of `Virtual`'s flush paths — simple/complex/
      shape-resample segments — converge on) is gated by a per-device
      pacing check against `self.max_refresh_rate` (a new
      `_last_flush_time` monotonic timestamp, reset in `activate()`): a
      device only receives a REAL network flush at its own configured
      rate, however often its priority virtual's loop actually ticks. The
      device's pixel buffer (`self._pixels`) is still updated every call,
      so a paced-down flush always sends the latest frame, never a stale
      one — this is delivery pacing, not staleness.

    Net effect: a virtual's slowest device keeps rendering at exactly its
    own configured rate (crystal's 30 is untouched — its own siblings-free
    virtual is a no-op case for this fix, `min([30]) == max([30])`); any
    faster sibling sharing a virtual with it is no longer capped down —
    proven headless in `tests/test_per_device_cadence.py` (two dummy
    devices, 30fps + 62fps, one virtual, real render thread; asserts the
    fast device's real-flush count is NOT pulled toward the slow one's) and
    validated live against the room's one existing mixed-rate virtual
    (`hues`) via the liveness flush-cadence endpoint. Not yet ported back
    to the fork source at `/home/javi/ledfx-src`.

Everything else is byte-identical to the fork at 149f4470 modulo the import
rewrite and the deviations above. When updating vendored files, re-diff
against that commit.
