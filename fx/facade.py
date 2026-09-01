"""In-process facade over the vendored render pipeline (SpotFX-authored).

SPECTRA Stage 1: api/ledfx_client._request() routes here instead of HTTP when
`settings.fx_in_process` is on (default OFF — production stays on HTTP).
Every public ledfx_client function then becomes a direct call into fx.* with
its request/response contract unchanged, so the trigger engine and all other
callers are untouched.

Each handler is a port of the fork's thin aiohttp handler onto the FxHost
registries; the source handler is cited above each. Ported faithfully,
including per-write save_config persistence. Omissions — surface SpotFX never
sends, dropped deliberately:
  - config "RANDOMIZE" payloads (virtual_effects.py:109-142, 333-370)
  - preset annotation on GET /api/scenes (scenes.py:31-56; needs the presets
    library, which is not vendored)
  - PUT /api/virtuals global pause toggle
  - GET /api/config's audio/melbanks section coercion (api/config.py:75-80):
    AUDIO_CONFIG_SCHEMA enumerates host audio devices — a hardware touch this
    facade must never make. Raw stored values are returned instead.

Host lifecycle: lazy singleton created on first call, config_dir from
`settings.fx_config_dir` (an fx-owned dir, NEVER the live LedFX ~/.ledfx).
Tests inject their own started FxHost via set_host().
"""
from __future__ import annotations

import base64
import io
import logging
import os
import time
from typing import Any, Optional

from PIL import ImageSequence

from fx import assets as fx_assets
from fx import shapemap
from fx.config import CORE_CONFIG_SCHEMA, save_config
from fx.consts import PROJECT_VERSION
from fx.effects import DummyEffect
from fx.events import BaseConfigUpdateEvent
from fx.host import FxHost
from fx.utils import generate_id, open_gif

logger = logging.getLogger(__name__)


class FacadeHTTPError(Exception):
    def __init__(self, status_code: int, body: dict):
        super().__init__(f"fx facade {status_code}: {body}")
        self.status_code = status_code
        self.body = body


class FacadeResponse:
    """Duck-type of the httpx.Response surface ledfx_client uses:
    .status_code, .json(), .raise_for_status()."""

    def __init__(self, body: dict, status_code: int = 200):
        self._body = body
        self.status_code = status_code

    def json(self) -> dict:
        return self._body

    def raise_for_status(self) -> "FacadeResponse":
        if self.status_code >= 400:
            raise FacadeHTTPError(self.status_code, self._body)
        return self


def _ok(body: dict) -> FacadeResponse:
    return FacadeResponse(body, 200)


def _invalid(reason: str) -> FacadeResponse:
    return FacadeResponse(
        {"status": "failed", "payload": {"type": "error", "reason": reason}},
        400,
    )


def _internal(reason: str) -> FacadeResponse:
    return FacadeResponse(
        {"status": "failed", "payload": {"type": "error", "reason": reason}},
        500,
    )


# ── Host lifecycle ────────────────────────────────────────────────────────────

_host: Optional[FxHost] = None


def set_host(host: Optional[FxHost]) -> None:
    """Test seam: install an already-started FxHost (None to clear)."""
    global _host
    _host = host


async def get_host() -> FxHost:
    global _host
    if _host is None:
        from config import settings

        config_dir = os.path.abspath(settings.fx_config_dir)
        os.makedirs(config_dir, exist_ok=True)
        host = FxHost(config_dir)
        await host.start()
        _host = host
    return _host


# ── Shared response builders (ports of fork api/virtual.py:14-38) ────────────

def _virtual_response(virtual) -> dict:
    response = {
        "config": virtual.config,
        "id": virtual.id,
        "is_device": virtual.is_device,
        "auto_generated": virtual.auto_generated,
        "segments": virtual.segments,
        "pixel_count": virtual.pixel_count,
        "active": virtual.active,
        "streaming": virtual.streaming,
        "last_effect": virtual.virtual_cfg.get("last_effect", None),
        "effect": {},
    }
    if virtual.active_effect and not isinstance(
        virtual.active_effect, DummyEffect
    ):
        response["effect"] = {
            "config": virtual.active_effect.config,
            "name": virtual.active_effect.name,
            "type": virtual.active_effect.type,
        }
    return response


