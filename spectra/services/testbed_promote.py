"""Push-to-real — the ONE way a test-bed-suggested mark can reach his real
trigger corpus (data/spotfx-music-analysis-plan/report.md, "Two decisions
this plan surfaces" #2, Admiral-approved scope 2026-09-09: "a button that
pushes a test-bed-suggested transition into his REAL trigger corpus... it
MUST go through a PROMOTION REVIEW step").

THE GATE IS STRUCTURAL, not a UI convention: `promote()` refuses
(`PromotionNotConfirmed`) unless `confirmed=True` arrives on the call
itself — there is no default, no "confirm once and it stays confirmed,"
every call is judged on its own. `spectra/api/testbed.py`'s route is the
ONLY caller, and the frontend's `PromotionReviewDialog.tsx` is the ONLY
thing that can produce a confirmed=True call — a bare "push" click with no
review step never reaches this function at all (see that component: the
mutation it fires is only wired to its own "Confirm & push" button, never
the initial "Push to real" button that opens it).

Respecting the two-trigger-store reality (AGENTS.md's "TWO trigger
copies"): this writes ONLY the fired copy (storage/spectra/triggers.json,
via trigger_store.upsert), the SAME store spectra/api/triggers.py's own
human-authoring POST writes, through the SAME validated write —
trigger_store.validate_action is the one reference-integrity check both
call. It never touches the legacy editor copy (storage/profiles/*.json) —
that store lives in the spot-effects process, unreachable from here by the
S3 import-discipline rule, and a promoted trigger is source="authored" in
the fired copy exactly like a hand-placed one, so profile_trigger_sync's
own upsert-only/provenance-gated-delete rules (spectra/services/
profile_trigger_sync.py) are never at risk of colliding with it — nothing
here EVER calls that reconciler.

A promoted trigger carries NO provenance of its own: source="authored"
and generator_key=None, exactly like a hand-placed one. Both halves are
deliberate. "authored" because front 3's regeneration/ownership-transfer
rule (spectra/models/trigger.py's own docstring) only ever applies to
midsong_generator's own seeded rows — a test-bed promotion is a human
decision, not a generation pass, and must never be silently overwritten by
a later `POST /api/triggers/generate`. generator_key=None because that
field is midsong_generator's own matching key; stamping a "testbed:..."
value there would put a non-generated row into the space a generated one
is identified by.

So a STORE OF OUR OWN is the only record that a given trigger came from
this page — which is what `promoted_trigger_ids()` /
`promoted_ids_by_uri()` exist for. spectra/services/testbed_marks.py reads
them to keep a promoted mark OUT of the scoring reference set: it sits at
the suggesting engine's own exact time_ms, so scoring against it would
grade that engine on marks it authored — the same circularity the
authored-only rule already refuses for generated rows, arriving through
the authored door. The mark is still SHOWN (flagged `promoted`), never
silently dropped.

THIS MODULE THEREFORE OWNS TWO STORES, AND THEIR BOUNDS DIFFER ON PURPOSE:

  promotions.json   — the HISTORY a human reads (every attempt, accepted or
                      refused), BOUNDED at _LOG_MAX_ENTRIES. Display and
                      audit; `GET /api/testbed/promotions` serves it.
  promoted_ids.json — the PROVENANCE the scoring exclusion depends on,
                      `{uri: [trigger_id, ...]}`, NEVER truncated.

Sourcing the exclusion from the bounded log is the defect this split
exists to prevent: refusals share that log's budget, so a run of refused
clicks evicts real promotions, `ReferenceMark.promoted` silently flips
back to False, and the excluded marks re-enter `scoring_marks()` — the
engine graded against its own pushed suggestions again, with the lane
tint, the `n_promoted` count and the metrics note all quietly stopping
saying so. The reads below UNION the durable index with whatever the log
window still shows, so a store written before this split existed keeps
its provenance with no migration; the union can only ADD ids, never
resurrect an expiry.

A repeat of the same click is REFUSED, never landed twice: an authored
trigger of the same action kind already within DUPLICATE_WINDOW_MS of the
requested moment on that song refuses by name (`PromotionDuplicate`) and is
logged like any other refusal. Every call mints a fresh id, so without this
a second confirm would stack a second trigger on the same tick — for a
fire_response that is the double-flare class the trigger engine's own
history is full of. The check and the write are ONE critical section under
trigger_store.write_lock (this runs on a worker thread, beside the
event-loop POST and the generator's own off-loop writes): two confirms in
flight at once — two tabs, a double-tap — cannot both pass the guard, and
the write cannot overwrite a trigger another writer landed in between.

Every promotion (accepted or refused) is appended to a durable, bounded log
(`storage/spectra/testbed/promotions.json`) — the visible proof this
button cannot write silently, readable via `GET /api/testbed/promotions`.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
import uuid
from typing import Optional

from spectra import config
from spectra.models.trigger import SpectraTrigger, TriggerAction
from spectra.services import trigger_store

logger = logging.getLogger(__name__)

_LOG_MAX_ENTRIES = 500
DUPLICATE_WINDOW_MS = 250
_log_lock = threading.Lock()


class PromotionNotConfirmed(ValueError):
    """confirmed=True didn't arrive on the call — the structural half of
    the review gate. Never caught and silently ignored by any caller."""


class PromotionDuplicate(ValueError):
    """An authored trigger of the same action kind already sits within
    DUPLICATE_WINDOW_MS of the requested moment on this song. Refused and
    logged, never a silent no-op: the caller is told which trigger."""


def _nearby_authored(uri: str, timestamp_ms: int, kind: str) -> Optional[SpectraTrigger]:
    for existing in trigger_store.list_for_song(uri):
        if (existing.source == "authored" and existing.action.kind == kind
                and abs(existing.timestamp_ms - timestamp_ms) <= DUPLICATE_WINDOW_MS):
            return existing
    return None


def _load_log() -> list[dict]:
    """A malformed or hand-edited file reads as an EMPTY log, never as
    whatever it happened to parse to. _record() appends to this and runs
    AFTER trigger_store.upsert has already landed the write: a non-list
    here would raise there, 500 a promotion that really happened, leave it
    out of the audit trail, and then refuse his retry as a duplicate."""
    if config.TESTBED_PROMOTIONS_FILE.exists():
        try:
            data = json.loads(config.TESTBED_PROMOTIONS_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("testbed promotions.json parse failed: %s", exc)
            return []
        if isinstance(data, list):
            return [e for e in data if isinstance(e, dict)]
        logger.warning("testbed promotions.json is a %s, not a list — "
                       "reading it as an empty log", type(data).__name__)
    return []


def _save_log(entries: list[dict]) -> None:
    path = config.TESTBED_PROMOTIONS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(entries[-_LOG_MAX_ENTRIES:], fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _record(entry: dict) -> None:
    with _log_lock:
        entries = _load_log()
        entries.append(entry)
        _save_log(entries)


def _load_promoted_index() -> dict[str, list[str]]:
    """{uri: [trigger_id, ...]}, or an EMPTY index when the file is absent,
    unparseable or the wrong shape — the same never-raise posture
    `_load_log` has, and for the same reason: this is written after the
    trigger has already landed."""
    path = config.TESTBED_PROMOTED_IDS_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("testbed promoted_ids.json parse failed: %s", exc)
        return {}
    if not isinstance(data, dict):
        logger.warning("testbed promoted_ids.json is a %s, not an object — "
                       "reading it as empty", type(data).__name__)
        return {}
    out: dict[str, list[str]] = {}
    for uri, ids in data.items():
        if isinstance(uri, str) and isinstance(ids, list):
            out[uri] = [i for i in ids if isinstance(i, str)]
    return out


def _save_promoted_index(index: dict[str, list[str]]) -> None:
    """NEVER truncated — see the module docstring. This file grows by one
    short id per promotion; his whole corpus is ~21k triggers, so even a
    pathological future of pushing every one of them is a few hundred KB."""
    path = config.TESTBED_PROMOTED_IDS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(index, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _remember_promoted(uri: str, trigger_id: str) -> None:
    with _log_lock:
        index = _load_promoted_index()
        ids = index.setdefault(uri, [])
        if trigger_id not in ids:
            ids.append(trigger_id)
        _save_promoted_index(index)


def promote(uri: str, timestamp_ms: int, action: TriggerAction,
           source_engine: str, source_mark_kind: str,
           confirmed: bool, trigger_offset_ms: int = 0) -> dict:
    """The one write path. Raises PromotionNotConfirmed (never writes,
    never logs a fabricated success) when confirmed is not literally True.
    Raises trigger_store.InvalidTriggerAction (the SAME check
    spectra/api/triggers.py's own POST applies) when the action references
    something that doesn't exist, and PromotionDuplicate when an authored
    trigger of this kind already sits within DUPLICATE_WINDOW_MS of the
    moment. Returns {"status": "promoted", "trigger_id": ...} on success."""
    at = time.time()
    if not confirmed:
        _record({
            "at": at, "uri": uri, "timestamp_ms": timestamp_ms,
            "source_engine": source_engine, "source_mark_kind": source_mark_kind,
            "status": "refused", "reason": "not_confirmed",
        })
        raise PromotionNotConfirmed(
            "a test-bed suggestion requires explicit review confirmation "
            "before it can reach the real trigger corpus")

    # Build the trigger BEFORE validating its reference integrity: pydantic
    # coerces a plain action dict (a direct service-level call, e.g. from a
    # test) into the correct discriminated TriggerAction subtype the same
    # way FastAPI already coerced it for an HTTP caller — one coercion
    # path, so validate_action always sees a real model, never a dict.
    trigger = SpectraTrigger(
        id=str(uuid.uuid4()),
        timestamp_ms=timestamp_ms,
        source="authored",
        generator_key=None,
        action=action,
        trigger_offset_ms=trigger_offset_ms,
    )

    try:
        trigger_store.validate_action(trigger.action)
    except trigger_store.InvalidTriggerAction as exc:
        _record({
            "at": at, "uri": uri, "timestamp_ms": timestamp_ms,
            "source_engine": source_engine, "source_mark_kind": source_mark_kind,
            "status": "refused", "reason": str(exc),
        })
        raise
    with trigger_store.write_lock:
        nearby = _nearby_authored(uri, timestamp_ms, trigger.action.kind)
        if nearby is None:
            trigger_store.upsert(uri, trigger)
    if nearby is not None:
        message = (f"a {trigger.action.kind} trigger already exists near this "
                   f"moment ({nearby.timestamp_ms}ms, id {nearby.id}) — not "
                   f"pushing a second one")
        _record({
            "at": at, "uri": uri, "timestamp_ms": timestamp_ms,
            "source_engine": source_engine, "source_mark_kind": source_mark_kind,
            "status": "refused", "reason": "duplicate",
            "detail": message, "existing_trigger_id": nearby.id,
        })
        raise PromotionDuplicate(message)

    # The durable provenance lands BEFORE the display log: if either write
    # were to fail, the one that keeps this trigger out of the scoring
    # reference set is the one that must already be on disk.
    _remember_promoted(uri, trigger.id)
    _record({
        "at": at, "uri": uri, "timestamp_ms": timestamp_ms,
        "source_engine": source_engine, "source_mark_kind": source_mark_kind,
        "status": "promoted", "trigger_id": trigger.id,
        "action_kind": trigger.action.kind,
    })
    logger.info("testbed promotion: %s @ %dms (%s from %s) -> trigger %s",
               uri, timestamp_ms, trigger.action.kind, source_engine, trigger.id)
    return {"status": "promoted", "trigger_id": trigger.id}


def log_for_song(uri: Optional[str] = None) -> list[dict]:
    entries = _load_log()
    if uri is None:
        return entries
    return [e for e in entries if e.get("uri") == uri]


def _logged_promoted_ids() -> dict[str, set[str]]:
    """Whatever the BOUNDED display log can still see. Unioned into the
    reads below purely so an install that promoted before promoted_ids.json
    existed keeps its provenance without a migration — never the source of
    truth, because entries here expire."""
    out: dict[str, set[str]] = {}
    for e in _load_log():
        if e.get("status") != "promoted":
            continue
        uri, tid = e.get("uri"), e.get("trigger_id")
        if isinstance(uri, str) and isinstance(tid, str):
            out.setdefault(uri, set()).add(tid)
    return out


def promoted_trigger_ids(uri: str) -> set[str]:
    """The fired-copy trigger ids this page pushed for ONE song — the only
    thing that can tell a promoted authored trigger from one he placed by
    hand (see the module docstring: nothing on the trigger itself does).
    Read from the NEVER-TRUNCATED index, so this answer does not change
    when the display log rotates."""
    ids = set(_load_promoted_index().get(uri, ()))
    ids |= _logged_promoted_ids().get(uri, set())
    return ids


def promoted_ids_by_uri() -> dict[str, set[str]]:
    """{uri: {trigger_id, ...}} from ONE read of each store — the
    whole-corpus listing's shape, so a song walk never re-reads per song."""
    out: dict[str, set[str]] = {
        uri: set(ids) for uri, ids in _load_promoted_index().items()}
    for uri, ids in _logged_promoted_ids().items():
        out.setdefault(uri, set()).update(ids)
    return out
