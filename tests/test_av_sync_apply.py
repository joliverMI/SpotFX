"""The AV-sync APPLY flow (owner ask 2026-08-28): the four holds, offline.

The measured number becoming a setting is where a sign error would cost
him a real evening, so every claim the dialogue makes to him is pinned
here:

  1. NOTHING TO APPLY WITHOUT A NUMBER — a refused estimate carries the
     instrument's own reason forward and offers no proposed value.
  2. ENOUGH TO DECIDE — the wobble, the named directional systematics and
     the recent runs are separate fields, never one blended figure.
  3. CURRENT vs PROPOSED, DIRECTION SPELLED OUT — both directions, and
     "none yet" for a room that has never been calibrated (never a
     borrowed number from a setting that does a different job).
  4. APPLY IS HIS PRESS — the write goes through PUT /api/room-controls,
     the established save path, and survives a read-back.

The lead's actual effect on the lights is a different and harder claim,
measured on the real render pipeline in tests/test_av_sync_lead_landing.py.
Nothing here touches his room or his storage.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.services import av_sync_session as sessions
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(scfg, "ROOM_COLOR_FILE", tmp_path / "room_color.json")
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(scfg, "AV_SYNC_MEASUREMENTS_FILE", tmp_path / "m.json")
    monkeypatch.setattr(scfg, "AV_SYNC_PATTERN_FILE", tmp_path / "p.json")
    sessions.current = None
    yield
    sessions.current = None


def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


def _est(av_offset_ms, *, ok=True, reason="", sigma=8.0):
    return {"ok": ok, "av_offset_ms": av_offset_ms, "sigma_ms": sigma,
            "systematic_later_ms": 22.0, "systematic_earlier_ms": 14.0,
            "systematic_bound_ms": 36.0,
            "systematics": [{"term": "camera exposure", "bound_ms": 16.0,
                             "direction": "lights_look_later",
                             "depends_on": "phone"}],
            "reason": reason, "statement": "a statement"}


# ── hold 1: nothing to apply without a number ──────────────────────────────

@pytest.mark.parametrize("reason", ["weak", "ambiguous", "unstable", "no_data",
                                    "clock", "audio", "light"])
def test_a_refused_estimate_offers_no_apply_and_keeps_its_own_reason(reason):
    from spectra.services import av_sync_lead

    prop = av_sync_lead.proposal(_est(None, ok=False, reason=reason, sigma=None),
                                 current=None)
    assert prop.applicable is False, "a refused measurement must offer no apply path"
    assert prop.proposed_lead_ms is None and prop.delta_ms is None
    assert prop.direction_sentence == ""
    assert prop.reason == reason, "the instrument's own reason must survive"


def test_an_ok_flag_without_a_number_is_still_a_refusal():
    """Belt and braces: applicable is gated on BOTH ok and a real number,
    so a future estimate shape that sets one without the other cannot
    produce a proposal out of None."""
    from spectra.services import av_sync_lead
    prop = av_sync_lead.proposal(_est(None, ok=True), current=None)
    assert prop.applicable is False and prop.proposed_lead_ms is None


def test_no_measurement_at_all_is_stated_not_guessed():
    from spectra.services import av_sync_lead
    prop = av_sync_lead.proposal(None, current=50)
    assert prop.applicable is False
    assert prop.reason == "no_measurement"
    assert prop.current_lead_ms == 50, "the current setting is still reported"


def test_a_refusal_never_falls_back_to_a_previous_runs_number():
    """The dangerous shortcut this rules out: offering the last good run's
    value when tonight's refuses. Recent runs are shown for CONTEXT; they
    are never promoted into a proposal."""
    from spectra.services import av_sync_lead
    recent = av_sync_lead.recent_runs([
        {"id": "a", "ok": True, "av_offset_ms": 130.0, "sigma_ms": 5.0},
    ])
    prop = av_sync_lead.proposal(_est(None, ok=False, reason="weak"),
                                 current=None, recent=recent)
    assert prop.applicable is False
    assert prop.proposed_lead_ms is None
    assert prop.recent and prop.recent[0]["av_offset_ms"] == 130.0


# ── hold 3: the sign translation, both directions ──────────────────────────

def test_lights_behind_proposes_firing_earlier():
    """The conventions-row worked example, direction one: measured +120
    (lights BEHIND the sound) on an uncalibrated room."""
    from spectra.services import av_sync_lead
    prop = av_sync_lead.proposal(_est(120.0), current=None)
    assert prop.applicable is True
    assert prop.proposed_lead_ms == 120
    assert prop.delta_ms == 120
    assert prop.direction_sentence == "Lights will fire 120 ms EARLIER than they do now."


def test_lights_ahead_proposes_firing_later():
    """Direction two, the half a one-sided proof would miss: measured -45
    (lights AHEAD) on a room already carrying +120."""
    from spectra.services import av_sync_lead
    prop = av_sync_lead.proposal(_est(-45.0), current=120)
    assert prop.applicable is True
    assert prop.proposed_lead_ms == 75
    assert prop.delta_ms == -45
    assert prop.direction_sentence == "Lights will fire 45 ms LATER than they do now."


def test_the_measurement_is_added_to_the_current_lead_never_assigned():
    """The whole reason the translation is not `proposed = measured`:
    assigning would silently undo an earlier calibration on every
    re-measure."""
    from spectra.services import av_sync_lead
    prop = av_sync_lead.proposal(_est(120.0), current=50)
    assert prop.proposed_lead_ms == 170, "a residual must add to what is already applied"
    assert prop.delta_ms == 120


def test_a_measurement_of_zero_says_so_rather_than_inventing_a_change():
    from spectra.services import av_sync_lead
    prop = av_sync_lead.proposal(_est(0.2), current=90)
    assert prop.proposed_lead_ms == 90 and prop.delta_ms == 0
    assert "No change" in prop.direction_sentence


def test_a_proposal_past_the_settings_own_bound_is_named_not_silently_clamped():
    from spectra.services import av_sync_lead
    prop = av_sync_lead.proposal(_est(1500.0), current=900)
    assert prop.applicable is False, "an out-of-range proposal must not be appliable"
    assert prop.out_of_range is True and prop.reason == "out_of_range"
    assert prop.proposed_lead_ms == av_sync_lead.LEAD_MAX_MS


def test_the_direction_sentence_is_never_a_bare_delta():
    """Hold 3 in one assertion: whatever the sign, the sentence names the
    lights, the direction IN WORDS, and the reference point."""
    from spectra.services import av_sync_lead
    for delta in (-400, -1, 1, 400):
        sentence = av_sync_lead.direction_sentence(delta)
        assert "Lights will fire" in sentence
        assert ("EARLIER" in sentence) == (delta > 0)
        assert ("LATER" in sentence) == (delta < 0)
        assert "than they do now" in sentence


# ── hold 3: current shows NONE YET, never a borrowed number ────────────────

def test_an_uncalibrated_room_reports_none_yet_not_zero():
    from spectra.services import av_sync_lead
    from spectra.services.room_controls import RoomControlState

    assert RoomControlState().av_sync_lead_ms is None, (
        "the shipped default must be None — nothing changes until his first apply")
    phrase = av_sync_lead.current_phrase(None)
    assert "none yet" in phrase
    assert "0" not in phrase, "None must never render as a 0 ms measurement"


def test_a_deliberate_zero_reads_differently_from_never_calibrated():
    from spectra.services import av_sync_lead
    assert av_sync_lead.current_phrase(0) != av_sync_lead.current_phrase(None)
    assert "no shift" in av_sync_lead.current_phrase(0)


def test_current_phrase_spells_the_direction_of_an_existing_lead():
    from spectra.services import av_sync_lead
    assert "earlier" in av_sync_lead.current_phrase(120)
    assert "later" in av_sync_lead.current_phrase(-120)


def test_nothing_in_the_apply_path_reads_the_spot_effects_offsets():
    """His remembered "150" is settings.audio_latency_ms (capture
    alignment) and the legacy buffer holds an inert -800. Neither is a
    previous value of this setting, and the apply path must never borrow
    one — structurally it cannot: spectra/ may not import spot-effects
    (scripts/check_process_split.py §1). Pinned here so a future edit that
    "helpfully" seeds a default from one fails loudly."""
    import pathlib
    src = pathlib.Path("spectra/services/av_sync_lead.py").read_text()
    body = src.split('"""', 2)[2]     # past the module docstring, which
                                      # names them on purpose
    for forbidden in ("audio_latency_ms", "ledfx_trigger_buffer_ms",
                      "from config", "import config"):
        assert forbidden not in body, f"apply path must not reach {forbidden}"