def _process_fallback(fallback):
    # Port of virtual_effects.py:15-39.
    if isinstance(fallback, bool):
        fallback = 300.0 if fallback else None
    elif isinstance(fallback, (int, float)) and fallback > 0:
        pass
    else:
        fallback = None
    return fallback


# ── /api/info (port of api/info.py) ──────────────────────────────────────────

async def _info_get(host) -> FacadeResponse:
    return _ok(
        {
            "url": "fx://in-process",
            "name": "SpotFX fx (vendored LedFX pipeline)",
            "version": PROJECT_VERSION,
            "developer_mode": host.config["dev_mode"],
            "features": {
                "sendspin": False,
                "param_transition": True,
                "param_transition_blend": True,
            },
        }
    )


# ── /api/config (port of api/config.py GET/PUT, core keys only) ─────────────

async def _config_get(host) -> FacadeResponse:
    keys = set(map(str, CORE_CONFIG_SCHEMA.schema.keys()))
    return _ok({key: host.config.get(key) for key in keys})


async def _config_put(host, body: dict) -> FacadeResponse:
    if not isinstance(body, dict):
        return _invalid("config patch must be an object")
    core_keys = set(map(str, CORE_CONFIG_SCHEMA.schema.keys()))
    unknown = set(body) - core_keys
    if unknown:
        return _invalid(f"unsupported config keys for fx facade: {sorted(unknown)}")
    try:
        validated = CORE_CONFIG_SCHEMA({**host.config, **body})
    except Exception as e:
        return _invalid(f"invalid config patch: {e}")
    host.config.update({k: validated[k] for k in body})
    save_config(config=host.config, config_dir=host.config_dir)
    host.events.fire_event(BaseConfigUpdateEvent(dict(body)))
    return _ok({"status": "success", "payload": {"type": "success",
                "reason": "Configuration Updated"}})


# ── /api/scenes (port of api/scenes.py) ──────────────────────────────────────

async def _scenes_get(host) -> FacadeResponse:
    scenes = {}
    for scene_id, scene_config in host.config["scenes"].items():
        payload = dict(scene_config)
        payload["active"] = host.scenes.is_active(scene_id)
        scenes[scene_id] = payload
    return _ok({"status": "success", "scenes": scenes})


async def _scenes_put(host, body: dict) -> FacadeResponse:
    action = body.get("action")
    if action not in ("activate", "activate_in", "deactivate", "rename"):
        return _invalid(f'Invalid action "{action}"')
    if body.get("id") is None:
        return _invalid('Required attribute "id" was not provided')
    scene_id = generate_id(body.get("id"))
    if scene_id not in host.config["scenes"]:
        return _invalid(f"Scene {scene_id} does not exist")
    scene = host.config["scenes"][scene_id]

    if action == "activate_in":
        ms = body.get("ms")
        if ms is None:
            return _invalid('Required attribute "ms" was not provided')
        host.loop.call_later(ms, host.scenes.activate, scene_id)
        return _ok({"status": "success", "payload": {"type": "info",
                    "reason": f"Scene {scene['name']} will activate in {ms}ms"}})
    if action == "activate":
        if not host.scenes.activate(scene_id):
            return _invalid(f"Scene {scene_id} could not be activated")
        return _ok({"status": "success", "payload": {"type": "info",
                    "reason": f"Activated {scene['name']}"}})
    if action == "deactivate":
        if not host.scenes.deactivate(scene_id):
            return _invalid(f"Scene {scene_id} could not be deactivated")
        return _ok({"status": "success", "payload": {"type": "info",
                    "reason": f"Deactivated {scene['name']}"}})
    # rename
    name = body.get("name")
    if name is None:
        return _invalid('Required attribute "name" was not provided')
    host.config["scenes"][scene_id]["name"] = name
    save_config(config=host.config, config_dir=host.config_dir)
    return _ok({"status": "success", "payload": {"type": "info",
                "reason": f"Renamed to {name}"}})


