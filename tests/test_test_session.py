"""TESTING IN PROGRESS — the room-visibility surface (his ask 2026-08-24).

The four load-bearing properties, each proven rather than asserted in a
docstring:

  1. THE AUTO FOLD lights the bar with zero agent discipline — each of
     the app's own test paths (preview_pause, flare_preview_hold,
     room_preview) on its own is enough.
  2. A DECLARATION shows regardless of who owns the lights, carries who
     and since-when, and RENEWS without resetting its start time.
  3. IT CLEARS ITSELF — expiry is evaluated at read, with no background
     task and no flag anyone must remember to clear.
  4. UNKNOWN IS HONEST — an unreadable store or a failing probe reports
     "unknown", never a cheerful "no". "no" is only ever reached on
     positive evidence of quiet.
"""
from __future__ import annotations

import json
import time

import pytest

from spectra import config as scfg
from spectra.services import test_session

# Captured BEFORE the autouse fixture below replaces it, so the two tests
# that need the genuine wiring can still reach it.
_REAL_AUTO_SOURCES = test_session._auto_sources


@pytest.fixture(autouse=True)
def _quiet_auto_sources(monkeypatch):
    """Default every auto source to OFF so each test opts in to exactly the
    one it is about. Without this, an unrelated module's leftover module
    global could make a "no" test pass or fail for the wrong reason."""
    monkeypatch.setattr(test_session, "_auto_sources", lambda: [])


def _source(key="src", live=True, raises=False, detail=None):
    def probe():
        if raises:
            raise RuntimeError("probe exploded")
        return live
    return test_session.AutoSource(
        key=key, label=f"{key} is holding the room", probe=probe,
        detail=(lambda: detail))


# ── 1. the auto fold ────────────────────────────────────────────────────

def test_quiet_room_with_nothing_running_reads_no():
    st = test_session.status()
    assert st["testing"] == "no"
    assert st["sources"] == []
    assert st["declared"] is None
    assert st["readable"] is True


def test_each_auto_source_alone_lights_the_bar(monkeypatch):
    for key in ("preview_pause", "flare_preview_hold", "room_preview"):
        monkeypatch.setattr(test_session, "_auto_sources",
                            lambda k=key: [_source(k)])
        st = test_session.status()
        assert st["testing"] == "yes", key
        assert [s["key"] for s in st["sources"]] == [key]
        assert st["sources"][0]["kind"] == "auto"


def test_the_real_auto_sources_are_the_three_paths_that_have_held_his_room():
    """The fold must actually reach the real modules — a test that only
    ever runs against fakes would pass while the wiring is wrong."""
    keys = [s.key for s in _REAL_AUTO_SOURCES()]
    assert keys == ["preview_pause", "flare_preview_hold", "room_preview"]


def test_real_preview_pause_lights_the_bar_end_to_end(monkeypatch):
    """Through the REAL preview_pause module — the 14-minute hold's own
    path — not a stand-in, and its deadline shape clears it too."""
    monkeypatch.setattr(test_session, "_auto_sources", _REAL_AUTO_SOURCES)
    from spectra.services import preview_pause
    try:
        preview_pause.start(30.0)
        st = test_session.status()
        assert st["testing"] == "yes"
        assert "preview_pause" in [s["key"] for s in st["sources"]]
        preview_pause.clear()
        assert test_session.status()["testing"] == "no"
    finally:
        preview_pause.clear()


def test_a_live_source_still_shows_when_a_sibling_probe_explodes(monkeypatch):
    """A broken module must not hide a real hold — the live source is still
    reported (and the answer stays "yes", since a hold is proven)."""
    monkeypatch.setattr(test_session, "_auto_sources",
                        lambda: [_source("broken", raises=True), _source("live")])
    st = test_session.status()
    assert st["testing"] == "yes"
    assert [s["key"] for s in st["sources"]] == ["live"]


def test_a_detail_that_explodes_never_hides_the_source(monkeypatch):
    def boom():
        raise RuntimeError("detail exploded")
    src = _source("live")
    src.detail = boom
    monkeypatch.setattr(test_session, "_auto_sources", lambda: [src])
    st = test_session.status()
    assert st["testing"] == "yes"
    assert st["sources"][0]["detail"] is None


# ── 2. the declared take ────────────────────────────────────────────────

