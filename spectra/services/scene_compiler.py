"""SPECTRA scene → per-virtual writes, through the shared-library device
model and the one write seam (fx_seam).

Two stages, deliberately separate (report §2.3):

  resolve_scene(scene, ctx) — FIRST, entries with effect_steps select their
      variant at the fire intensity (decision: star-fold-entry-growth): the
      winning step's effect + param set replace the base pair wholesale, and
      the pick lands in the resolution report as an "effect" row — so the
      editor's test-fire at a chosen intensity shows exactly the effect that
      intensity selects. THEN every ValueBinding → scalar via
      binding_resolver (map/steps/fallback/random_sign/dice, coercion from
      the shared param registry — against the SELECTED effect's params).
      Returns a fully-scalar single-effect deep copy plus the report. A
      binding resolving to None leaves its field unset — the fire doesn't
      touch that param.

  compile_scene(resolved, color_set) — the pure SceneV2 compiler, ported
      verbatim in semantics: "all" expands to every imported virtual,
      categories to member subtrees, narrower entries override wider ones
      (all < category < virtual); color_set colours land only on mode="set"
      entries; fixed entries pin their own.

fire_scene() is the API entry: dry_run=True (default) stops at the seam —
no LedFX I/O, writes + resolution report returned for display. The real
fire goes through fx_seam.apply_writes (HTTP to the external LedFX service
until S3 hands SPECTRA the lights in-process through the same seam).

fire_scene's own entry_ramp_ms fallback chain (2026-08-19): the scene's own
entry_ramp_ms wins when authored; else room.global_transition_ms when he's
explicitly set a flat manual override; else the NEW default,
room_controls.scene_transition_ms(room, intensity) — an intensity-scaled
crossfade between two Inspector settings (his ask: scale transition time by
intensity, linearly). See room_controls.py's own docstring for the
gentle/hard naming and the settings themselves.
"""
from __future__ import annotations

import logging
from random import Random
from typing import Any, Optional

from fx import device_model
from spectra.models.binding import ValueBinding
from spectra.models.scene import SceneDeviceConfig, SceneV2
from spectra.services import binding_resolver, fx_seam
from spectra.services.binding_resolver import FireContext
from spectra.services.color_sets import ColorSetCard, ColorSetEntry

logger = logging.getLogger(__name__)


def resolve_scene(scene: SceneV2, ctx: FireContext) -> SceneV2:
    """Deep copy with every binding resolved to a scalar in its param's
    value space. ctx.resolved collects the per-binding report."""
    resolved = scene.model_copy(deep=True)
    for dev in resolved.devices:
        if dev.effect_steps:
            effect_type, params = dev.select_variant(ctx.intensity)
            ctx.resolved.append({
                "entry": dev.target or "all", "param": "effect",
                "signal": "trigger_intensity", "dice": None,
                "value": effect_type})
            dev.effect_type = effect_type
            dev.params = dict(params)
            dev.effect_steps = []
        for pname, value in list(dev.params.items()):
            if not isinstance(value, ValueBinding):
                continue
            meta = device_model.get_param_meta(dev.effect_type, pname)
            kind, lo, hi = binding_resolver.kind_for_meta(meta)
            out = binding_resolver.apply_binding(value, ctx, kind, lo, hi)
            ctx.resolved.append({
                "entry": dev.target or "all", "param": pname,
                "signal": value.signal, "dice": value.dice, "value": out})
            if out is None:
                del dev.params[pname]
            else:
                dev.params[pname] = out
        for field in ("brightness", "background_brightness"):
            value = getattr(dev, field)
            if not isinstance(value, ValueBinding):
                continue
            out = binding_resolver.apply_binding(
                value, ctx, binding_resolver.KIND_NUMERIC, 0.0, 1.0)
            ctx.resolved.append({
                "entry": dev.target or "all", "param": field,
                "signal": value.signal, "dice": value.dice, "value": out})
            setattr(dev, field, out)
    return resolved


def _entry_config(dev: SceneDeviceConfig, display_mode: str = "default",
                  light_bg_color: str = "#201830") -> dict[str, Any]:
    config: dict[str, Any] = dict(dev.params)
    if dev.color.mode == "fixed":
        if dev.color.color_value:
            # LedFX gradient params accept solid hex and gradient strings.
            config["gradient"] = dev.color.color_value
        if dev.color.bg_color and not device_model.bg_color_blocked(dev.effect_type):
            from spectra.services.room_controls import resolve_authored_bg_color
            config["background_color"] = resolve_authored_bg_color(
                dev.color.bg_color, display_mode, light_bg_color)
        if dev.color.bg_mode:
            config["background_mode"] = dev.color.bg_mode
    if dev.brightness is not None:
        config["brightness"] = dev.brightness
    if dev.background_brightness is not None:
        config["background_brightness"] = dev.background_brightness
    # An accent-capable effect (sparks_color on power) must never ride on
    # LedFX's own schema default (white) or a stale value from whatever the
    # virtual last rendered — ported from spot-effects' trigger_engine.py
    # accent-defaults-to-black-on-fire rule (services/morph_aspects.
    # accent_param_for): always write the accent explicitly, black unless
    # the scene entry itself authored a value for it.
    accent_param = device_model.accent_param_for(dev.effect_type)
    if accent_param and accent_param not in config:
        config[accent_param] = "#000000"
    return config


