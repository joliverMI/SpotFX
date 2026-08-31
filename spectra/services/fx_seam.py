"""SPECTRA's ONE write seam — every live write or read of the lights passes
through this module (apply_writes / get_virtuals / set_virtual_config),
nothing else in spectra/ performs LedFX I/O (spectra/services/ledfx_release.py
is the one documented exception, and only for the post-release cleanup path,
which must reach LedFX even after ownership has already moved to
"released" — see that module's own docstring).

S3: the transport is routed by the LIGHT OWNERSHIP RECORD
(fx/light_ownership.py), enforced here — in the write path — not by
convention:

  spot-effects owns   HTTP PUTs to the external LedFX service (the S1
                      behavior): the owner's Fire button writing through the
                      one process that drives the devices. Not a second
                      writer — LedFX is the writer.
  spectra owns        in-process PUTs through fx.facade into the live host
                      the handover activated. Zero HTTP.
  handing-over        REFUSED. During the switch nobody writes; the API
                      surfaces the error to the owner instead of racing the
                      handover.
  released            REFUSED — the panic handle (fx.light_ownership.
                      RELEASED). Fires stay refused until the way-back
                      handover lands.

Bounded concurrency + a hard per-request deadline carry the write-plane
lesson (the 2026-08-12 outage was leaked slots parking calls forever).

Tests never call this module (dry_run stops at the compiler).
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from fx import device_model, light_ownership
from spectra import config

logger = logging.getLogger(__name__)

REQUEST_DEADLINE_S = 10.0
MAX_IN_FLIGHT = 4

_slots = asyncio.Semaphore(MAX_IN_FLIGHT)

# Liveness blind spot (spectra-room-fault-diagnosis, 2026-08-14): frame
# freshness alone can't tell "streaming the wrong effect" apart from healthy
# — it only proves the render loop pushed A frame. This is additive
# observability for the case the fix above now handles instead of hiding:
# a requested type switch that would have hit fx/facade.py's stale-tween-PUT
# drop. Not a health signal on its own (a switch landing correctly is
# expected, ordinary traffic) — surfaced on /spectra/api/liveness for a human
# to notice a virtual that's switching types unusually often.
_type_switches_landed = 0
_last_type_switch: dict | None = None


def stats() -> dict:
    return {"type_switches_landed": _type_switches_landed,
            "last_type_switch": _last_type_switch}


class HandoverInProgress(RuntimeError):
    """Raised when a fire arrives while the room is changing hands."""


class RoomReleased(RuntimeError):
    """Raised when a fire arrives while the room is released to Home
    Assistant (the panic handle) — refused until the way-back handover
    lands."""


def _require_owner() -> str:
    """The owner to route THIS call through, or raise the same refusal
    apply_writes always has — a single place so every new primitive added
    here (get_virtuals, set_virtual_config, ...) refuses identically rather
    than re-deriving the branch."""
    owner = light_ownership.load().owner
    if owner in (light_ownership.SPECTRA, light_ownership.SPOT_EFFECTS):
        return owner
    if owner == light_ownership.RELEASED:
        raise RoomReleased(
            "room released to Home Assistant — fires are refused until the "
            "way-back handover lands")
    raise HandoverInProgress(
        "light handover in progress — fires are refused until it lands")


async def apply_writes(writes: list[dict], *, transition_ms: int = 0) -> None:
    """Send compiled writes as effect switches over the transport the
    ownership record grants. Raises on the first hard failure — the API
    surfaces it to the owner instead of half-applying a scene silently.

    transition_ms > 0 is the OVERRIDE BLEND entry-ramp equivalent
    (SceneV2.entry_ramp_ms): writes blend in (hue-arc for colour) instead of
    landing as an instant switch. 0 (the default) is today's unchanged
    instant-jump behaviour."""
    owner = _require_owner()
    if owner == light_ownership.SPECTRA:
        await _apply_via_facade(writes, transition_ms)
    else:
        await _apply_via_http(writes, transition_ms)


async def get_virtuals() -> dict:
    """GET the live virtuals map ({id: {config, effect: {type, config},
    ...}}) over the transport the ownership record grants — same routing as
    apply_writes, for callers that need to READ current state rather than
    write an effect (spectra/services/dark_light.py: snapshotting a
    background before locking it, confirming a lock/unlock landed)."""
    owner = _require_owner()
    if owner == light_ownership.SPECTRA:
        from fx import facade
        resp = await facade.handle("GET", "/api/virtuals")
        resp.raise_for_status()
    else:
        async with httpx.AsyncClient(base_url=config.ledfx_url(),
                                     timeout=REQUEST_DEADLINE_S) as client:
            async with _slots:
                resp = await client.get("/api/virtuals")
            resp.raise_for_status()
    return resp.json().get("virtuals", {})


async def set_virtual_config(virtual_id: str, patch: dict) -> None:
    """POST a partial virtual-config merge (e.g. {"dark_lock": bool}) — the
    device-level config PATCH, distinct from apply_writes' effect PUT — over
    the transport the ownership record grants. Raises on failure, same
    contract as apply_writes."""
    owner = _require_owner()
    if owner == light_ownership.SPECTRA:
        from fx import facade
        resp = await facade.handle(
            "POST", "/api/virtuals", json={"id": virtual_id, "config": patch})
        resp.raise_for_status()
    else:
        async with httpx.AsyncClient(base_url=config.ledfx_url(),
                                     timeout=REQUEST_DEADLINE_S) as client:
            async with _slots:
                resp = await client.post(
                    "/api/virtuals", json={"id": virtual_id, "config": patch})
            resp.raise_for_status()


async def set_virtual_active(virtual_id: str, active: bool) -> None:
    """PUT a virtual's ACTIVE flag over the transport the ownership record
    grants — the flag itself, distinct from `apply_writes`' effect PUT and
    from `set_virtual_config`'s device-config merge.

    Added for the room mapping run, which has to bring a fixture's own
    strip up for the capture when the room's carrier stands in front of it
    inactive (spectra/services/room_mapping.py's ACTIVATION section is the
    binding statement, including that the run restores what it found).
    Raises on failure, same contract as apply_writes: a capture that
    believes it activated something it did not would photograph a dark
    fixture and store the result."""
    owner = _require_owner()
    payload = {"active": bool(active)}
    if owner == light_ownership.SPECTRA:
        from fx import facade
        resp = await facade.handle("PUT", f"/api/virtuals/{virtual_id}",
                                   json=payload)
        resp.raise_for_status()
    else:
        async with httpx.AsyncClient(base_url=config.ledfx_url(),
                                     timeout=REQUEST_DEADLINE_S) as client:
            async with _slots:
                resp = await client.put(f"/api/virtuals/{virtual_id}",
                                        json=payload)
            resp.raise_for_status()


async def set_virtual_effect(virtual_id: str, effect_type: str,
                             effect_config: dict) -> None:
    """POST an effect onto a virtual — the CREATE, which `apply_writes`'
    PUT cannot do (the facade's own effects PUT refuses a virtual with no
    active effect). Same routing and the same raise-on-failure contract;
    also for the mapping run's activation of an idle strip."""
    owner = _require_owner()
    payload = {"type": effect_type, "config": dict(effect_config or {})}
    if owner == light_ownership.SPECTRA:
        from fx import facade
        resp = await facade.handle(
            "POST", f"/api/virtuals/{virtual_id}/effects", json=payload)
        resp.raise_for_status()
    else:
        async with httpx.AsyncClient(base_url=config.ledfx_url(),
                                     timeout=REQUEST_DEADLINE_S) as client:
            async with _slots:
                resp = await client.post(
                    f"/api/virtuals/{virtual_id}/effects", json=payload)
            resp.raise_for_status()


