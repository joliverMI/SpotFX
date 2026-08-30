"""PUT /api/room-controls is a TRUE PARTIAL UPDATE — the regression proof.

THE DEFECT (established live 2026-08-30, real data loss): the handler bound
its request body straight to the full RoomControlState, so a body naming ONE
field silently reset every field it did not name to that field's model
default, and save_room_controls persisted the result. Two of the owner's own
values were confirmed wiped in his real storage/spectra/room_controls.json
this way — his av_sync_lead_ms calibration and his force_scene_scene_id pin.
It predates PR #214 and bites every partial caller: Home Assistant scripts,
curl operations, anything unenumerated.

The proofs, in the captain's own order:
  (a) a partial PUT naming one field preserves every other STORED field
      byte-for-byte — RED against the pre-fix handler, green after.
  (b) the retired `ambient_mode` alias maps all three values onto the
      binary pair.
  (c) a body carrying both dialects: the NEW key wins, and the response
      names the conflict.
  (d) a full-body PUT (the web UI's own shape) behaves exactly as before —
      byte-identical stored result.
  (e) the reconcilers still see the TRUE previous state: they fire on a
      genuine change and stay silent on a no-op.

No LedFX I/O, no audio hardware, no live storage.
"""
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


def _seed_a_lived_in_room() -> dict:
    """His shape, not a bare default: a calibrated A/V lead, a Force Scene
    pin, a Force Colour pin, a dimmed room, a picked ambient area — exactly
    the class of value the defect ate."""
    from spectra.services import room_controls as rc
    state = rc.RoomControlState(
        display_mode="dark",
        brightness_multiplier=0.6,
        ambient_enabled=True,
        ambient_on_music_pause=False,
        ambient_color="#f5da8c",
        ambient_color_dark="#8b7e53",
        ambient_hue_group_ids=["dining-hues"],
        global_transition_ms=1200,
        scene_change_mode="triggers_only",
        av_sync_lead_ms=-38,
        force_scene_enabled=True,
        force_scene_scene_id="scene-abc",
        force_color_enabled=True,
        force_color_target_id="set-xyz",
        rainbow_select_limit=0.8,
    )
    rc.save_room_controls(state)
    return _stored()


# ── (a) the whole point: a partial PUT preserves everything else ──────────

def test_partial_put_preserves_every_unnamed_field_byte_for_byte():
    before = _seed_a_lived_in_room()
    resp = _client().put("/api/room-controls", json={"brightness_multiplier": 0.4})
    assert resp.status_code == 200, resp.text
    after = _stored()

    assert after["brightness_multiplier"] == 0.4, "the named field is applied"
    changed = {k for k in before if before[k] != after.get(k)}
    assert changed == {"brightness_multiplier"}, \
        ("a partial PUT must touch ONLY the field it names — these were "
         f"silently rewritten: {sorted(changed - {'brightness_multiplier'})}")
    assert set(after) == set(before), "no key appears or disappears"

    # The two values his real file actually lost, named explicitly so a
    # future regression reads as the incident it is, not a diff.
    assert after["av_sync_lead_ms"] == -38, "his A/V calibration survived"
    assert after["force_scene_scene_id"] == "scene-abc", "his Force Scene pin survived"
    assert resp.json()["av_sync_lead_ms"] == -38, \
        "the response echoes the MERGED state, not the caller's fragment"


def test_partial_put_of_a_single_pin_leaves_the_rest_alone():
    """The operational restore shape: naming force_scene_scene_id alone must
    not disturb the A/V lead sitting next to it (and vice versa)."""
    _seed_a_lived_in_room()
    client = _client()
    client.put("/api/room-controls", json={"force_scene_scene_id": "scene-def"})
    client.put("/api/room-controls", json={"av_sync_lead_ms": -38})
    after = _stored()
    assert after["force_scene_scene_id"] == "scene-def"
    assert after["av_sync_lead_ms"] == -38
    assert after["brightness_multiplier"] == 0.6
    assert after["ambient_color"] == "#f5da8c"


def test_an_empty_body_changes_nothing():
    before = _seed_a_lived_in_room()
    assert _client().put("/api/room-controls", json={}).status_code == 200
    assert _stored() == before, "a body naming nothing must write nothing new"


def test_an_unknown_key_is_ignored_and_never_stored():
    before = _seed_a_lived_in_room()
    resp = _client().put("/api/room-controls",
                         json={"brightness_multiplier": 0.4, "not_a_field": 7})
    assert resp.status_code == 200, resp.text
    after = _stored()
    assert "not_a_field" not in after
    assert set(after) == set(before)


