"""SPECTRA feedback-session store (Stage 2, spectra/services/feedback.py)
— offline proof of the server-side half of the two binding requirements
(spectra-design-decisions.md "Feedback-session design requirements"):

  1. capture_moment() reads the live bridge state for a mark (degrading to
     None/None when the bridge is down, never raising).
  2. save_batch()/load_all_batches()/load_entries() round-trip one Send
     press as a single durable, atomic, uri/since-filterable record, with
     bounded growth (oldest whole batch evicted first, the newest batch
     never evicted).

The client-side half (mark-then-nudge queue, localStorage persistence,
nudge arithmetic) has no Python surface — proved by chrome-devtools-axi
eye-check against the dev server per the PR description, and by the
end-to-end API round trip below standing in for the batch-send contract
the frontend relies on.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "FEEDBACK_FILE", tmp_path / "feedback.json")


def test_capture_moment_degrades_when_bridge_unreachable():
    from spectra.services import feedback

    moment = feedback.capture_moment()
    assert moment["uri"] is None and moment["position_ms"] is None, \
        "the real (untouched, never-connected) bridge singleton reports no " \
        "track — capture_moment degrades to neutral, never raises"
    assert isinstance(moment["wall_ms"], int) and moment["wall_ms"] > 0


def test_capture_moment_reads_live_bridge_state(monkeypatch):
    import sys
    import types

    from spectra.services import feedback

    fake_bridge = types.SimpleNamespace(
        track_uri=lambda: "spotify:track:abc123",
        track_position_ms=lambda: 42_000,
    )
    fake_engine_module = types.SimpleNamespace(bridge=fake_bridge)
    monkeypatch.setitem(sys.modules, "spectra.services.engine", fake_engine_module)

    moment = feedback.capture_moment()
    assert moment["uri"] == "spotify:track:abc123"
    assert moment["position_ms"] == 42_000


def test_save_batch_round_trips_and_is_atomic(tmp_path):
    from spectra import config as scfg
    from spectra.services import feedback

    assert feedback.load_all_batches() == [], "no file yet — empty"

    entries = [
        feedback.FeedbackEntry(id="a", wall_ms=1000, uri="spotify:track:x",
                               position_ms=5000, note="great drop"),
        feedback.FeedbackEntry(id="b", wall_ms=2000, uri="spotify:track:x",
                               position_ms=8000, note=""),
    ]
    batch = feedback.save_batch(entries)
    assert batch.session_id
    assert batch.received_ms > 0
    assert len(batch.entries) == 2

    batches = feedback.load_all_batches()
    assert len(batches) == 1
    assert batches[0]["session_id"] == batch.session_id
    assert [e["id"] for e in batches[0]["entries"]] == ["a", "b"]

    # atomic write — no leftover temp file
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == [], f"atomic write left a temp file behind: {leftovers}"
    assert scfg.FEEDBACK_FILE.exists()


def test_load_entries_filters_by_uri_and_since():
    from spectra.services import feedback

    feedback.save_batch([
        feedback.FeedbackEntry(id="a", wall_ms=1000, uri="spotify:track:x", position_ms=1000, note="one"),
        feedback.FeedbackEntry(id="b", wall_ms=5000, uri="spotify:track:y", position_ms=2000, note="two"),
    ])
    feedback.save_batch([
        feedback.FeedbackEntry(id="c", wall_ms=9000, uri="spotify:track:x", position_ms=3000, note="three"),
    ])

    all_entries = feedback.load_entries()
    assert {e["id"] for e in all_entries} == {"a", "b", "c"}
    assert all("session_id" in e for e in all_entries), \
        "every flattened entry carries its batch's session_id"

    x_only = feedback.load_entries(uri="spotify:track:x")
    assert {e["id"] for e in x_only} == {"a", "c"}

    since_5000 = feedback.load_entries(since_ms=5000)
    assert {e["id"] for e in since_5000} == {"b", "c"}


def test_batch_send_failure_does_not_corrupt_prior_batches(monkeypatch):
    """A failed write must never lose an already-persisted batch — the
    frontend's retry contract (a failed Send keeps the local queue intact
    and simply tries the same POST again) only holds if the store itself
    never half-writes."""
    from spectra.services import feedback

    feedback.save_batch([feedback.FeedbackEntry(id="a", wall_ms=1, note="first")])

    def boom(*a, **kw):
        raise OSError("disk full")

    original = feedback._atomic_write_json
    monkeypatch.setattr(feedback, "_atomic_write_json", boom)
    with pytest.raises(OSError):
        feedback.save_batch([feedback.FeedbackEntry(id="b", wall_ms=2, note="second")])
    monkeypatch.setattr(feedback, "_atomic_write_json", original)

    assert [e["id"] for e in feedback.load_entries()] == ["a"], \
        "the first batch survives a failed second write untouched"


def test_bounded_growth_evicts_oldest_batch_but_never_the_newest(monkeypatch):
    from spectra.services import feedback

    monkeypatch.setattr(feedback, "FEEDBACK_MAX_ENTRIES", 3)

    feedback.save_batch([feedback.FeedbackEntry(id=f"a{i}", wall_ms=i, note="") for i in range(2)])
    feedback.save_batch([feedback.FeedbackEntry(id=f"b{i}", wall_ms=i, note="") for i in range(2)])

    ids = {e["id"] for e in feedback.load_entries()}
    assert ids == {"b0", "b1"}, "oldest batch evicted once the cap is exceeded"

    # a single batch alone exceeding the cap is never evicted — it's the
    # one just sent, and there is nothing older left to drop instead
    feedback.save_batch([feedback.FeedbackEntry(id=f"c{i}", wall_ms=i, note="") for i in range(5)])
    ids = {e["id"] for e in feedback.load_entries()}
    assert ids == {f"c{i}" for i in range(5)}
