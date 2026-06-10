"""
SpotFX — LedFX REST API client.

Responsibilities:
  - Fire scenes / effect commands
  - Measure round-trip latency to LedFX (used for trigger timing offset)
  - List available scenes (for the UI music event builder)
  - Read / write virtual effect configs and global settings
  - Poll key virtual states every 5 s (cached in state.ledfx_virtual_cache)

Command bus
-----------
set_virtual_effect and set_config queue into an 8 ms coalesce window.
Within the window, patches for the same (virtual, effect_type) key are merged
(newer keys overwrite older), then all pending updates fire simultaneously via
asyncio.gather. This means two concurrent ramps on the same virtual produce one
HTTP request per step instead of two, and near-simultaneous instant commands
targeting the same virtual are merged atomically.

Anything that does not benefit from merging (trigger_scene, set_virtual_config,
all reads) calls the internal _direct variants and bypasses the bus.
"""
from __future__ import annotations
import asyncio
import logging
import time
from collections import deque
from typing import Optional

import httpx

from config import settings
from models.state import state

logger = logging.getLogger(__name__)

# Shared async client (reuse connections)
_client: Optional[httpx.AsyncClient] = None

# Separate client for the latency probe so the probe's RTT measurement isn't
# contaminated by queueing behind trigger writes. The main client caps
# concurrent connections to avoid overloading LedFX; the probe needs its own
# connection to reflect true network+server RTT, not pool queue time.
_probe_client: Optional[httpx.AsyncClient] = None

# Cached global brightness — updated whenever we set it so ramps start from the right value
_current_brightness: float = 1.0

# ── Command bus ────────────────────────────────────────────────────────────────
_effect_bus: dict[tuple, dict] = {}   # (virtual_id, effect_type) → merged config patch
_config_bus: dict = {}                # global config patch (global_brightness, etc.)
_bus_task: Optional[asyncio.Task] = None
BUS_WINDOW_MS = 8  # coalesce window; must be << ramp step_ms (25 ms)


# ── Ambient-mode trigger exclusion ──────────────────────────────────────────────
# When SpotFX Ambient Mode is on, the targeted virtuals are driven to a static
# full-brightness color via the Hue REST API (see services/ambient_mode.py) and
# must be ignored by the trigger engine. Rather than filter at every action type,
# we drop their writes at the single choke point all effect/config writes pass
# through (_set_virtual_effect_direct + set_virtual_config). Updated on toggle.
_ambient_excluded: set[str] = set()


def set_ambient_excluded(virtual_ids) -> None:
    """Replace the set of virtuals whose trigger-driven writes should be dropped."""
    global _ambient_excluded
    _ambient_excluded = set(virtual_ids or ())
    logger.info("Ambient-mode excluded virtuals: %s", sorted(_ambient_excluded) or "(none)")


def is_ambient_excluded(virtual_id: str) -> bool:
    return virtual_id in _ambient_excluded


_capture_gate_diag_logged = False
# Counter-based "force allow" so callers can temporarily bypass the capture
# gate. Used by manual fire paths (events.html → POST /events/{id}/fire) so
# the user's explicit action always reaches LedFX even mid-capture. Counter
# (not bool) so nested usage and concurrent fires don't fight.
_force_allow_count = 0


def _capture_in_progress() -> bool:
    """Return True when audio_shape_service is recording any URI. Used to
    short-circuit LedFX HTTP calls so the capture doesn't compete with
    LedFX writes for event-loop time / PulseAudio frames. Re-enables
    automatically when capture finishes (audio_shape_service clears its
    `_recording_uri` and the next call dispatches normally).

    Returns False whenever `_force_allow_count > 0`, so manual-fire paths
    wrapped in `force_allow()` always pass through. Also returns False when
    the `suppress_triggers_during_capture` setting is OFF, letting triggers
    fire during capture.
    """
    if _force_allow_count > 0:
        return False
    try:
        from config import settings
        if not settings.suppress_triggers_during_capture:
            return False
    except Exception:
        pass
    global _capture_gate_diag_logged
    try:
        from services.audio_shape_service import audio_shape_service
        rec = audio_shape_service._recording_uri
        if rec and not _capture_gate_diag_logged:
            logger.info("LedFX gate: capture detected, muting LedFX calls (uri=%s)", rec)
            _capture_gate_diag_logged = True
        elif not rec and _capture_gate_diag_logged:
            logger.info("LedFX gate: capture finished, resuming LedFX calls")
            _capture_gate_diag_logged = False
        return bool(rec)
    except Exception as exc:
        if not _capture_gate_diag_logged:
            logger.warning("LedFX gate: could not read audio_shape_service: %r", exc)
            _capture_gate_diag_logged = True
        return False


