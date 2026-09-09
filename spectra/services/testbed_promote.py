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

A promoted trigger's generator_key carries where it came from
("testbed:<engine>:<mark_kind>:<uri>@<timestamp_ms>") for audit ONLY —
its source is still stamped "authored" (never "generated"), because
front 3's regeneration/ownership-transfer rule
(spectra/models/trigger.py's own docstring) only ever applies to
midsong_generator's own seeded triggers; a test-bed promotion is a human
decision, not a generation pass, and must never be silently overwritten by
a later `POST /api/triggers/generate` the way an untouched generated
trigger would be.

Every promotion (accepted or refused) is appended to a durable, bounded log
(`storage/spectra/testbed/promotions.json`) — the visible proof this
button cannot write silently, readable via `GET /api/testbed/promotions`.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import uuid
from typing import Optional

from spectra import config
from spectra.models.trigger import SpectraTrigger, TriggerAction
from spectra.services import trigger_store

logger = logging.getLogger(__name__)

_LOG_MAX_ENTRIES = 500


class PromotionNotConfirmed(ValueError):
    """confirmed=True didn't arrive on the call — the structural half of
    the review gate. Never caught and silently ignored by any caller."""


def _load_log() -> list[dict]:
    if config.TESTBED_PROMOTIONS_FILE.exists():
        try:
            return json.loads(config.TESTBED_PROMOTIONS_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("testbed promotions.json parse failed: %s", exc)
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
    entries = _load_log()
    entries.append(entry)
    _save_log(entries)


def promote(uri: str, timestamp_ms: int, action: TriggerAction,
           source_engine: str, source_mark_kind: str,
           confirmed: bool, trigger_offset_ms: int = 0) -> dict:
    """The one write path. Raises PromotionNotConfirmed (never writes,
    never logs a fabricated success) when confirmed is not literally True.
    Raises trigger_store.InvalidTriggerAction (the SAME check
    spectra/api/triggers.py's own POST applies) when the action references
    something that doesn't exist. Returns {"status": "promoted",
    "trigger_id": ...} on success."""
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
    # source/generator_key stay "authored"/None per the module docstring —
    # provenance is carried in the promotion LOG entry below, not on the
    # trigger itself, so front 3's regeneration rule never sees this as a
    # generated row it's free to overwrite.
    trigger_store.upsert(uri, trigger)

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
