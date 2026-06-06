"""
SpotFX — Scene-override builder.

Flattens one MorphStepAction (or a list of morph_set lane picks) into the
`virtuals` payload + per-virtual `transition_time` map that the scene-override
dispatch path pushes into the shared `spotfx-morph-temp` scene on LedFX.

The flattener reuses `morph_compiler.compile_target` so the abstract → raw-param
math (aspect_scale, nudge intensity, scale_offset conversion for x/y, etc.)
stays identical to the bus-based path. The only difference is that we DON'T
issue any LedFX writes here — we just produce the final state.

A built payload always carries `action: "ignore"` entries for every imported
virtual NOT touched by this morph. This is critical: LedFX's POST-with-id
merges at the virtual level, so without explicit "ignore" entries the temp
scene would accumulate stale "activate" entries from previous morphs and
fire them on the next activate.
"""
from __future__ import annotations

from typing import Optional

from models.music_event import Action, MorphStepAction
from services import effect_params as _ep
from services.morph_compiler import collect_bg_color_per_vid, compile_target


def _final_state_for_virtual(vid: str, switches: list, patches: list, virtual_cache: dict) -> Optional[dict]:
    """Resolve one virtual's post-morph state from its switch (at most one) and
    patch writes. Returns {action, type, config} or None if the virtual ends up
    with no meaningful state (e.g. no switch + no patches + nothing cached)."""
    # Find the switch for this vid (compile_target emits at most one per target,
    # and the executor's two-pass guarantees the switch lands BEFORE any patch).
    switch = next((w for w in switches if w.virtual_id == vid), None)
    my_patches = [w for w in patches if w.virtual_id == vid]

    cached_eff = (virtual_cache.get(vid) or {}).get("effect") or {}
    if switch is not None:
        etype = switch.new_effect_type
        cfg = dict(switch.starter_config or {})
    else:
        etype = cached_eff.get("type")
        cfg = dict(cached_eff.get("config") or {})

    if not etype:
        return None

    for w in my_patches:
        # Patches against the post-switch effect type (compile_target's two-pass
        # design guarantees patches were computed against the new effect after
        # the switch was applied to the working cache).
        cfg.update(w.patch or {})

    return {"action": "activate", "type": etype, "config": cfg}


def _collect_writes(actions: list[MorphStepAction], virtual_cache: dict, intensity_resolver) -> tuple[list, list, int]:
    """Compile every MorphStepAction's targets into (switch_writes, patch_writes, max_ramp_ms).
    `intensity_resolver(source: str) -> Optional[float]` mirrors the engine's
    _beat_intensity_now for nudge targets so this builder is testable without
    threading the engine."""
    switches = []
    patches = []
    max_ramp_ms = 0

    for action in actions:
        ramp_ms = action.ramp_ms if action.ramp_ms is not None else 0
        if ramp_ms is not None:
            max_ramp_ms = max(max_ramp_ms, ramp_ms)

        step_source = getattr(action, "intensity_source", None) or "rms_total"
        intensity = None
        if any(t.mode == "nudge" and t.aspect != "effect" for t in action.targets):
            intensity = intensity_resolver(step_source)

        # Pre-scan bg_color targets so effect-switch starter_config can carry
        # the auto-derived accent color (same hint the bus path uses).
        bg_color_per_vid = collect_bg_color_per_vid(action)

        # Pass 1: effect-switch targets compile against current cache
        for target in action.targets:
            if target.aspect != "effect":
                continue
            switches.extend(compile_target(target, virtual_cache, default_ramp_ms=ramp_ms,
                                           bg_color_per_vid=bg_color_per_vid))

        # Mutate the working cache with the post-switch state so Pass 2 sees it
        # — same mechanic as the executor. We don't touch the real
        # `state.ledfx_virtual_cache` here; caller passes a copy if they don't
        # want their cache mutated.
        for sw in switches:
            virtual_cache.setdefault(sw.virtual_id, {})["effect"] = {
                "type": sw.new_effect_type,
                "config": dict(sw.starter_config or {}),
            }

        # Pass 2: non-effect targets compile against post-switch cache
        for target in action.targets:
            if target.aspect == "effect":
                continue
            t_intensity = intensity if target.mode == "nudge" else None
            patches.extend(compile_target(
                target, virtual_cache,
                default_ramp_ms=ramp_ms,
                intensity=t_intensity,
            ))
            # Per-target ramp_ms can override the action's default
            t_ramp = target.ramp_ms if target.ramp_ms is not None else ramp_ms
            if t_ramp is not None:
                max_ramp_ms = max(max_ramp_ms, t_ramp)

    return switches, patches, max_ramp_ms