def capture_muting_active() -> bool:
    """True when LedFX writes are currently being muted by the capture gate
    (capture in progress, suppress setting on, not inside force_allow()).

    The trigger engine checks this to DEFER firing instead of dispatching a
    fire that would be silently dropped while still marking the trigger fired —
    which permanently loses every trigger that lands during a capture window.
    """
    return _capture_in_progress()


from contextlib import contextmanager

@contextmanager
def force_allow():
    """Temporarily disable the capture gate for the wrapped block. Used by
    fire_event_now so manual test-fires from the UI always reach LedFX,
    capture in progress or not. Callers should `await drain_bus()` before
    leaving the context if their writes go through the coalesce bus — the
    bus flush task fires 8 ms later, and if it lands after the context
    exits the writes will hit the closed gate again."""
    global _force_allow_count
    _force_allow_count += 1
    try:
        yield
    finally:
        _force_allow_count -= 1


async def drain_bus() -> None:
    """Await any in-flight coalesce-bus flush so writes queued during the
    surrounding `force_allow()` block actually reach LedFX before the gate
    closes again. Safe to call when no flush is pending (no-op)."""
    task = _bus_task
    if task is None or task.done():
        return
    try:
        await task
    except Exception:
        pass


# ── Server-side param-tween capability ───────────────────────────────────────
# Does the connected LedFX interpolate config params for us (the `transition_ms`
# field on PUT /api/virtuals/{id}/effects)? None = not yet probed. Populated by
# refresh_capabilities() at startup. We must NOT send transition_ms to a LedFX
# that lacks the feature: it would silently ignore it and apply an instant jump
# (worse than the client-side ramp), so the legacy loops stay the fallback.
_server_tween_supported: Optional[bool] = None


async def refresh_capabilities() -> None:
    """Probe GET /api/info once and cache whether LedFX supports server-side
    param tweening. Safe to call repeatedly (e.g. after reconnect)."""
    global _server_tween_supported
    resp = await _request("GET", "/api/info", label="info")
    if resp is None:
        return
    try:
        feats = (resp.json() or {}).get("features", {}) or {}
        _server_tween_supported = bool(feats.get("param_transition", False))
    except Exception:
        _server_tween_supported = False
    logger.info(
        "LedFX server-side param tween: %s",
        "supported" if _server_tween_supported else "not supported",
    )


def server_tween_enabled() -> bool:
    """True only when the user setting AND the live LedFX capability both allow
    server-side tweening."""
    return bool(settings.server_side_tween) and _server_tween_supported is True


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=settings.ledfx_url,
            # Split timeout instead of a blanket 5.0s. LedFX is on localhost and
            # answers in ~1ms, so a 5s *read* meant one stalled request camped on
            # its connection for 5 full seconds — long enough for 40fps ramps to
            # exhaust the pool during a brief LedFX hiccup. read/write 1.5s still
            # leaves huge margin but releases a hung conn 3x sooner. pool=0.5s
            # makes a saturated pool fail fast (shed the frame) rather than queue.
            timeout=httpx.Timeout(connect=2.0, read=1.5, write=1.5, pool=0.5),
            # 8 was too small under bursty load: a flare chain (4-8 patches at
            # once) plus the periodic latency probe + virtual-state poll +
            # snapshot-warm fans out faster than the pool can recycle, and
            # observed pool degradation pinned conns at 1 with steady
            # ConnectTimeouts. 32 gives headroom for parallel bursts;
            # localhost handles many concurrent loopback sockets cheaply,
            # and httpx still queues writes per-connection. The in-flight
            # semaphore (24) is the real bound — it binds before the pool does,
            # so backpressure queues gracefully instead of raising PoolTimeout.
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
        )
    return _client


# ── Load governor: in-flight semaphore + circuit breaker ────────────────────────
# Background: a brief LedFX stall used to spiral into a pool-exhaustion storm.
# Ramps fire frames at 40fps across every virtual and the bus flush overlaps
# under stall, so concurrent connection demand climbed without bound until the
# pool saturated and every call raised PoolTimeout — pinning a CPU and flooding
# the log. There was no backpressure. These two mechanisms add it:
#   1. Semaphore caps SpotFX's *total* concurrent LedFX requests, so overlapping
#      ramps/flushes queue on the slot instead of racing for connections.
#   2. Circuit breaker: after N consecutive failures it opens for a short
#      cooldown, during which calls short-circuit (frames shed) instead of
#      hammering a dead/slow LedFX. Auto-closes on the first success.
_LEDFX_MAX_INFLIGHT = 24          # < pool max_connections (32) so we bind here first
_HELD_THRESHOLD_MS = 30.0         # record a "held" event when a frame waits >this for a slot
_BREAKER_FAIL_THRESHOLD = 5       # consecutive failures before the circuit opens
_BREAKER_COOLDOWN_S = 2.0         # how long the circuit stays open before a half-open probe

