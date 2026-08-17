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


def color_set_preferred(card_availability: str, scene_preference: str,
                        room_mode: str) -> bool:
    """PREFERENCE (owner ask 2026-08-17) — a second, orthogonal axis from
    the AVAILABILITY function above. Availability decides whether an item
    plays at all in the current room mode; this decides which of the
    still-available colour sets a SCENE draws from. Callers must apply both
    (availability first) — this function only judges preference and says
    nothing about whether `card_availability` itself passes the room mode.

    The owner's rule, verbatim: a scene preferring dark "doesn't run light
    mode color sets unless the system is set to light mode" — an explicit
    system mode always settles the question. Generalised symmetrically (his
    example only named Light overriding a dark preference, but a scene
    preferring light under an explicit system Dark can't be left with zero
    eligible sets either): preference is consulted ONLY while the room is
    Hybrid (room_mode == "default"). Under an explicit Dark or Light room
    mode, every set that already passed AVAILABILITY is used as-is,
    preference or not.

    Within Hybrid: no preference (scene_preference == "default") matches
    everything — unchanged behaviour, the mechanism is inert until a scene
    declares one. A declared preference matches every UNMARKED
    ("default") card — his own ask was additive ("you don't have to
    change any color sets"), so a set nobody has classified yet still
    plays — and every card marked the SAME way; it excludes only a card
    explicitly marked the OPPOSITE mode."""
    if scene_preference == "default":
        return True
    if room_mode != "default":
        return True
    if card_availability == "default":
        return True
    return card_availability == scene_preference
