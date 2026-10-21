"""ABSORB MUSIC'S LIGHT STAND-DOWN — the lights stay untouched while an
Absorb window plays songs nobody is hearing (data/absorb-music-plan/
report.md §6.3, phase 2; his Q3 answer, verbatim: "nothing").

Absorb (SpotFX's services/absorb.py) plays a playlist on Serenity with the
house silent so the capture path records every song's audio shape. Music
playing on Serenity drives the whole show, and an evening window lands in a
`music: "show"` house mode, so without this the room would run a full light
show on songs nobody hears. Nothing existing prevents that: Serenity is on
the music-device allowlist, and `suppress_triggers_during_capture` only
gates the retired LedFX write plane.

THE SIGNAL. SpotFX's "state" broadcast carries `absorb` (its
`status_brief()`); spectra/services/bridge.py's `absorb_holds_lights()` is
True while it says `lights_held`. SpotFX sets that only AFTER it has proven
the house silent, and clears it the moment it gives the house back — first
thing on a yield to his own music, last thing on a close. The bridge holds
it across a disconnect but never past `bridge.ABSORB_STALE_S`.

WHERE IT IS ENFORCED — each choke point checked individually (the §86
lesson: a family-level "this path is gated" belief has been wrong three
times in this codebase):

  bridge.conductor_deferral / sequencer_deferral   drift, the colour
                                     journey, the Pulse feed, sequencer rolls
  scene_sequencer.fire_scene_by_id   every automatic scene change — his
                                     fire_scene triggers, the song-start
                                     transition, planned cues, drop-led
                                     switches. origin="house" passes: the
                                     house layer's own look is the house's,
                                     not the music's
  engine._response_gate / _update_gate  flares, charge/lull/drop, drop
                                     sequence members, update flares, and a
                                     staggered kind batch waking late
  engine.fire_analysed_color_event   the analysed colour moment
  trigger_engine select_color_set    a stored colour trigger
  engine._show_cue                   Light Show High/Low Trigger arms
  engine._on_track_uri               a Show Sequence's "wait N songs" never
                                     counts an absorb song; Ambient's
                                     on-music-pause rule reads it as UNKNOWN
                                     (carries the current hold forward)
  house._default_playing             absorb's playback is not the room's
                                     music: a "show" mode never hands in

NAMED, NEVER SILENT: every refusal at fire_scene_by_id and the response /
update gates is recorded in fire_history's "deferred" bucket with
`reason: "absorb"`, and the hold's start and end are each one "absorb" line
in the show log — a held room and a broken room must not look the same.

Proof, from the show side (tests/test_absorb_stand_down.py): the real
trigger engine over a real position feed with a window open — zero writes
at fx_seam, every deferral named — then the same sweep after release
fires for real.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

REASON = "absorb"


def active() -> bool:
    """Is an Absorb window holding the lights still right now. Never
    raises — a broken read must not break a fire."""
    try:
        from spectra.services.engine import bridge
        return bool(bridge.absorb_holds_lights())
    except Exception:                                    # noqa: BLE001
        logger.exception("absorb_hold: could not read the bridge — not holding")
        return False


def reason() -> Optional[str]:
    return REASON if active() else None


def record_deferral(key: str, detail: Optional[dict] = None) -> None:
    """One named "deferred" entry for something Absorb held back."""
    try:
        from spectra.services import fire_history
        fire_history.record_fire("deferred", key,
                                 {**(detail or {}), "reason": REASON})
    except Exception:                                    # noqa: BLE001
        logger.exception("absorb_hold: could not record a deferral")


def record_transition(held: bool, brief: Optional[dict]) -> None:
    """The show-log line for the hold starting or ending."""
    try:
        from spectra.services import fire_history
        b = brief or {}
        fire_history.record_fire("absorb", "held" if held else "released", {
            "run_id": b.get("run_id"), "state": b.get("state"),
            "stage": b.get("stage")})
    except Exception:                                    # noqa: BLE001
        logger.exception("absorb_hold: could not record the hold changing")
