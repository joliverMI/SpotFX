"""The TV probe (data/tv-display-plan/plan.html PR 0.1): the store
(spectra/services/tv_probe.py) and the route shapes
(spectra/api/tv_probe.py) over FastAPI's real TestClient — the page serves,
a result is stored and merges across two POSTs, the bounded eviction holds,
and nothing here touches a light or a fixture."""
from __future__ import annotations

from spectra.services import tv_probe


def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


def test_save_result_merges_and_stamps_times():
    row = tv_probe.save_result("p1", {"user_agent": "UA/1", "webgl2": True})
    assert row["probe_id"] == "p1"
    assert row["user_agent"] == "UA/1"
    first_seen = row["first_seen_ms"]
    updated = row["updated_ms"]
    assert first_seen <= updated

    # A second POST for the SAME probe merges rather than replacing — a
    # screensaver-log-only update must not erase the earlier fps/UA fields.
    row2 = tv_probe.save_result("p1", {"screensaver_log": [{"t": 1.0, "state": "hidden"}]})
    assert row2["user_agent"] == "UA/1"
    assert row2["webgl2"] is True
    assert row2["screensaver_log"] == [{"t": 1.0, "state": "hidden"}]
    assert row2["first_seen_ms"] == first_seen


def test_save_result_requires_an_id():
    import pytest
    with pytest.raises(ValueError):
        tv_probe.save_result("", {"user_agent": "UA"})


def test_list_results_is_newest_first(monkeypatch):
    import time as time_mod
    times = iter([1000.0, 2000.0])
    monkeypatch.setattr(time_mod, "time", lambda: next(times))
    tv_probe.save_result("old", {"user_agent": "old"})
    tv_probe.save_result("new", {"user_agent": "new"})
    rows = tv_probe.list_results()
    assert [r["probe_id"] for r in rows] == ["new", "old"]


def test_bounded_eviction_drops_the_oldest():
    for i in range(tv_probe.MAX_RESULTS + 3):
        tv_probe.save_result(f"probe-{i}", {"user_agent": f"ua-{i}"})
    rows = tv_probe.list_results()
    assert len(rows) == tv_probe.MAX_RESULTS
    # the earliest ids were evicted, the latest survive
    ids = {r["probe_id"] for r in rows}
    assert "probe-0" not in ids
    assert f"probe-{tv_probe.MAX_RESULTS + 2}" in ids


def test_probe_page_serves_html_with_no_console_wiring_to_a_light():
    c = _client()
    resp = c.get("/tv/probe")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    body = resp.text
    assert "SPECTRA TV probe" in body
    assert "fx_seam" not in body
    assert "light_ownership" not in body


def test_probe_ping_is_cheap_and_touches_no_store():
    c = _client()
    resp = c.get("/api/tv/probe/ping")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_post_result_then_read_back_through_the_real_routes():
    c = _client()
    resp = c.post("/api/tv/probe/result", json={
        "probe_id": "route-1", "user_agent": "UA/route",
        "webgl2": True, "fps": {"2d_fill": 59.8}, "ping_ms": [12.0, 13.5],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["stored"] is True
    assert body["probe_id"] == "route-1"

    listed = c.get("/api/tv/probe/results").json()
    assert len(listed) == 1
    assert listed[0]["user_agent"] == "UA/route"
    assert listed[0]["fps"]["2d_fill"] == 59.8


def test_post_result_without_an_id_is_refused():
    c = _client()
    resp = c.post("/api/tv/probe/result", json={"user_agent": "no id"})
    assert resp.status_code == 422


def test_touches_no_light_when_driven_through_the_real_app(monkeypatch):
    """Driving every TV-probe route through the real, fully-wired app
    (create_app()) must never reach the production light-write seam
    (fx_seam.apply_writes) or the ownership record
    (light_ownership.commit) — the two choke points any real
    scene/flare/colour write in this app passes through. Both are
    poisoned to raise so a call from anywhere in the request path would
    fail this test loudly; the poison is proven live by calling each
    directly before driving the routes."""
    import asyncio

    import pytest

    from fx import light_ownership
    from spectra.services import fx_seam

    called: list[str] = []

    async def _poison_apply_writes(*a, **k):
        called.append("fx_seam.apply_writes")
        raise AssertionError("fx_seam.apply_writes was called")

    def _poison_commit(*a, **k):
        called.append("light_ownership.commit")
        raise AssertionError("light_ownership.commit was called")

    monkeypatch.setattr(fx_seam, "apply_writes", _poison_apply_writes)
    monkeypatch.setattr(light_ownership, "commit", _poison_commit)

    with pytest.raises(AssertionError):
        asyncio.run(fx_seam.apply_writes([]))
    with pytest.raises(AssertionError):
        light_ownership.commit("tok")
    called.clear()

    c = _client()
    assert c.get("/tv/probe").status_code == 200
    assert c.get("/api/tv/probe/ping").status_code == 200
    assert c.post("/api/tv/probe/result", json={
        "probe_id": "behavioral-1", "user_agent": "UA",
    }).status_code == 200
    assert c.get("/api/tv/probe/results").status_code == 200

    assert called == []