def test_declare_records_who_reason_and_since(tmp_path):
    rec = test_session.declare("firstmate", "live room proof", 600)
    assert rec["actor"] == "firstmate"
    assert rec["reason"] == "live room proof"
    assert rec["ttl_s"] == 600
    assert rec["expires_ms"] > rec["since_ms"]

    st = test_session.status()
    assert st["testing"] == "yes"
    assert st["declared"]["actor"] == "firstmate"
    assert st["since_ms"] == rec["since_ms"]
    assert [s["kind"] for s in st["sources"]] == ["declared"]
    assert "firstmate" in st["sources"][0]["label"]


def test_a_declaration_shows_with_no_auto_source_at_all():
    """The whole point of the declared half: work the app cannot see."""
    test_session.declare("an external agent", "driving fixtures", 60)
    st = test_session.status()
    assert st["testing"] == "yes"
    assert st["sources"] and st["sources"][0]["kind"] == "declared"


def test_renewing_the_same_actor_keeps_the_original_since():
    first = test_session.declare("firstmate", "proof", 60)
    time.sleep(0.01)
    second = test_session.declare("firstmate", "proof (still)", 60)
    assert second["since_ms"] == first["since_ms"]
    assert second["expires_ms"] > first["expires_ms"]


def test_a_different_actor_starts_a_fresh_since():
    """A second agent taking over is a NEW take — showing the first one's
    start time under the second one's name would misreport how long his
    room has been busy."""
    first = test_session.declare("agent-a", "proof", 60)
    time.sleep(0.01)
    second = test_session.declare("agent-b", "other proof", 60)
    assert second["since_ms"] > first["since_ms"]


def test_renewing_after_expiry_does_not_claim_the_old_start_time():
    now = time.time()
    test_session.declare("firstmate", "proof", 1)
    # Rewrite the stored record as long-expired, same actor.
    raw = json.loads(scfg.TEST_SESSION_FILE.read_text())
    raw["expires_ms"] = (now - 3600) * 1000.0
    raw["since_ms"] = (now - 7200) * 1000.0
    scfg.TEST_SESSION_FILE.write_text(json.dumps(raw))
    fresh = test_session.declare("firstmate", "proof again", 60)
    assert fresh["since_ms"] > raw["since_ms"]


def test_ttl_is_capped_and_floored():
    assert test_session.declare("a", "r", 10_000)["ttl_s"] == test_session.MAX_TTL_S
    assert test_session.declare("b", "r", 0.0001)["ttl_s"] == test_session.MIN_TTL_S


def test_blank_actor_and_reason_get_readable_fallbacks():
    rec = test_session.declare("   ", "", 60)
    assert rec["actor"] == "an agent"
    assert rec["reason"] == "live testing"


# ── 3. it clears itself ─────────────────────────────────────────────────

def test_an_expired_declaration_is_invisible_with_no_background_task():
    """The core anti-14-minute-hold property: expiry is evaluated AT READ.
    Nothing runs between the declare and the read here — no task, no sweep,
    no cleanup — and the record still stops showing."""
    test_session.declare("firstmate", "proof", 60)
    now_ms = time.time() * 1000.0
    assert test_session.status(now_ms=now_ms)["testing"] == "yes"
    assert test_session.status(now_ms=now_ms + 61_000)["testing"] == "no"


def test_expiry_is_evaluated_at_read_not_stamped_at_write():
    test_session.declare("firstmate", "proof", 5)
    later = time.time() * 1000.0 + 6_000
    rec, readable = test_session.declared(now_ms=later)
    assert rec is None and readable is True
    # ...and the file is still there, untouched — nothing pruned it.
    assert scfg.TEST_SESSION_FILE.exists()


def test_clear_drops_the_declaration_and_reports_whether_one_existed():
    assert test_session.clear() is False
    test_session.declare("firstmate", "proof", 60)
    assert test_session.clear() is True
    assert test_session.status()["testing"] == "no"


def test_a_declaration_survives_a_restart(monkeypatch):
    """Durable, not in-memory: a SPECTRA restart mid-test must not silently
    drop a live declaration and go quiet on him. Simulated by re-reading
    the store with every module global gone (there are none — the read is
    the file)."""
    test_session.declare("firstmate", "proof", 600)
    raw = json.loads(scfg.TEST_SESSION_FILE.read_text())
    assert raw["actor"] == "firstmate"
    assert test_session.status()["testing"] == "yes"


