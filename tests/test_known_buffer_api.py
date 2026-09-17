"""THE KNOWN AUDIO BUFFER's wire and settings — the routes, the room
controls, and the surfacing in engine status.

The one structural claim worth stating up front: THERE IS NO INBOUND PUSH
ROUTE and there must not be. River publishes on its own loopback surface
and SPECTRA subscribes; a second way in is a second thing that can
disagree about what the current reading is. `test_there_is_no_inbound_push_
route` holds that.
"""
from __future__ import annotations

import time

import pytest

from spectra import config as scfg
from spectra.services import known_buffer as kb
from spectra.services import room_controls as rc


@pytest.fixture(autouse=True)
def _room(tmp_path, monkeypatch):
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")


def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


def _payload(value=500, **over):
    body = {"effects_fire_later_by_ms": value, "t_ms": int(time.time() * 1000),
            "source": "measured", "epoch": 0, "floor_clamped": True,
            "governed": False, "parec_buffer_ms": 0.0, "flowing": False,
            "floor_ms": 500, "update_period_ms": 15000, "hold_limit_ms": 60000,
            "stale": False, "age_ms": 900.0}
    body.update(over)
    return body


# ── the settings ────────────────────────────────────────────────────────
def test_the_five_settings_ship_with_the_ratified_defaults():
    st = rc.RoomControlState()
    assert st.known_buffer_source_url == "http://127.0.0.1:8097"
    assert st.known_buffer_floor_ms == 500
    assert st.known_buffer_ceiling_ms == 1500
    assert st.known_buffer_update_period_s == 15.0
    assert st.known_buffer_stale_periods == 4.0


def test_the_floor_is_read_from_configuration_not_frozen_as_a_constant():
    """He proposed 500 with a question mark, so it has to be settable —
    and the value actually applied has to follow the setting."""
    st = rc.RoomControlState(known_buffer_floor_ms=350)
    assert kb.effective_value_ms(None, st) == 350
    assert "350" not in str(kb.LOG_RETENTION_S)          # not a constant anywhere
    assert kb.effective_value_ms(None, rc.RoomControlState()) == 500


def test_the_bounds_are_declared_so_the_ranges_cannot_drift():
    assert rc.field_bounds("known_buffer_floor_ms") == (0, 10000)
    assert rc.field_bounds("known_buffer_ceiling_ms") == (0, 10000)
    assert rc.field_bounds("known_buffer_stale_periods") == (1.0, 100.0)


def test_these_are_settings_and_not_environment_variables():
    """Env in this app is for credentials and arming levers only. Nothing
    under spectra/ may read one of these from the environment."""
    import pathlib
    for path in pathlib.Path("spectra").rglob("*.py"):
        text = path.read_text()
        for name in ("KNOWN_BUFFER_SOURCE_URL", "KNOWN_BUFFER_FLOOR",
                     "SPECTRA_KNOWN_BUFFER"):
            assert name not in text, f"{path} reads {name} from the environment"


def test_the_settings_are_not_exposed_to_the_settings_console():
    """av_sync_lead_ms's own precedent: a timing calibration belongs to the
    instrument that measured it, and the URL is an opaque address."""
    from spectra.services import settings_console
    for name in settings_console.SETTINGS_REGISTRY:
        assert not name.startswith("known_buffer_")


def test_a_partial_put_preserves_the_new_fields(tmp_path):
    rc.save_room_controls(rc.RoomControlState(known_buffer_floor_ms=420,
                                              known_buffer_source_url="http://river"))
    client = _client()
    r = client.put("/api/room-controls", json={"brightness_multiplier": 0.5})
    assert r.status_code == 200
    saved = rc.load_room_controls()
    assert saved.known_buffer_floor_ms == 420
    assert saved.known_buffer_source_url == "http://river"


def test_the_settings_are_tunable_through_the_ordinary_put():
    client = _client()
    r = client.put("/api/room-controls", json={"known_buffer_floor_ms": 600,
                                               "known_buffer_stale_periods": 6.0})
    assert r.status_code == 200
    assert rc.load_room_controls().known_buffer_floor_ms == 600
    assert kb.state()["floor_ms"] == 600
    assert kb.state()["stale_periods"] == 6.0