def _set_entry_by_virtual(color_set: ColorSetCard) -> dict[str, ColorSetEntry]:
    by_vid: dict[str, ColorSetEntry] = {}
    for entry in color_set.entries:
        for vid in device_model.resolve_scope(entry.scope.virtual_ids,
                                              entry.scope.categories,
                                              entry.scope.roles):
            by_vid[vid] = entry
    return by_vid


def _apply_set_colors(config: dict[str, Any], effect_type: str,
                      entry: ColorSetEntry, display_mode: str = "default",
                      light_bg_color: str = "#201830") -> dict[str, Any]:
    config = dict(config)   # never mutate the config shared across virtuals
    if entry.color_value:
        config["gradient"] = entry.color_value
    if entry.bg_color and not device_model.bg_color_blocked(effect_type):
        from spectra.services.room_controls import resolve_authored_bg_color
        config["background_color"] = resolve_authored_bg_color(
            entry.bg_color, display_mode, light_bg_color)
    if entry.bg_mode:
        config["background_mode"] = entry.bg_mode
    if entry.brightness is not None:
        config["brightness"] = entry.brightness
    if entry.background_brightness is not None:
        config["background_brightness"] = entry.background_brightness
    return config


def compile_scene(scene: SceneV2,
                  color_set: Optional[ColorSetCard] = None, *,
                  display_mode: str = "default",
                  light_bg_color: str = "#201830") -> list[dict[str, Any]]:
    """[{virtual_id, effect_type, config}] — pure. Callers pass a RESOLVED
    scene (resolve_scene first); a stray binding here is a programming error
    and fails loudly rather than serializing into a LedFX config.

    display_mode/light_bg_color are PASSED IN, never loaded here (this
    function must stay I/O-free) — fire_scene below loads
    room_controls.RoomControlState and threads its display_mode/
    display_light_bg_color through, the same way it already threads
    brightness_multiplier and the transition. Only "light" mode does
    anything with these; every other caller's default ("default"/hybrid)
    reproduces today's behaviour exactly — see room_controls.
    resolve_authored_bg_color for the substitution itself."""
    for dev in scene.devices:
        if dev.effect_steps:
            raise ValueError(
                f"compile_scene got unresolved effect steps on "
                f"'{dev.target or 'all'}' — run resolve_scene first")
        for pname, value in dev.params.items():
            if isinstance(value, ValueBinding):
                raise ValueError(
                    f"compile_scene got an unresolved binding on '{pname}' — "
                    "run resolve_scene first")
    writes: dict[str, dict[str, Any]] = {}
    set_mode_vids: set[str] = set()
    for kind in ("all", "category", "virtual"):
        for dev in scene.devices:
            if dev.target_kind != kind:
                continue
            if kind == "all":
                virtual_ids = list(dict.fromkeys(device_model.get_all_virtual_ids()))
                if not virtual_ids:
                    logger.warning("scene %s: all-devices entry resolves to no "
                                   "virtuals (no categories imported)", scene.name)
            elif kind == "category":
                virtual_ids = device_model.get_virtuals_for_category(dev.target)
                if not virtual_ids:
                    logger.warning("scene %s: category '%s' resolves to no virtuals",
                                   scene.name, dev.target)
            else:
                virtual_ids = [dev.target]
            config = _entry_config(dev, display_mode, light_bg_color)
            for vid in virtual_ids:
                # entry_id/color_mode ride along for the S2 engine (drift
                # declarations and palette mechanics follow the WINNING entry
                # per virtual); the write seams read only the first three keys.
                writes[vid] = {
                    "virtual_id": vid,
                    "effect_type": dev.effect_type,
                    "config": config,
                    "entry_id": dev.id,
                    "color_mode": dev.color.mode,
                }
                if dev.color.mode == "set":
                    set_mode_vids.add(vid)
                else:
                    set_mode_vids.discard(vid)
    if color_set is not None:
        by_vid = _set_entry_by_virtual(color_set)
        for vid in set_mode_vids:
            entry = by_vid.get(vid)
            if entry is None:
                continue
            w = writes[vid]
            w["config"] = _apply_set_colors(w["config"], w["effect_type"], entry,
                                            display_mode, light_bg_color)
    return list(writes.values())