def test_the_write_is_atomic_leaving_no_tmp_files():
    test_session.declare("firstmate", "proof", 60)
    leftovers = [p.name for p in scfg.TEST_SESSION_FILE.parent.iterdir()
                 if p.name.endswith(".tmp")]
    assert leftovers == []


# ── 4. unknown is honest ────────────────────────────────────────────────

def test_an_unreadable_store_reports_unknown_never_no():
    scfg.TEST_SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    scfg.TEST_SESSION_FILE.write_text("{not json at all")
    st = test_session.status()
    assert st["testing"] == "unknown"
    assert st["readable"] is False


def test_a_record_with_no_usable_deadline_reports_unknown():
    """We cannot prove the declaration is expired, so we must not claim
    nobody is testing."""
    scfg.TEST_SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    scfg.TEST_SESSION_FILE.write_text(json.dumps(
        {"actor": "firstmate", "reason": "proof", "since_ms": 1}))
    assert test_session.status()["testing"] == "unknown"


def test_a_failing_probe_reports_unknown_when_nothing_else_proves_yes(monkeypatch):
    monkeypatch.setattr(test_session, "_auto_sources",
                        lambda: [_source("broken", raises=True)])
    st = test_session.status()
    assert st["testing"] == "unknown"
    assert st["readable"] is False


def test_auto_sources_failing_to_resolve_at_all_reports_unknown(monkeypatch):
    def boom():
        raise ImportError("module gone")
    monkeypatch.setattr(test_session, "_auto_sources", boom)
    assert test_session.status()["testing"] == "unknown"


def test_a_proven_hold_outranks_an_unreadable_store(monkeypatch):
    """"yes" is the strongest answer: if something IS demonstrably holding
    his room, an unrelated unreadable store must not soften that to
    "unknown"."""
    monkeypatch.setattr(test_session, "_auto_sources", lambda: [_source("live")])
    scfg.TEST_SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    scfg.TEST_SESSION_FILE.write_text("{broken")
    assert test_session.status()["testing"] == "yes"


def test_no_is_only_reached_on_positive_evidence_of_quiet(monkeypatch):
    """Belt-and-braces on the rule that matters most: every path that
    yields "no" must have had BOTH halves readable."""
    monkeypatch.setattr(test_session, "_auto_sources",
                        lambda: [_source("quiet", live=False)])
    st = test_session.status()
    assert st["testing"] == "no"
    assert st["readable"] is True


# ── the endpoint shapes ─────────────────────────────────────────────────

def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from spectra.api import test_session as router_mod
    app = FastAPI()
    app.include_router(router_mod.router)
    return TestClient(app)


def test_get_endpoint_shape():
    c = _client()
    body = c.get("/api/test-session").json()
    assert set(body) >= {"testing", "sources", "declared", "since_ms", "readable"}
    assert body["testing"] == "no"


def test_declare_endpoint_round_trips_and_clear_endpoint_drops_it():
    c = _client()
    r = c.post("/api/test-session/declare",
               json={"actor": "firstmate", "reason": "live proof", "ttl_s": 300})
    assert r.status_code == 200
    assert r.json()["declared"]["actor"] == "firstmate"
    assert r.json()["status"]["testing"] == "yes"

    assert c.get("/api/test-session").json()["testing"] == "yes"

    r = c.post("/api/test-session/clear")
    assert r.json()["cleared"] is True
    assert r.json()["status"]["testing"] == "no"


def test_declare_without_a_ttl_is_refused():
    """A declaration with no deadline is exactly the defect this feature
    exists to prevent — it must be impossible to create one."""
    c = _client()
    r = c.post("/api/test-session/declare",
               json={"actor": "firstmate", "reason": "live proof"})
    assert r.status_code == 422
    r = c.post("/api/test-session/declare",
               json={"actor": "firstmate", "reason": "p", "ttl_s": 0})
    assert r.status_code == 422


def test_the_router_is_registered_on_the_real_app():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    client = TestClient(create_app())
    assert client.get("/api/test-session").status_code == 200
    assert client.post("/api/test-session/clear").status_code == 200
