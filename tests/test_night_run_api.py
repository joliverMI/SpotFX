"""THE NIGHT-RUN WIRE — auth, the exact payloads Home Assistant sends, and
the shape River's morning backstop is built against.

THE TOKEN IN THIS FILE IS A TEST FIXTURE. The real one lives in the
environment on the deploy host and in a 0600 file outside this repository;
nothing here reads either, and nothing in `spectra/api/night_run.py` logs a
presented value.
"""
from __future__ import annotations

import pytest

from fx import light_ownership as lo
from spectra.services import night_run

_ORIGINAL_OWNERSHIP_FILE = lo.OWNERSHIP_FILE
TOKEN = "a-test-token-not-his"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    lo.OWNERSHIP_FILE = tmp_path / "ownership.json"
    lo._save(lo.OwnershipRecord(owner=lo.RELEASED))
    monkeypatch.setenv("SPECTRA_NIGHT_RUN_TOKEN", TOKEN)
    yield
    lo.OWNERSHIP_FILE = _ORIGINAL_OWNERSHIP_FILE


def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


def _auth(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


START = {"event": "sleep-window-start", "ts": "2026-09-01T01:00:00Z",
         "source": "home-assistant"}


# ── AUTH ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("headers", [
    {},                                    # absent
    {"Authorization": "Bearer wrong"},     # mismatched
    {"Authorization": TOKEN},              # no scheme
    {"Authorization": "Basic " + TOKEN},   # wrong scheme
])
@pytest.mark.parametrize("path", ["/api/night-run/start",
                                  "/api/night-run/abort"])
def test_a_push_without_the_right_bearer_is_401(headers, path):
    """Absent and mismatched get the SAME answer: telling a caller which of
    the two it was is a free hint."""
    with _client() as client:
        resp = client.post(path, json=START, headers=headers)
    assert resp.status_code == 401


@pytest.mark.parametrize("path", ["/api/night-run/start",
                                  "/api/night-run/abort"])
def test_an_unprovisioned_host_fails_closed(monkeypatch, path):
    """No token in the environment means the seam is SHUT, not open — a
    deploy that forgot the variable refuses starts rather than accepting
    anonymous ones."""
    monkeypatch.delenv("SPECTRA_NIGHT_RUN_TOKEN", raising=False)
    with _client() as client:
        resp = client.post(path, json=START, headers=_auth())
    assert resp.status_code == 401


def test_the_token_is_read_at_request_time_not_at_import(monkeypatch):
    """Rotating the secret is an environment edit and a restart, with no
    module global that could keep serving the old one."""
    monkeypatch.setenv("SPECTRA_NIGHT_RUN_TOKEN", "rotated")
    with _client() as client:
        assert client.post("/api/night-run/abort", json=START,
                           headers=_auth("rotated")).status_code == 200
        assert client.post("/api/night-run/abort", json=START,
                           headers=_auth(TOKEN)).status_code == 401


def test_the_reads_need_no_auth():
    """River asked for a read with no auth, and a read cannot start
    anything."""
    with _client() as client:
        assert client.get("/api/night-run/fixtures").status_code == 200
        assert client.get("/api/night-run/queue").status_code == 200


# ── THE PUSHES ─────────────────────────────────────────────────────────────

def test_a_declined_start_is_http_200_because_it_is_a_normal_outcome():
    """A 4xx here would teach the other side to treat a working boundary as
    a fault, and Home Assistant's push is fire-and-forget with nothing to
    retry."""
    night_run.save_declaration("nightly", [{"kind": "map",
                                            "room_id": "lounge"}])
    with _client() as client:
        resp = client.post("/api/night-run/start", json=START,
                           headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == night_run.STATE_DECLINED
    assert body["refusal"] == "not_owned"
    assert "never takes the room" in body["detail"]


def test_the_start_payload_is_home_assistants_own_and_is_recorded_verbatim():
    """Every field optional and extras allowed: a fire-and-forget push must
    never fail validation over a field this side did not need."""
    with _client() as client:
        resp = client.post("/api/night-run/start",
                           json={**START, "context": {"user_id": None}},
                           headers=_auth())
    assert resp.status_code == 200
    stored = night_run.load_nights()[-1]
    assert stored["trigger"]["event"] == "sleep-window-start"
    assert stored["trigger"]["context"] == {"user_id": None}


@pytest.mark.parametrize("event,state,by_morning", [
    ("sleep-ended", night_run.STATE_ABORTED, False),
    ("light-touched", night_run.STATE_ABORTED, False),
    ("morning-routine", night_run.STATE_ENDED_BY_MORNING, True),
])
def test_the_one_abort_endpoint_carries_three_facts(event, state, by_morning):
    with _client() as client:
        resp = client.post("/api/night-run/abort",
                           json={"event": event, "source": "home-assistant"},
                           headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == state
    assert body["ended_by_morning"] is by_morning


# ── THE DECLARATION ────────────────────────────────────────────────────────

def test_declaring_a_queue_round_trips_and_a_typo_is_refused_at_declaration():
    with _client() as client:
        bad = client.put("/api/night-run/queue",
                         json={"label": "n", "items": [{"kind": "nope",
                                                        "room_id": "r"}]})
        assert bad.status_code == 400
        assert "kind must be" in bad.json()["detail"]
        assert client.get("/api/night-run/queue").json()["declared"] is False

        good = client.put("/api/night-run/queue", json={
            "label": "nightly", "items": [{"kind": "map",
                                           "room_id": "lounge"}]})
        assert good.status_code == 200
        body = client.get("/api/night-run/queue").json()
        assert body["declared"] is True
        assert body["queue"]["label"] == "nightly"
        assert body["night"]["declared"] is True


# ── THE EXPORT ─────────────────────────────────────────────────────────────

def test_the_export_answers_with_both_lists_even_before_any_night_has_run():
    """A stable address: River's backstop must be able to read it on day one
    without a night having happened."""
    with _client() as client:
        body = client.get("/api/night-run/fixtures").json()
    for key in ("run_id", "state", "started", "ended", "fixtures",
                "standing_lit_under_dark"):
        assert key in body, key
    assert isinstance(body["fixtures"], list)
    assert isinstance(body["standing_lit_under_dark"], list)


def test_the_night_state_reaches_engine_status():
    """River reads the run's state THERE to restore the house's own dark."""
    with _client() as client:
        body = client.get("/api/engine/status").json()
    assert "night_run" in body
    assert body["night_run"]["active"] is False
    assert "planned_end_label" in body["night_run"]
