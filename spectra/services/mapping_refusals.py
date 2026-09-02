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
composition it is being asked to read back, a room whose own light moved
while a gray-code stack was being read (`ambient_drift` — the window), and — since the unattended
capture client — a capture MACHINE with no usable camera, a session that
never arrives or does not come back, and a queue somebody stopped — and,
since the night-run seam, a sleep-window start arriving while SPECTRA does
not hold the room, or with no night queue declared. Plus one
WARNING, which is a different thing from a refusal: a map that will come out as a single piece
still runs and is still worth keeping, it just cannot show a wave. Each has a sentence below or is
confirmed to have one at its own site. Since the wire-frame raise of
2026-09-01 that list also carries the camera's own PER-RUN SETTINGS: a
client that sends a frame bigger than its camera, a client that never
adopts the frame size a run needs, one of the four PINNED LEVERS
(integration time, gain, white balance temperature, focus) the camera would
not take, and an integration time so long the protocol cannot average its
frames. And since the LEVER SELF-TEST, one more that is a MEASUREMENT
rather than a read-back: a camera whose exposure control does not reach its
sensor (`lever_not_connected`, with `LEVER_REFUSING` naming the verdicts
that stop a run and the two that deliberately do not). Plus one FACT,
`unseen_note`, which is neither: an emitter whose light this pose could not
see ran perfectly well and is worth recording as such (`pose_changed_note`
is the second one). What is NOT expected — a genuine bug
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
                  bright the room is. At the 320x180 the wire carried until
                  2026-09-01 his whole 736-pixel composition was ALWAYS
                  this, from any pose: the frame's entire perimeter is
                  1,000 camera pixels and the composition needs ~1,472.
      MARGINAL    above that bar but inside RESOLUTION_SAFETY_FACTOR of it.
                  A decode here would SUCCEED and be WRONG — a low bit
                  flipped by a fraction of a pixel lands, by gray code's own
                  guarantee, on a plausible NEIGHBOUR. The captain's ruling
                  on splitting the run per fixture: "marginal is the state
                  that produces a confident wrong answer". At 320x180 his
                  ring alone — 560 pixels needing ~1,120 camera pixels of a
                  frame whose whole border is ~1,000 — was this one.

    BOTH SENTENCES QUOTE THE FRAME SIZE THEY WERE MEASURED AT, from the
    caller's own `width`/`height`, which is why the wire-frame raise moved
    the numbers without touching this function: the commissioning read now
    asks for 1920x1080 (`capture_settings`), where the same wrap carries
    ~4,600 camera pixels and the same composition clears the margin with
    2.5x to spare. A refusal here after the raise is a REAL pose problem —
    too far away, or too much of the frame spent on the rest of the room —
    and no longer an arithmetic impossibility.

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


# ── THE CAMERA'S PER-RUN SETTINGS ──────────────────────────────────────────
#
# Since 2026-09-01 a run may ask the camera for a bigger wire frame (the
# commissioning read needs 1920x1080 to tell 736 LEDs apart) and for a
# manual integration time and gain. `spectra/services/capture_settings.py`
# is the binding statement for all three. Each has a way of not happening,
# and each of those ways is an EXPECTED condition with a sentence here.


def upscaled_frame(width: int, height: int, source_w: int,
                   source_h: int) -> str:
    """A CLIENT SENT A FRAME BIGGER THAN THE CAMERA IT CAME FROM. Named and
    dropped, never counted.

    WHY THIS IS A REFUSAL AND NOT A SHRUG: `gray_code.resolution_report`
    counts CAMERA PIXELS, so pixels invented by interpolation would inflate
    the count and a target that cannot be resolved would report that it can
    — which is exactly the confident-wrong-answer the MARGINAL verdict
    exists to refuse, arriving through a side door. A bigger picture of the
    same 720p image is not more detail.

    Both shipped clients pick their own rung with
    `capture_settings.choose`, which cannot produce this; a client that
    reaches it is a client that ignored its own camera."""
    return (f"the camera sent a {width}x{height} frame from a "
            f"{source_w}x{source_h} image, so most of it is interpolation "
            f"rather than detail. Frames like that are dropped, not counted: "
            f"a decode measures how many CAMERA pixels see each LED, and "
            f"invented pixels would make an unreadable target look readable. "
            f"Set the capture client's --capture-size to what this camera "
            f"really produces, or use a camera that reaches the size the run "
            f"asked for.")


