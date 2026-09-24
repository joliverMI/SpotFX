"""The test bed's "Use as room default" button (data/transition-alignment-
plan/report.md section 5 task 4 item (a)) writes NOTHING of its own — it
sends exactly the three fields spectra/web/src/testbed/edgeKnobs.ts's
`roomControlsPatchForUseAsDefault` builds (transition_window_beats,
transition_edge_sensitivity, transition_max_per_song) through the
EXISTING `PUT /api/room-controls` partial merge. This is the "unit test
for the write path" the ship task's own acceptance calls for: a genuine
partial payload carrying only these three keys leaves every other stored
field untouched, and a later GET returns the new values — the two halves
of "nothing is written until the button; the button's write shows up on
GET /api/room-controls"."""
from __future__ import annotations

import json

import pytest


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(scfg, "ROOM_COLOR_FILE", tmp_path / "room_color.json")
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")


def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


def _stored() -> dict:
    from spectra import config as scfg
    return json.loads(scfg.ROOM_CONTROLS_FILE.read_text(encoding="utf-8"))


def test_the_exact_use_as_default_payload_writes_only_those_three_fields():
    """A calibrated av_sync_lead_ms — a value the partial-merge regression
    (tests/test_room_controls_partial_put.py) already proves must survive
    an unrelated partial PUT — must ALSO survive this specific one."""
    client = _client()
    seeded = client.put("/api/room-controls", json={"av_sync_lead_ms": 42}).json()
    assert seeded["av_sync_lead_ms"] == 42

    # exactly the shape edgeKnobs.ts::roomControlsPatchForUseAsDefault sends
    resp = client.put("/api/room-controls", json={
        "transition_window_beats": 2,
        "transition_edge_sensitivity": 1.1,
        "transition_max_per_song": 6,
    })
    assert resp.status_code == 200
    saved = resp.json()
    assert saved["transition_window_beats"] == 2
    assert saved["transition_edge_sensitivity"] == pytest.approx(1.1)
    assert saved["transition_max_per_song"] == 6
    assert saved["av_sync_lead_ms"] == 42, (
        "the button's write must not disturb a field it never named")

    stored = _stored()
    assert stored["transition_window_beats"] == 2
    assert stored["transition_edge_sensitivity"] == pytest.approx(1.1)
    assert stored["transition_max_per_song"] == 6
    assert stored["av_sync_lead_ms"] == 42


def test_a_later_get_reflects_the_written_values():
    """The acceptance bar, verbatim: 'the button's write shows up on
    GET /api/room-controls'."""
    client = _client()
    client.put("/api/room-controls", json={
        "transition_window_beats": 3,
        "transition_edge_sensitivity": 0.75,
        "transition_max_per_song": 20,
    })
    got = client.get("/api/room-controls").json()
    assert got["transition_window_beats"] == 3
    assert got["transition_edge_sensitivity"] == pytest.approx(0.75)
    assert got["transition_max_per_song"] == 20


def test_out_of_bounds_values_are_rejected_not_silently_clamped():
    client = _client()
    resp = client.put("/api/room-controls", json={"transition_window_beats": 999})
    assert resp.status_code in (400, 422)
    resp2 = client.put("/api/room-controls", json={"transition_max_per_song": 1})
    assert resp2.status_code in (400, 422)