def room_active_set() -> Optional[ColorSetCard]:
    """The colour set the room currently wears (shared room state). A fire
    without an explicit set compiles with THIS — the owner's sets, never
    effect-default LedFX wheel colours (owner defect fix, part c). None
    only while the room is genuinely set-less, which the conductor's
    bootstrap makes a transient state.

    THE TERMINAL FALLBACK, so only the OVERLAY resolves here, never the
    mode gate: every other automatic choke point that fails its own
    resolve_for_fire_mode_gated check (an explicit color_set_id, a
    resolved group member) degrades BY FALLING BACK TO THIS FUNCTION —
    see fire_scene_by_id's own docstring ("falls back to the room's
    active set, same as an unresolved/unknown color_set_id already
    does"). Re-applying the mode gate here would turn that fallback into
    a dead end (None, no colour at all) instead of the room's own actual
    set. active_set_id is always a concrete "set" id, never a group's —
    every writer of this field (apply_set_directly, the sequencer/
    response-engine colour picks) already resolves through
    color_set_groups first — so resolve_for_fire's group branch never
    triggers here; this is always the set-branch chain-every-enclosing-
    group overlay (found missing 2026-08-19: every trigger-driven fire
    goes through this exact fallback, since none of his 22,013 fire_scene
    triggers carry an explicit color_set_id)."""
    from spectra.services import color_journey, color_set_groups, color_sets
    set_id = color_journey.load_room().active_set_id
    if set_id is None:
        return None
    card = color_sets.get_by_id(set_id)
    if card is None:
        return None
    return color_set_groups.resolve_for_fire(card)


async def fire_scene(scene: SceneV2, *, intensity: float = 0.5,
                     color_set: Optional[ColorSetCard] = None,
                     dry_run: bool = True,
                     rng: Random | None = None) -> dict[str, Any]:
    """Resolve at the given intensity (effect selection included), compile,
    and (live only) send through the seam. The returned resolution report +
    writes are the test-fire display: dry and live runs share every step up
    to the seam — a test-fire at a chosen intensity IS the honest window
    into what that intensity selects, display_mode's black->Light
    substitution included. With no explicit color_set the scene wears the
    room's active set. Live writes carry scene.entry_ramp_ms as the
    OVERRIDE BLEND entry-ramp equivalent (0 = instant, unchanged); when
    a scene doesn't author its own, the room's global_transition_ms (the
    ledfx_global_transition equivalent) wins if he's set it explicitly,
    else the intensity-scaled scene_transition_ms(room, intensity) is the
    fallback ramp — see the module docstring's fallback-chain note."""
    if color_set is None:
        color_set = room_active_set()
    # A LOCAL, lazy import — room_controls must never be a module-level
    # name in this file (see AGENTS.md's light-mode-fix-import-crash
    # entry): loaded once here, both branches below reuse `room`.
    from spectra.services import room_controls
    room = room_controls.load_room_controls()
    ctx = FireContext(intensity, rng=rng)
    resolved = resolve_scene(scene, ctx)
    writes = compile_scene(resolved, color_set,
                           display_mode=room.display_mode,
                           light_bg_color=room.display_light_bg_color)
    if not dry_run:
        # The brightness-multiplier room control scales the ACTUAL bytes
        # sent to hardware only — never the returned/baselined writes, so
        # dry-run and live previews stay byte-identical (the honest-window
        # invariant) and the engine's carried baseline stays at the
        # authored level (the multiplier only ever touches final output).
        multiplier = room.brightness_multiplier
        live_writes = writes if multiplier == 1.0 else [
            {**w, "config": room_controls.apply_brightness(w["config"], multiplier)}
            for w in writes]
        entry_ramp_ms = (scene.entry_ramp_ms or room.global_transition_ms
                        or room_controls.scene_transition_ms(room, intensity))
        await fx_seam.apply_writes(live_writes, transition_ms=entry_ramp_ms)
        logger.info("SPECTRA scene '%s' fired at intensity %.2f: %d virtual "
                    "writes%s", scene.name, intensity, len(writes),
                    f" (colour set '{color_set.name}')" if color_set else "")
        # Re-baseline the evolution engine: drift's declared life restarts
        # from these initial conditions. The ORIGINAL scene rides along —
        # the response engine re-rolls its intact 🎲 bindings.
        from spectra.services import engine
        engine.on_scene_fired(scene, writes,
                              color_set.id if color_set else None)
    return {"dry_run": dry_run, "intensity": intensity, "writes": writes,
            "resolved_bindings": ctx.resolved, "dice_rolls": ctx.dice_rolls()}