def _compose_room_effect(w: dict) -> dict:
    """Apply the room-effects layer's per-emitter gain to one write, on its
    way out — the ONE place a running Dim Wave composes with whatever the
    show is doing (spectra/services/room_effects.py's docstring is the
    binding statement).

    Identity by construction when nothing is running: room_effects.compose
    returns the caller's own dict object back, so the seam's normal path is
    byte-identical to before this feature existed. A write the layer issued
    ITSELF carries `room_effect` and is left alone — it already has the gain
    in it, and scaling it twice would square the wave."""
    if w.get("room_effect"):
        return w
    from spectra.services import room_effects
    cfg = room_effects.compose(w["virtual_id"], w.get("effect_type") or "",
                               w["config"])
    return w if cfg is w["config"] else {**w, "config": cfg}


def _body(w: dict, transition_ms: int = 0) -> dict:
    w = _compose_room_effect(w)
    body = {
        "type": w["effect_type"],
        "config": device_model.round_int_params(w["effect_type"], w["config"]),
    }
    if transition_ms > 0:
        # Same tween shape fx_executor uses for glides — hue-arc blend,
        # never through grey, never a colour-recreation crossfade.
        body["transition_ms"] = transition_ms
        body["transition_blend"] = "hue"
        body["easing"] = "linear"
    return body