async def _scenes_post(host, body: dict) -> FacadeResponse:
    # Port of api/scenes.py:181-337 (create + update, snapshot + explicit
    # virtuals payloads).
    scene_name = body.get("name")
    scene_image = body.get("scene_image")
    scene_snapshot = body.get("snapshot", False)
    scene_id = body.get("id")

    if scene_id:
        sanitized = generate_id(scene_id)
        if sanitized not in host.config["scenes"]:
            return _invalid(
                f"Scene with id '{scene_id}' does not exist. To create a new "
                "scene, omit the 'id' field."
            )
        scene_id = sanitized
        scene_config = dict(host.config["scenes"][scene_id])
        if scene_name is not None:
            scene_config["name"] = scene_name
        if scene_image is not None:
            scene_config["scene_image"] = scene_image
    else:
        if not scene_name:
            return _invalid("Required attribute 'name' was not provided")
        dupe_id = generate_id(scene_name)
        dupe_index = 1
        scene_id = dupe_id
        while scene_id in host.config["scenes"]:
            scene_id = f"{dupe_id}-{dupe_index}"
            dupe_index += 1
        if scene_image is None:
            scene_image = "Wallpaper"
        if body.get("virtuals") is None:
            scene_snapshot = True
        scene_config = {
            "name": scene_name,
            "virtuals": {},
            "scene_image": scene_image,
            "scene_puturl": body.get("scene_puturl"),
            "scene_tags": body.get("scene_tags"),
            "scene_payload": body.get("scene_payload"),
            "scene_midiactivate": body.get("scene_midiactivate"),
        }

    if not scene_snapshot:
        virtuals = body.get("virtuals")
        if virtuals is not None:
            scene_config["virtuals"] = {}
            for virtual_id, virtual_data in virtuals.items():
                if not isinstance(virtual_data, dict):
                    continue
                entry = {}
                for key in ("action", "type", "config"):
                    if key in virtual_data:
                        entry[key] = virtual_data[key]
                if "preset" in virtual_data and "type" in virtual_data:
                    entry["preset"] = virtual_data["preset"]
                scene_config["virtuals"][virtual_id] = entry
    else:
        scene_config["virtuals"] = {}
        for virtual in host.virtuals.values():
            effect = {}
            if virtual.active_effect and not isinstance(
                virtual.active_effect, DummyEffect
            ):
                effect["type"] = virtual.active_effect.type
                effect["config"] = virtual.active_effect.config
            scene_config["virtuals"][virtual.id] = effect

    host.config["scenes"][scene_id] = scene_config
    save_config(config=host.config, config_dir=host.config_dir)
    return _ok({"status": "success",
                "scene": {"id": scene_id, "config": scene_config}})


async def _scenes_delete(host, body: dict) -> FacadeResponse:
    if body.get("id") is None:
        return _invalid('Required attribute "id" was not provided')
    scene_id = generate_id(body.get("id"))
    if scene_id not in host.config["scenes"]:
        return _invalid(f"Scene {scene_id} does not exist")
    del host.config["scenes"][scene_id]
    save_config(config=host.config, config_dir=host.config_dir)
    return _ok({"status": "success"})


# ── /api/virtuals (port of api/virtuals.py GET/POST) ────────────────────────

async def _virtuals_get(host) -> FacadeResponse:
    response = {"status": "success", "paused": host.virtuals._paused,
                "virtuals": {}}
    for virtual in host.virtuals.values():
        response["virtuals"][virtual.id] = _virtual_response(virtual)
    return _ok(response)


async def _virtuals_post(host, body: dict) -> FacadeResponse:
    virtual_config = body.get("config")
    if virtual_config is None:
        return _invalid('Required attribute "config" was not provided')
    virtual_id = body.get("id")
    if virtual_id is not None:
        virtual = host.virtuals.get(virtual_id)
        if virtual is None:
            return _invalid(f"Virtual with ID {virtual_id} not found")
        virtual.config = virtual_config
        virtual.virtual_cfg["config"] = virtual.config
    else:
        virtual_id = generate_id(virtual_config.get("name"))
        virtual = host.virtuals.create(
            id=virtual_id, is_device=False, config=virtual_config, ledfx=host
        )
        host.config["virtuals"].append(
            {
                "id": virtual.id,
                "config": virtual.config,
                "is_device": virtual.is_device,
                "auto_generated": virtual.auto_generated,
            }
        )
        virtual.virtual_cfg = host.config["virtuals"][-1]
    save_config(config=host.config, config_dir=host.config_dir)
    return _ok(
        {
            "status": "success",
            "payload": {"type": "success",
                        "reason": f"Updated Virtual {virtual.name}"},
            "virtual": {
                "config": virtual.config,
                "id": virtual.id,
                "is_device": virtual.is_device,
                "auto_generated": virtual.auto_generated,
            },
        }
    )