# Pool self-heal: the breaker handles a slow/dead LedFX, but it can't escape a
# *wedged pool* — leaked CLOSE-WAIT sockets (e.g. seeded by a LedFX restart that
# severs SpotFX's keepalive connections) squat on all 32 pool slots, so every
# request — including the breaker's half-open probe — raises PoolTimeout forever.
# When failures persist past this many seconds, recycle the httpx client: close
# it and rebuild a fresh pool, dropping the dead sockets so the next probe can
# actually connect. Duration-based (not a raw count) so it fires whether the
# failures arrived in one burst or one-per-cooldown-probe.
_RECYCLE_AFTER_FAIL_S = 5.0       # continuous-failure duration before recycling the client
_RECYCLE_MIN_INTERVAL_S = 5.0     # don't recycle more than once per this window

_inflight_sem: Optional[asyncio.Semaphore] = None
_consecutive_failures = 0
_breaker_open_until = 0.0         # time.monotonic() deadline; circuit open while now < this
_first_failure_at = 0.0           # time.monotonic() of the first failure in the current streak (0 = none)
_last_recycle = 0.0               # time.monotonic() of the last client recycle

# Rate-limit the failure log so a stall produces one line/sec, not a storm.
_last_fail_log = 0.0
_FAIL_LOG_INTERVAL_S = 1.0
_suppressed_fail_logs = 0

# ── Load-shed event ring buffer ─────────────────────────────────────────────────
# Server-side so the Debug page shows the last several events even if it wasn't
# open when they happened. Survives page reloads (not service restarts). Events
# of the same kind within _EVENT_COALESCE_S collapse into one row with a count,
# so a burst reads as "held ×312" rather than 312 rows.
_events: deque = deque(maxlen=60)
_event_counters: dict = {"held": 0, "shed": 0, "breaker_open": 0, "recovered": 0, "recycled": 0}
_EVENT_COALESCE_S = 2.0


def _record_event(kind: str, detail: str = "", held_ms: Optional[float] = None) -> None:
    now_wall = time.time()
    _event_counters[kind] = _event_counters.get(kind, 0) + 1
    if _events:
        last = _events[-1]
        if last["kind"] == kind and (now_wall - last["ts"]) < _EVENT_COALESCE_S:
            last["count"] += 1
            last["ts"] = now_wall
            last["detail"] = detail
            if held_ms is not None:
                last["max_held_ms"] = max(last.get("max_held_ms", 0.0), held_ms)
            return
    ev = {"ts": now_wall, "kind": kind, "detail": detail, "count": 1}
    if held_ms is not None:
        ev["max_held_ms"] = held_ms
    _events.append(ev)


def _get_sem() -> asyncio.Semaphore:
    # Constructed lazily on first use so it binds to the running event loop.
    global _inflight_sem
    if _inflight_sem is None:
        _inflight_sem = asyncio.Semaphore(_LEDFX_MAX_INFLIGHT)
    return _inflight_sem


def _breaker_is_open() -> bool:
    return _breaker_open_until > time.monotonic()


def _on_success() -> None:
    global _consecutive_failures, _breaker_open_until, _first_failure_at
    if _breaker_open_until:                 # was open or half-open → recovered
        _breaker_open_until = 0.0
        _record_event("recovered")
        logger.info("LedFX circuit recovered after %d consecutive failures", _consecutive_failures)
    _consecutive_failures = 0
    _first_failure_at = 0.0


def _on_failure(exc: Exception, label: str) -> None:
    global _consecutive_failures, _breaker_open_until, _last_fail_log, _suppressed_fail_logs, _first_failure_at
    _consecutive_failures += 1
    now = time.monotonic()
    if _first_failure_at == 0.0:            # mark the start of this failure streak
        _first_failure_at = now
    if now - _last_fail_log >= _FAIL_LOG_INTERVAL_S:
        extra = f" (+{_suppressed_fail_logs} suppressed)" if _suppressed_fail_logs else ""
        logger.error("LedFX request failed [%s]: %r%s", label, exc, extra)
        _last_fail_log = now
        _suppressed_fail_logs = 0
    else:
        _suppressed_fail_logs += 1
    if _consecutive_failures >= _BREAKER_FAIL_THRESHOLD:
        was_open = _breaker_open_until > now
        _breaker_open_until = now + _BREAKER_COOLDOWN_S   # (re)arm cooldown on each failure
        if not was_open:
            _record_event("breaker_open", f"{_consecutive_failures} consecutive fails")
            logger.warning(
                "LedFX circuit OPEN: %d consecutive failures, shedding for %.1fs",
                _consecutive_failures, _BREAKER_COOLDOWN_S,
            )


