"""
SpotFX — Ambient Mode.

A front-page / Home-Assistant toggle that switches a chosen device category to a
static, full-brightness color (or white temperature) and removes those devices
from music-reactive triggers.

Why this exists
---------------
Philips Hue's Entertainment *streaming* API (what LedFX uses for low-latency
music reactivity) caps brightness well below a normal static scene and mixes the
color LEDs for white, so streamed white never reaches full output. The Hue
*REST* API does — `dimming.brightness=100` with a `color_temperature` drives the
bulbs' dedicated white LEDs at full lumens.

So Ambient Mode, for each Hue device in the target category:
  1. FREEZES the LedFX Hue device (ledfx_client.freeze_hue_device) — LedFX stops
     that device's entertainment stream so the bridge reverts to normal REST mode
     and drops all flush frames. The driving virtual stays ACTIVE and rendering;
     only the device output is muted. The trigger engine, scenes, and morphs run
     normally and need zero ambient knowledge — nothing to exclude or park.
  2. PUTs every light in the entertainment group to the configured color at full
     brightness over the Hue REST API (after the freeze, so the now-stopped stream
     can't override it).

Ambient is held PER GROUP: each Hue device in the target category (one
entertainment group / room per LedFX device) can be frozen independently.
`state.ambient_groups` is the source of truth for which groups are held;
`state.ambient_mode_enabled` stays in sync as "any group held" for the UI/HA.

Disable (per group) first FADES the bulbs on the bridge itself — a Hue REST
write with `dynamics.duration` toward the wake scene's color at a dimmed
brightness (settings.ambient_transition_s / ambient_fade_brightness) — while
the device is still frozen, so REST owns the bulbs for the whole fade. Only
then does it unfreeze and activate the configured wake scene
(settings.ambient_wake_scene), verifying its virtuals came up — unfreezing
only re-arms the stream; if the driving Hue virtual has no active effect,
nothing ever streams and the bulbs stay stuck on the ambient REST color. The
wake scene puts a real effect on them, and because the fade already landed
near the wake color the REST→stream handoff is gentle instead of a hard cut.

Catch-up: the wake scene look is only a landing pad — the music look it
replaced should ease back in rather than snap in at the next trigger. Right
before the wake scene fires we capture the current effect (type + config) on
its 'activate' virtuals; after the wake verifies, we ask LedFX to TWEEN the
config back to that capture over settings.ambient_catchup_s (server-side
param interpolation, the same mechanism SpotFX color ramps use — nothing
temporary to restore, so no cleanup/watchdog is needed). If the captured
effect is a different type than the wake effect (rare — 34/37 scenes drive
the Hues with 'power', same as wake), we set it directly and the virtual's
own transition_time crossfades it. The next SpotFX trigger/scene change then
takes over from a look that already matches.

Bridge credentials (ip / app-key / entertainment id) are read live from the
LedFX Hue device config — SpotFX stores no Hue secrets of its own.

Non-Hue devices in the category are left on their normal reactive path (logged).
"""
from __future__ import annotations

import asyncio
import logging
import time

import httpx

from api import ledfx_client
from config import settings
from services.device_category_service import get_category, get_category_by_name

logger = logging.getLogger(__name__)

# Cache of resolved light resource-ids per (bridge_ip, entertainment_id).
# The mapping rarely changes; cleared implicitly on process restart.
_light_cache: dict[tuple[str, str], list[str]] = {}

# Serializes enable/disable so rapid front-page (or HA) toggles can't overlap
# and fight each other over the Hue stream. Created lazily to bind to the loop.
_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def busy() -> bool:
    """True while an enable/disable/fade is mid-flight (lock held). The ambient
    reconciler checks this so it can't unfreeze a device mid-fade."""
    return _lock is not None and _lock.locked()


# ── Color math ───────────────────────────────────────────────────────────────

def _gamma(c: float) -> float:
    return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92