# ── /api/virtuals/{id} (port of api/virtual.py GET/PUT) ─────────────────────

async def _virtual_get(host, virtual_id: str) -> FacadeResponse:
    virtual = host.virtuals.get(virtual_id)
    if virtual is None:
        return _invalid(f"Virtual with ID {virtual_id} not found")
    return _ok({"status": "success", virtual.id: _virtual_response(virtual)})


async def _virtual_put_active(host, virtual_id: str, body: dict) -> FacadeResponse:
    virtual = host.virtuals.get(virtual_id)
    if virtual is None:
        return _invalid(f"Virtual with ID {virtual_id} not found")
    active = body.get("active")
    if active is None:
        return _invalid('Required attribute "active" was not provided')

    if active:
        if not virtual._active_effect or isinstance(
            virtual.active_effect, DummyEffect
        ):
            last_effect = virtual.virtual_cfg.get("last_effect", None)
            if last_effect:
                effect_config = virtual.get_effects_config(last_effect)
                if effect_config:
                    effect = host.effects.create(
                        ledfx=host, type=last_effect, config=effect_config
                    )
                    virtual.set_effect(effect)
                    virtual.update_effect_config(effect)
    try:
        virtual.active = active
    except (ValueError, RuntimeError) as msg:
        return _internal(f"Unable to set virtual {virtual.id} status: {msg}")

    virtual.virtual_cfg["active"] = virtual.active
    save_config(config=host.config, config_dir=host.config_dir)
    return _ok({"status": "success", "active": virtual.active})


# ── SpotFX deviation #29: a write that did not take must never report success ─

def _verify_effect_took(host, virtual, effect_type):
    """Read the live instance BACK and say whether this virtual is actually
    driving `effect_type` now.  Returns (took, reason_if_not).

    A returning write call is not evidence.  The defect this exists for:
    a same-type effects PUT takes the in-place `active_effect.update_config`
    branch, which never touches `virtual.active` — so against a virtual that
    was evicted at config load (it still holds an effect object but runs no
    render thread) the write lands on a dead object, the executor log fills
    with glide writes, the response says success, and the fixture stays
    dark.  One honest repair is attempted first — activating the virtual is
    exactly what the type-switch branch one `elif` over already does
    unconditionally, and that asymmetry WAS the bug — and only a verified
    read-back is allowed to report success.
    """
    if virtual.active_effect is None:
        return False, "no effect instance on the virtual"
    if isinstance(virtual.active_effect, DummyEffect):
        return False, "virtual is holding a DummyEffect, not the written one"
    if virtual.active_effect.type != effect_type:
        return False, (
            f"virtual is driving '{virtual.active_effect.type}', "
            f"not the written '{effect_type}'"
        )
    if not virtual.active:
        logger.error(
            "fx facade: %s holds effect '%s' but is NOT ACTIVE — a write to "
            "it would land on nothing; attempting to activate",
            virtual.id, effect_type,
        )
        try:
            virtual.active = True
        except (ValueError, RuntimeError) as exc:
            return False, (
                f"virtual is not active and could not be activated "
                f"({type(exc).__name__}: {exc})"
            )
        if not virtual.active:
            return False, "virtual is not active and did not activate"
        if virtual.active_effect is None or isinstance(
            virtual.active_effect, DummyEffect
        ):
            return False, "activation cleared the effect instance"
        logger.warning(
            "fx facade: reactivated %s to make the '%s' write real",
            virtual.id, effect_type,
        )
    return True, ""


# ── /api/virtuals/{id}/effects (port of api/virtual_effects.py) ─────────────