async def _maybe_recycle_client() -> None:
    """Self-heal a wedged connection pool. When requests have been failing
    continuously for longer than _RECYCLE_AFTER_FAIL_S — the signature of leaked
    CLOSE-WAIT sockets the breaker's cooldown can't clear — close the httpx
    client and drop the reference so the next _get_client() builds a fresh pool.
    Rate-limited to once per _RECYCLE_MIN_INTERVAL_S. Called from the failure
    path, so it runs on a half-open probe once the streak is old enough."""
    global _client, _last_recycle
    now = time.monotonic()
    if _first_failure_at == 0.0 or (now - _first_failure_at) < _RECYCLE_AFTER_FAIL_S:
        return
    if (now - _last_recycle) < _RECYCLE_MIN_INTERVAL_S:
        return
    _last_recycle = now
    old = _client
    _client = None                          # next _get_client() rebuilds a clean pool
    _record_event("recycled", f"{_consecutive_failures} fails over {now - _first_failure_at:.0f}s")
    logger.warning(
        "LedFX client recycled after %.0fs of failures (%d consecutive) — rebuilding connection pool",
        now - _first_failure_at, _consecutive_failures,
    )
    if old is not None:
        try:
            await old.aclose()              # close leaked sockets; safe — breaker is open, ~no in-flight
        except Exception:
            pass


async def _request(method: str, path: str, *, label: str, **kwargs):
    """Single choke point for every LedFX call on the main client. Applies the
    circuit breaker and in-flight semaphore, then sends the request.

    Returns the httpx.Response on success, or None when the call was shed
    (circuit open) or failed (logged + recorded). Never raises — callers map
    None to their own empty/false fallback. measure_latency() deliberately does
    NOT go through here: it uses the isolated probe client so its RTT reflects
    true server latency, not queue time."""
    if _breaker_is_open():
        _record_event("shed", label)
        return None
    sem = _get_sem()
    t0 = time.monotonic()
    await sem.acquire()
    held_ms = (time.monotonic() - t0) * 1000
    if held_ms >= _HELD_THRESHOLD_MS:
        _record_event("held", label, held_ms=held_ms)
    try:
        resp = await _get_client().request(method, path, **kwargs)
        resp.raise_for_status()
        _on_success()
        return resp
    except Exception as exc:
        _on_failure(exc, label)
        await _maybe_recycle_client()
        return None
    finally:
        sem.release()


def get_health() -> dict:
    """Snapshot of LedFX load-governor state for the Debug page. `now` is the
    server wall-clock so the client can render relative times without clock
    skew. Events are newest-first."""
    return {
        "now": time.time(),
        "breaker_open": _breaker_is_open(),
        "consecutive_failures": _consecutive_failures,
        "max_inflight": _LEDFX_MAX_INFLIGHT,
        "counters": dict(_event_counters),
        "events": list(reversed(_events)),
    }


def _get_probe_client() -> httpx.AsyncClient:
    """
    Dedicated httpx client for the latency probe. Keeping it separate from
    `_client` ensures the RTT measurement reflects true network+LedFX
    response time rather than the queue time waiting for a spot in the
    trigger-writes pool. Otherwise `effective_offset_ms` would swing
    wildly during chain bursts and shift trigger timing by seconds.
    """
    global _probe_client
    if _probe_client is None or _probe_client.is_closed:
        _probe_client = httpx.AsyncClient(
            base_url=settings.ledfx_url,
            timeout=2.0,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
        )
    return _probe_client


# ── Internal direct-fire helpers (bypass bus) ─────────────────────────────────

async def _set_virtual_effect_direct(virtual_id: str, effect_type: str, config: dict) -> bool:
    if virtual_id in _ambient_excluded:
        return True   # Ambient Mode owns this virtual via Hue REST; drop trigger writes
    if _capture_in_progress():
        return True   # capture-in-progress mute (acts like success so callers don't error)
    resp = await _request(
        "PUT", f"/api/virtuals/{virtual_id}/effects",
        json={"type": effect_type, "config": config},
        label=f"effect:{virtual_id}",
    )
    return resp is not None


async def _set_config_direct(patch: dict) -> bool:
    if _capture_in_progress():
        return True   # capture-in-progress mute
    resp = await _request("PUT", "/api/config", json=patch, label="config")
    return resp is not None


async def _set_virtual_effect_tween_direct(
    virtual_id: str, effect_type: str, config: dict, transition_ms: int, easing: str
) -> bool:
    """Single PUT asking LedFX to interpolate `config` params to target over
    transition_ms (server-side, per render frame). Same gating as
    _set_virtual_effect_direct."""
    if virtual_id in _ambient_excluded:
        return True
    if _capture_in_progress():
        return True
    resp = await _request(
        "PUT", f"/api/virtuals/{virtual_id}/effects",
        json={
            "type": effect_type,
            "config": config,
            "transition_ms": int(transition_ms),
            "easing": easing,
        },
        label=f"tween:{virtual_id}",
    )
    return resp is not None