def _hex_to_xy(hex_color: str) -> tuple[float, float]:
    """Hex RGB -> CIE xy chromaticity (Philips Wide-gamut D65 matrix)."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
    except (ValueError, IndexError):
        return 0.3127, 0.3290  # fall back to D65 white
    r, g, b = _gamma(r), _gamma(g), _gamma(b)
    X = r * 0.664511 + g * 0.154324 + b * 0.162028
    Y = r * 0.283881 + g * 0.668433 + b * 0.047685
    Z = r * 0.000088 + g * 0.072310 + b * 0.986039
    total = X + Y + Z
    if total == 0:
        return 0.3127, 0.3290
    return X / total, Y / total


def _light_payload(transition_ms: int | None = None) -> dict:
    """Build the Hue REST light state from current settings (full-brightness).
    transition_ms > 0 adds a bridge-side dynamics ramp toward that state."""
    bri = max(1, min(100, int(settings.ambient_brightness)))
    body: dict = {"on": {"on": True}, "dimming": {"brightness": float(bri)}}
    if settings.ambient_color_mode == "color":
        x, y = _hex_to_xy(settings.ambient_color)
        body["color"] = {"xy": {"x": round(x, 4), "y": round(y, 4)}}
    else:
        kelvin = max(2000, min(6500, int(settings.ambient_kelvin)))
        mirek = max(153, min(500, round(1_000_000 / kelvin)))
        body["color_temperature"] = {"mirek": mirek}
    if transition_ms and transition_ms > 0:
        body["dynamics"] = {"duration": int(transition_ms)}
    return body


def _fade_payload(color: str | None, transition_ms: int) -> dict:
    """Hue REST state for the ambient-OFF fade: dim toward the wake color over
    transition_ms on the bridge itself. color=None fades brightness only."""
    bri = max(1, min(100, int(settings.ambient_fade_brightness)))
    body: dict = {
        "on": {"on": True},
        "dimming": {"brightness": float(bri)},
        "dynamics": {"duration": int(transition_ms)},
    }
    if color:
        x, y = _hex_to_xy(color)
        body["color"] = {"xy": {"x": round(x, 4), "y": round(y, 4)}}
    return body


# ── Target resolution ──────────────────────────────────────────────────────────

def _target_virtuals() -> list[str]:
    """Virtual ids of the configured target category (by id, then by name)."""
    key = (settings.ambient_target_category or "").strip()
    if not key:
        return []
    cat = get_category(key) or get_category_by_name(key)
    return list(cat.virtuals) if cat else []


async def _hue_cfg(device_id: str) -> dict | None:
    """Return the LedFX Hue device config for a device id, or None if not Hue."""
    rec = await ledfx_client.get_device(device_id)
    rec = rec.get(device_id, rec) if isinstance(rec, dict) else {}
    cfg = rec.get("config", rec) if isinstance(rec, dict) else {}
    if cfg.get("entertainment_id") and cfg.get("ip_address") and cfg.get("username"):
        return cfg
    return None


async def _all_virtuals() -> dict:
    # force=True: must read topology even during an audio capture, else segment
    # discovery misses driving virtuals (e.g. single-color-effect) and they keep
    # streaming over the REST-set bulbs.
    raw = await ledfx_client.get_all_virtuals(force=True)
    return raw.get("virtuals", raw) if isinstance(raw, dict) else {}


def _segment_devices(vobj: dict) -> set[str]:
    """Device ids referenced by a virtual's segments ([device_id, start, end, ...])."""
    devs: set[str] = set()
    for seg in (vobj.get("segments") or []):
        if isinstance(seg, (list, tuple)) and seg:
            devs.add(seg[0])
    return devs


# ── Hue bridge REST ──────────────────────────────────────────────────────────

def _bridge_client(cfg: dict) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"https://{cfg['ip_address']}",
        headers={"hue-application-key": cfg["username"]},
        verify=False,  # bridge uses a self-signed cert
        timeout=4.0,
    )


async def _resolve_lights(cfg: dict) -> list[str]:
    """Map the entertainment group's channels to Hue light resource ids (cached)."""
    cache_key = (cfg["ip_address"], cfg["entertainment_id"])
    if cache_key in _light_cache:
        return _light_cache[cache_key]
    rids: list[str] = []
    try:
        async with _bridge_client(cfg) as client:
            ent = (await client.get("/clip/v2/resource/entertainment")).json()["data"]
            ent_owner = {e["id"]: e["owner"]["rid"] for e in ent}
            lights = (await client.get("/clip/v2/resource/light")).json()["data"]
            dev_light = {l["owner"]["rid"]: l["id"] for l in lights}
            ec = (await client.get(
                f"/clip/v2/resource/entertainment_configuration/{cfg['entertainment_id']}"
            )).json()["data"][0]
            seen: set[str] = set()
            for channel in ec.get("channels", []):
                for member in channel.get("members", []):
                    svc = member.get("service", {})
                    if svc.get("rtype") == "entertainment":
                        lr = dev_light.get(ent_owner.get(svc.get("rid")))
                        if lr and lr not in seen:
                            seen.add(lr)
                            rids.append(lr)
                        break
    except Exception as exc:
        logger.error("Ambient: failed to resolve Hue lights for %s: %r", cfg.get("ip_address"), exc)
        return []
    _light_cache[cache_key] = rids
    return rids