async def _effects_put(host, virtual_id: str, body: dict) -> FacadeResponse:
    virtual = host.virtuals.get(virtual_id)
    if virtual is None:
        return _invalid(f"Virtual with ID {virtual_id} not found")
    if not virtual.active_effect:
        return _invalid(f"Virtual {virtual_id} has no active effect")

    effect_config = body.get("config") or {}
    effect_type = body.get("type")
    fallback = _process_fallback(body.get("fallback", None))

    transition_ms = body.get("transition_ms")
    easing = body.get("easing", "linear")
    transition_blend = body.get("transition_blend", "rgb")
    if transition_blend not in ("rgb", "hue"):
        transition_blend = "rgb"
    use_tween = (
        isinstance(transition_ms, (int, float))
        and transition_ms > 0
        and isinstance(effect_config, dict)
        and len(effect_config) > 0
        and virtual.active_effect is not None
        and virtual.active_effect.type == effect_type
    )

    # Stale tween PUT: addressed to a type that is no longer active — drop
    # (virtual_effects.py:174-190).
    if (
        isinstance(transition_ms, (int, float))
        and transition_ms > 0
        and not use_tween
        and virtual.active_effect is not None
        and not isinstance(virtual.active_effect, DummyEffect)
        and virtual.active_effect.type != effect_type
    ):
        logger.info(
            "fx facade: ignoring stale tween PUT for %s on %s (active: %s)",
            effect_type, virtual_id, virtual.active_effect.type,
        )
        return _ok({"status": "success", "effect": {}})

    # Stale patch-tagged PUT (virtual_effects.py:196-210).
    if (
        bool(body.get("patch"))
        and virtual.active_effect is not None
        and not isinstance(virtual.active_effect, DummyEffect)
        and virtual.active_effect.type != effect_type
    ):
        logger.info(
            "fx facade: ignoring stale patch PUT for %s on %s (active: %s)",
            effect_type, virtual_id, virtual.active_effect.type,
        )
        return _ok({"status": "success", "effect": {}})

    if fallback is not None and virtual.streaming:
        return FacadeResponse(
            {"status": "failed", "payload": {"type": "error",
             "reason": f"Virtual {virtual_id} being streamed to"}}, 409)

    config_override = None
    try:
        if use_tween:
            effect = virtual.active_effect
            config_override = {**effect.config, **effect_config}
            effect.start_param_transitions(
                effect_config, int(transition_ms), easing, transition_blend
            )
        elif virtual.active_effect and virtual.active_effect.type == effect_type:
            # Color-key writes recreate the effect to ride the crossfade;
            # everything else updates in place (virtual_effects.py:238-270).
            if virtual.active_effect.config.get("color_blend", True) and next(
                (
                    key
                    for key in effect_config.keys()
                    if "color" in key and not key.startswith("background")
                ),
                None,
            ):
                effect = host.effects.create(
                    ledfx=host,
                    type=effect_type,
                    config={**virtual.active_effect.config, **effect_config},
                )
                virtual.set_effect(effect, fallback=fallback)
            else:
                effect = virtual.active_effect
                virtual.active_effect.update_config(effect_config)
        else:
            effect = host.effects.create(
                ledfx=host, type=effect_type, config=effect_config
            )
            virtual.set_effect(effect, fallback=fallback)
    except (ValueError, RuntimeError) as msg:
        return _internal(f"Unable to set effect: {msg}")

    took, why = _verify_effect_took(host, virtual, effect_type)
    if not took:
        return _internal(
            f"Effect write to {virtual_id} did not take ({effect_type}): {why}"
        )

    virtual.update_effect_config(effect, config_override=config_override)
    save_config(config=host.config, config_dir=host.config_dir)

    return _ok(
        {
            "status": "success",
            "effect": {
                "config": (config_override if config_override is not None
                           else effect.config),
                "name": effect.name,
                "type": effect.type,
            },
        }
    )


async def _effects_post(host, virtual_id: str, body: dict) -> FacadeResponse:
    virtual = host.virtuals.get(virtual_id)
    if virtual is None:
        return _invalid(f"Virtual with ID {virtual_id} not found")
    effect_type = body.get("type")
    if effect_type is None:
        return _invalid("Required attribute 'type' was not provided")
    effect_config = body.get("config")
    if effect_config is None:
        effect_config = virtual.get_effects_config(effect_type)

    effect = host.effects.create(
        ledfx=host, type=effect_type, config=effect_config
    )
    fallback = _process_fallback(body.get("fallback", None))
    if fallback is not None and virtual.streaming:
        return FacadeResponse(
            {"status": "failed", "payload": {"type": "error",
             "reason": f"Virtual {virtual_id} is being streamed to"}}, 409)
    try:
        virtual.set_effect(effect, fallback=fallback)
    except (ValueError, RuntimeError) as msg:
        return _internal(f"Unable to set effect on {virtual_id}: {msg}")
    virtual.update_effect_config(effect)
    save_config(config=host.config, config_dir=host.config_dir)
    return _ok(
        {
            "status": "success",
            "effect": {"config": effect.config, "name": effect.name,
                       "type": effect.type},
        }
    )