# ── hold 2: enough to decide, not one figure ───────────────────────────────

def test_wobble_systematics_and_recent_runs_are_separate_fields():
    from spectra.services import av_sync_lead
    prop = av_sync_lead.proposal(_est(120.0), current=None).as_dict()
    assert prop["sigma_ms"] == 8.0
    assert prop["systematic_later_ms"] == 22.0
    assert prop["systematic_earlier_ms"] == 14.0
    assert prop["systematics"][0]["term"] == "camera exposure"
    assert prop["sigma_ms"] != prop["systematic_later_ms"], (
        "statistical wobble and directional systematics must never be blended")


def test_a_stored_record_carries_its_systematic_bound_rather_than_zero():
    """A stored measurement keeps only the TOTAL bound. Reporting zero
    directional uncertainty for it would understate the number — the one
    direction this dialogue must not err in."""
    from spectra.services import av_sync_lead
    stored = {"ok": True, "av_offset_ms": 60.0, "sigma_ms": 4.0,
              "systematic_bound_ms": 30.0, "statement": ""}
    prop = av_sync_lead.proposal(stored, current=None)
    assert prop.systematic_later_ms == 30.0 and prop.systematic_earlier_ms == 30.0


def test_recent_runs_are_newest_first_and_keep_refused_runs():
    from spectra.services import av_sync_lead
    rows = av_sync_lead.recent_runs([
        {"id": "1", "ok": True, "av_offset_ms": 100.0, "sigma_ms": 5.0},
        {"id": "2", "ok": False, "av_offset_ms": None, "sigma_ms": None},
        {"id": "3", "ok": True, "av_offset_ms": 130.0, "sigma_ms": 6.0},
    ])
    assert [r["id"] for r in rows] == ["3", "2", "1"], "newest first"
    assert rows[1]["ok"] is False, "a refused run is itself information, kept"