async def set_virtual_effect_tween(
    virtual_id: str, effect_type: str, config: dict,
    transition_ms: int, easing: str = "linear",
) -> None:
    """Ask LedFX to smoothly interpolate `config` params to their targets over
    transition_ms, advanced server-side per render frame — one PUT instead of a
    ~40fps client loop. Drains the coalesce bus first so this lands after any
    queued instant writes, and commits the target into the local cache (the
    target is committed to LedFX now, so subsequent compiles should see it)."""
    await drain_bus()
    await _set_virtual_effect_tween_direct(
        virtual_id, effect_type, dict(config), transition_ms, easing
    )
    effect_cfg = (
        state.ledfx_virtual_cache.get(virtual_id, {})
        .get("effect", {})
        .get("config", {})
    )
    effect_cfg.update(config)


# ── Bus flush ─────────────────────────────────────────────────────────────────

async def _flush_bus() -> None:
    global _bus_task
    await asyncio.sleep(BUS_WINDOW_MS / 1000)
    effect_snap = dict(_effect_bus)
    config_snap = dict(_config_bus)
    _effect_bus.clear()
    _config_bus.clear()
    _bus_task = None
    coros = [
        _set_virtual_effect_direct(vid, etype, patch)
        for (vid, etype), patch in effect_snap.items()
    ]
    if config_snap:
        coros.append(_set_config_direct(config_snap))
    if coros:
        await asyncio.gather(*coros)


def _schedule_bus_flush() -> None:
    global _bus_task
    if _bus_task is None or _bus_task.done():
        _bus_task = asyncio.create_task(_flush_bus())


# ── Public write API (goes through bus) ───────────────────────────────────────

async def set_virtual_effect(virtual_id: str, effect_type: str, config: dict) -> None:
    """
    Queue a virtual effect patch into the coalesce bus.
    Patches for the same (virtual_id, effect_type) within the bus window are merged;
    later keys overwrite earlier ones.
    """
    key = (virtual_id, effect_type)
    _effect_bus[key] = {**_effect_bus.get(key, {}), **config}
    _schedule_bus_flush()


async def set_config(patch: dict) -> None:
    """
    Queue a global config patch into the coalesce bus.
    Multiple patches within the bus window are merged; later keys overwrite earlier.
    """
    global _current_brightness
    if "global_brightness" in patch:
        _current_brightness = patch["global_brightness"]
    _config_bus.update(patch)
    _schedule_bus_flush()


# ── Other API calls (bypass bus) ──────────────────────────────────────────────

async def measure_latency() -> float:
    """
    Send a lightweight status request to LedFX and return the RTT in ms.
    Updates state.ledfx_rtt_ms.

    Uses a dedicated httpx client so the probe doesn't queue behind trigger
    writes — that would inflate RTT under load and skew effective_offset_ms.
    """
    if _capture_in_progress():
        return state.ledfx_rtt_ms or 0.0   # mute during capture; keep last known RTT
    client = _get_probe_client()
    try:
        t0 = time.monotonic()
        await client.get("/api/info")
        rtt_ms = (time.monotonic() - t0) * 1000
        state.ledfx_rtt_ms = rtt_ms
        return rtt_ms
    except Exception as exc:
        logger.warning("LedFX latency probe failed: %r", exc)
        return 0.0


async def _activate_scene_per_virtual(scene_id: str) -> bool:
    """Apply a scene by writing each virtual's effect individually, so the
    ambient-excluded virtuals are skipped (the per-virtual write guard drops
    them). Used while Ambient Mode is on, because LedFX's native scene-activate
    is atomic and would re-drive the Hue bulbs we're holding static.

    Replicates the visible result of activate for the NON-ambient virtuals:
    each scene entry carries its effect `type` + `config`."""
    resp = await _request("GET", "/api/scenes", label=f"scene_fetch:{scene_id}")
    if resp is None:
        return False
    scene = ((resp.json() or {}).get("scenes") or {}).get(scene_id)
    if not scene:
        logger.warning("trigger_scene: scene '%s' not found for per-virtual apply", scene_id)
        return False
    coros = []
    for vid, entry in (scene.get("virtuals") or {}).items():
        if vid in _ambient_excluded:
            continue  # held static by Ambient Mode — never re-drive it
        if not isinstance(entry, dict) or entry.get("action", "activate") != "activate":
            continue
        etype = entry.get("type")
        if etype:
            coros.append(_set_virtual_effect_direct(vid, etype, entry.get("config") or {}))
    if coros:
        await asyncio.gather(*coros)
    return True


async def trigger_scene(scene_id: str) -> bool:
    """
    Activate a LedFX scene by its scene_id.
    Returns True on success.

    While Ambient Mode is on, apply the scene per-virtual (skipping the held Hue
    virtuals) instead of the atomic activate that would override them.
    """
    if _capture_in_progress():
        return True   # capture-in-progress mute
    if _ambient_excluded:
        ok = await _activate_scene_per_virtual(scene_id)
        if ok:
            logger.info("LedFX scene applied per-virtual (ambient hold): %s", scene_id)
        return ok
    resp = await _request(
        "PUT", "/api/scenes",
        json={"id": scene_id, "action": "activate"},
        label=f"scene:{scene_id}",
    )
    if resp is not None:
        logger.info("LedFX scene triggered: %s", scene_id)
        return True
    return False


