"""Stage 3 review view (spectra/services/show_reconstruction.py) — the
reconstruction slice: given a show-log window + notes, the merged timeline
is correct and ordered. See its module docstring for the ordering rule
(position_ms primary, missing-position entries last by wall_ms) and the
session-window definition (one feedback batch, padded by SESSION_PAD_MS
around that song's note wall-times).
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "FEEDBACK_FILE", tmp_path / "feedback.json")
    # SHOW_LOG_FILE/FIRE_HISTORY_FILE already isolated by the autouse
    # _isolated_fire_history conftest fixture.


# ═══ merge_timeline — pure ordering rule ═══════════════════════════════

def test_merge_timeline_orders_by_position_ms():
    from spectra.services.show_reconstruction import merge_timeline

    events = [
        {"wall_ms": 1000, "position_ms": 30000, "bucket": "scenes", "key": "s1", "detail": {}},
        {"wall_ms": 4000, "position_ms": 10000, "bucket": "scenes", "key": "s2", "detail": {}},
    ]
    notes = [
        {"wall_ms": 2000, "position_ms": 20000, "id": "n1", "note": "here"},
    ]
    merged = merge_timeline(events, notes)
    assert [item["position_ms"] for item in merged] == [10000, 20000, 30000]
    assert [item["type"] for item in merged] == ["event", "note", "event"]


def test_merge_timeline_ties_broken_by_wall_ms():
    from spectra.services.show_reconstruction import merge_timeline

    events = [{"wall_ms": 5000, "position_ms": 10000, "bucket": "scenes", "key": "a", "detail": {}}]
    notes = [{"wall_ms": 1000, "position_ms": 10000, "id": "n1", "note": "same spot"}]
    merged = merge_timeline(events, notes)
    assert [item["type"] for item in merged] == ["note", "event"], \
        "same position_ms — the earlier wall-clock arrival (the note) sorts first"


def test_merge_timeline_puts_missing_position_last_ordered_by_wall_ms():
    from spectra.services.show_reconstruction import merge_timeline

    events = [
        {"wall_ms": 9000, "position_ms": None, "bucket": "responses", "key": "flare", "detail": {}},
        {"wall_ms": 100, "position_ms": 5000, "bucket": "scenes", "key": "s1", "detail": {}},
    ]
    notes = [
        {"wall_ms": 3000, "position_ms": None, "id": "n1", "note": "bridge was down"},
    ]
    merged = merge_timeline(events, notes)
    assert merged[0]["position_ms"] == 5000
    # both position-less entries land after every positioned one, ordered
    # among themselves by wall_ms (3000 before 9000)
    assert [item.get("id") or item.get("key") for item in merged[1:]] == ["n1", "flare"]


def test_merge_timeline_preserves_event_and_note_fields():
    from spectra.services.show_reconstruction import merge_timeline

    events = [{"wall_ms": 1, "position_ms": 1, "bucket": "scenes", "key": "s1",
              "detail": {"scene_name": "Pulse"}}]
    notes = [{"wall_ms": 2, "position_ms": 2, "id": "n1", "note": "loved it"}]
    merged = merge_timeline(events, notes)
    ev, note = merged
    assert ev == {"type": "event", "wall_ms": 1, "position_ms": 1,
                  "bucket": "scenes", "key": "s1", "detail": {"scene_name": "Pulse"}}
    assert note == {"type": "note", "wall_ms": 2, "position_ms": 2,
                    "id": "n1", "note": "loved it"}


def test_merge_timeline_empty_inputs():
    from spectra.services.show_reconstruction import merge_timeline
    assert merge_timeline([], []) == []


# ═══ list_sessions / reconstruct — store-backed ═════════════════════════

def _save_batch(entries):
    from spectra.services import feedback
    return feedback.save_batch([feedback.FeedbackEntry(**e) for e in entries])


def test_list_sessions_names_songs_and_orders_newest_first():
    from spectra.services import show_reconstruction

    _save_batch([{"id": "a", "wall_ms": 1000, "uri": "spotify:track:x", "position_ms": 1000, "note": "x1"}])
    _save_batch([
        {"id": "b", "wall_ms": 5000, "uri": "spotify:track:y", "position_ms": 2000, "note": "y1"},
        {"id": "c", "wall_ms": 6000, "uri": "spotify:track:y", "position_ms": 3000, "note": "y2"},
    ])

    sessions = show_reconstruction.list_sessions()
    assert len(sessions) == 2
    assert sessions[0]["uris"] == ["spotify:track:y"], "second batch sent later — newest first"
    assert sessions[0]["note_count"] == 2
    assert sessions[1]["uris"] == ["spotify:track:x"]


def test_list_sessions_newest_first_holds_even_on_a_received_ms_tie(monkeypatch):
    """Two batches sent within the same wall-clock millisecond must still
    order newest-appended-first — list_sessions() reverses store order
    rather than sorting by received_ms for exactly this reason."""
    import time

    from spectra.services import show_reconstruction

    monkeypatch.setattr(time, "time", lambda: 1234.0)
    _save_batch([{"id": "a", "wall_ms": 1, "uri": "spotify:track:x", "position_ms": 1, "note": ""}])
    _save_batch([{"id": "b", "wall_ms": 2, "uri": "spotify:track:y", "position_ms": 2, "note": ""}])

    sessions = show_reconstruction.list_sessions()
    assert sessions[0]["received_ms"] == sessions[1]["received_ms"], "tie set up as intended"
    assert sessions[0]["uris"] == ["spotify:track:y"], "the batch sent second stays newest-first on a tie"


def test_reconstruct_scopes_to_session_and_song(monkeypatch):
    from spectra.services import fire_history, show_reconstruction

    batch = _save_batch([
        {"id": "n1", "wall_ms": 100_000, "uri": "spotify:track:x", "position_ms": 30000, "note": "drop"},
    ])

    # inside the padded window for this song
    fire_history.append_show_log("scenes", "pulse", {"scene_name": "Pulse"},
                                 uri="spotify:track:x", position_ms=29000, now_ms=95_000)
    # outside the padded window
    fire_history.append_show_log("scenes", "far", {"scene_name": "Far"},
                                 uri="spotify:track:x", position_ms=1000, now_ms=1_000)
    # inside the window but a different song — must not leak in
    fire_history.append_show_log("scenes", "other-song", {"scene_name": "Other"},
                                 uri="spotify:track:z", position_ms=29000, now_ms=95_500)

    result = show_reconstruction.reconstruct(batch.session_id, "spotify:track:x")
    assert result["window"] == {
        "start_wall_ms": 100_000 - show_reconstruction.SESSION_PAD_MS,
        "end_wall_ms": 100_000 + show_reconstruction.SESSION_PAD_MS,
    }
    keys = {item.get("key") for item in result["timeline"] if item["type"] == "event"}
    assert keys == {"pulse"}
    notes = [item for item in result["timeline"] if item["type"] == "note"]
    assert [n["id"] for n in notes] == ["n1"]


def test_reconstruct_unknown_session_or_song_returns_empty_timeline():
    from spectra.services import show_reconstruction

    result = show_reconstruction.reconstruct("no-such-session", "spotify:track:x")
    assert result == {"session_id": "no-such-session", "uri": "spotify:track:x",
                      "window": None, "timeline": []}

    batch = _save_batch([{"id": "a", "wall_ms": 1, "uri": "spotify:track:x", "position_ms": 1, "note": ""}])
    result = show_reconstruction.reconstruct(batch.session_id, "spotify:track:never-marked")
    assert result["timeline"] == []


# ═══ API surface ═════════════════════════════════════════════════════════

def test_api_review_endpoints():
    from fastapi.testclient import TestClient

    from spectra.app import create_app
    from spectra.services import fire_history

    client = TestClient(create_app())

    r = client.get("/api/review/sessions")
    assert r.status_code == 200 and r.json() == []

    payload = {"entries": [
        {"id": "m1", "wall_ms": 100_000, "uri": "spotify:track:show", "position_ms": 30000,
         "note": "lights dropped a beat late"},
    ]}
    r = client.post("/api/feedback/batch", json=payload)
    assert r.status_code == 200
    session_id = r.json()["session_id"]

    r = client.get("/api/review/sessions")
    assert r.status_code == 200
    sessions = r.json()
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == session_id
    assert sessions[0]["uris"] == ["spotify:track:show"]

    fire_history.append_show_log("scenes", "pulse", {"scene_name": "Pulse"},
                                 uri="spotify:track:show", position_ms=29500, now_ms=99_000)

    r = client.get("/api/review/timeline", params={"session_id": session_id, "uri": "spotify:track:show"})
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == session_id
    assert [item["type"] for item in body["timeline"]] == ["event", "note"]

    r = client.get("/api/review/timeline", params={"session_id": "bogus", "uri": "spotify:track:show"})
    assert r.status_code == 200 and r.json()["timeline"] == []

    r = client.get("/api/review/timeline", params={"session_id": session_id})
    assert r.status_code == 422, "uri is required"