async def _stream_active(cfg: dict) -> bool | None:
    """Is the device's entertainment session running on its bridge?
    None = bridge unreachable / unknown (treat as healthy — don't heal blind)."""
    try:
        async with _bridge_client(cfg) as client:
            ec = (await client.get(
                f"/clip/v2/resource/entertainment_configuration/{cfg['entertainment_id']}"
            )).json()["data"][0]
            return ec.get("status") == "active"
    except Exception as exc:
        logger.warning("Ambient: stream status check failed for %s: %r",
                       cfg.get("ip_address"), exc)
        return None


def _driven_and_should_stream(did: str, all_v: dict) -> bool:
    """True when some ACTIVE virtual with an effect covers this device — i.e.
    LedFX should be streaming to it. An intentionally-dark scene leaves the
    driving virtual inactive → False, so the heal never fights an off-scene."""
    for vid, vobj in all_v.items():
        if not isinstance(vobj, dict):
            continue
        if ((vid == did or did in _segment_devices(vobj))
                and vobj.get("active") and vobj.get("effect")):
            return True
    return False


async def _check_released_streams(released: dict[str, dict], attempts: int = 3,
                                  delay: float = 2.0) -> list[str]:
    """Released devices whose driving virtual is active+effect but whose bridge
    entertainment session stays inactive across `attempts` checks (retries give
    a just-kicked stream time to come up)."""
    stuck = set(released)
    for i in range(attempts):
        all_v = await _all_virtuals()
        still: set[str] = set()
        for did in stuck:
            if not _driven_and_should_stream(did, all_v):
                continue
            if await _stream_active(released[did]) is False:
                still.add(did)
        stuck = still
        if not stuck or i == attempts - 1:
            break
        await asyncio.sleep(delay)
    return sorted(stuck)


async def _heal_stuck(stuck: list[str], hue_cfgs: dict[str, dict],
                      catchup_s: float | None = None) -> dict:
    """Recover released devices whose entertainment stream is dead — the bridge
    reverts their bulbs to the pre-session state (typically the ambient white)
    with zero reactivity, while the freeze flag reads correct so freeze-drift
    reconciling never fires (bug seen live 2026-07-24 after a LedFX restart).
    Freeze→unfreeze forces LedFX to tear down and re-arm the DTLS session
    (exactly what the manual select+deselect workaround did), then the wake
    kick restarts streaming and the catch-up eases back to the music look."""
    captured = await _capture_wake_targets()
    for did in stuck:
        await ledfx_client.freeze_hue_device(did, True)
    for did in stuck:
        await ledfx_client.freeze_hue_device(did, False)
    wake = await _wake_kick()
    if wake.get("status") == "on":
        await _catchup(captured, catchup_s)
    still = [did for did in stuck if await _stream_active(hue_cfgs[did]) is False]
    if still:
        logger.error("Ambient heal: %s STILL have no entertainment stream after "
                     "freeze-cycle + wake", still)
    else:
        logger.info("Ambient heal: entertainment stream restored for %s", stuck)
    return {"healed": [d for d in stuck if d not in still], "still_stuck": still}


async def _apply_hue(cfg: dict, body: dict | None = None) -> int:
    """Set every light in the group to a REST state (default: the configured
    static full-brightness color). Returns the number of lights set.

    The entertainment stream is NOT stopped here: callers deactivate the LedFX
    virtuals first, so LedFX itself tears the stream down. Sending our own
    'action stop' directly to the bridge while LedFX still owns the session
    raced LedFX's Hue socket and could wedge its (synchronous) flush — so we
    leave stream lifecycle entirely to LedFX."""
    if body is None:
        body = _light_payload()
    try:
        async with _bridge_client(cfg) as client:
            lights = await _resolve_lights(cfg)
            count = 0
            for rid in lights:
                resp = await client.put(f"/clip/v2/resource/light/{rid}", json=body)
                if resp.status_code < 400:
                    count += 1
            return count
    except Exception as exc:
        logger.error("Ambient: failed to apply Hue REST state on %s: %r", cfg.get("ip_address"), exc)
        return 0


# ── Public API ───────────────────────────────────────────────────────────────

# Cached {device_id: friendly name} of the target category's Hue groups —
# used by the group picker UI / HA and the control endpoint's id validation.
_groups_cache: tuple[float, dict[str, str]] | None = None
_GROUPS_CACHE_TTL_S = 300.0