async def _apply_via_http(writes: list[dict], transition_ms: int = 0) -> None:
    async with httpx.AsyncClient(base_url=config.ledfx_url(),
                                 timeout=REQUEST_DEADLINE_S) as client:
        for w in writes:
            async with _slots:
                resp = await client.put(
                    f"/api/virtuals/{w['virtual_id']}/effects",
                    json=_body(w, transition_ms))
            resp.raise_for_status()
    logger.info("fx seam: %d writes applied via %s", len(writes),
                config.ledfx_url())


# Base Effect.CONFIG_SCHEMA fields (fx/effects/__init__.py:359-409) that are
# valid on ANY effect type — unlike an effect-specific param, which
# genuinely shouldn't leak across a type switch.
_CARRY_FORWARD_KEYS = ("background_brightness", "brightness")


async def _current_effect(facade, virtual_id: str) -> dict | None:
    """Read-only GET of virtual_id's currently-active effect
    ({"config": ..., "name": ..., "type": ...}), or None if unknown (bad id,
    no host, or nothing active yet)."""
    resp = await facade.handle("GET", f"/api/virtuals/{virtual_id}")
    if resp.status_code != 200:
        return None
    return resp.json().get(virtual_id, {}).get("effect") or None


async def _is_type_switch(facade, virtual_id: str, effect_type: str) -> bool:
    """True if virtual_id is NOT currently running effect_type (read-only
    GET, no write-plane effect). Unknown (GET fails — bad id, no host) reads
    as False so the write still goes out as a single PUT and the PUT itself
    reports the real error, unchanged from today."""
    current = await _current_effect(facade, virtual_id)
    current_type = (current or {}).get("type")
    return current_type is not None and current_type != effect_type


def _carry_forward_brightness(config: dict, current_effect: dict | None) -> dict:
    """A genuine effect-type switch builds a FRESH effect instance
    (fx/effects/__init__.py:_apply_config's `self._config != {}` branch) —
    any base CONFIG_SCHEMA field the outgoing write doesn't set falls back
    to LedFX's schema default (1.0), not whatever the room was actually
    showing a moment before. 28 of his 50 real colour sets never author
    `background_brightness` for crystal-mapper, so this was a real, visible
    full-brightness flash on every one of them
    (data/spectra-transition-brightness-flash/report.md). Carry the
    previous effect's value forward instead — no prior effect
    (current_effect is None, e.g. process start before any fire has ever
    touched this virtual) has nothing to carry, so today's implicit default
    is correct there."""
    prev_config = (current_effect or {}).get("config") or {}
    carried = {k: prev_config[k] for k in _CARRY_FORWARD_KEYS
              if k not in config and k in prev_config}
    return {**config, **carried} if carried else config


async def _apply_via_facade(writes: list[dict], transition_ms: int = 0) -> None:
    global _type_switches_landed, _last_type_switch
    from fx import facade
    for w in writes:
        vid = w["virtual_id"]
        current = await _current_effect(facade, vid) if transition_ms > 0 else None
        current_type = (current or {}).get("type")
        if transition_ms > 0 and current_type is not None \
                and current_type != w["effect_type"]:
            # fx/facade.py's stale-tween-PUT guard (447-461) silently drops
            # a combined type-switch+transition PUT — a blend only makes
            # sense between two states of the SAME effect. Land the switch
            # instantly first; the write already carries the full target
            # config, so there is nothing left to tween.
            w = {**w, "config": _carry_forward_brightness(w["config"], current)}
            resp = await facade.handle(
                "PUT", f"/api/virtuals/{vid}/effects", json=_body(w, 0))
            _type_switches_landed += 1
            _last_type_switch = {"virtual_id": vid, "effect_type": w["effect_type"]}
        else:
            resp = await facade.handle(
                "PUT", f"/api/virtuals/{vid}/effects",
                json=_body(w, transition_ms))
        resp.raise_for_status()
    logger.info("fx seam: %d writes applied in-process (spectra owns)",
                len(writes))