def test_an_out_of_range_setting_is_refused_not_clamped():
    client = _client()
    assert client.put("/api/room-controls",
                      json={"known_buffer_stale_periods": 0.2}).status_code == 422
    assert client.put("/api/room-controls",
                      json={"known_buffer_update_period_s": 0}).status_code == 422


# ── the routes ──────────────────────────────────────────────────────────
def test_the_read_returns_the_state_block():
    kb.record(_payload(value=640))
    body = _client().get("/api/timing/effects-fire-later").json()
    for key in ("effects_fire_later_by_ms", "published_ms", "at", "age_s",
                "state", "source", "floor_ms", "ceiling_ms", "update_period_s",
                "stale_periods", "flags", "reference_ms", "compensation_ms",
                "sentence", "apply_gate", "applied", "river"):
        assert key in body, key
    assert body["published_ms"] == 640
    assert body["state"] == "fresh"


def test_the_raw_series_is_readable():
    kb.record(_payload(value=500))
    kb.record(_payload(value=620))
    rows = _client().get("/api/timing/effects-fire-later/log").json()["readings"]
    assert [r["effects_fire_later_by_ms"] for r in rows] == [500, 620]


def test_there_is_no_inbound_push_route():
    """River pushes nothing into SPECTRA. A POST here must not exist — and
    if one is ever added, this test is the conversation about why."""
    app = _client().app
    for route in app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/api/timing"):
            assert set(getattr(route, "methods", set())) <= {"GET", "HEAD"}, path


def test_the_state_block_is_folded_into_engine_status():
    kb.record(_payload(value=640))
    body = _client().get("/api/engine/status").json()
    assert "known_buffer" in body
    assert body["known_buffer"]["published_ms"] == 640
    # ONE function builds it, so the two surfaces cannot disagree.
    assert body["known_buffer"] == _client().get("/api/timing/effects-fire-later").json()


def test_applying_an_av_sync_lead_re_bases_the_reference():
    """The lead measurement absorbed the buffer as it stood; the delta must
    start again from there or the same milliseconds are counted twice."""
    now = int(time.time() * 1000)
    kb.record(_payload(value=900, t_ms=now, floor_clamped=False, governed=True))
    kb.record(_payload(value=1200, t_ms=now + 1, floor_clamped=False, governed=True))
    assert kb.state()["compensation_ms"] == 300
    r = _client().put("/api/room-controls", json={"av_sync_lead_ms": -38})
    assert r.status_code == 200
    assert r.json()["known_buffer_reference_ms"] == 1200
    assert kb.state()["compensation_ms"] == 0
    # AND THE LEAD ITSELF IS UNTOUCHED BY ANY OF THIS.
    assert rc.load_room_controls().av_sync_lead_ms == -38


def test_an_unrelated_put_does_not_re_base_the_reference():
    now = int(time.time() * 1000)
    kb.record(_payload(value=900, t_ms=now, floor_clamped=False, governed=True))
    kb.record(_payload(value=1200, t_ms=now + 1, floor_clamped=False, governed=True))
    r = _client().put("/api/room-controls", json={"brightness_multiplier": 0.9})
    assert "known_buffer_reference_ms" not in r.json()
    assert kb.state()["compensation_ms"] == 300


def test_the_show_clock_is_still_the_only_application_point():
    """The seam is RULED and wired — at exactly one place. A second
    application point could quietly disagree with this one, so the trigger
    poll must be the only caller and show_clock_ms the only formula."""
    import inspect
    from spectra.services import av_sync_lead, engine
    poll = inspect.getsource(engine._run_trigger_engine)
    assert "known_buffer.compensation_ms()" in poll
    assert poll.count("show_clock_ms") == 1
    # and nothing else in the engine reaches for it as a clock term
    whole = inspect.getsource(engine)
    assert whole.count("known_buffer.compensation_ms") == 1
    # the subtraction lives in one line, beside the lead it must never be
    # added to with the same sign
    body = inspect.getsource(av_sync_lead.show_clock_ms)
    assert "- int(known_buffer_ms or 0)" in body
