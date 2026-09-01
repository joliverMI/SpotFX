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
empty emitter set, a phone that goes away, a camera that cannot resolve the
composition it is being asked to read back — and one WARNING, which is a
different thing from a refusal: a map that will come out as a single piece
still runs and is still worth keeping, it just cannot show a wave. Each has a sentence below or is
confirmed to have one at its own site — plus one FACT, `unseen_note`, which
is neither: an emitter whose light this pose could not see ran perfectly
well and is worth recording as such. What is NOT expected — a genuine bug
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
    "The room ran out of its held time before this run finished. Everything "
    "measured so far is kept — press Start mapping again to carry on, or map "
    "fewer parts at once (the plan says how many, and how long, before you "
    "press).")


def too_long_refusal(estimate_s: float, hard_cap_s: float) -> str:
    """A run whose own estimate is past the hard cap on ONE held room,
    refused BEFORE the room goes dark and never silently truncated.

    THE SHAPE OF THE ANSWER MATTERS: this names the cost and hands the
    choice back. It must never propose (or perform) a coarser granularity
    on his behalf — granularity and block size are HIS decisions, and a
    surprising value is a decision, not an error. The plan line already
    carries pieces, minutes and the ceiling; this sentence says which
    bound was crossed and by how much."""
    return (f"This run would hold the room dark for about "
            f"{estimate_s / 60.0:.0f} minutes, and one continuous hold is "
            f"capped at {hard_cap_s / 60.0:.0f}. Nothing was written. Map "
            f"part of the room at a time — leave some carriers out of this "
            f"run and map them in a second pass — or choose a setting that "
            f"gives fewer pieces; the plan shows the cost of each before you "
            f"press.")


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


def unresolvable_composition(report: dict, width: int, height: int, *,
                             target_label: str = "") -> str:
    """THE CAMERA CANNOT READ THIS TARGET — refused two captures in, before
    the room is held dark for the other twenty.

    THE LIVE FAILURE THIS EXISTS FOR (2026-09-01, both runs of the
    commissioning test on his tv-mapper): the whole 736-pixel composition
    imaged into a few dozen camera pixels, so every pattern and its
    inverse landed on the SAME camera pixels and cancelled. The run spent
    ~42 seconds, decoded 0 of 736, and the frozen table read that as
    "occlusion or blob-merge" — an attribution pointing at his room for
    what was an instrument pointed at something it cannot resolve.
    `gray_code.MIN_CAMERA_PX_PER_INDEX` carries the arithmetic.

    IT SAYS WHICH OF TWO THINGS IT IS, because a different act clears each
    and because they indict different things:

      IMPOSSIBLE  below the Nyquist bar. Nothing can be decoded however
                  bright the room is. His whole 736-pixel composition,
                  through the 320x180 frame the phone sends, is this.
      MARGINAL    above that bar but inside RESOLUTION_SAFETY_FACTOR of it.
                  A decode here would SUCCEED and be WRONG — a low bit
                  flipped by a fraction of a pixel lands, by gray code's own
                  guarantee, on a plausible NEIGHBOUR. The captain's ruling
                  on splitting the run per fixture: "marginal is the state
                  that produces a confident wrong answer". His ring alone,
                  560 pixels needing ~1120 camera pixels of a frame whose
                  whole border is ~1000, is this one.

    THE SHAPE OF THE ANSWER, the same discipline `too_long_refusal` keeps:
    name the measurement, name the bar, and hand back the choice. It never
    quietly commissions a coarser version of what was asked for — WHAT is
    being commissioned is his decision, and the frozen table judges the
    target's own pixel count because that is what the stored mapper says.
    """
    from spectra.services import gray_code

    lit = int(report.get("lit_pixels") or 0)
    total = int(report.get("total") or 0)
    needed = int(report.get("needed_camera_px") or 0)
    safe = int(report.get("safe_camera_px") or 0)
    per = float(report.get("camera_px_per_index") or 0.0)
    verdict = str(report.get("verdict")
                  or gray_code.RESOLUTION_IMPOSSIBLE)
    what = f"{target_label} " if target_label else ""
    subject = target_label or "the composition"
    if lit <= 0:
        return (f"The camera saw no light from {subject} at all: with every "
                f"one of its {total} pixels turned on, not one camera pixel "
                f"came out brighter than the dark reference. Nothing was "
                f"measured and nothing was written. Check the phone is "
                f"pointed at the television, that the fixtures actually lit, "
                f"and that the frame is not so dark the difference rounds "
                f"away — then press Commission again.")
    if verdict == gray_code.RESOLUTION_MARGINAL:
        return (f"MARGINAL, so this run refused rather than guessing. From "
                f"where the phone is standing, {what}images {lit} camera "
                f"pixels for its {total} — about {per:.2f} each, which "
                f"clears the {report.get('min_camera_px_per_index')} "
                f"absolute minimum but not the "
                f"{report.get('safe_camera_px_per_index')} this instrument "
                f"insists on ({safe} camera pixels, of the {width}x{height} "
                f"frame the phone sends). In that band a decode SUCCEEDS "
                f"and is WRONG: one bit flipped by a fraction of a pixel "
                f"lands on a neighbouring LED, so the answer comes back "
                f"confident and plausible and untrue — which is the one "
                f"outcome a ground-truth test must never produce. Nothing "
                f"was written. Move the phone closer, or commission a "
                f"smaller piece — one fixture, or one segment — then press "
                f"Commission again.")
    return (f"From where the phone is standing, this camera cannot tell "
            f"{subject}'s pixels apart. With all {total} of them on, "
            f"{'it' if target_label else 'the composition'} lights {lit} "
            f"camera pixels — about {per:.2f} per pixel, where reading them "
            f"back needs about {report.get('min_camera_px_per_index')} each "
            f"({needed} in total, of the {width}x{height} frame the phone "
            f"sends). Below that, a pattern and its opposite land on the "
            f"same camera pixels and cancel, so nothing can be decoded "
            f"however bright the room is. Nothing was written. Move the "
            f"phone closer, frame just the television, or commission a "
            f"smaller piece — one fixture, or one segment — then press "
            f"Commission again.")