def build_scene_state(
    actions: list[MorphStepAction],
    virtual_cache: dict,
    intensity_resolver=lambda src: None,
) -> dict:
    """Compile + flatten one-or-more MorphStepActions into the scene-override
    payload structure.

    Returns:
      {
        "scene_virtuals":       dict[vid, {action, type?, config?}],    # full imported set
        "transition_times_ms":  dict[vid, int],                         # touched vids only
        "touched_virtuals":     list[str],
        "post_state_per_vid":   dict[vid, {type, config}],              # for cache update post-fire
      }

    `virtual_cache` is mutated to reflect post-switch state (so callers should
    pass a shallow-cloned copy if they don't want their real cache touched).
    The caller is responsible for owning the cache copy semantics.

    `intensity_resolver(source)` returns the beat intensity for a given source
    (rms_total / rms_bass / onset_score) or None if no song is playing.
    """
    actions = [a for a in actions if isinstance(a, MorphStepAction) and a.targets]
    switches, patches, max_ramp_ms = _collect_writes(actions, virtual_cache, intensity_resolver)

    touched_vids: list[str] = []
    seen: set[str] = set()
    for w in switches + patches:
        if w.virtual_id not in seen:
            seen.add(w.virtual_id)
            touched_vids.append(w.virtual_id)

    scene_virtuals: dict[str, dict] = {}
    post_state: dict[str, dict] = {}

    # Touched virtuals: emit activate with full final (type, config)
    for vid in touched_vids:
        state = _final_state_for_virtual(vid, switches, patches, virtual_cache)
        if state is None:
            continue
        scene_virtuals[vid] = state
        post_state[vid] = {"type": state["type"], "config": dict(state["config"])}

    # Every other imported virtual: explicit "ignore" so LedFX's per-virtual
    # merge can't resurrect stale entries from a prior morph.
    for vid in _ep.get_all_virtual_ids():
        if vid not in scene_virtuals:
            scene_virtuals[vid] = {"action": "ignore"}

    transition_times_ms = {vid: max_ramp_ms for vid in touched_vids}

    return {
        "scene_virtuals":      scene_virtuals,
        "transition_times_ms": transition_times_ms,
        "touched_virtuals":    touched_vids,
        "post_state_per_vid":  post_state,
    }


def morph_actions_from_event(event, preselected_morph_picks=None) -> list[MorphStepAction]:
    """Pull out every MorphStepAction the dispatch path would fire for this event.

    - single: event.actions (filter to MorphStepActions; the picker has already
              run, but for scene-override we accept all morph_step alternatives
              since the planner pre-pick is what really matters at fire time).
    - morph_set: derived from `preselected_morph_picks` (list of MorphPick, i.e.
              (lane_name, action, offset_ms)) if provided; otherwise empty
              (caller should pre-pick before building).
    - sequence / beat_sequence: returns empty list — caller (planner) should
              detect this and warn that scene_override is currently unsupported
              for sequenced events.
    """
    if preselected_morph_picks:
        return [p.action for p in preselected_morph_picks if isinstance(p.action, MorphStepAction)]

    if event.event_type == "single":
        return [a for a in (event.actions or []) if isinstance(a, MorphStepAction)]

    if event.event_type == "morph_set":
        # Without pre-picks we can't deterministically know which lane action
        # will fire — caller must provide them.
        return []

    # sequence / beat_sequence not honored in Phase 1
    return []