async def resolve_groups(force: bool = False) -> dict[str, str]:
    """{device_id: friendly name} for every Hue group ambient can hold,
    resolved from the target category (cached — topology is stable)."""
    global _groups_cache
    now = time.monotonic()
    if not force and _groups_cache and now - _groups_cache[0] < _GROUPS_CACHE_TTL_S:
        return dict(_groups_cache[1])
    hue_cfgs = await _resolve_hue_cfgs()
    names = {did: str(cfg.get("name") or did) for did, cfg in hue_cfgs.items()}
    if names:
        _groups_cache = (now, names)
        return names
    # Empty result: a genuinely-empty target category and "LedFX unreachable"
    # are indistinguishable here (ledfx_client maps failures to {}). Serve the
    # last known groups past their TTL rather than stripping the picker to
    # "No Hue groups found" during a transient outage (2026-08-12 incident).
    if _groups_cache:
        logger.warning(
            "Ambient: group discovery returned nothing (LedFX unreachable?) — "
            "serving %d cached group name(s)", len(_groups_cache[1]),
        )
        return dict(_groups_cache[1])
    return names


async def set_groups(want: set[str] | None, transition_s: float | None = None,
                     catchup_s: float | None = None) -> dict:
    """Reconcile ambient to exactly `want` (None = all target groups).
    Locked so rapid toggles / HA calls can't overlap mid-fade."""
    async with _get_lock():
        return await _set_groups_impl(want, transition_s, catchup_s)


async def enable() -> dict:
    """All target groups on (legacy entry point — HA `enabled=true` w/o groups)."""
    return await set_groups(None)


async def disable() -> dict:
    """All groups off."""
    return await set_groups(set())


async def _resolve_hue_cfgs() -> dict[str, dict]:
    """Resolve {device_id: hue_cfg} for every Hue device backing the target
    category's virtuals (via their segments). Shared by enable/disable/reconcile.
    Topology is stable, so re-resolving each time is robust across restarts."""
    all_v = await _all_virtuals()
    target_devices: set[str] = set()
    for vid in _target_virtuals():
        target_devices |= _segment_devices(all_v.get(vid, {}))
        target_devices.add(vid)  # device-backed virtual references itself
    hue_cfgs: dict[str, dict] = {}
    for did in target_devices:
        cfg = await _hue_cfg(did)
        if cfg:
            hue_cfgs[did] = cfg
    return hue_cfgs


async def _wake_fade_color() -> str | None:
    """Color the off-fade should land on: the wake scene's dominant color on
    its 'activate' virtual (background_color, else a plain-hex gradient/color).
    None = fade brightness only, keeping the current color."""
    scene_id = (settings.ambient_wake_scene or "").strip()
    if not scene_id:
        return None
    try:
        scene = next(
            (s for s in await ledfx_client.get_scenes() if s.get("id") == scene_id), None
        )
        for spec in ((scene or {}).get("virtuals") or {}).values():
            if not (isinstance(spec, dict) and spec.get("action") == "activate"):
                continue
            cfg = spec.get("config") or {}
            for key in ("background_color", "gradient", "color"):
                val = cfg.get(key)
                if isinstance(val, str) and val.startswith("#"):
                    return val
    except Exception as exc:
        logger.warning("Ambient: could not derive wake fade color: %r", exc)
    return None


async def _capture_wake_targets() -> dict[str, dict]:
    """Snapshot the current (music) effect on the wake scene's 'activate'
    virtuals, taken just before the wake scene replaces it, so the catch-up
    can ease back to it: {vid: {type, config, wake_type}}. Virtuals with no
    active effect are skipped (nothing to return to)."""
    scene_id = (settings.ambient_wake_scene or "").strip()
    if not scene_id:
        return {}
    captured: dict[str, dict] = {}
    try:
        scene = next(
            (s for s in await ledfx_client.get_scenes() if s.get("id") == scene_id), None
        )
        for vid, spec in ((scene or {}).get("virtuals") or {}).items():
            if not (isinstance(spec, dict) and spec.get("action") == "activate"):
                continue
            rec = await ledfx_client.get_virtual(vid)
            vobj = rec.get(vid, {}) if isinstance(rec, dict) else {}
            eff = vobj.get("effect") or {}
            if vobj.get("active") and eff.get("type"):
                captured[vid] = {
                    "type": eff["type"],
                    "config": dict(eff.get("config") or {}),
                    "wake_type": spec.get("type"),
                }
    except Exception as exc:
        logger.warning("Ambient catch-up: could not capture pre-wake effects: %r", exc)
    return captured


