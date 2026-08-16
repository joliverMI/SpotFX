"""Colour Set Group resolution — day-one bar item §10 ("rotating/synced
pools", docs/SPECTRA_SPEC.md). SPECTRA's read-only colour_sets.py projection
used to drop every kind=="group" field on load (extra="ignore" over an
untyped card) and every consumer filtered to kind=="set" — a Group was
structurally invisible everywhere, confirmed 2026-08-15. This module is the
ONE place a Group id gets turned into the concrete member Set it should
apply; every choke point that can receive an explicit colour-set id
(POST /room-color/apply, the select_color_set trigger action, a
FireSceneAction's color_set_id via scene_sequencer.fire_scene_by_id, the
editor's baseline/preview endpoint) resolves through it before using the
card for anything else. A "set" card passes through unchanged.

Ported from spot-effects services/trigger_engine.py
(_select_color_set_member / _execute_set_color's merge step), per the
fidelity rule: cycle (wrap/bounce)/weighted picking, exclude_current,
Palette Sync, and the group's own override `entries` merged onto the picked
member — all exercised by his 8 real authored groups
(storage/color_sets.json, read live 2026-08-15: 100% mode="cycle",
exclude_current=True, palette_sync=True; 5/8 carry real override entries;
none use weighted mode or the retired mode-lane/scene-group machinery
below) — confirmed against his actual data, not assumed.

Deliberately NOT ported (owner-retired or architecturally inapplicable):
dark/light "mode lane" variants (dark_variant/light_variant — §36 RETIRED,
zero real usage) and the SCENE_GROUP_COLOR_REF/CURRENT_COLOR_GROUP_REF
sentinels (§42 RETIRED, depends on §2 Scene Groups, which doesn't exist in
SPECTRA). Per-trigger advance/direction/pick_mode overrides aren't ported
either: SPECTRA's SelectColorSetAction/FireSceneAction carry only a set_id —
no authoring surface asks for anything else, and no real group needs them.
Every pick here is advance=1, direction=forward, the group's own `mode`.
Groups also never enter the sequencer's own wheel-travel colour-set roll
(color_wheel.wheel_positions / scene_sequencer._default_eligible_sets both
still filter to kind=="set") — that automatic mechanism picks by chromatic
wheel position, which a Group (a pool, not a palette) has none of; a Group
is only ever reached by an explicit author choice. Free-but-same-intent
(D1): Palette Sync's anchor reuses SPECTRA's OWN room-colour state
(color_journey.RoomColorState.active_set_id / wheel_position_deg) instead of
re-deriving a parallel last-applied-id/hue tracker the way legacy's
trigger_engine does (state.last_color_set_id / a private _palette_hue) —
same intent, already-persisted SPECTRA mechanism.

Cursor state (which member a cycling/bouncing group is currently on) is
IN-MEMORY ONLY, per group id, exactly like legacy's _color_cursor* dicts —
it resets on process restart; nothing here persists it.
"""
from __future__ import annotations

import logging
import random
from typing import Optional

from spectra.services.color_sets import ColorSetCard, ColorSetEntry, SetScope

logger = logging.getLogger(__name__)

# Per-group cycling state — module-level, in-memory only (see module docstring).
_cursor: dict[str, int] = {}
_cursor_dir: dict[str, int] = {}

# ColorSetEntry fields SPECTRA's projection carries (no accent_color/ramp_ms —
# color_sets.py never modeled those; see its own docstring).
_MERGE_FIELDS = ("color_kind", "color_value", "bg_color", "bg_mode",
                 "brightness", "background_brightness")


def _bounce_step(idx: int, d: int, n: int) -> tuple[int, int]:
    nxt = idx + d
    if nxt >= n:
        d, nxt = -1, idx - 1
    elif nxt < 0:
        d, nxt = 1, idx + 1
    return nxt, d


