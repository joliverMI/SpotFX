"""NAMED REFUSALS FOR THE MAPPING PATH — the standard the exposure lock set.

THE LIVE FAILURE THIS EXISTS FOR (his first real run, 2026-08-31):
`POST /api/rooms/{id}/map` raised `fx_seam.RoomReleased` out of
`room_mapping.live_virtual_ids` and reached him as a bare 500 with a stack
trace — for a condition this system ANTICIPATES. The ambient phase field
already names it ("unavailable"), the ownership bar shows it, and the way
back is one press. A stack trace tells him none of that.

THE BAR, and it was already met one module over: `mapping_session` refuses a
camera that cannot lock exposure BY NAME, saying which browser and which
capability. Everything on this path is held to the same standard — every
expected condition is a sentence that says what happened and what to do
next, in his words, never an exception class leaking through a 500.

WHAT COUNTS AS EXPECTED HERE: an ownership state (released to Home
Assistant, or a handover mid-flight), an ownership loss DURING a run, the
hold's own 3-minute ceiling, a fixture that stops answering mid-run, an
empty emitter set, a phone that goes away — and one WARNING, which is a
different thing from a refusal: a map that will come out as a single piece
still runs and is still worth keeping, it just cannot show a wave. Each has a sentence below or is
confirmed to have one at its own site. What is NOT expected — a genuine bug
— still raises, and should: a sentence invented for it would be a lie.

ONE WORDING PER CONDITION, here, so the route, the run and the page cannot
disagree about what happened — the same reason `mapping_session.
lock_refusal` is a single string rather than three that drifted apart.
"""
from __future__ import annotations

from typing import Optional

#: What a run reports when the room changes hands underneath it. Both halves
#: matter: the already-captured footprints are KEPT (a partial map is worth
#: something; a discarded one is worth nothing), and the sentence says so.
MID_RUN_LOSS = (
    "The lights were handed over part-way through, so mapping stopped there. "
    "Everything measured before that is kept — take the room back on the "
    "ownership bar and press Start mapping again to finish the rest.")

#: The hold's absolute ceiling (flare_preview_hold.MAX_HOLD_DURATION_S).
#: Reachable by a long run, and previously surfaced as the bare word
#: "max_duration" inside "the room could not be held: ...".
HOLD_CEILING = (
    "The room can only be held for three minutes at a time, and this run "
    "reached that. Everything measured so far is kept — press Start mapping "
    "again to carry on, or map fewer parts at once (the plan says how many "
    "before you press).")


def ownership_refusal(exc: BaseException) -> Optional[str]:
    """The sentence for an ownership refusal from `fx_seam`, or None when
    this is not one — in which case the caller must let it raise. Matched on
    the CLASS, not on message text, so a reworded refusal upstream cannot
    silently stop being recognised here.

    Imported lazily: this module is reached from the API layer, and
    `fx_seam` pulls in the whole write path."""
    from spectra.services import fx_seam
    if isinstance(exc, fx_seam.RoomReleased):
        return ("The lights are released (managed from Home Assistant right "
                "now), so nothing here can turn a fixture on to photograph "
                "it. Take the room back on the ownership bar, then press "
                "Start mapping again.")
    if isinstance(exc, fx_seam.HandoverInProgress):
        return ("The lights are changing hands right now, so mapping is "
                "refused until that lands. Give it a moment, then press "
                "Start mapping again.")
    return None


def hold_refusal(reason: str) -> str:
    """What a refused hold means, in his words. `reason` is the hold seam's
    own machine word."""
    if reason == "max_duration":
        return HOLD_CEILING
    if not reason or reason == "no writes":
        return ("The room could not be held for this measurement — nothing "
                "was rendering to take a snapshot of. Check that SPECTRA is "
                "driving the lights, then press Start mapping again.")
    return f"The room could not be held for this measurement: {reason}"


def capture_refusal(emitter_label: str, exc: BaseException) -> str:
    """One emitter's own failure, named with what it was measuring. An
    ownership loss is NOT routed here — that ends the run (MID_RUN_LOSS);
    this is for the fixture that stopped answering while its neighbours are
    still fine, which is why the run carries on past it."""
    return (f"{emitter_label} could not be measured ({type(exc).__name__}: "
            f"{exc}). The rest of the run carried on — check that fixture is "
            f"powered and reachable, then map it again on its own.")


def one_piece_warning(carrier_id: str, pixels: int, block_pixels: int, *,
                      splittable: bool = True) -> str:
    """A map of ONE piece, said in his words, before the room goes dark.

    Found on his own first real run (2026-08-31): his TV wrap is configured
    as a SINGLE segment, so "segments for a strip" produced one emitter —
    the exact outcome the granularity feature exists to avoid, and one that
    looks like a successful map right up until a wave will not travel along
    it. "auto" now resolves that case to blocks (`emitters.
    resolve_granularity`); this sentence is for whenever a run still comes
    out as one piece — an explicit "Whole carrier", a one-segment strip he
    chose "Segments" for — because a warning about what a map CAN'T do
    belongs before the dark room, not after it.

    A WARNING, not a refusal: the map is real and worth keeping (a whole
    strip's footprint is exactly what a room-level dimmer wants). It only
    cannot show motion ALONG the strip."""
    if not splittable:
        return (f"{carrier_id} can only be measured as one piece, so this "
                f"map cannot show a wave travelling along it — it copies one "
                f"effect onto every segment, so a part of it cannot be lit "
                f"on its own.")
    pieces = max(1, int(pixels) // max(1, int(block_pixels)))
    return (f"{carrier_id} is being mapped as ONE piece, so this map cannot "
            f"show a wave travelling along it — every pixel of it dims "
            f"together. Choose Blocks to measure it in {pieces} pieces "
            f"instead ({pixels} pixels at {block_pixels} a block).")