def test_a_bad_value_is_refused_and_nothing_is_stored():
    before = _seed_a_lived_in_room()
    resp = _client().put("/api/room-controls", json={"brightness_multiplier": 9.0})
    assert resp.status_code == 422, resp.text
    assert _stored() == before, "a refused PUT must leave the file untouched"

    assert _client().put("/api/room-controls", json=["not", "an", "object"]
                         ).status_code == 422
    assert _stored() == before


# ── (b) the alias: all three retired ambient_mode values ─────────────────

@pytest.mark.parametrize("mode,enabled,on_pause", [
    ("always", True, False),
    ("off", False, False),
    ("auto", False, True),
])
def test_ambient_mode_alias_maps_all_three_values(mode, enabled, on_pause, monkeypatch):
    """"auto" IS the music-pause behaviour, so a caller naming it gets it.
    That is the ONE place this alias differs from PR #214's disk migration,
    which forced ambient_on_music_pause False even for "auto" — a one-time
    owner ruling about his STORED state ("set it to false for now"), not
    about what a caller explicitly asks for now."""
    _no_live_ambient(monkeypatch)
    _seed_a_lived_in_room()
    resp = _client().put("/api/room-controls", json={"ambient_mode": mode})
    assert resp.status_code == 200, resp.text
    after = _stored()
    assert after["ambient_enabled"] is enabled
    assert after["ambient_on_music_pause"] is on_pause
    assert "ambient_mode" not in after, "the alias is a PUT-path translation, never stored"
    assert resp.json()["ambient_mode_alias"]["received"] == mode
    # And it is still a partial update — the alias names ambient only.
    assert after["av_sync_lead_ms"] == -38
    assert after["force_scene_scene_id"] == "scene-abc"


def test_an_unusable_ambient_mode_value_is_refused(monkeypatch):
    before = _seed_a_lived_in_room()
    resp = _client().put("/api/room-controls", json={"ambient_mode": "sometimes"})
    assert resp.status_code == 422, resp.text
    assert _stored() == before


# ── (c) both dialects in one body: the NEW key wins ──────────────────────

def test_new_key_wins_over_the_alias_and_the_response_says_so(monkeypatch):
    _no_live_ambient(monkeypatch)
    _seed_a_lived_in_room()
    resp = _client().put("/api/room-controls",
                         json={"ambient_mode": "always", "ambient_enabled": False})
    assert resp.status_code == 200, resp.text
    assert _stored()["ambient_enabled"] is False, "the new key wins the field"
    note = resp.json()["ambient_mode_alias"]
    assert note["ignored_from_alias"] == ["ambient_enabled"]
    assert "ambient_mode" in note["conflict"] and "new key wins" in note["conflict"]


def test_the_alias_still_fills_a_field_the_new_dialect_left_out(monkeypatch):
    """Per-field precedence, not all-or-nothing: "auto" names two fields, so
    an explicit ambient_enabled takes that one and the alias still supplies
    the music-pause half."""
    _no_live_ambient(monkeypatch)
    _seed_a_lived_in_room()
    resp = _client().put("/api/room-controls",
                         json={"ambient_mode": "auto", "ambient_enabled": True})
    assert resp.status_code == 200, resp.text
    after = _stored()
    assert after["ambient_enabled"] is True
    assert after["ambient_on_music_pause"] is True


# ── (d) the web UI's own shape is unchanged ──────────────────────────────

def test_a_full_body_put_is_byte_identical_to_the_old_whole_object_bind(monkeypatch):
    """The frontend round-trips the whole object (spectra/web/src/queries.ts
    useSaveRoomControls). A full body overlays every key, so the merge
    cannot change what it stores — proven against the model's own
    serialization of the same payload, which is exactly what the pre-fix
    handler wrote."""
    from spectra.services import room_controls as rc
    _no_live_ambient(monkeypatch)
    _seed_a_lived_in_room()

    body = rc.RoomControlState(
        display_mode="light",
        display_light_bg_color="#201830",
        display_light_bg_brightness=0.25,
        brightness_multiplier=0.9,
        ambient_enabled=False,
        ambient_color="#112233",
        global_transition_ms=800,
        scene_change_mode="full",
        av_sync_lead_ms=12,
        force_scene_enabled=False,
        force_scene_scene_id=None,
        rainbow_select_limit=0.7,
    ).model_dump()

    resp = _client().put("/api/room-controls", json=body)
    assert resp.status_code == 200, resp.text
    assert "ambient_mode_alias" not in resp.json()

    merged = _stored()
    expected = json.loads(rc.RoomControlState.model_validate(body).model_dump_json())
    assert merged == expected, \
        "a whole-object PUT must store exactly what the old bind stored"