def frame_size_not_adopted(want: tuple, got: tuple, source: tuple,
                           pending: int) -> str:
    """The run asked for a bigger frame and the client never sent one.

    A client that CAN'T reach the size is not this: it downgrades honestly
    to the largest rung its camera has and the run carries on at that size,
    saying which it got. This is the client that never answered at all — an
    old page still running from a cached bundle, a capture client from
    before the ladder existed — and the honest act is to refuse rather than
    read a 1080p question out of 320x180 frames."""
    src = (f" (its camera reports {source[0]}x{source[1]})"
           if source and source[0] else "")
    return (f"this run needs {want[0]}x{want[1]} frames and the camera is "
            f"still sending {got[0]}x{got[1]}{src}. Nothing was measured and "
            f"nothing was written. Reload the Rooms page (an old tab keeps "
            f"its cached copy of the capture code), or restart the capture "
            f"client, then press again — {pending} frame"
            f"{'' if pending == 1 else 's'} arrived at the old size while "
            f"this run waited.")


def manual_camera_unavailable(refused: list, request: dict,
                              lock: dict) -> str:
    """A run asked for a manual integration time or gain and the camera did
    not take it.

    THE SAME RULE THE EXPOSURE LOCK LIVES BY, one lever further: a returning
    write call is never evidence, so this fires on the READ-BACK. Measuring
    under whatever the camera decided instead, while reporting the numbers
    that were asked for, is the one thing this path must never do — a
    comparison between two exposure regimes is worthless if one of them
    quietly did not happen.

    A run that asked for NEITHER lever never reaches this: converge-then-
    freeze is still the default and a camera with no manual controls maps
    exactly as it always has."""
    asked = []
    if request.get("exposure_time") is not None:
        asked.append(f"integration time {request['exposure_time']} "
                     f"(x100 us, i.e. {request['exposure_time'] * 1e-4:.4g}s)")
    if request.get("gain") is not None:
        asked.append(f"gain {request['gain']}")
    got = []
    if lock.get("exposure_time") is not None:
        got.append(f"integration time {lock['exposure_time']}")
    if lock.get("gain") is not None:
        got.append(f"gain {lock['gain']}")
    ranges = []
    if lock.get("exposure_time_range"):
        ranges.append(f"integration time {lock['exposure_time_range'][0]:g}"
                      f"..{lock['exposure_time_range'][1]:g}")
    if lock.get("gain_range"):
        ranges.append(f"gain {lock['gain_range'][0]:g}"
                      f"..{lock['gain_range'][1]:g}")
    return ("this run asked the camera for " + (" and ".join(asked) or "manual settings")
            + ", and the camera did not take "
            + ("them" if len(asked) > 1 else "it") + ": "
            + ("; ".join(str(r) for r in refused) or "no control answered")
            + ". " + (f"It reports {', '.join(got)}. " if got else "")
            + (f"This camera offers {', '.join(ranges)}. " if ranges else "")
            + "Nothing was measured and nothing was written — a run that "
              "reported the numbers it asked for while measuring under "
              "whatever the camera chose instead would be worse than no run. "
              "Ask for a value inside this camera's own range, or run without "
              "the manual levers (the default is still: let the exposure "
              "settle on the scene, then freeze it).")