async def _catchup(captured: dict[str, dict], catchup_s: float | None) -> None:
    """Ease the wake virtuals from the wake look back to the captured music
    look. Same effect type → server-side config tween over catchup_s;
    different type → direct set (the virtual's own transition_time
    crossfades). Fire-and-forget on LedFX — nothing to restore afterward."""
    t_s = settings.ambient_catchup_s if catchup_s is None else catchup_s
    t_s = max(0.0, min(float(t_s), 60.0))
    if t_s <= 0 or not captured:
        return
    for vid, eff in captured.items():
        try:
            if eff.get("wake_type") == eff["type"]:
                await ledfx_client.set_virtual_effect_tween(
                    vid, eff["type"], eff["config"], int(t_s * 1000)
                )
                logger.info(
                    "Ambient catch-up: tweening %s back to its %s look over %.1fs",
                    vid, eff["type"], t_s,
                )
            else:
                await ledfx_client._set_virtual_effect_direct(vid, eff["type"], eff["config"])
                logger.info(
                    "Ambient catch-up: %s pre-wake effect %r ≠ wake type %r — "
                    "restored via normal crossfade", vid, eff["type"], eff.get("wake_type"),
                )
        except Exception as exc:
            logger.error("Ambient catch-up failed for %s: %r", vid, exc)


async def _commit_state(want: set[str]) -> None:
    """Make `want` the authoritative held-group set: state, disk, UI broadcast."""
    from models.state import state
    state.ambient_groups = sorted(want)
    state.ambient_mode_enabled = bool(want)
    try:
        from routers.settings_router import _load_settings_file, _save_settings_file
        saved = _load_settings_file()
        saved["ambient_mode_enabled"] = state.ambient_mode_enabled
        saved["ambient_groups"] = state.ambient_groups
        _save_settings_file(saved)
    except Exception as exc:
        logger.error("Ambient: failed to persist group state: %r", exc)
    try:
        from services.websocket_manager import ws_manager
        await ws_manager.broadcast_state(state)
    except Exception:
        pass


async def _set_groups_impl(want: set[str] | None, transition_s: float | None,
                           catchup_s: float | None = None) -> dict:
    """Drive per-device freeze + Hue REST toward `want`.

    ON  (wanted): freeze (LedFX stops that device's entertainment stream so the
        bridge reverts to REST mode), THEN write the static color via REST —
        freeze must complete first, else a live stream frame overrides REST.
        Idempotent for already-held groups (re-asserts stop + color instantly);
        newly-held groups ramp up over the transition.
    OFF (held but no longer wanted): fade toward the wake color on the bridge
        (`dynamics.duration`; the device is still frozen so REST owns the bulbs
        for the whole fade), then unfreeze and kick the wake scene so the
        stream takes over at roughly the color it starts streaming — then ease
        back to the captured pre-wake music look over catchup_s (_catchup)."""
    hue_cfgs = await _resolve_hue_cfgs()
    if not hue_cfgs:
        logger.warning("Ambient: no Hue devices resolved from category %r",
                       settings.ambient_target_category)
    if want is None:
        want = set(hue_cfgs)
    else:
        unknown = sorted(want - set(hue_cfgs))
        if unknown:
            logger.warning("Ambient: ignoring unknown group id(s) %s (known: %s)",
                           unknown, sorted(hue_cfgs))
        want = want & set(hue_cfgs)

    frozen: set[str] = set()
    for did in hue_cfgs:
        if await ledfx_client.get_hue_frozen(did):
            frozen.add(did)
    to_off = sorted(frozen - want)

    t_s = settings.ambient_transition_s if transition_s is None else transition_s
    t_s = max(0.0, min(float(t_s), 15.0))

    frozen_ok = 0
    total_lights = 0
    for did in sorted(want):
        ramp_ms = int(t_s * 1000) if did not in frozen else None
        if await ledfx_client.freeze_hue_device(did, True):
            frozen_ok += 1
        total_lights += await _apply_hue(hue_cfgs[did], body=_light_payload(ramp_ms))

    wake: dict | None = None
    if to_off:
        if t_s > 0:
            fade = _fade_payload(await _wake_fade_color(), int(t_s * 1000))
            for did in to_off:
                await _apply_hue(hue_cfgs[did], body=fade)
            await asyncio.sleep(t_s)  # bridge runs the fade; reconciler skips while busy()
        # Capture the current music look as late as possible (triggers keep
        # updating the still-rendering effect during ambient) but BEFORE the
        # wake scene replaces it.
        captured = await _capture_wake_targets()
        for did in to_off:
            await ledfx_client.freeze_hue_device(did, False)
        wake = await _wake_kick()
        if wake.get("status") == "on":
            await _catchup(captured, catchup_s)

    # Stream-health check on every released device (not just the ones released
    # this call): a dead entertainment session leaves bulbs stuck on the
    # bridge's pre-session state — typically the ambient white — with the
    # freeze flag reading correct. Covers startup restore after a LedFX
    # restart and a failed wake above.
    released = {did: hue_cfgs[did] for did in hue_cfgs if did not in want}
    if released:
        stuck = await _check_released_streams(released)
        if stuck:
            logger.warning("Ambient: released device(s) %s have a dead "
                           "entertainment stream — healing", stuck)
            await _heal_stuck(stuck, hue_cfgs, catchup_s)

    await _commit_state(want)
    logger.info(
        "Ambient groups → %s: %d/%d frozen, %d light(s) set, released %s (fade %.1fs)",
        sorted(want) or "none", frozen_ok, len(want), total_lights,
        to_off or "none", t_s if to_off else 0.0,
    )
    return {"ambient_groups": sorted(want), "frozen": frozen_ok,
            "lights_set": total_lights, "released": to_off, "wake": wake}