async def ensure_scene(scene_id: str, name: str) -> bool:
    """Make sure a scene with `scene_id` exists on LedFX. No-op if present;
    otherwise POST a fresh empty scene with `name`. The caller is responsible
    for choosing a `name` whose LedFX-normalized id (lowercase, spaces and
    underscores → hyphens) matches `scene_id` — e.g. name='SpotFX Morph Temp'
    normalizes to id='spotfx-morph-temp'.

    Used at SpotFX startup to guarantee the shared scene-override temp scene
    exists before any morph tries to update + activate it. Direct-fire
    (bypasses the 8 ms bus)."""
    if _capture_in_progress():
        return True
    resp = await _request("GET", "/api/scenes", label="ensure_scene:list")
    if resp is None:
        logger.warning("ensure_scene: could not list scenes — scene-override morphs will fail loudly at fire time")
        return False
    scenes = (resp.json() or {}).get("scenes") or {}
    if scene_id in scenes:
        return True
    if await _request(
        "POST", "/api/scenes",
        json={"name": name, "virtuals": {}, "scene_image": ""},
        label="ensure_scene:create",
    ) is None:
        logger.warning("ensure_scene: could not create '%s' — scene-override morphs will fail loudly at fire time", scene_id)
        return False
    # Re-fetch and confirm the id we wanted is what LedFX created.
    resp2 = await _request("GET", "/api/scenes", label="ensure_scene:confirm")
    scenes2 = (resp2.json() or {}).get("scenes") or {} if resp2 is not None else {}
    if scene_id not in scenes2:
        logger.warning(
            "ensure_scene: posted name '%s' but LedFX did not create id '%s' (got: %s)",
            name, scene_id, sorted(scenes2.keys())[-5:],
        )
        return False
    logger.info("ensure_scene: created '%s' on LedFX", scene_id)
    return True


async def update_scene_virtuals(scene_id: str, virtuals: dict) -> bool:
    """Update a scene's `virtuals` dict via POST. The caller passes the COMPLETE
    desired virtuals payload (LedFX merges at the virtual level, so any virtual
    omitted here keeps its previous entry from a prior update). Direct-fire."""
    if _capture_in_progress():
        return True
    resp = await _request(
        "POST", "/api/scenes",
        json={"id": scene_id, "virtuals": virtuals},
        label=f"update_scene:{scene_id}",
    )
    return resp is not None


async def delete_scene(scene_id: str) -> bool:
    """Remove a scene from LedFX. Direct-fire. Not used in the morph fire path —
    kept so a future 'reset temp scene' control can call it."""
    if _capture_in_progress():
        return True
    # DELETE with a JSON body the way LedFX expects.
    resp = await _request("DELETE", "/api/scenes", json={"id": scene_id}, label=f"delete_scene:{scene_id}")
    return resp is not None


async def get_scenes() -> list[dict]:
    """
    Fetch the list of available LedFX scenes.
    Returns an empty list if LedFX is unreachable.
    """
    if _capture_in_progress():
        return []
    resp = await _request("GET", "/api/scenes", label="get_scenes")
    if resp is None:
        return []
    scenes_dict = (resp.json() or {}).get("scenes", {})
    return [{"id": sid, **meta} for sid, meta in scenes_dict.items()]


async def get_config() -> dict:
    """Fetch LedFX global config (GET /api/config). Returns {} on failure."""
    if _capture_in_progress():
        return {}
    resp = await _request("GET", "/api/config", label="get_config")
    return resp.json() if resp is not None else {}


async def get_virtual(virtual_id: str) -> dict:
    """Fetch a single LedFX virtual's current state. Returns {} on failure."""
    if _capture_in_progress():
        return state.ledfx_virtual_cache.get(virtual_id, {})
    resp = await _request("GET", f"/api/virtuals/{virtual_id}", label=f"get_virtual:{virtual_id}")
    return resp.json() if resp is not None else {}


async def get_all_virtuals(force: bool = False) -> dict:
    """Fetch all LedFX virtuals. Returns {} on failure.

    force=True bypasses the capture gate — used by deliberate user actions
    (e.g. Ambient Mode discovery) that must read virtual topology even while an
    audio capture is muting the per-frame trigger writes."""
    if not force and _capture_in_progress():
        return {}
    resp = await _request("GET", "/api/virtuals", label="get_all_virtuals")
    return resp.json() if resp is not None else {}


async def get_device(device_id: str) -> dict:
    """Fetch a single LedFX device's record (incl. config). Returns {} on failure.
    Used by Ambient Mode to read a Hue device's bridge ip/key/entertainment id."""
    resp = await _request("GET", f"/api/devices/{device_id}", label=f"get_device:{device_id}")
    return resp.json() if resp is not None else {}