# ── (e) the reconcilers still see the TRUE previous state ────────────────

def _no_live_ambient(monkeypatch):
    """The ambient reconcile's leaf effect, stubbed — this file proves the
    change DETECTION, not the Hue takeover (tests/test_ambient_transition.py
    owns that)."""
    calls: list[dict] = []
    from spectra.services import ambient_music_gate

    async def _fake(*, wait: bool = True):
        calls.append({"wait": wait})
        return {"status": "turning_on", "intent": "on", "phase": "turning_on"}

    monkeypatch.setattr(ambient_music_gate, "reconcile_now", _fake)
    return calls


def test_a_partial_put_that_genuinely_changes_ambient_still_reconciles(monkeypatch):
    calls = _no_live_ambient(monkeypatch)
    _seed_a_lived_in_room()          # ambient_enabled=True on disk
    resp = _client().put("/api/room-controls", json={"ambient_enabled": False})
    assert resp.status_code == 200, resp.text
    assert len(calls) == 1, "a genuine ambient change must reconcile"
    assert "ambient_result" in resp.json()


def test_a_partial_put_that_does_not_touch_ambient_stays_silent(monkeypatch):
    calls = _no_live_ambient(monkeypatch)
    _seed_a_lived_in_room()
    resp = _client().put("/api/room-controls", json={"brightness_multiplier": 0.4})
    assert resp.status_code == 200, resp.text
    assert calls == [], "an unrelated field must not churn the Hue stream"
    assert "ambient_result" not in resp.json()


def test_re_sending_the_same_ambient_value_is_a_no_op(monkeypatch):
    """The merge must compare against the TRUE previous state — under the
    pre-fix handler a partial body's unnamed fields arrived as defaults, so
    "did this change" was answered against a fiction."""
    calls = _no_live_ambient(monkeypatch)
    _seed_a_lived_in_room()          # ambient_enabled=True, colour #f5da8c
    resp = _client().put("/api/room-controls",
                         json={"ambient_enabled": True, "ambient_color": "#f5da8c"})
    assert resp.status_code == 200, resp.text
    assert calls == [], "re-sending what is already stored must reconcile nothing"


def test_dark_light_reconciles_on_a_genuine_change_only(monkeypatch):
    _no_live_ambient(monkeypatch)
    seen: list[str] = []
    from spectra.services import dark_light

    async def _fake(mode, cats, virts, bg="#201830", bright=0.3):
        seen.append(mode)
        return {"status": "ok", "mode": mode}

    monkeypatch.setattr(dark_light, "reconcile", _fake)
    _seed_a_lived_in_room()          # display_mode="dark" on disk

    client = _client()
    assert client.put("/api/room-controls",
                      json={"brightness_multiplier": 0.4}).status_code == 200
    assert seen == [], "an unrelated field must not repaint the room"

    resp = client.put("/api/room-controls", json={"display_mode": "default"})
    assert resp.status_code == 200, resp.text
    assert seen == ["default"]
    assert "dark_light_result" in resp.json()


def test_force_scene_fires_on_its_own_edit_and_not_on_an_unrelated_one(monkeypatch):
    """Also the sharpest statement of the defect: under the pre-fix handler
    the second PUT reset force_scene_enabled to False outright."""
    _no_live_ambient(monkeypatch)
    from spectra.services import room_controls as rc
    rc.save_room_controls(rc.RoomControlState(force_scene_enabled=False,
                                              av_sync_lead_ms=-38))
    client = _client()

    first = client.put("/api/room-controls", json={"force_scene_enabled": True})
    assert first.status_code == 200, first.text
    assert first.json()["force_scene_result"] == {"status": "skipped",
                                                  "reason": "no scene pinned"}, \
        "enabling the pin is its own edit — it always states an outcome"

    second = client.put("/api/room-controls", json={"brightness_multiplier": 0.5})
    assert second.status_code == 200, second.text
    assert "force_scene_result" not in second.json(), \
        "an unrelated field must not re-fire the pin"
    after = _stored()
    assert after["force_scene_enabled"] is True, "the pin survived the unrelated save"
    assert after["av_sync_lead_ms"] == -38