#: THE LEVER SELF-TEST'S OWN VERDICT WORDS. Named here, beside every other
#: expected condition, so the self-test, the run that refuses on it and the
#: page that shows it cannot describe the same measurement three ways.
LEVER_OK = "ok"
LEVER_NO_SIGNAL = "no_signal"
LEVER_NO_RESPONSE = "no_response"
LEVER_DRIFT = "drift"
LEVER_UNPROVABLE = "unprovable"
LEVER_UNPROVEN = "unproven"
#: The verdicts that stop a calibration-grade run, and every one of them is
#: a MEASUREMENT. The two that do NOT are deliberate: "we could not check"
#: is not "we checked and it is broken" — the same distinction `night_exit`
#: draws between DARK and UNKNOWN, and `witness` between contaminated and
#: witness_unavailable. Refusing on a check we could not make would invent
#: a fault.
#:
#: A CAMERA THAT WOULD NOT TAKE THE TEST'S OWN COMMANDS is `unprovable`,
#: not a refusal, and deliberately so: the run may not have asked for that
#: lever at all, and its own `camera_refusal` gate still stops it by name
#: if it did.
LEVER_REFUSING = (LEVER_NO_SIGNAL, LEVER_NO_RESPONSE, LEVER_DRIFT)


def lever_not_connected(verdict: dict) -> str:
    """THE SETTING IS NOT THE LIGHT — the sentence for a camera that took
    its exposure control and did nothing with it.

    THE LIVE FAILURE THIS EXISTS FOR (2026-09-01, the browser path): three
    integration times were commanded — 10 ms, 60 ms and 200 ms, a factor of
    twenty end to end — and the driver echoed every one of them back
    without complaint while the measured light stayed flat at the noise
    floor (footprint weights 0.0, 0.0014 and 0.0051, against the
    `light_field.UNSEEN_WEIGHT` of 1.0 an emitter must clear to count as
    seen at all). Every read-back said yes. Nothing about the light did. An
    evening of calibration went into a camera that was measuring its own
    mood.

    So the refusal quotes BOTH measurements and both commands, and says
    what it means in plain words: a run through this camera would not be
    measuring the room."""
    a, b = _lever_pair(verdict)
    kind = verdict.get("verdict")
    head = (f"the camera's exposure control is not reaching the sensor. "
            if kind == LEVER_NO_RESPONSE else
            f"the camera measured no usable light at either commanded "
            f"exposure. " if kind == LEVER_NO_SIGNAL else
            f"the camera's sensitivity moved between two IDENTICAL "
            f"commanded settings. ")
    return (
        head
        + f"Commanded {a} and measured {_lever_weight(verdict, 0)}; "
          f"commanded {b} and measured {_lever_weight(verdict, 1)}"
        + (f"; commanded {b} again and measured "
           f"{_lever_weight(verdict, 2)}" if len(verdict.get('readings') or []) > 2
           else "")
        + ". "
        + ("A sensor that obeys its own integration time puts more light in "
           "the frame when it is given more time; this one did not, so what "
           "a calibration through it measured would be the camera's mood, "
           "not the room. Nothing was written."
           if kind in (LEVER_NO_RESPONSE, LEVER_DRIFT) else
           "Either this pose sees none of that emitter's light, or the "
           "exposure control is doing nothing — and either way a "
           "calibration taken through it would measure nothing. Check the "
           "aim first, then the camera. Nothing was written."
           if kind == LEVER_NO_SIGNAL else
           "The driver refused the commanded controls, so there is no "
           "regime to measure in. Nothing was written.")
        + " (spectra/services/lever_selftest.py; the driver's own read-back "
          "passed — this is the measurement it cannot make.)")


def _lever_pair(verdict: dict) -> tuple[str, str]:
    readings = verdict.get("readings") or []
    words = []
    for i in (0, 1):
        if i < len(readings):
            e = readings[i].get("exposure_time")
            words.append(f"an integration time of {e} (x100 us, "
                         f"{(e or 0) * 1e-4:.4g}s)" if e is not None
                         else "the camera's own converged exposure")
        else:
            words.append("nothing")
    return words[0], words[1]


