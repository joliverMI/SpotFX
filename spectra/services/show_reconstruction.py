"""Stage 3 of the owner's feedback sessions — the review view (spectra-
design-decisions.md "Feedback-session design requirements"): reconstruct a
played show from the durable SHOW LOG (spectra/services/fire_history.py)
and pin his feedback notes (spectra/services/feedback.py) against it, per
song within a session.

SESSION = one feedback batch (one Send press — his own "do some feedback
for a bit, then hit send" unit). There is no separate session store; a
batch's own `session_id`/`received_ms` already identify a played show, so
Stage 3 reads through the same two stores Stage 1/2 already write rather
than inventing a third.

WINDOW = the wall-clock span of that session's notes FOR ONE SONG (min to
max `wall_ms` among that uri's entries in the batch), padded by
SESSION_PAD_MS on both sides so a scene change firing just before his first
mark or just after his last one is still visible for context — a note is
always a reaction to something that already happened, so the pad leans
slightly toward "catch the trigger", not toward "catch the aftermath".
Show-log entries for OTHER songs never leak in even if their wall time
falls inside the window (e.g. a quick skip-and-back during the session):
the query is uri-scoped, matching how the show log itself is written (see
fire_history.load_show_log's uri filter).

merge_timeline() is the pure reconstruction slice, spec-tested in
tests/test_show_reconstruction.py: events and notes are tagged, then
ordered by SONG POSITION (position_ms) — the axis he actually reviews
against, not wall time. An entry missing position_ms (the bridge was down
when it was captured/fired) cannot be placed on that axis at all; those
sort AFTER every positioned entry, ordered among themselves by wall_ms,
rather than being interleaved by a wall time that has no relationship to
where a positioned neighbour landed.
"""
from __future__ import annotations

from typing import Optional

from spectra.services import feedback, fire_history

SESSION_PAD_MS = 20_000


def _sort_key(item: dict) -> tuple:
    pos = item.get("position_ms")
    if pos is None:
        return (1, item.get("wall_ms") or 0, 0)
    return (0, pos, item.get("wall_ms") or 0)


def merge_timeline(events: list[dict], notes: list[dict]) -> list[dict]:
    """Merge show-log events + feedback notes into one ordered timeline.
    Pure function — no I/O — so the ordering rule can be spec-tested
    directly against hand-built fixtures."""
    timeline: list[dict] = []
    for e in events:
        timeline.append({
            "type": "event",
            "wall_ms": e.get("wall_ms"),
            "position_ms": e.get("position_ms"),
            "bucket": e.get("bucket"),
            "key": e.get("key"),
            "detail": e.get("detail") or {},
        })
    for n in notes:
        timeline.append({
            "type": "note",
            "wall_ms": n.get("wall_ms"),
            "position_ms": n.get("position_ms"),
            "id": n.get("id"),
            "note": n.get("note", ""),
        })
    timeline.sort(key=_sort_key)
    return timeline


def _find_batch(session_id: str) -> Optional[dict]:
    for batch in feedback.load_all_batches():
        if batch.get("session_id") == session_id:
            return batch
    return None


def list_sessions() -> list[dict]:
    """One row per feedback batch — the review page's session picker.
    Newest first, each naming the songs it has notes for. Batches are
    already stored in send order (feedback.save_batch appends, oldest
    first), so reversing that order is the exact newest-first answer —
    sorting by `received_ms` instead would tie (and silently misorder)
    two batches sent within the same wall-clock millisecond."""
    out = []
    for batch in feedback.load_all_batches():
        entries = batch.get("entries", [])
        uris = sorted({e["uri"] for e in entries if e.get("uri")})
        out.append({
            "session_id": batch.get("session_id"),
            "received_ms": batch.get("received_ms"),
            "note_count": len(entries),
            "uris": uris,
        })
    return list(reversed(out))


def reconstruct(session_id: str, uri: str) -> dict:
    """The merged, ordered timeline for one song within one session:
    that song's notes from this session's batch, pinned against the
    show-log events fired for it inside the padded session window."""
    batch = _find_batch(session_id)
    notes = [e for e in (batch.get("entries", []) if batch else []) if e.get("uri") == uri]
    if not notes:
        return {"session_id": session_id, "uri": uri, "window": None, "timeline": []}

    wall_times = [n["wall_ms"] for n in notes]
    window = {
        "start_wall_ms": max(0, min(wall_times) - SESSION_PAD_MS),
        "end_wall_ms": max(wall_times) + SESSION_PAD_MS,
    }
    events = [
        e for e in fire_history.load_show_log(uri=uri)
        if window["start_wall_ms"] <= e.get("wall_ms", 0) <= window["end_wall_ms"]
    ]
    return {
        "session_id": session_id,
        "uri": uri,
        "window": window,
        "timeline": merge_timeline(events, notes),
    }