def capture_refusal(emitter_label: str, exc: BaseException) -> str:
    """One emitter's own failure, named with what it was measuring. An
    ownership loss is NOT routed here — that ends the run (MID_RUN_LOSS);
    this is for the fixture that stopped answering while its neighbours are
    still fine, which is why the run carries on past it."""
    return (f"{emitter_label} could not be measured ({type(exc).__name__}: "
            f"{exc}). The rest of the run carried on — check that fixture is "
            f"powered and reachable, then map it again on its own.")


def unseen_note(emitter_label: str, pose_id: str = "", *,
                retried: bool = False) -> str:
    """A FACT, not a refusal and not a warning: this emitter ran and the
    camera saw none of its light from where the phone was standing.

    Found on his first real map (2026-08-31): 22 emitters ran, 14 footprints
    were stored, and the 8 that produced ~zero lit-minus-dark — far-side TV
    blocks, sconce spill outside the frame — simply vanished from the store.
    The physics was right; the record was silent. The wording is deliberately
    neutral: a second pose can see this emitter later, so nothing here says
    anything went wrong.

    `retried` distinguishes the two findings, and they are genuinely
    different: a plain unseen is one measurement, while a retried one has
    also had the leading alternative explanation — the previous emitter's
    fade bleeding into this one's dark reference — removed by a second
    capture with a much longer dark settle. Saying so is the difference
    between "we did not see it" and "we looked twice, properly"."""
    where = f" (pose {pose_id})" if pose_id else ""
    if retried:
        # The retry ALREADY ruled out the leading alternative explanation (a
        # neighbour's fade contaminating the dark reference), so this
        # sentence can say what the plain one only guessed at.
        return (f"No light seen from this pose{where}, retried with an "
                f"extended settle: {emitter_label} was measured twice, the "
                f"second time with the room left dark three times as long, "
                f"and landed at nothing both times. Its light really is "
                f"outside this shot — photograph the room from somewhere "
                f"that can see it, and this piece fills in.")
    return (f"No light seen from this pose{where}: {emitter_label} was lit "
            f"and the camera measured nothing from it. Its light is most "
            f"likely outside the frame — photograph the room from somewhere "
            f"that can see it, and this piece fills in.")


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