def _lever_weight(verdict: dict, index: int) -> str:
    readings = verdict.get("readings") or []
    if index >= len(readings):
        return "nothing"
    r = readings[index]
    if not r.get("ok"):
        return f"no reading ({r.get('reason') or 'unknown'})"
    # The floor rides on the verdict rather than being imported, so the
    # sentence quotes the number the test actually judged against.
    floor = float(verdict.get("signal_floor") or 0.0)
    w = float(r.get("weight") or 0.0)
    return (f"{w:.3f} ({'above' if w >= floor else 'below'} the {floor:g} an "
            f"emitter must clear to count as seen)")


def exposure_too_long(exposure_s: float, fps: float, min_frames: int,
                      max_capture_s: float) -> str:
    """The requested integration time is so long that even the longest
    capture window cannot average `min_frames`.

    A sensor integrating for E seconds delivers at most 1/E frames a
    second — no tap rate or window length changes that — so past a point
    the honest answer is that this exposure and this protocol cannot both
    happen. Refused BEFORE the room goes dark, in the shape
    `too_long_refusal` already keeps: name the measurement, name the bound,
    hand the choice back."""
    return (f"an integration time of {exposure_s:.3g}s gives at most "
            f"{fps:.2f} frames a second, so averaging the {min_frames} "
            f"frames a capture needs would take longer than the "
            f"{max_capture_s:g}s a single capture window is allowed. Nothing "
            f"was written. Ask for a shorter integration time, or raise the "
            f"gain instead — it costs noise rather than frames.")


def ambient_drift(track: dict, *, target_label: str = "",
                  stage: str = "", signature: Optional[dict] = None) -> str:
    """THE LIGHT IN THE ROOM CHANGED WHILE THE READING WAS BEING TAKEN.

    THE LIVE FAILURE THIS EXISTS FOR (2026-09-01, his first per-fixture
    run): the phone was pointed at the right sconce with A WINDOW IN VIEW,
    in daylight, with cloud moving. The pose was fine — the resolution gate
    passed honestly at 5.375 camera pixels per index. The decode still came
    back 34 of 88, 22 of those in the wrong order, and 30 camera pixels
    decoded confidently to indices that do not exist. Cloud changed the
    daylight BETWEEN a pattern and its inverse, and lit-minus-dark cannot
    subtract a reference that moved underneath it. The frozen table read
    that as an instrument-indicted fail, which is true and useless: it
    needs somebody to remember today to know it meant the window.

    SO IT IS SAID IN HIS OWN NOUNS. Not "ambient instability" — the window,
    the shots, and the three things he can actually do about it: shade it,
    frame it out of view, or wait until dark. The measured drift and the
    bound travel with the sentence so the boundary is inspectable rather
    than a number buried in a module.

    IT SAYS WHERE IT STOPPED, because that is the difference between a run
    that spent his room's dark time and one that did not: the gate refuses
    on the first capture that breaks the bound, not at the end.

    `signature` is the cheap cross-check
    (`gray_code.confident_wrong_signature`) when a whole stack happens to
    exist at the moment of refusal — the decode's own out-of-range pixels
    CONFIRMING that two different scenes were compared. It is a
    confirmation of a refusal that already stands on its own measurement,
    never the thing the refusal rests on, and it is simply absent when the
    gate refused early — which is the normal, cheaper case."""
    worst = (track or {}).get("worst") or {}
    bound = float((track or {}).get("bound") or 0.0)
    drift = float((track or {}).get("max_drift") or 0.0)
    peak = float((track or {}).get("peak") or 0.0)
    what = f"{target_label} " if target_label else ""
    where = stage or str(worst.get("label") or "")
    kind = str(worst.get("kind") or "")
    tile = str(worst.get("worst_tile") or "")

    if kind.startswith("pair"):
        between = (f"between one pattern and its opposite "
                   f"({worst.get('pair_label') or 'the pair before it'} and "
                   f"{where})")
    else:
        between = f"between the first shot of the stack and {where or 'a later shot'}"
    corner = (f", strongest in one corner of the frame (tile {tile})"
              if kind.endswith("regional") and tile else "")

    lines = [
        f"THE LIGHT IN THE ROOM CHANGED WHILE {('THE ' + target_label.upper()) if target_label else 'THIS'} "
        f"WAS BEING READ, so this run stopped rather than measuring the "
        f"weather. Something in frame that is not {what or 'the fixture'}"
        f" — a window is the usual one — moved by {drift:.1f} grey levels "
        f"{between}{corner}, where this reading can only survive {bound:.1f} "
        f"(a tenth of the {peak:.1f} the fixture itself is worth in this "
        f"frame). Every pixel is read as the difference between a shot and "
        f"its opposite, so light that changes between the two shots is "
        f"counted as the fixture and the answer comes back confident and "
        f"wrong.",
        "Shade the window, point the phone so the window is out of frame, "
        "or wait until it is dark outside — then press Commission again. "
        "Nothing was written and no result was judged.",
    ]
    if signature and signature.get("present"):
        lines.append(
            f"The shots already taken say the same thing on their own: "
            f"{signature.get('out_of_range_pixels')} camera pixels decoded "
            f"confidently to positions this fixture does not have, which "
            f"only happens when two shots were of different scenes.")
    return " ".join(lines)