async def _effects_delete(host, virtual_id: str) -> FacadeResponse:
    virtual = host.virtuals.get(virtual_id)
    if virtual is None:
        return _invalid(f"Virtual with ID {virtual_id} not found")
    virtual.clear_effect()
    virtual.virtual_cfg.pop("effect", None)
    save_config(config=host.config, config_dir=host.config_dir)
    return _ok({"status": "success", "effect": {}})


# ── /api/virtuals/{id}/shape (port of api/virtual_shape.py) ─────────────────

def _shape_summary(virtual, shape) -> dict:
    in_sync = bool(
        virtual._segments
        and [list(s) for s in virtual._segments]
        == [list(s) for s in shape.segments]
    )
    return {
        "width": shape.width,
        "height": shape.height,
        "live": int(shape.n_leds),
        "gaps": int(shape.width * shape.height - shape.n_leds),
        "device": shape.device_id,
        "digest": shape.digest,
        "in_sync": in_sync,
        "resampling": virtual._resample is not None,
    }


async def _shape_get(host, virtual_id: str) -> FacadeResponse:
    virtual = host.virtuals.get(virtual_id)
    if virtual is None:
        return _invalid(f"Virtual with ID {virtual_id} not found")
    text = virtual.config.get("shape_map", "") or ""
    shape = getattr(virtual, "_shape", None)
    return _ok(
        {
            "status": "success",
            "shape_map": text,
            "compiled": _shape_summary(virtual, shape) if shape else None,
        }
    )


async def _shape_put(host, virtual_id: str, body: dict) -> FacadeResponse:
    virtual = host.virtuals.get(virtual_id)
    if virtual is None:
        return _invalid(f"Virtual with ID {virtual_id} not found")
    text = body.get("shape_map")
    if not isinstance(text, str):
        return _invalid("shape_map (string) is required")
    dry_run = bool(body.get("dry_run", False))

    if not text.strip():
        if dry_run:
            return _ok({"status": "success", "summary": None})
        virtual.config = {"shape_map": ""}
        if getattr(virtual, "virtual_cfg", None) is not None:
            virtual.virtual_cfg["config"] = virtual.config
        save_config(config=host.config, config_dir=host.config_dir)
        return _ok({"status": "success", "cleared": True})

    try:
        shape = shapemap.parse(text)
    except shapemap.ShapeMapError as e:
        return _ok({"status": "error",
                    "errors": [{"line": ln, "msg": msg} for ln, msg in e.errors]})
    except Exception as e:
        return _ok({"status": "error", "errors": [{"line": 0, "msg": str(e)}]})

    if dry_run:
        g = shapemap.build_gather(shape)
        owner = [-1] * (shape.width * shape.height)
        for i in range(shape.n_leds):
            for j, cell in enumerate(g["idx"][i]):
                if g["live"][i][j]:
                    owner[int(cell)] = i
        return _ok(
            {
                "status": "success",
                "summary": _shape_summary(virtual, shape),
                "cells": [[int(r), int(c), i]
                          for i, (r, c) in enumerate(shape.led_rc)],
                "coverage": owner,
                "catchment_k": g["live"].sum(axis=1).astype(int).tolist(),
                "truncated": int(g["truncated"]),
            }
        )

    old_segments = [list(s) for s in virtual._segments]
    try:
        virtual.config = {"shape_map": text, "rows": shape.height}
        virtual.update_segments(shape.segments)
    except Exception as e:
        logger.warning("fx facade: shape apply failed on %s (%s) — restoring",
                       virtual_id, e)
        try:
            if old_segments:
                virtual.update_segments(old_segments)
        except Exception:
            logger.exception("fx facade: segment restore failed on %s", virtual_id)
        return _internal(f"shape apply failed: {e}")
    if getattr(virtual, "virtual_cfg", None) is not None:
        virtual.virtual_cfg["config"] = virtual.config
        virtual.virtual_cfg["segments"] = virtual._segments
    save_config(config=host.config, config_dir=host.config_dir)
    return _ok({"status": "success",
                "summary": _shape_summary(virtual, virtual._shape)})


# ── /api/devices/{id} + freeze (ports of api/device.py GET,
#    api/device_freeze.py) ─────────────────────────────────────────────────────

async def _device_get(host, device_id: str) -> FacadeResponse:
    device = host.devices.get(device_id)
    if device is None:
        return _invalid(f"Device {device_id} was not found")
    return _ok(dict(device.config))