async def _wake_kick() -> dict:
    """Restart the Hue entertainment stream after unfreeze.

    Unfreezing only re-arms streaming: LedFX streams to a Hue device when its
    driving virtual is active with an effect. If that virtual went inactive
    while ambient held the bulbs, the bulbs stay stuck on the ambient REST
    color indefinitely. Activating the wake scene puts a real effect on the
    Hue virtuals, which restarts the stream; the next SpotFX trigger/scene
    change then overwrites it through the normal path — no hand-back needed.

    Verifies the scene's 'activate' virtuals actually came up (active + effect
    present), re-firing the activate up to 3 times before giving up."""
    scene_id = (settings.ambient_wake_scene or "").strip()
    if not scene_id:
        return {"status": "skipped"}

    scene = next(
        (s for s in await ledfx_client.get_scenes() if s.get("id") == scene_id), None
    )
    if scene is None:
        logger.error(
            "Ambient wake: scene %r not found on LedFX — Hue bulbs may stay on the "
            "ambient color until the next scene change", scene_id,
        )
        return {"status": "scene_missing", "scene": scene_id}
    watch = sorted(
        vid for vid, spec in (scene.get("virtuals") or {}).items()
        if isinstance(spec, dict) and spec.get("action") == "activate"
    )
    if not watch:
        await ledfx_client.trigger_scene(scene_id)
        logger.warning("Ambient wake: scene %r has no 'activate' virtuals — fired blind", scene_id)
        return {"status": "unverified", "scene": scene_id}

    dark: list[str] = watch
    for attempt in range(1, 4):
        await ledfx_client.trigger_scene(scene_id)
        for _ in range(6):
            await asyncio.sleep(0.5)
            dark = []
            for vid in watch:
                rec = await ledfx_client.get_virtual(vid)
                vobj = rec.get(vid, {}) if isinstance(rec, dict) else {}
                if not (vobj.get("active") and vobj.get("effect")):
                    dark.append(vid)
            if not dark:
                logger.info(
                    "Ambient wake: scene %r on — virtual(s) %s active (attempt %d)",
                    scene_id, watch, attempt,
                )
                return {"status": "on", "scene": scene_id, "virtuals": watch, "attempts": attempt}
        logger.warning(
            "Ambient wake: attempt %d — %s still inactive, re-firing %r",
            attempt, dark, scene_id,
        )
    logger.error(
        "Ambient wake: gave up after 3 attempts — %s never came up; bulbs may stay "
        "on the ambient color until the next scene change", dark,
    )
    return {"status": "failed", "scene": scene_id, "dark": dark}


async def reapply() -> dict:
    """Re-assert ambient for the currently-held groups (e.g. settings changed).
    set_groups is idempotent for held groups (re-freeze is a no-op that
    re-asserts the stop, then re-writes REST), so this just refreshes the color."""
    from models.state import state
    if state.ambient_groups:
        return await set_groups(set(state.ambient_groups))
    if state.ambient_mode_enabled:  # legacy: flag on with no group detail = all
        return await set_groups(None)
    return {"status": "inactive"}