def capture_refusal(emitter_label: str, exc: BaseException) -> str:
    """One emitter's own failure, named with what it was measuring. An
    ownership loss is NOT routed here — that ends the run (MID_RUN_LOSS);
    this is for the fixture that stopped answering while its neighbours are
    still fine, which is why the run carries on past it.

    A SCONCE GETS THE MAINS CHECK FIRST (the Admiral's own order — see
    `witness.SCONCE_MAINS_FIRST_CHECK`): `light.dimmer_kitchen_sconce` is
    the kitchen sconces' mains supply and it is a switch, so at 0% both
    sconces are simply dead — indistinguishable from a dead controller or a
    lost network from anywhere inside this app, and an hour gone if it is
    not the first thing checked. FIRST is the whole point: a line buried
    under three paragraphs about networks is the hour this exists to save."""
    from spectra.services import witness
    said = (f"{emitter_label} could not be measured ({type(exc).__name__}: "
            f"{exc}). The rest of the run carried on — check that fixture is "
            f"powered and reachable, then map it again on its own.")
    return witness.sconce_diagnostic(
        said, sconce_involved=witness.mentions_sconce(emitter_label))


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


# ── THE UNATTENDED PATH ────────────────────────────────────────────────────
#
# A capture run used to need a person at every step: open the page, grant
# the camera, wait for the lock, aim, press. The unattended client
# (spectra/capture_client/) and the queue runner
# (spectra/services/capture_queue.py) remove the middle of that, and they
# introduce conditions of their own. Each gets a sentence HERE, for the same
# reason every other one on this path does: a queue that runs while nobody
# is watching is read afterwards, from a log, by someone who was asleep —
# so "item 3 failed" is useless and the sentence has to carry the whole
# story on its own.

#: What refuses a run when nothing is holding a camera on the room. It names
#: BOTH ways in, because since the unattended client there are two, and a
#: sentence that names only the phone would send him to the wrong machine.
#: The words "no phone connected" are kept deliberately: they are what this
#: condition has always said, and the proofs that read it still read it.
NO_SESSION = (
    "no capture session — no phone connected and no capture client running. "
    "Open the Rooms page on a phone and start its camera, or start the "
    "unattended capture client on a machine that has one "
    "(python -m spectra.capture_client).")


def no_camera(detail: str, host: str = "") -> str:
    """The capture MACHINE has no usable camera — refused before a single
    frame, and before the room is asked to go dark for it.

    Reached from the client's own start-up and reported over the session, so
    it lands on the same surface every other refusal here does: the client
    connects and says what is wrong rather than dying silently on a laptop
    nobody is looking at. A run then refuses with the camera's own reason
    instead of the generic "not locked yet"."""
    where = f" on {host}" if host else ""
    return (f"the capture client{where} could not open a camera: {detail}. "
            f"Nothing was measured and nothing was written. Check the camera "
            f"is plugged in, that no other program is holding it, and that "
            f"this machine's user may read it, then start the client again.")


