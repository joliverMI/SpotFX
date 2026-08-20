"""Global "SPECTRA is previewing" pause (owner ask, 2026-08-17, Colour
Set/Group editor's Preview button — spectra/services/room_preview.py was
the original and, since 2026-08-20, spectra/services/flare_preview.py is a
second caller: the flare scrubbing-preview timeline arms this for as long
as its overlay stays open, via a frontend heartbeat — see that module's
docstring). While active it OUTRANKS every existing deferral reason
(pause/dinner_party/ambient/force_scene) at the automatic-fire choke
points that already compose with them — spectra/services/bridge.py's
conductor_deferral/sequencer_deferral, engine.fire_response_event/
fire_scene_update_event, and scene_sequencer.fire_scene_by_id — because a
hand-held preview is the most explicit, momentary override a room can be
under: an automatic scene/response/set change landing mid-drag (or
mid-scrub) would fight exactly what the Admiral is looking at.

Room_preview's OWN writes never route through those gated choke points
(they go straight through fx_seam, the same seam dark_light.py uses) so
there is no self-deadlock: starting a preview does not block the preview's
own apply. flare_preview's writes never route through them either — it
fires against a scratch, hardware-dark RecordingExecutor (see its own
docstring), so its "apply" never reaches a real device at all.

In-memory only, one deadline at a time (a room has one Admiral, and
room_preview itself only ever runs one session) — like color_set_groups'
cursor state, this resets on a SPECTRA restart, which is acceptable: a
restart mid-preview has bigger problems than an unpaused sequencer.
"""
from __future__ import annotations

import time

_until: float | None = None


def start(duration_s: float) -> None:
    """(Re)arm the pause for duration_s from now, monotonic clock."""
    global _until
    _until = time.monotonic() + duration_s


def clear() -> None:
    global _until
    _until = None


def active() -> bool:
    return _until is not None and time.monotonic() < _until


def remaining_s() -> float:
    if _until is None:
        return 0.0
    return max(0.0, _until - time.monotonic())