def test_recent_runs_are_capped_at_the_display_limit():
    from spectra.services import av_sync_lead
    many = [{"id": str(i), "ok": True, "av_offset_ms": float(i), "sigma_ms": 1.0}
            for i in range(40)]
    rows = av_sync_lead.recent_runs(many)
    assert len(rows) == av_sync_lead.RECENT_RUNS
    assert rows[0]["id"] == "39", "the cap keeps the newest, not the oldest"


def test_spread_needs_two_numbers_and_ignores_refused_runs():
    from spectra.services import av_sync_lead
    one = av_sync_lead.recent_runs([{"id": "1", "ok": True, "av_offset_ms": 100.0}])
    assert av_sync_lead.spread_ms(one) is None
    mixed = av_sync_lead.recent_runs([
        {"id": "1", "ok": True, "av_offset_ms": 100.0},
        {"id": "2", "ok": False, "av_offset_ms": None},
        {"id": "3", "ok": True, "av_offset_ms": 118.0},
    ])
    assert av_sync_lead.spread_ms(mixed) == 18.0


# ── the clock half: the sign law at the seam ───────────────────────────────

def test_show_clock_applies_the_lead_in_the_lead_direction():
    from spectra.services import av_sync_lead
    assert av_sync_lead.show_clock_ms(10_000, 120) == 10_120, (
        "positive lead => position reads further along => fires earlier")
    assert av_sync_lead.show_clock_ms(10_000, -120) == 9_880
    assert av_sync_lead.show_clock_ms(10_000, None) == 10_000
    assert av_sync_lead.show_clock_ms(10_000, 0) == 10_000


def test_a_missing_position_is_never_invented_from_a_lead():
    from spectra.services import av_sync_lead
    assert av_sync_lead.show_clock_ms(None, 500) is None


def test_the_engine_applies_the_lead_at_exactly_one_place():
    """Hold 3 of the decision: one application point, so no second path can
    quietly disagree. Pinned by source inspection because the cost of a
    second one is silent."""
    import pathlib
    hits = []
    for path in pathlib.Path("spectra").rglob("*.py"):
        if path.name == "av_sync_lead.py":
            continue
        if "show_clock_ms(" in path.read_text():
            hits.append(str(path))
    assert hits == ["spectra/services/engine.py"], (
        f"the lead must be applied in exactly one place, found: {hits}")


# ── hold 4: apply is his press, through the established save path ─────────