def session_lost(waited_s: float, *, ever_connected: bool) -> str:
    """The queue asked for a capture session and did not get one — either it
    never arrived, or it went away and did not come back inside the wait.

    A queue that stops here KEEPS everything it already measured; the
    sentence says so, because an unattended run that stopped half way is a
    real result and a discarded one is not."""
    if ever_connected:
        return (f"the capture session went away and did not come back within "
                f"{waited_s:.0f}s, so the rest of this queue was not run. "
                f"Everything measured before that is kept. Start the capture "
                f"client again and run the remaining items.")
    return (f"no capture session arrived within {waited_s:.0f}s, so nothing "
            f"in this queue was run and nothing was written. Start the "
            f"capture client on the machine with the camera, then start the "
            f"queue again.")


def queue_stopped(remaining: int) -> str:
    """Someone pressed Stop. Not a failure, and the count says exactly how
    much of the declared list never ran."""
    return (f"the capture queue was stopped, so {remaining} remaining "
            f"item{'' if remaining == 1 else 's'} did not run. Everything "
            f"measured before that is kept.")


def pose_changed_note(previous: str, now: str) -> str:
    """A FACT, like `unseen_note` — not a refusal and not a warning about
    anything going wrong.

    The camera was REOPENED part-way through a queue (the client reopens it
    when the capture pipe dies, never for a plain WebSocket drop), so its
    exposure was re-locked and its byte scale is its own again. Footprints
    from either side of this line are each internally comparable and are NOT
    comparable across it. The queue says so rather than leaving a map that
    looks like one measurement and is two."""
    return (f"the camera was reopened during this queue (pose {previous} -> "
            f"{now}), so its exposure was locked again and its brightness "
            f"scale starts over. Footprints measured before this point and "
            f"after it are each comparable among themselves, but not with "
            f"each other — re-map anything you want to compare across it in "
            f"one pass.")
# ── THE NIGHT RUN ──────────────────────────────────────────────────────────
#
# Home Assistant pushes one event when his `Sleeping` helper has been on for
# thirty continuous minutes, and one the moment it goes off or he touches a
# light (spectra/services/night_run.py). Nobody is awake for any of it, so
# the same rule as the queue above applies twice over: the record IS the
# run, and a night that did not happen has to say why in a sentence a person
# reads at breakfast.


def night_not_owned(owner: str) -> str:
    """THE BOUNDARY, and it is the whole reason this seam is safe to give a
    key to: a start event arriving while SPECTRA does not hold the room is
    DECLINED. It does not take the room, ask for it, or queue itself behind
    a handover.

    The Admiral's word, embedded on the order: the night trigger gets NO
    room-take exception, ever — "it does not help itself to his room while
    he sleeps. That boundary is worth more than an occasional missed
    night." Taking the room back is a human act; a machine that could do it
    at 1am on a schedule is a machine that can wake him up.

    A DECLINE IS A NORMAL RECORDED OUTCOME, not an error, which is why this
    reads as a statement of fact rather than an apology or an instruction to
    go and fix something."""
    where = {
        "released": "released (his lights are Home Assistant's right now)",
        "spot-effects": "held by the older SpotFX process",
        "handing-over": "changing hands right now",
    }.get(owner, f"held by {owner!r}")
    return (f"The night run declined: SPECTRA does not hold the lights — "
            f"they are {where}. Nothing was measured, nothing was turned on "
            f"and nothing about the room was touched. This trigger never "
            f"takes the room; take it back on the ownership bar when you "
            f"want tonight's queue to run.")


NO_DECLARED_NIGHT_QUEUE = (
    "The night run declined: no night queue has been declared. Nothing was "
    "measured and nothing about the room was touched. Declare the list of "
    "runs you want the night to work through (PUT /api/night-run/queue, the "
    "same items the capture queue takes), and the next sleep window will "
    "run it.")


def night_already_running(run_id: str) -> str:
    """A second start event while a night is already in flight. Fire-and-
    forget from HA means a duplicate is entirely possible and is not a
    fault; it is also not a reason to start a second run over the top of the
    first."""
    return (f"The night run declined: night {run_id} is already running, so "
            f"this start event was recorded and otherwise ignored. Nothing "
            f"about the room was touched.")


