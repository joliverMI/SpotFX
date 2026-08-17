"""Per-item display-mode availability (owner ask, 2026-08-17): scenes,
colour sets, and colour groups (models/color_set.py's ColorSetCard covers
both) each carry their own `display_availability: "default" | "dark" |
"light"`, independent of RoomControlState.display_mode (the room's OWN
global Hybrid/Dark/Light state, spectra/services/dark_light.py).

The rule, as the owner stated it:

    item="light"    available while the room is light or default/hybrid,
                     skipped while the room is dark.
    item="dark"      available while the room is dark or default/hybrid,
                     skipped while the room is light.
    item="default"   always available.

Consulted only by SPECTRA's own AUTOMATIC selection paths — scene_sequencer's
own roll + colour-set roll, trigger_engine's generated-trigger scene pick,
color_set_groups' member cycling, and the hard gate at scene_sequencer.
fire_scene_by_id / trigger_engine._default_select_color_set. A manual apply,
preview, or test-fire bypasses this entirely, the same "explicit human
action skips automatic gating" convention Force Scene already established.
"""
from __future__ import annotations

from typing import Literal

DisplayAvailability = Literal["default", "dark", "light"]
RoomDisplayMode = Literal["default", "dark", "light"]


def available_in_room_mode(item_availability: str, room_mode: str) -> bool:
    """True if an item marked `item_availability` may be used while the
    room's own display_mode is `room_mode`. Unknown/stale values on either
    side default to eligible — sparse or legacy data never silently vetoes."""
    if item_availability == "light":
        return room_mode != "dark"
    if item_availability == "dark":
        return room_mode != "light"
    return True