async def clear_virtual_effect(virtual_id: str) -> bool:
    """Clear the active effect on a virtual (DELETE /api/virtuals/{id}/effects).
    For Hue this stops the entertainment stream so REST state changes stick.
    Bypasses the ambient-exclusion guard (this IS the ambient path)."""
    resp = await _request(
        "DELETE", f"/api/virtuals/{virtual_id}/effects",
        label=f"clear_effect:{virtual_id}",
    )
    return resp is not None


async def set_virtual_active(virtual_id: str, active: bool) -> bool:
    """Activate/deactivate a virtual (PUT /api/virtuals/{id} {"active": bool}).

    Deactivating stops the virtual streaming to its devices but PRESERVES its
    effect; reactivating resumes that exact effect. Ambient Mode uses this to
    park/un-park Hue-backed virtuals without losing what they were showing.

    Single-shot, best-effort: activating a Hue-spanning virtual makes LedFX run
    a blocking entertainment handshake (several seconds) that can exceed our HTTP
    read timeout. We do NOT retry — retries pile up behind the still-processing
    activation and wedge the client. LedFX completes the activation server-side
    regardless of whether we read the response in time, so a timeout here is
    harmless; the virtual still comes up a moment later. Returns True only on a
    confirmed success body."""
    resp = await _request(
        "PUT", f"/api/virtuals/{virtual_id}",
        json={"active": bool(active)},
        label=f"active:{virtual_id}",
    )
    if resp is not None:
        try:
            return (resp.json() or {}).get("status") == "success"
        except Exception:
            pass
    return False


async def set_virtual_config(virtual_id: str, config: dict) -> bool:
    """
    Patch a virtual's device config (max_brightness, transition_time, etc.).
    POST /api/virtuals  body: {"id": virtual_id, "config": config}
    This merges with the existing virtual config — only specified fields are changed.
    """
    if virtual_id in _ambient_excluded:
        return True   # Ambient Mode owns this virtual via Hue REST; drop trigger writes
    if _capture_in_progress():
        return True   # capture-in-progress mute
    resp = await _request(
        "POST", "/api/virtuals",
        json={"id": virtual_id, "config": config},
        label=f"virtual_config:{virtual_id}",
    )
    if resp is not None:
        logger.debug("LedFX virtual config patched on '%s': %s", virtual_id, config)
        return True
    return False


def get_virtual_cache(virtual_id: str) -> dict:
    """Return the cached virtual state dict (from the last poll). Empty dict if not cached."""
    return state.ledfx_virtual_cache.get(virtual_id, {})


def get_cached_param(virtual_id: str, param_name: str) -> float | None:
    """Return a numeric effect param from the polled cache, or None if not found."""
    cfg = state.ledfx_virtual_cache.get(virtual_id, {}).get("effect", {}).get("config", {})
    val = cfg.get(param_name)
    return float(val) if val is not None else None


# ── Ramp functions (go through bus; step_ms=25 → 40 fps) ─────────────────────