def _hue_distance(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def _palette_sync_anchor(members: list) -> Optional[int]:
    """Index of the member representing the room's current palette: the
    room's own last-applied set when it's a member here, else the member
    nearest the room's current wheel position. None = neither anchors
    (fall back to the group's private cursor)."""
    from spectra.services import color_journey, color_sets, color_wheel
    room = color_journey.load_room()
    last_id = room.active_set_id
    if last_id:
        for i, m in enumerate(members):
            if m.color_set_id == last_id:
                return i
    room_deg = room.wheel_position_deg
    if room_deg is None:
        return None
    best: Optional[int] = None
    best_d = 1e9
    for i, m in enumerate(members):
        card = color_sets.get_by_id(m.color_set_id)
        if card is None:
            continue
        pos = color_wheel.wheel_position(card).position_deg
        if pos is None:
            continue
        d = _hue_distance(pos, room_deg)
        if d < best_d:
            best, best_d = i, d
    return best


def _pick_member(group: ColorSetCard) -> Optional[str]:
    """Pick one member id, advancing (and returning) the group's cursor.
    Mirrors legacy's _select_color_set_member at SPECTRA's fixed advance=1/
    direction=forward/pick_mode=default (see module docstring)."""
    members = group.members
    if not members:
        return None
    n = len(members)
    cur = _cursor.get(group.id)

    if group.palette_sync:
        anchor = _palette_sync_anchor(members)
        if anchor is not None and anchor != cur:
            cur = anchor  # re-anchored: the private cycle history no longer applies

    if group.mode == "cycle":
        if cur is None:
            idx = 0
            _cursor_dir[group.id] = 1
        elif group.cycle_behavior == "bounce" and n > 1:
            d = _cursor_dir.get(group.id, 1)
            idx, d = _bounce_step(cur, d, n)
            guard = 0
            while idx == cur and guard < n:   # unreachable at advance=1, n>1; kept for safety
                idx, d = _bounce_step(idx, d, n)
                guard += 1
            _cursor_dir[group.id] = d
        else:  # wrap (or single-member bounce)
            idx = (cur + 1) % n
            if idx == cur and n > 1:
                idx = (idx + 1) % n
    else:  # weighted
        last_idx = cur if group.exclude_current else None
        weights = [0.0 if i == last_idx else m.weight for i, m in enumerate(members)]
        if sum(weights) == 0:
            weights = [m.weight for m in members]
        if sum(weights) == 0:
            weights = [1.0] * n
        idx = random.choices(range(n), weights=weights, k=1)[0]

    _cursor[group.id] = idx
    return members[idx].color_set_id


def _overlay(entries: list[ColorSetEntry], merged: dict[str, ColorSetEntry]) -> None:
    """Resolve each entry's scope to virtual ids and layer its non-None
    fields onto `merged` in place — later entries (and later calls) win
    per field, per virtual. Mirrors legacy's _execute_set_color overlay."""
    from fx import device_model
    for entry in entries:
        vids = device_model.resolve_scope(entry.scope.virtual_ids,
                                          entry.scope.categories,
                                          entry.scope.roles)
        for vid in vids:
            tgt = merged.get(vid)
            if tgt is None:
                merged[vid] = tgt = ColorSetEntry()
            for f in _MERGE_FIELDS:
                v = getattr(entry, f)
                if v is not None:
                    setattr(tgt, f, v)


def resolve_for_fire(card: ColorSetCard) -> Optional[ColorSetCard]:
    """A "set" card passes through unchanged. A "group" card picks a member
    (advancing its cursor) and returns a synthetic card carrying the
    MEMBER's own id/name — so wheel position / room active_set_id / a
    future Palette Sync anchor check all resolve against the real stored
    member, exactly like legacy's `state.last_color_set_id` — with entries
    = the member's palette overlaid by the group's own override entries
    (group wins per field, per virtual; entries covering virtuals the
    member doesn't apply to still land). None = the group has no usable
    member (empty, or every member id is stale/not-a-set) — callers fall
    back exactly the way an unresolved plain set id already does."""
    if card.kind != "group":
        return card
    from spectra.services import color_sets
    chosen_id = _pick_member(card)
    if not chosen_id:
        logger.info("colour group '%s' has no members", card.name)
        return None
    member = color_sets.get_by_id(chosen_id)
    if member is None or member.kind != "set":
        logger.warning("colour group '%s' member %s missing or not a set",
                       card.name, chosen_id)
        return None
    if not card.entries:
        return member
    merged: dict[str, ColorSetEntry] = {}
    _overlay(member.entries, merged)
    _overlay(card.entries, merged)
    if not merged:
        return member
    entries = [
        ColorSetEntry(scope=SetScope(virtual_ids=[vid]),
                      **e.model_dump(exclude={"scope"}))
        for vid, e in merged.items()
    ]
    return member.model_copy(update={"entries": entries})


def resolve_ref(set_id: str) -> ColorSetCard:
    """Look up set_id and resolve it to a concrete 'set' card — raises
    ValueError (unknown id / unusable group) for callers that want a hard
    failure (the explicit manual-apply surfaces). Callers that want a
    graceful fallback to the room's active set instead should call
    resolve_for_fire directly on an already-looked-up card (scene_sequencer
    .fire_scene_by_id's convention: a missing/unusable colour set silently
    wears the room's active set rather than failing a scene fire)."""
    from spectra.services import color_sets
    card = color_sets.get_by_id(set_id)
    if card is None:
        raise ValueError(f"colour set '{set_id}' not found")
    resolved = resolve_for_fire(card)
    if resolved is None:
        raise ValueError(f"colour group '{card.name}' has no usable member")
    return resolved