def test_the_write_goes_through_room_controls_and_reads_back():
    from spectra.services import av_sync_lead

    client = _client()
    before = client.get("/api/room-controls").json()
    assert before["av_sync_lead_ms"] is None, "a fresh room is uncalibrated"

    state = dict(before)
    state["av_sync_lead_ms"] = 120
    put = client.put("/api/room-controls", json=state)
    assert put.status_code == 200
    assert put.json()["av_sync_lead_ms"] == 120

    # THE READ-BACK: a save that returns its own echo proves nothing.
    after = client.get("/api/room-controls").json()
    assert after["av_sync_lead_ms"] == 120
    assert av_sync_lead.current_lead_ms() == 120, (
        "the value the show clock reads must be the value he saved")


def test_applying_moves_only_that_one_field():
    """HIS DATA: one setting on his press, nothing else."""
    client = _client()
    before = client.get("/api/room-controls").json()
    state = dict(before)
    state["av_sync_lead_ms"] = -75
    client.put("/api/room-controls", json=state)
    after = client.get("/api/room-controls").json()
    changed = {k for k in after if after[k] != before.get(k)}
    assert changed == {"av_sync_lead_ms"}


def test_the_previous_value_can_be_put_back_the_same_way():
    """The undo affordance, in room-controls' own conventions (a second
    explicit press through the same path — this surface has no change
    log)."""
    client = _client()
    state = dict(client.get("/api/room-controls").json())
    state["av_sync_lead_ms"] = 200
    client.put("/api/room-controls", json=state)
    state["av_sync_lead_ms"] = None
    client.put("/api/room-controls", json=state)
    assert client.get("/api/room-controls").json()["av_sync_lead_ms"] is None


def test_the_setting_refuses_a_value_past_its_declared_bound():
    from pydantic import ValidationError
    from spectra.services.room_controls import RoomControlState
    with pytest.raises(ValidationError):
        RoomControlState(av_sync_lead_ms=9000)


def test_the_lead_is_not_agent_tellable():
    """Excluded from Sonic on force_scene_*'s precedent: a measured
    calibration belongs to the instrument that measured it."""
    from spectra.services.settings_console import SETTINGS_REGISTRY
    assert "av_sync_lead_ms" not in SETTINGS_REGISTRY


# ── the proposal endpoint ─────────────────────────────────────────────────

def test_the_proposal_endpoint_refuses_before_any_measurement_exists():
    client = _client()
    body = client.get("/api/av-sync/apply-proposal").json()
    assert body["applicable"] is False
    assert body["reason"] == "no_measurement"
    assert body["source"] == "none"
    assert body["current_phrase"].startswith("none yet")


def test_the_proposal_endpoint_reads_the_newest_stored_run():
    from spectra.services import av_sync_session as sessions

    for offset in (90.0, 118.0):
        sessions.append_measurement(
            {"id": f"r{offset}", "at_iso": "2026-08-28T00:00:00+0000",
             "mode": "pattern", "ok": True, "av_offset_ms": offset,
             "sigma_ms": 6.0, "systematic_bound_ms": 20.0, "statement": "s",
             "reason": ""})
    client = _client()
    body = client.get("/api/av-sync/apply-proposal").json()
    assert body["source"] == "stored"
    assert body["applicable"] is True
    assert body["proposed_lead_ms"] == 118
    assert body["direction_sentence"].endswith("EARLIER than they do now.")
    assert [r["av_offset_ms"] for r in body["recent"]] == [118.0, 90.0]
    assert body["spread_ms"] == 28.0
    assert "two runs" in body["two_runs_note"].lower()


def test_the_proposal_endpoint_composes_with_an_already_applied_lead():
    """End to end over the wire: apply once, measure a residual, and the
    next proposal builds on the applied value rather than replacing it."""
    from spectra.services import av_sync_session as sessions

    client = _client()
    state = dict(client.get("/api/room-controls").json())
    state["av_sync_lead_ms"] = 118
    client.put("/api/room-controls", json=state)

    sessions.append_measurement(
        {"id": "resid", "at_iso": "2026-08-28T00:01:00+0000", "mode": "pattern",
         "ok": True, "av_offset_ms": -18.0, "sigma_ms": 5.0,
         "systematic_bound_ms": 20.0, "statement": "s", "reason": ""})
    body = client.get("/api/av-sync/apply-proposal").json()
    assert body["current_lead_ms"] == 118
    assert body["proposed_lead_ms"] == 100
    assert body["direction_sentence"] == "Lights will fire 18 ms LATER than they do now."