async def _freeze_get(host, device_id: str) -> FacadeResponse:
    device = host.devices.get(device_id)
    if device is None:
        return _invalid(f"Device {device_id} was not found")
    return _ok({"id": device_id,
                "frozen": bool(getattr(device, "_frozen", False))})


async def _freeze_put(host, device_id: str, body: dict) -> FacadeResponse:
    device = host.devices.get(device_id)
    if device is None:
        return _invalid(f"Device {device_id} was not found")
    frozen = body.get("freeze")
    if frozen is None:
        return _invalid("Required attribute 'freeze' was not provided")
    set_frozen = getattr(device, "set_frozen", None)
    if set_frozen is None:
        return _invalid(f"Device {device_id} does not support freeze")
    await set_frozen(bool(frozen))
    return _ok({"status": "success",
                "payload": {"id": device_id, "frozen": bool(frozen)}})


# ── /api/devices list / create / update (SpotFX-authored, for the SPECTRA
#    device edit page — the fork's own api/devices.py + api/device.py PUT are
#    not vendored). DELETE is deliberately NOT offered: the owner asked to
#    "edit and create devices", and removing a device tears down its virtuals
#    and rewrites his scenes.
# ─────────────────────────────────────────────────────────────────────────────

def _device_entry(host, device) -> dict:
    """One device as the page reads it: identity, type, live config, and the
    virtuals whose segments name it (that mapping is what the per-device
    flash measurement and the category editor both need)."""
    virtual_ids = sorted(
        v.id for v in host.virtuals.values()
        if any(seg[0] == device.id for seg in (getattr(v, "_segments", None) or []))
    )
    return {"id": device.id, "type": device.type,
            "config": dict(device.config), "online": device.is_online(),
            "active": device.is_active(), "virtuals": virtual_ids}


async def _devices_get(host) -> FacadeResponse:
    return _ok({"devices": {d.id: _device_entry(host, d)
                            for d in host.devices.values()}})


async def _devices_post(host, body: dict) -> FacadeResponse:
    """Create through the vendored Devices.add_new_device — the same call the
    fork's own create endpoint makes, so the device, its virtual, its segment
    and the persisted config all land the one way that is known to work."""
    device_type = body.get("type")
    config = body.get("config")
    if not device_type or not isinstance(config, dict):
        return _invalid("Required attributes 'type' and 'config' were not provided")
    try:
        device = await host.devices.add_new_device(device_type, dict(config))
    except Exception as e:
        return _invalid(f"device creation failed: {e}")
    if device is None:
        return _invalid("device creation failed: the address could not be resolved")
    return _ok({"status": "success", "device": _device_entry(host, device)})


async def _device_put(host, device_id: str, body: dict) -> FacadeResponse:
    """Update one device's config in place and persist it — the vendored
    update_config revalidates against the driver's own schema, re-segments
    its virtuals and re-activates them, exactly as the fork's PUT does."""
    device = host.devices.get(device_id)
    if device is None:
        return _invalid(f"Device {device_id} was not found")
    config = body.get("config")
    if not isinstance(config, dict):
        return _invalid("Required attribute 'config' was not provided")
    try:
        device.update_config(dict(config))
    except Exception as e:
        return _invalid(f"device config rejected: {e}")
    for entry in host.config["devices"]:
        if entry["id"] == device_id:
            entry["config"] = device.config
            break
    save_config(config=host.config, config_dir=host.config_dir)
    return _ok({"status": "success", "device": _device_entry(host, device)})


# ── /api/assets + /api/get_gif_frames (ports of api/assets.py,
#    api/get_gif_frames.py) ────────────────────────────────────────────────────

async def _assets_get(host) -> FacadeResponse:
    try:
        return _ok({"assets": fx_assets.list_assets(host.config_dir)})
    except Exception as e:
        return _internal(f"Failed to list assets: {e}")


async def _assets_post(host, files: dict, data: dict) -> FacadeResponse:
    # httpx multipart shape from ledfx_client.upload_asset:
    # files={"file": (filename, bytes, mime)}, data={"path": dest_path}
    file_entry = (files or {}).get("file")
    file_data = file_entry[1] if isinstance(file_entry, tuple) else file_entry
    asset_path = (data or {}).get("path")
    if not file_data or not asset_path:
        return _invalid("Missing file or path")
    success, abs_path, error = fx_assets.save_asset(
        host.config_dir, asset_path, file_data, allow_overwrite=True
    )
    if not success:
        return _invalid(f"Failed to save asset: {error}")
    return _ok({"status": "success", "path": asset_path})


