"""THE DROP TIMING OFFSET — every drop fires this much off its mark (the
Admiral, 2026-10-12: "Let's start by shifting the drops so they fire 400ms
earlier and then work on the UI to manually drag that marker"). Read this
before touching anything that decides WHEN a drop fires, or how long a
charge/lull builds toward one.

WHAT IT IS. One OFFSET-family quantity (docs/SPECTRA_TIMING_CONVENTIONS.md):
signed ms, NEGATIVE = the drop fires EARLIER, positive = later, 0 = on the
mark — the same unit and sign law as SpectraTrigger.trigger_offset_ms,
FlareKind.trigger_offset_ms and SceneV2.trigger_offset_ms. It RELOCATES the
drop's moment; it is not a lead. Default -400 (the Admiral's number).

WHERE IT COMES FROM (`resolve_offset_ms`), most specific first:
  1. the scene's own SceneV2.drop_timing_offset_ms, when set (None = not
     set). This is the slot the follow-up drag UI on a scene's drop-sequence
     preview writes; nothing writes it yet.
  2. the room's RoomControlState.drop_timing_offset_ms (Sonic-editable, the
     room bar's Scenes panel).
A single drop's own moment is already editable without a new field: a
stored drop trigger carries SpectraTrigger.trigger_offset_ms, and a drop
sequence's drop handle moves on the Timeline (drop_sequences.apply_edit).
Both still ADD to this offset — all OFFSET family, so the sum is ordinary
arithmetic.

WHERE IT LANDS — exactly ONE place moves the drop: trigger_engine.tick()
adds it to the target of every fire_response trigger whose event class is
"drop" (his stored drops and the drop-sequence members alike), beside the
trigger's own offset and the band's flare-kind offset. Everything a drop
carries rides that one fire, so nothing else is shifted separately:
  - the drop arm (scene_response._drive_phase) and with it the Shockwave
    (`drop_shock_on`), the strip drop, `drop_intensity`;
  - the drop-led scene cut ON the drop (drop_switch MOMENT_DROP), cut in
    the same _fire call just before the drop member — and with it a
    transition program run on the mark (drop_switch.HANDOFF_PROGRAM,
    anchor 0: the program has no lead of its own to double-shift);
  - a Fireworks meld's LATE cut, when its moment is "swallow_delay_s after
    the drop" (trigger_engine._arm_late_switch passes this offset to
    drop_switch.late_release, which measures that delay from the drop's
    actual fire). The OTHER two late moments — the next big hit and the
    deadline — stay on the music's own drop mark, as late_release's own
    docstring says: they are moments in the song, not the relocated fire.
The drop's automatic LEAD stays 0, unconditionally
(trigger_engine._response_switch_lead_ms): a drop still BEGINS on its
(now relocated) mark; this offset moves the mark, never the anchor rule.

THE BUILD ENDS ON THE NEW MARK. A charge or lull building to a drop
(phase_partner's rule) is told the gap to where the drop will FIRE, not to
its stored timestamp (`build_gap_ms`) — so the lull ramp's 90% / hang 10%
and the breath-hold (phase_grammar.breath_keys_for: black from
gap - breath to gap) end exactly on the shifted mark. The charge/lull
triggers themselves are NOT moved.

THE CLAMP. A drop never relocates to (or before) the start of its own
build: `shift_drop_ms` keeps it at least MIN_BUILD_MS after the lull (or
charge) it ends, so a lull 300 ms before its drop cannot end up firing
after it. Real lull->drop gaps are seconds; the clamp only names the edge.

NOT MOVED, stated: a drop the bridge classifies from the retired legacy
engine's broadcast (no forward notice — nothing to relocate), and the
protected windows (drop_firing.Window — two beats of reach around the drop
already cover 400 ms).

Pure: no I/O. Callers hand in the room controls and the scene.
"""
from __future__ import annotations

from typing import Any, Optional

DEFAULT_DROP_OFFSET_MS = -400
MIN_OFFSET_MS = -2000
MAX_OFFSET_MS = 2000

MIN_BUILD_MS = 100
"""The least a relocated drop sits after the start of its own build."""


def clamp(offset_ms: Any) -> int:
    try:
        v = int(round(float(offset_ms)))
    except (TypeError, ValueError):
        return DEFAULT_DROP_OFFSET_MS
    return max(MIN_OFFSET_MS, min(MAX_OFFSET_MS, v))


def resolve_offset_ms(room: Any = None, scene: Any = None) -> int:
    """The drop offset in force: the scene's own when it has one, else the
    room's, else the default. Never raises."""
    scene_value = getattr(scene, "drop_timing_offset_ms", None) if scene is not None else None
    if scene_value is not None:
        return clamp(scene_value)
    room_value = getattr(room, "drop_timing_offset_ms", None) if room is not None else None
    if room_value is not None:
        return clamp(room_value)
    return DEFAULT_DROP_OFFSET_MS


def shift_drop_ms(drop_ms: int, offset_ms: int,
                  build_start_ms: Optional[int] = None) -> int:
    """Where a drop marked at `drop_ms` fires. `build_start_ms` is the lull
    (or charge) whose build it ends, when known — the drop never fires
    within MIN_BUILD_MS of it (and an offset that would push it there stops
    at that floor; a later-than-mark offset is never clamped)."""
    shifted = int(drop_ms) + int(offset_ms)
    if build_start_ms is not None and offset_ms < 0:
        floor = min(int(drop_ms), int(build_start_ms) + MIN_BUILD_MS)
        shifted = max(shifted, floor)
    return shifted


def applied_offset_ms(drop_ms: int, offset_ms: int,
                      build_start_ms: Optional[int] = None) -> int:
    """`shift_drop_ms` expressed as the offset actually applied."""
    return shift_drop_ms(drop_ms, offset_ms, build_start_ms) - int(drop_ms)


def build_gap_ms(start_ms: int, target_ms: Optional[int],
                 target_class: Optional[str], offset_ms: int) -> Optional[int]:
    """The gap a charge/lull starting at `start_ms` builds over, when its
    build ends on a trigger at `target_ms` of class `target_class`: to where
    that trigger FIRES — a drop's relocated moment, anything else unmoved.
    None when there is nothing to build to (the caller's flat default)."""
    if target_ms is None:
        return None
    end = (shift_drop_ms(target_ms, offset_ms, start_ms)
           if target_class == "drop" else int(target_ms))
    gap = end - int(start_ms)
    return gap if gap > 0 else None
