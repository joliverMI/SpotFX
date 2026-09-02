"""RUNNING A CALIBRATION — the pose check, then the declared queue, then one
append-only entry in the lineage.

READ FIRST: `spectra/models/calibration.py` (what a calibration is) and
`spectra/services/pose_fingerprint.py` (what the pose check can and cannot
tell apart). This module is the ORCHESTRATION and holds no opinion of its
own about either.

IT ACQUIRES NOTHING. Every light this drives is driven through
`spectra/services/capture_runs.py` — the one seam — so the exposure lock,
the lever self-test, the ownership refusal, the hold ceiling and the
one-run-at-a-time lock all apply exactly as they do to a button press, and
a gate added there is added here for free. There is no calibration mode
anywhere in this codebase that a run behaves differently under, and the
declared items are validated by `capture_queue.parse_items` — the ONE
validator — rather than by a second dialect that reads almost the same.

THE NEVER-TAKES-HIS-ROOM BOUNDARY IS UNMOVED. Nothing here asks for the
room, waits for a handover, or behaves differently when nobody is awake: a
calibration run happens only when SPECTRA already holds the lights, exactly
like every capture run today, and when it does not the run is REFUSED with
`mapping_refusals`' own sentence and the refusal is recorded. No piece of
this design needed an exception to that, which is worth saying explicitly
because the brief asked to be told if one did.

WHAT STOPS A RUN, and it is exactly one thing: a MEASURED CAMERA MOVE
(`mapping_refusals.POSE_REFUSING`). The plan is explicit that a moved camera
must be a named refusal rather than silently incomparable data. Everything
else — a changed room, an inconclusive fingerprint, a pose with too few
anchors to discriminate — RUNS, and what is withheld is the COMPARABILITY
CLAIM, recorded on the entry as `comparable=False` with the reason. The
captain's requirement is the reason for that split, verbatim: "a calibration
refusing because he moved a chair is a system that expires for reasons he
cannot see."

AN EXPLICIT PRESS STILL WINS AND NAMES THE CONTRADICTION. `force=True` runs
past a measured camera move and records `overrode_camera_moved` on the
entry — the Force Scene precedent this codebase already uses everywhere a
human deliberately overrides a gate. It never re-anchors the pose as a side
effect: moving the pose is its own act (`establish_pose`), because a
silently re-anchored pose would erase the very thing that noticed.

THE LINEAGE IS APPEND-ONLY AND A REFUSED RUN IS AN ENTRY. `night_run`
records a declined night and `commissioning` stores a refused pass for the
same reason: "did it run?" must be a read, never a silence
indistinguishable from the seam being broken.

AMENDING IN PART is `run_amendment`, and it is the SAME function body with
a smaller declaration: the same pose check, the same queue machinery, the
same one lineage entry. What it adds is ONE gate, and only when it would
leave a carrier holding footprints from two different nights —
`spectra/services/amendment.py` is the binding statement for it. Nothing
about an amendment softens a gate a full run applies; it narrows what is
measured, and it supersedes exactly what it measured.

AN AMENDMENT THAT DOES NOT FINISH APPLIES NOTHING (`_land_unapplied`, the
Admiral's ruling of 2026-09-01). Its measurements stay in the lineage and
the room map is put back exactly as it was, because a half-measured carrier
would leave his room holding neither the old calibration nor the new one but
a mixture assembled by wherever the run stopped. A cut-short FULL RUN is
unchanged and still keeps its partials — `spectra/services/amendment.py`
carries both halves of that reasoning.

THE NIGHT RUNS THIS FUNCTION, not a copy of it. `run_calibration` and
`run_amendment` take `capture_queue.run_queue`'s own `guard` and `save`
seams and pass them straight through, so an unattended night gets the hard
05:30 planned-end bound per item and a record written after each one,
without a night-only path that could drift from what a button press does.
Both default to None; there is no night mode anywhere below this line.

EDITING THE DECLARATION IS APPEND-ONLY TOO. `record_declaration_change`
keeps the WHOLE PRIOR DECLARATION on its entry, so what run 3 asked for is
recoverable after run 4 asked for something else — the declaration on the
calibration is the CURRENT one, and the lineage is where the previous ones
live.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from spectra.models.calibration import (Calibration, CalibrationRun,
                                        EmitterMeasurement, ItemOutcomeRecord,
                                        PinnedCamera, PoseFingerprint,
                                        declaration_snapshot)
from spectra.models import calibration as cal_model
from spectra.services import (amendment, calibration_store, capture_queue,
                              capture_runs, light_field, mapping_refusals,
                              pose_fingerprint)

logger = logging.getLogger(__name__)

#: THE ENTRY KINDS live on the model, which is what every reader outside
#: this module imports. Re-exported here because this module's own callers
#: have always read them from it.
KIND_RUN = cal_model.KIND_RUN
KIND_AMENDMENT = cal_model.KIND_AMENDMENT
KIND_FINGERPRINT = cal_model.KIND_FINGERPRINT
KIND_DECLARATION = cal_model.KIND_DECLARATION

#: How long a calibration run waits for a present, LOCKED camera session
#: before giving up — `capture_queue.wait_for_session`'s own wait, through
#: that module's own function, because a calibration started from a cron
#: line has the same "start the queue, then start the client" shape a plain
#: queue does and must not be the one path with a different answer.
SESSION_WAIT_S = capture_queue.DEFAULT_SESSION_WAIT_S


# ── the pose ───────────────────────────────────────────────────────────────

async def establish_pose(cal: Calibration, *, placement: Optional[str] = None,
                         label: str = "") -> tuple[Calibration, CalibrationRun]:
    """TAKE OR RE-ANCHOR THIS CALIBRATION'S POSE: drive the room's carriers,
    measure where each one's light lands, keep the best-spread few as
    anchors, and record whether this anchor set can tell a moved camera from
    a changed room.

    RE-ANCHORING IS A DELIBERATE ACT and never a side effect of a run: it
    starts a NEW comparable series, so doing it automatically after a camera
    move would erase the very thing that noticed. The previous pose is not
    edited — the fingerprint is replaced and the lineage keeps the entry that
    took the old one, which is what makes "when did this pose change" a
    read."""
    entry = CalibrationRun(kind=KIND_FINGERPRINT, label=label)
    if placement is not None:
        cal.pose.placement = placement

    room = light_field.get_room(cal.room_id)
    if room is None:
        return _refuse(cal, entry, mapping_refusals.calibration_no_room(
            cal.room_id), "no_room")

    view, waited = await capture_queue.wait_for_session(SESSION_WAIT_S)
    if view is None:
        return _refuse(cal, entry, waited, "session")

    outcome = await capture_runs.run_pose_fingerprint(
        cal.room_id, exposure_time=cal.camera.exposure_time,
        gain=cal.camera.gain, white_balance=cal.camera.white_balance,
        focus=cal.camera.focus)
    entry.session_id = outcome.session_id
    entry.pose_id = outcome.pose_id
    entry.seconds = outcome.seconds
    entry.lever = outcome.lever
    entry.camera = dict(outcome.result.get("camera") or {})
    entry.notes.extend(outcome.result.get("problems") or [])
    entry.notes.extend(outcome.result.get("notes") or [])
    if outcome.status != capture_runs.STATUS_OK:
        return _refuse(cal, entry, outcome.detail,
                       outcome.refusal or "fingerprint")

    measured = [pose_fingerprint.PoseReference(**r)
                for r in outcome.result.get("references") or []]
    anchors = pose_fingerprint.select_anchors(measured)
    if not anchors:
        return _refuse(cal, entry, mapping_refusals.pose_no_anchors(
            "every carrier was driven and the camera saw none of them"),
            "no_anchors")

    ok, note = pose_fingerprint.discriminating(anchors)
    cal.pose = PoseFingerprint(
        camera=dict(outcome.result.get("identity") or {}),
        placement=cal.pose.placement, pose_id=outcome.pose_id,
        references=anchors, spread=round(pose_fingerprint.spread(anchors), 5),
        discriminating=ok, note=note, taken_at=time.time(),
        taken_by_run=entry.id)
    # THE REGIME THAT PROVED ITSELF, kept on the artefact rather than only in
    # one run's log: "these numbers were taken by a camera whose exposure
    # control was MEASURED, not merely read back" is a property of the
    # calibration.
    if outcome.lever:
        cal.lever = outcome.lever
    entry.status = capture_runs.STATUS_OK
    entry.fingerprint = {"verdict": mapping_refusals.POSE_MATCH,
                         "established": True,
                         "anchors": [a.emitter_id for a in anchors],
                         "measured": len(measured),
                         "anchor_spread": cal.pose.spread,
                         "discriminating": ok, "note": note}
    entry.detail = _established_sentence(cal.pose, len(measured))
    if note:
        entry.notes.append(note)
    cal.append_run(entry)
    return calibration_store.save(cal), entry


def _established_sentence(pose: PoseFingerprint, measured: int) -> str:
    where = f" at {pose.placement}" if pose.placement else ""
    kept = len(pose.references)
    return (f"Pose recorded{where}: {measured} fixture"
            f"{'' if measured == 1 else 's'} driven, the "
            f"{kept} best-spread kept as reference"
            f"{'' if kept == 1 else 's'} "
            f"({', '.join(r.label or r.emitter_id for r in pose.references)}). "
            + ("From here on this calibration can tell a moved camera from a "
               "changed room." if pose.discriminating
               else "This pose can notice that something changed and cannot "
                    "say which — see the note."))


async def check_pose(cal: Calibration) -> tuple[pose_fingerprint.Judgement,
                                                capture_runs.RunOutcome | None]:
    """Is the camera where it was? Drives only this pose's recorded anchors.

    A DIFFERENT CAMERA SHORT-CIRCUITS BEFORE ANY LIGHT: a different capture
    machine or device is a different pose by definition and by arithmetic (a
    footprint is `lit - dark` in one camera's own byte scale), so there is
    nothing to learn from twenty seconds of his dark room."""
    if not cal.pose.established:
        judgement = pose_fingerprint.Judgement(
            verdict=mapping_refusals.POSE_UNESTABLISHED)
        judgement.reason = mapping_refusals.pose_verdict_sentence(
            judgement.as_dict())
        return judgement, None

    view = capture_runs.session_view()
    identity = pose_fingerprint.identity_from_hello(view.get("client") or {})
    note = pose_fingerprint.identity_changed(cal.pose.camera, identity)
    if note:
        return pose_fingerprint.judge(cal.pose.references, [],
                                      identity_note=note), None

    outcome = await capture_runs.run_pose_fingerprint(
        cal.room_id,
        emitter_ids=[r.emitter_id for r in cal.pose.references],
        exposure_time=cal.camera.exposure_time, gain=cal.camera.gain,
        white_balance=cal.camera.white_balance, focus=cal.camera.focus)
    if outcome.status != capture_runs.STATUS_OK:
        # THE CHECK ITSELF COULD NOT BE MADE. That is not a finding about the
        # camera or the room — the same distinction `lever_selftest` draws
        # between `unproven` and a measurement — so it is `cannot_tell` and
        # the run's own gate (ownership, the lock, the lever) refuses on its
        # own better sentence if it is going to.
        judgement = pose_fingerprint.Judgement(
            verdict=mapping_refusals.POSE_CANNOT_TELL,
            why=outcome.detail or "the pose check could not be taken",
            problems=list(outcome.result.get("problems") or []))
        judgement.reason = mapping_refusals.pose_verdict_sentence(
            judgement.as_dict())
        return judgement, outcome

    observed = [pose_fingerprint.PoseReference(**r)
                for r in outcome.result.get("references") or []]
    return pose_fingerprint.judge(
        cal.pose.references, observed,
        problems=list(outcome.result.get("problems") or [])), outcome


# ── the run ────────────────────────────────────────────────────────────────

async def run_calibration(cal: Calibration, *, force: bool = False,
                          label: str = "", guard=None, save=None
                          ) -> tuple[Calibration, CalibrationRun]:
    """Check the pose, run the WHOLE declared queue, append one lineage
    entry.

    Returns the SAVED calibration and the entry, in every path including
    every refusal — a refused run is a fact about the evening and the
    record is what a person reads afterwards.

    `guard` and `save` are `capture_queue.run_queue`'s own two seams, passed
    straight through and defaulting to None so a button press behaves
    exactly as it did before they existed. THEY ARE NOT A CALIBRATION MODE
    and cannot soften anything: `guard` is a per-item VETO (the night's hard
    05:30 planned-end bound — spectra/services/night_run.py), and `save` is
    where the queue's record is written after each item, which is how an
    unattended night's own record stays in step with the queue's. Both are
    the night seam's, and they exist here rather than in a night-only copy
    of this function so that a calibration run at 2am is the same run as a
    calibration run at 2pm."""
    entry = CalibrationRun(kind=KIND_RUN, label=label)
    if not cal.items:
        return _refuse(cal, entry,
                       mapping_refusals.calibration_nothing_declared(),
                       "nothing_declared")
    return await _run_declared(cal, entry, [dict(i) for i in cal.items],
                               force=force, label=label, guard=guard,
                               save=save)


async def run_amendment(cal: Calibration, names: list[str], *,
                        overrides: Optional[dict] = None,
                        whole_carrier: bool = False, force: bool = False,
                        label: str = "", guard=None, save=None
                        ) -> tuple[Calibration, CalibrationRun]:
    """AMEND IN PART: re-measure a NAMED SUBSET of the declaration, under
    this calibration's own pose check and its own pinned settings, and
    append one entry that supersedes exactly what it measured.

    `spectra/services/amendment.py` is the binding statement for the one
    gate this adds — whether the amended footprints may sit beside the ones
    it leaves in place. Everything else is `run_calibration`'s own body,
    deliberately: an amendment must not be able to acquire, soften or skip
    anything a full run applies.

    `overrides` changes CAPTURE PARAMETERS for this run only (a granularity,
    a settle time, a scope) and never what the calibration declares —
    changing that is an edit, which is its own lineage entry. `whole_carrier`
    drops the named emitter scoping so the amendment re-takes each carrier
    whole; it is the named way past the mixing gate, and it is a wider
    measurement rather than a weaker check.

    `force` runs past a MEASURED CAMERA MOVE exactly as it does for a full
    run, and NEVER past the mixing gate — a forced full run costs a
    comparability claim the record then names, where a forced mix would
    leave one carrier's own footprints disagreeing with each other with
    nothing downstream able to tell."""
    entry = CalibrationRun(kind=KIND_AMENDMENT, label=label,
                           amended=[str(n) for n in (names or [])])
    if not cal.items:
        return _refuse(cal, entry,
                       mapping_refusals.calibration_nothing_declared(),
                       "nothing_declared")
    subset = amendment.resolve_subset(cal, list(names or []), overrides,
                                      whole_carrier=whole_carrier)
    if subset.refusal:
        return _refuse(cal, entry, subset.refusal, "amendment")
    entry.amended = list(subset.names)
    return await _run_declared(cal, entry, subset.items, force=force,
                               label=label, mix_gate=True, guard=guard,
                               save=save)


async def _run_declared(cal: Calibration, entry: CalibrationRun,
                        declared: list[dict], *, force: bool, label: str,
                        mix_gate: bool = False, guard=None, save=None
                        ) -> tuple[Calibration, CalibrationRun]:
    """THE ONE BODY a full run and an amendment share. The only difference
    between them is WHAT WAS DECLARED and, for an amendment, the one extra
    gate — so a gate added here is added to both, which is the same
    discipline `capture_runs` keeps one level down."""
    entry.declared = [dict(i) for i in declared]

    room = light_field.get_room(cal.room_id)
    if room is None:
        return _refuse(cal, entry, mapping_refusals.calibration_no_room(
            cal.room_id), "no_room")
    if not declared:
        return _refuse(cal, entry,
                       mapping_refusals.calibration_nothing_declared(),
                       "nothing_declared")
    try:
        items = capture_queue.parse_items(declared)
    except ValueError as exc:
        return _refuse(cal, entry, str(exc), "declaration")
    if capture_queue.running():
        live = capture_queue.current
        return _refuse(cal, entry, mapping_refusals.calibration_already_running(
            (live.label or live.id) if live is not None else "one"), "busy")

    view, waited = await capture_queue.wait_for_session(SESSION_WAIT_S)
    if view is None:
        return _refuse(cal, entry, waited, "session")
    entry.session_id = view.get("session_id") or ""
    entry.pose_id = view.get("pose_id") or ""

    # THE POSE COMES FIRST, always: a run appended to a lineage that claims
    # one pose has to know whether it still is one before it spends the
    # room's dark time on twelve items.
    #
    # A CALIBRATION WITH NO POSE YET TAKES ONE HERE, as its own lineage
    # entry, and then runs. Doing it in the same press is what makes a
    # calibration one act rather than two — and it is the honest cost of the
    # first run only: from here on a re-run drives the anchors alone.
    # Nothing is COMPARED on that first pass, because there is nothing to
    # compare against, and the entry says exactly that rather than claiming
    # a match it did not measure.
    if not cal.pose.established:
        cal, pose_entry = await establish_pose(cal, label=label)
        entry.notes.append(pose_entry.detail)
        if pose_entry.lever:
            entry.lever = pose_entry.lever
        judgement = pose_fingerprint.Judgement(
            verdict=mapping_refusals.POSE_UNESTABLISHED)
        judgement.reason = mapping_refusals.pose_verdict_sentence(
            judgement.as_dict())
        fp_outcome = None
    else:
        judgement, fp_outcome = await check_pose(cal)
    entry.fingerprint = judgement.as_dict()
    if fp_outcome is not None and fp_outcome.lever:
        entry.lever = fp_outcome.lever
    if judgement.refuses and not force:
        return _refuse(cal, entry, judgement.reason, "pose")
    if judgement.refuses:
        # AN EXPLICIT PRESS WINS AND NAMES THE CONTRADICTION — Force Scene's
        # own precedent. The pose is NOT re-anchored as a side effect.
        entry.notes.append(
            "overrode_camera_moved: this run was started deliberately after "
            "the pose check said the camera had moved. Its footprints are "
            "not comparable with the ones this calibration already holds — "
            "re-anchor the pose to start a new comparable series.")

    # THE MIXING GATE, and it is asked AFTER the pose check and BEFORE the
    # room goes dark: it needs the pose verdict, and an amendment that was
    # always going to refuse must cost nothing but the pose check itself.
    # `force` never reaches it — see `run_amendment`'s docstring.
    if mix_gate:
        # Read the room back: `establish_pose` above may have run since the
        # copy at the top was taken, and the gate reasons about what is
        # stored right now.
        room = light_field.get_room(cal.room_id) or room
        mix = amendment.judge_mix(cal, room, declared, judgement.verdict)
        entry.mix = mix.as_dict()
        if mix.refusal:
            return _refuse(cal, entry, mix.refusal, "would_mix")
        if mix.mixes:
            entry.mixed_carriers = mix.carriers
            entry.notes.append(mix.note)

    # THE ROLLBACK, taken before the first light and used only when an
    # AMENDMENT does not finish. `spectra/services/amendment.py` is the
    # binding statement; the short of it is the Admiral's ruling, that a
    # half-measured carrier would leave his room holding neither the old
    # calibration nor the new one, assembled by wherever the run stopped.
    # A FULL RUN TAKES NONE — it keeps its partials, as every run in this
    # codebase has always promised to.
    rollback = amendment.Rollback.take(room) if mix_gate else None

    started = time.time()
    queue_run = capture_queue.new_run(items, label=label or cal.name)
    entry.queue_run_id = queue_run.id
    await capture_queue.run_queue(items, label=label or cal.name,
                                  run=queue_run, guard=guard, save=save)
    entry.seconds = time.time() - started
    entry.items = [_item_record(o) for o in queue_run.outcomes]
    entry.status = _run_status(queue_run)
    entry.detail = _run_detail(queue_run, entry.status)
    entry.refusal = _run_refusal(queue_run, entry.status)
    entry.notes.extend(queue_run.notes)
    entry.notes.extend(_item_sentences(queue_run))
    entry.camera = _camera_record(cal, queue_run)
    # WHAT THE RUN ITSELF REPORTED ABOUT MIXING, which is the authority: the
    # gate predicts from stored data, `room_mapping.scope_plan` knows what
    # the plan actually produced.
    for outcome in queue_run.outcomes:
        for carrier_id in ((outcome.run or {}).get("mixed_carriers") or []):
            if carrier_id not in entry.mixed_carriers:
                entry.mixed_carriers.append(carrier_id)
    # The lever verdict of whichever item earned one — every item of one run
    # shares a session, so they share the verdict too (it is cached on the
    # session by fingerprint). The pose check usually earns it first, which
    # is why this only fills a gap.
    if not entry.lever:
        entry.lever = _first_lever(queue_run)

    # SUPERSESSION IS PER EMITTER. `entry.emitters` is exactly what this
    # entry measured — an amendment's three ranges, not its carrier's
    # twenty — so an emitter this run did not touch keeps the entry that
    # took it as its origin, and provenance keeps saying so.
    #
    # UNLESS IT LANDED UNAPPLIED, in which case it superseded NOTHING and
    # says so — see `_land_unapplied`.
    if rollback is not None and entry.status != capture_runs.STATUS_OK:
        _land_unapplied(cal, entry, rollback, queue_run)
    origin = cal.emitter_origin()
    entry.superseded = ({} if not entry.applied
                        else {e: origin[e] for e in entry.emitters
                              if e in origin})
    entry.comparable, entry.comparable_note = _comparability(
        cal, entry, judgement)
    cal.append_run(entry)
    return calibration_store.save(cal), entry


def _land_unapplied(cal: Calibration, entry: CalibrationRun,
                    rollback: "amendment.Rollback", queue_run) -> None:
    """AN AMENDMENT THAT DID NOT FINISH APPLIES NOTHING.

    The Admiral's ruling, 2026-09-01, and `spectra/services/amendment.py`
    carries the whole of it. In one sentence: a partial that applies itself
    leaves his lighting neither the old calibration nor the new one but a
    mixture assembled by where the clock fell, and he could not know which
    parts of his room run on which measurement.

    WHAT IS KEPT AND WHAT IS PUT BACK, and the split is the point. KEPT: the
    lineage entry, its per-item outcomes, and every `EmitterMeasurement` row
    the run took — so a diff can still read what it saw, and so a night that
    was cut short can still say what it learned. PUT BACK: the room map,
    footprint for footprint, exactly as it was before the first light.

    A RUN THAT MEASURED NOTHING NEEDS NO ROLLBACK and does not get one — a
    write for its own sake, on a store whose whole value is being the one
    live map, is a risk with nothing on the other side of it.

    IT IS NEVER SILENT. The entry carries `applied=False` and the sentence,
    the note goes on the record, and provenance reports the emitters as
    `unapplied` rather than as superseded or missing."""
    if not entry.emitters:
        return
    # Re-read: the run has been writing through its own loaded copy of the
    # room, so restoring into the stale object the snapshot came from would
    # discard whatever else it legitimately recorded.
    room = light_field.get_room(cal.room_id)
    if room is None:
        # The room went away mid-run. There is nothing to put back and
        # nothing to claim — say so rather than reporting a rollback that
        # did not happen.
        entry.applied = False
        entry.unapplied_reason = mapping_refusals.calibration_no_room(
            cal.room_id)
        entry.notes.append(entry.unapplied_reason)
        return
    result = rollback.apply_to(room)
    light_field.put_room(room)
    entry.applied = False
    entry.unapplied_reason = mapping_refusals.amendment_landed_unapplied(
        entry.amended, len(entry.emitters), _cut_short_reason(queue_run))
    entry.notes.append(entry.unapplied_reason)
    logger.warning(
        "calibration %s: amendment %s was cut short and applied nothing — "
        "%d footprint(s) restored, %d discarded",
        cal.id, entry.id, result["restored"], len(result["discarded"]))


def _cut_short_reason(queue_run) -> str:
    """WHY it stopped, in the run's own words — his morning routine, a lost
    camera, a stopped queue. Named rather than summarised, because "cut
    short" without a reason is the log entry this whole record exists to
    replace."""
    for outcome in queue_run.outcomes:
        if outcome.status != capture_runs.STATUS_OK and outcome.detail:
            return outcome.detail
    return "It stopped before it had finished."


def _run_status(queue_run) -> str:
    counts = queue_run.counts
    if counts.get(capture_runs.STATUS_OK) and not (
            counts.get(capture_runs.STATUS_PARTIAL)
            or counts.get(capture_runs.STATUS_REFUSED)
            or counts.get(capture_queue.STATUS_NOT_RUN)
            or counts.get(capture_queue.STATUS_STOPPED)):
        return capture_runs.STATUS_OK
    if counts.get(capture_runs.STATUS_OK) or counts.get(
            capture_runs.STATUS_PARTIAL):
        # SOME OF IT LANDED is a third thing, never folded into either of the
        # other two — `capture_runs`' own rule, one level up.
        return capture_runs.STATUS_PARTIAL
    return capture_runs.STATUS_REFUSED


def _item_sentences(queue_run) -> list[str]:
    """The distinct sentences the items themselves produced, in order.

    Kept on the entry because a run's own summary counts outcomes and a
    person reading the lineage months later needs the REASON, not the
    arithmetic — `mapping_refusals`' own wording, never a second one."""
    out: list[str] = []
    for o in queue_run.outcomes:
        if o.detail and o.detail not in out:
            out.append(o.detail)
    return out


def _run_detail(queue_run, status: str) -> str:
    """The entry's own sentence. A run where NOTHING landed must carry the
    reason, not just the count: "1 declared: 1 refused" tells a reader
    nothing they can act on."""
    summary = queue_run.summary
    if status != capture_runs.STATUS_REFUSED:
        return summary
    sentences = _item_sentences(queue_run)
    return f"{summary} — {' '.join(sentences)}" if sentences else summary


def _run_refusal(queue_run, status: str) -> str:
    """WHICH refusal, when every item refused for the same named reason.
    Mixed reasons stay empty rather than picking one — the sentences are all
    on the entry either way."""
    if status != capture_runs.STATUS_REFUSED:
        return ""
    kinds = {o.refusal for o in queue_run.outcomes if o.refusal}
    return kinds.pop() if len(kinds) == 1 else ""


def _item_record(outcome) -> ItemOutcomeRecord:
    run = outcome.run or {}
    return ItemOutcomeRecord(
        index=outcome.index, name=outcome.name, kind=outcome.kind,
        room_id=outcome.room_id, status=outcome.status,
        detail=outcome.detail, refusal=outcome.refusal,
        attempts=outcome.attempts, pose_id=outcome.pose_id,
        seconds=outcome.seconds,
        emitters=[e for e in (run.get("emitter_ids") or []) if e],
        witness=dict(run.get("witness") or {}),
        # WHAT EACH EMITTER ACTUALLY MEASURED, kept on the entry itself: the
        # room map holds only the LATEST footprint, so without this a diff
        # between two of this calibration's own entries would have nothing
        # to read (`spectra/services/calibration_diff.py`).
        measurements=[EmitterMeasurement(**m)
                      for m in (run.get("measurements") or [])
                      if m.get("emitter_id")])


def _first_lever(queue_run) -> dict:
    for o in queue_run.outcomes:
        lever = (o.run or {}).get("lever") or {}
        if lever.get("verdict"):
            return lever
    return {}


def _camera_record(cal: Calibration, queue_run) -> dict:
    """WHAT REGIME THIS RUN WAS MEASURED IN. The declared pinned levers are
    the authority (every item of a calibration run is given them); the frame
    size and the read-back live on each item's own run record, which is
    where an honest downgrade to what the camera actually has belongs."""
    return {"pinned": cal.camera.model_dump(),
            "items": len(queue_run.outcomes)}


def _comparability(cal: Calibration, entry: CalibrationRun,
                   judgement: pose_fingerprint.Judgement) -> tuple[bool, str]:
    """MAY THIS RUN'S NUMBERS BE COMPARED with the earlier runs of this same
    calibration? Two independent gates, and they are reported separately
    because they fail for different reasons:

      1. THE POSE matched (one camera, one place).
      2. THE PINNED REGIME is identical to the one the last run used — a
         footprint is `lit - dark` in a camera's own byte scale, so two
         regimes are two scales and the pose matching perfectly does not
         save them.

    THE FIRST RUN UNDER A POSE IS COMPARABLE by definition: it is the
    baseline of the series, not a run that failed to match anything."""
    previous = cal.last_run
    if judgement.verdict == mapping_refusals.POSE_UNESTABLISHED:
        # A POSE THAT WAS TAKEN is the baseline of a series. A pose that
        # COULD NOT BE TAKEN is not — and claiming a baseline for it would
        # be the quiet lie this whole record exists to prevent, since every
        # later run would then compare itself against nothing.
        if not cal.pose.established:
            return False, ("No pose could be recorded for this run, so there "
                           "is nothing for a later run to compare itself "
                           "against. Take the pose, then run it again.")
        return True, ("This run establishes the series: every later run that "
                      "matches this pose and these camera settings will be "
                      "comparable with it.")
    if not judgement.matched:
        return False, judgement.reason
    if previous is None:
        return True, ("The first run under this pose — the baseline every "
                      "later one is compared against.")
    was = PinnedCamera(**((previous.camera or {}).get("pinned") or {}))
    if not cal.camera.same_as(was):
        return False, mapping_refusals.pose_regime_changed(
            was.differences(cal.camera))
    return True, ("The camera is where it was and its settings are "
                  "unchanged, so this run may be compared with the earlier "
                  "ones.")


def _refuse(cal: Calibration, entry: CalibrationRun, detail: str,
            refusal: str) -> tuple[Calibration, CalibrationRun]:
    """Record a refusal AS AN ENTRY and save. Nothing about a refused run is
    silent, and nothing about it is an exception either: the caller gets the
    record and the record says what happened."""
    entry.status = capture_runs.STATUS_REFUSED
    entry.detail = detail
    entry.refusal = refusal
    entry.comparable = False
    entry.comparable_note = "this run did not happen"
    cal.append_run(entry)
    return calibration_store.save(cal), entry


# ── editing the declaration ────────────────────────────────────────────────

def record_declaration_change(cal: Calibration, changes: list[str], *,
                              previous: Optional[dict] = None,
                              label: str = "") -> CalibrationRun:
    """EDITING THE DECLARATION KEEPS LINEAGE (the plan's own words): the
    edit is an entry, so a later reader can see that run 4 measured a
    different list from run 3 and why the two do not line up.

    `previous` IS THE WHOLE PRIOR DECLARATION, not just a list of change
    sentences, and that is what makes "append-only, never rewritten" true of
    the declaration itself. The calibration carries the CURRENT declaration
    and an edit moves it; without the snapshot, "what did run 3 ask for"
    stops being answerable the moment run 4 asks for something else — the
    sentences say what changed and cannot rebuild what was there.
    `declaration_snapshot(cal)` taken BEFORE the edit is what to pass.

    A DECLARATION EDIT NEVER TOUCHES A MEASUREMENT. It is not a `run` entry
    — nothing was driven — so it never counts towards `Calibration.ran`,
    never appears as the last run, and supersedes nothing: the footprints
    the old declaration produced stay exactly where they are, still credited
    to the runs that took them."""
    entry = CalibrationRun(kind=KIND_DECLARATION, label=label,
                           status=capture_runs.STATUS_OK,
                           detail="; ".join(changes) or "no change",
                           previous_declaration=dict(previous or {}),
                           notes=list(changes))
    return cal.append_run(entry)


def view(cal: Calibration, *, room=None) -> dict:
    """The full read: the artefact, its lineage, and its provenance resolved
    against the live room map right now.

    ABSENCE IS A READ. A calibration that has never run says so in a
    sentence rather than returning an empty result set that looks like a run
    finding nothing, and a pose that was never taken says that too."""
    body = cal.model_dump()
    body["provenance"] = calibration_store.provenance(cal, room=room)
    body["ran"] = cal.ran
    body["state"] = _state_sentence(cal)
    body["pose_established"] = cal.pose.established
    # WHAT HE CAN AMEND, by the names he wrote — so a caller never has to
    # guess an item's name out of the declaration's own shape.
    body["item_names"] = amendment.declared_names(cal)
    body["amendable"] = amendment.amendable(cal)
    # WHAT WAS MEASURED AND NEVER APPLIED — a cut-short amendment waiting to
    # be run again. Named on the read rather than left for someone to notice
    # in the lineage, because "nothing changed until you say so" is only
    # true if he is told.
    body["unapplied"] = [
        {"id": r.id, "at": r.at, "kind": r.kind, "amended": list(r.amended),
         "emitters": r.emitters, "reason": r.unapplied_reason}
        for r in cal.runs if r.kind in cal_model.RUN_KINDS and not r.applied]
    return body


def _state_sentence(cal: Calibration) -> str:
    if not cal.pose.established and not cal.ran:
        return ("This calibration has never run and has no pose recorded. "
                "Running it will take the pose and then measure what it "
                "declares.")
    if not cal.pose.established:
        return ("This calibration has run but has no pose recorded, so "
                "nothing can tell whether the camera has moved since. Take "
                "its pose to start a comparable series.")
    if not cal.ran:
        return (f"The pose is recorded"
                + (f" at {cal.pose.placement}" if cal.pose.placement else "")
                + ", and nothing has been measured under it yet.")
    last = cal.last_run
    runs = len([r for r in cal.runs if r.kind == KIND_RUN])
    amended = len([r for r in cal.runs if r.kind == KIND_AMENDMENT])
    # AMENDMENTS ARE COUNTED SEPARATELY, because they answer a different
    # question: "when did this last measure EVERYTHING it declares" is not
    # "when did it last measure anything", and one number for both would
    # answer neither.
    what = (f"{runs} run{'' if runs == 1 else 's'}"
            + (f" and {amended} amendment{'' if amended == 1 else 's'}"
               if amended else "") + " recorded")
    if last is None:
        return f"{what}."
    return f"{what}; the last one {last.status} — {last.detail}"