#: The event name Home Assistant sends when his ~05:50 morning routine runs.
#: NOT a synonym for the others — see `night_ended_by_morning`.
MORNING_ROUTINE = "morning-routine"


def night_ended_by_morning() -> str:
    """AN ORDINARY ENDING, and the one place in this file where saying so
    plainly is the whole job.

    His Home Assistant morning routine starts around 05:50 every day and
    will end any overnight run whether or not this side had a dawn line of
    its own — it is what stopped SPECTRA at 05:50 on 2026-09-01 with nobody
    pressing anything. That is a PLANNED end, not an interruption and not a
    fault: a night that ran until his morning ran exactly as long as it was
    ever going to.

    IT IS DELIBERATELY A DIFFERENT SENTENCE AND A DIFFERENT RECORDED STATE
    from `night_aborted`. Waking up early and reaching for a light says
    something about the run (it disturbed him, or he needed the room);
    the morning arriving says nothing at all. Folding them together would
    make every ordinary night read as an incident, which is how a record
    stops being read."""
    return ("The night run ended with his morning routine, which is where "
            "every night ends: measuring stopped at the piece in flight, the "
            "room was handed straight back, and everything measured is kept. "
            "This is an ordinary ending, not an interruption.")


def night_will_not_fit(estimate_s: float, window_s: float,
                       planned_end: str) -> str:
    """THE HARD PLANNED END, refused BEFORE the room goes dark.

    His Home Assistant morning routine runs the flag at 05:30 house time and
    the BLINDS OPEN around 05:40 — daylight into the frame, which is a
    capture contaminant, not merely an interruption. So 05:30 is a bound, not
    a preference: a run that cannot finish before it must not start, and an
    item that cannot finish before it must not be started either.

    THE SHAPE OF THE ANSWER, `too_long_refusal`'s own discipline: name the
    cost, name the bound, hand the choice back. It never quietly drops items
    to make the night fit — WHICH runs happen is his declaration, and a
    surprising subset is a decision, not an error."""
    return (f"The night run declined: the declared queue needs about "
            f"{estimate_s / 60:.0f} minutes and there are only about "
            f"{max(0.0, window_s) / 60:.0f} left before {planned_end}, when "
            f"his morning routine runs and the blinds open — daylight in the "
            f"frame is a contaminant, so nothing is scheduled past it. "
            f"Nothing was measured and nothing about the room was touched. "
            f"Declare a shorter queue, or start it earlier.")


def night_item_will_not_fit(name: str, estimate_s: float, window_s: float,
                            planned_end: str, remaining: int) -> str:
    """One item that cannot finish before his morning. The queue stops here
    rather than starting something that would run into daylight; everything
    already measured is kept."""
    return (f"'{name}' needs about {estimate_s / 60:.0f} minutes and only "
            f"about {max(0.0, window_s) / 60:.0f} remain before "
            f"{planned_end} (his morning routine, and the blinds open just "
            f"after), so it was not started — nor were the "
            f"{max(0, remaining - 1)} item(s) after it. Everything measured "
            f"tonight is kept.")


def night_aborted(source: str) -> str:
    """A FACT, like `unseen_note` — not a refusal and not a failure.

    A touched house is his house: `Sleeping` went off, or he reached for a
    light. Everything measured so far is KEPT, which is what makes stopping
    the moment he stirs cheap enough to do without hesitating.

    The morning routine is NOT routed here — it has its own sentence and its
    own recorded state (`night_ended_by_morning`), because an ordinary
    ending and an interruption are different facts."""
    why = {
        "sleep-ended": "the sleep window ended",
        "light-touched": "a light was touched in the house",
    }.get(source, f"Home Assistant said so ({source})")
    return (f"The night run stopped because {why}. Measuring stopped at the "
            f"piece in flight, the room was handed straight back, and "
            f"everything measured up to that point is kept.")