async def ramp_brightness(target: float, ramp_ms: int, step_ms: int = 25) -> None:
    """Smoothly ramp global brightness from _current_brightness to target over ramp_ms."""
    start = _current_brightness
    steps = max(1, ramp_ms // step_ms)
    for i in range(1, steps + 1):
        val = round(start + (target - start) * (i / steps), 4)
        await set_config({"global_brightness": val})
        if i < steps:
            await asyncio.sleep(step_ms / 1000)


async def ramp_effect_params(
    virtual_id: str, effect_type: str, patch: dict, ramp_ms: int, step_ms: int = 25
) -> None:
    """Smoothly ramp one or more numeric effect params from their cached values
    to targets over ramp_ms.

    patch: {param_name: target_value, ...}

    When the connected LedFX supports server-side tweening, this is ONE PUT with
    transition_ms (LedFX interpolates per render frame — smooth, no network per
    frame); the call then holds for ramp_ms so callers that await the ramp keep
    their existing sequencing/choreography. Otherwise it falls back to the
    legacy client-side loop (one batched PUT per ~25ms step).
    """
    if ramp_ms > 0 and server_tween_enabled():
        await set_virtual_effect_tween(virtual_id, effect_type, patch, ramp_ms)
        # Preserve the wall-clock contract: awaited callers (await_ramps=True,
        # sequences) expect this to span the ramp; background spawns just idle.
        await asyncio.sleep(ramp_ms / 1000)
        return

    starts = {p: (get_cached_param(virtual_id, p) or 0.0) for p in patch}
    steps = max(1, ramp_ms // step_ms)
    for i in range(1, steps + 1):
        t = i / steps
        frame = {p: round(starts[p] + (patch[p] - starts[p]) * t, 4) for p in patch}
        await set_virtual_effect(virtual_id, effect_type, frame)
        if i < steps:
            await asyncio.sleep(step_ms / 1000)
    # Update cache with final values after ramp completes
    effect_cfg = state.ledfx_virtual_cache.get(virtual_id, {}).get("effect", {}).get("config", {})
    effect_cfg.update(patch)


async def ramp_gradient_params(
    virtual_id: str, effect_type: str, patch: dict, ramp_ms: int, step_ms: int = 25
) -> None:
    """Smoothly interpolate gradient/color string params from their cached values
    to targets over ramp_ms.

    patch: {param_name: target_css_string, ...}

    When the connected LedFX supports server-side tweening it interpolates solid
    colours (RGB lerp) and gradients (LUT lerp) for us — ONE PUT with
    transition_ms, then hold for ramp_ms to keep caller sequencing. Otherwise
    falls back to the legacy client-side loop using interpolate_gradient().
    """
    if ramp_ms > 0 and server_tween_enabled():
        await set_virtual_effect_tween(virtual_id, effect_type, patch, ramp_ms)
        await asyncio.sleep(ramp_ms / 1000)
        return

    from services.gradient_interpolation import interpolate_gradient
    cfg = state.ledfx_virtual_cache.get(virtual_id, {}).get("effect", {}).get("config", {})
    starts = {p: (cfg.get(p) or "") for p in patch}
    steps = max(1, ramp_ms // step_ms)
    for i in range(1, steps + 1):
        t = i / steps
        frame = {p: interpolate_gradient(starts[p], patch[p], t) for p in patch}
        await set_virtual_effect(virtual_id, effect_type, frame)
        if i < steps:
            await asyncio.sleep(step_ms / 1000)
    # Update cache with final values after ramp completes
    effect_cfg = state.ledfx_virtual_cache.get(virtual_id, {}).get("effect", {}).get("config", {})
    effect_cfg.update(patch)


async def ramp_polar_offset(
    virtual_id: str, effect_type: str,
    target_angle: float, target_radius: float,
    ramp_ms: int, step_ms: int = 25,
) -> None:
    """Interpolate x_offset+y_offset in polar space.

    target_angle: degrees, 0=top (y=1,x=0), clockwise.
    target_radius: 0..1 in frontend space (0=centre, 1=edge in -1..1 coords).
    Shortest angular path is always taken.
    """
    import math as _math
    _cx = get_cached_param(virtual_id, "x_offset")
    _cy = get_cached_param(virtual_id, "y_offset")
    cur_x_l = _cx if _cx is not None else 0.5
    cur_y_l = _cy if _cy is not None else 0.5
    cx = (cur_x_l - 0.5) * 2   # convert to frontend -1..1
    cy = (cur_y_l - 0.5) * 2
    cur_r = _math.sqrt(cx ** 2 + cy ** 2)
    cur_a = _math.degrees(_math.atan2(cx, cy))  # atan2(x,y) → 0=top, CW positive
    delta = ((target_angle - cur_a) + 180) % 360 - 180  # shortest angular path
    steps = max(1, ramp_ms // step_ms)
    for i in range(1, steps + 1):
        t = i / steps
        a_rad = _math.radians(cur_a + delta * t)
        r = cur_r + (target_radius - cur_r) * t
        x_l = round(_math.sin(a_rad) * r / 2 + 0.5, 4)
        y_l = round(_math.cos(a_rad) * r / 2 + 0.5, 4)
        await set_virtual_effect(virtual_id, effect_type, {"x_offset": x_l, "y_offset": y_l})
        if i < steps:
            await asyncio.sleep(step_ms / 1000)
    # Update cache with final values
    cfg = state.ledfx_virtual_cache.get(virtual_id, {}).get("effect", {}).get("config", {})
    a_final = _math.radians(cur_a + delta)
    cfg["x_offset"] = round(_math.sin(a_final) * target_radius / 2 + 0.5, 4)
    cfg["y_offset"] = round(_math.cos(a_final) * target_radius / 2 + 0.5, 4)


# ── Virtual state poller ───────────────────────────────────────────────────────

def _get_polled_virtuals() -> list[str]:
    """Return virtual IDs to poll, from device categories."""
    from services import effect_params
    return effect_params.get_all_virtual_ids()


async def poll_virtual_states() -> None:
    """Poll key LedFX virtuals every 5 s and cache results in state."""
    # Probe server-side tween support once at startup (re-probes if LedFX was
    # unreachable on the first pass, until a definite answer lands).
    await refresh_capabilities()
    while True:
        if _server_tween_supported is None:
            await refresh_capabilities()
        for vid in _get_polled_virtuals():
            data = await get_virtual(vid)
            if data:
                state.ledfx_virtual_cache[vid] = data.get(vid, data)
        await asyncio.sleep(5)


async def latency_loop() -> None:
    """Periodically re-measure LedFX latency every 30 seconds."""
    while True:
        await measure_latency()
        await asyncio.sleep(30)