async def _gif_frames_post(host, body: dict) -> FacadeResponse:
    path_url = body.get("path_url")
    if path_url is None:
        return _invalid('Required attribute "path_url" was not provided')
    gif_image = open_gif(path_url, config_dir=host.config_dir)
    if not gif_image:
        return _invalid(f"Failed to open GIF image from: {path_url}")
    frames = []
    for frame in ImageSequence.Iterator(gif_image):
        with io.BytesIO() as output:
            frame.convert("RGB").save(output, format="JPEG")
            frames.append(base64.b64encode(output.getvalue()).decode("utf-8"))
    return _ok({"status": "success", "frame_count": len(frames),
                "frames": frames})


# ── Router ────────────────────────────────────────────────────────────────────

async def handle(
    method: str,
    path: str,
    *,
    json: Any = None,
    files: Any = None,
    data: Any = None,
    **_ignored,  # httpx kwargs like timeout= are transport details
) -> FacadeResponse:
    """Dispatch one ledfx_client request to the in-process pipeline. Returns
    a FacadeResponse; unknown routes get a 404 so raise_for_status() surfaces
    them exactly like an HTTP miss would."""
    host = await get_host()
    body = json if isinstance(json, dict) else {}
    parts = [p for p in path.split("/") if p]  # e.g. ["api","virtuals","x","effects"]

    if parts[:1] != ["api"]:
        return FacadeResponse({"status": "failed", "reason": f"unknown path {path}"}, 404)
    route = parts[1:]

    match (method.upper(), route):
        case ("GET", ["info"]):
            return await _info_get(host)
        case ("GET", ["config"]):
            return await _config_get(host)
        case ("PUT", ["config"]):
            return await _config_put(host, body)
        case ("GET", ["scenes"]):
            return await _scenes_get(host)
        case ("PUT", ["scenes"]):
            return await _scenes_put(host, body)
        case ("POST", ["scenes"]):
            return await _scenes_post(host, body)
        case ("DELETE", ["scenes"]):
            return await _scenes_delete(host, body)
        case ("GET", ["virtuals"]):
            return await _virtuals_get(host)
        case ("POST", ["virtuals"]):
            return await _virtuals_post(host, body)
        case ("GET", ["virtuals", vid]):
            return await _virtual_get(host, vid)
        case ("PUT", ["virtuals", vid]):
            return await _virtual_put_active(host, vid, body)
        case ("PUT", ["virtuals", vid, "effects"]):
            return await _effects_put(host, vid, body)
        case ("POST", ["virtuals", vid, "effects"]):
            return await _effects_post(host, vid, body)
        case ("DELETE", ["virtuals", vid, "effects"]):
            return await _effects_delete(host, vid)
        case ("GET", ["virtuals", vid, "shape"]):
            return await _shape_get(host, vid)
        case ("PUT", ["virtuals", vid, "shape"]):
            return await _shape_put(host, vid, body)
        case ("GET", ["devices"]):
            return await _devices_get(host)
        case ("POST", ["devices"]):
            return await _devices_post(host, body)
        case ("GET", ["devices", did]):
            return await _device_get(host, did)
        case ("PUT", ["devices", did]):
            return await _device_put(host, did, body)
        case ("GET", ["devices", did, "freeze"]):
            return await _freeze_get(host, did)
        case ("PUT", ["devices", did, "freeze"]):
            return await _freeze_put(host, did, body)
        case ("GET", ["assets"]):
            return await _assets_get(host)
        case ("POST", ["assets"]):
            return await _assets_post(host, files, data)
        case ("POST", ["get_gif_frames"]):
            return await _gif_frames_post(host, body)
    return FacadeResponse(
        {"status": "failed", "reason": f"fx facade has no route for "
         f"{method} {path}"}, 404)


async def measure_rtt_ms() -> float:
    """In-process 'RTT': time one info round-trip through the facade. Feeds
    the same state.ledfx_rtt_ms the HTTP probe feeds (effectively ~0)."""
    t0 = time.perf_counter()
    await handle("GET", "/api/info")
    return (time.perf_counter() - t0) * 1000
