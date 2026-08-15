"""The settings-console MECHANISM + AUTHORITY BOUNDARY (standing order 5) —
offline proof, no network, no ANTHROPIC_API_KEY required for the bulk of
this file.

The proofs:
  1. SETTINGS_REGISTRY is a real, explicit allowlist — every key exists on
     RoomControlState and carries the SAME bounds RoomControlState enforces.
  2. validate_change/apply_change reject an unknown key, an out-of-range
     value (with the legal range + nearest legal value surfaced), and a
     malformed hex colour — nothing persists on rejection.
  3. apply_change persists through room_controls' own store + ambient
     reconcile (the same calls the human PUT handler makes) and leaves a
     visible, bounded change-log entry; undo reverts through the SAME
     validated path and marks the original entry undone.
  4. settings_agent._dispatch is the WHOLE tool-name -> code mapping: only
     "get_settings" and "set_setting" do anything; any other name is
     rejected without touching storage — proof the boundary is structural,
     not a prompt instruction, and provable without a live model call.
  5. The API layer: registry/log/undo/message/transcribe all respond
     correctly offline, including the 503s a missing ANTHROPIC_API_KEY /
     unwired transcriber produce.

One test (test_live_model_can_apply_a_change) additionally proves the real
tool loop against the live Anthropic API — SKIPPED here (no
ANTHROPIC_API_KEY in this sandbox); it would run this exact suite's own
assertions against a real model when a key is present.
"""
from __future__ import annotations

import asyncio
import os

import pytest


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(scfg, "SETTINGS_LOG_FILE", tmp_path / "settings_log.json")
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(scfg, "COLOR_SETS_FILE", tmp_path / "color_sets.json")

    from spectra.services import settings_agent
    settings_agent._SESSIONS.clear()


# ═══ 1. registry ═════════════════════════════════════════════════════════

def test_registry_is_an_explicit_allowlist_matching_room_control_bounds():
    from spectra.services import room_controls as rc
    from spectra.services import settings_console as sc

    assert set(sc.SETTINGS_REGISTRY) == {
        "brightness_multiplier", "global_transition_ms",
        "ambient_enabled", "ambient_color", "scene_change_mode",
    }
    # force_scene_* deliberately excluded — see settings_console.py docstring
    assert "force_scene_enabled" not in sc.SETTINGS_REGISTRY
    assert "force_scene_scene_id" not in sc.SETTINGS_REGISTRY

    spec = sc.SETTINGS_REGISTRY["brightness_multiplier"]
    ge, le = rc.field_bounds("brightness_multiplier")
    assert (spec.min, spec.max) == (ge, le) == (0.0, 1.0), \
        "registry bounds are READ from RoomControlState, not re-typed"

    assert sc.SETTINGS_REGISTRY["scene_change_mode"].choices == \
        ["transitions", "analysed", "full"]


# ═══ 2. validation rejects, nothing persists ════════════════════════════

def test_unknown_key_rejected():
    from spectra.services import settings_console as sc

    with pytest.raises(sc.SettingChangeError) as exc:
        sc.validate_change("force_scene_enabled", True)
    assert "allowed_keys" in exc.value.detail
    assert "force_scene_enabled" not in exc.value.detail["allowed_keys"]


def test_out_of_range_rejected_with_nearest_legal_value():
    from spectra.services import settings_console as sc

    with pytest.raises(sc.SettingChangeError) as exc:
        sc.validate_change("brightness_multiplier", 2.0)
    assert exc.value.detail["nearest_legal_value"] == 1.0

    with pytest.raises(sc.SettingChangeError) as exc:
        sc.validate_change("global_transition_ms", -500)
    assert exc.value.detail["nearest_legal_value"] == 0


def test_bad_enum_and_bad_hex_rejected():
    from spectra.services import settings_console as sc

    with pytest.raises(sc.SettingChangeError):
        sc.validate_change("scene_change_mode", "sometimes")
    with pytest.raises(sc.SettingChangeError):
        sc.validate_change("ambient_color", "chartreuse")
    with pytest.raises(sc.SettingChangeError):
        sc.validate_change("ambient_color", "#zzzzzz")


def test_rejection_never_writes(tmp_path):
    from spectra import config as scfg
    from spectra.services import settings_console as sc

    with pytest.raises(sc.SettingChangeError):
        sc.validate_change("brightness_multiplier", 5.0)
    assert not scfg.ROOM_CONTROLS_FILE.exists()
    assert not scfg.SETTINGS_LOG_FILE.exists()


# ═══ 3. apply_change + log + undo ════════════════════════════════════════

def test_apply_change_persists_and_logs():
    from spectra.services import room_controls as rc
    from spectra.services import settings_console as sc

    result = _run(sc.apply_change("brightness_multiplier", 0.4))
    assert result["status"] == "applied"
    assert result["old_value"] == 1.0 and result["new_value"] == 0.4
    assert rc.load_room_controls().brightness_multiplier == 0.4

    log = sc.load_log()
    assert len(log) == 1 and log[0]["key"] == "brightness_multiplier"
    assert log[0]["source"] == "agent" and log[0]["undone"] is False


def test_apply_change_reconciles_ambient_only_on_ambient_fields():
    from spectra.services import settings_console as sc

    result = _run(sc.apply_change("brightness_multiplier", 0.6))
    assert "ambient_result" not in result, \
        "unrelated field change must not trigger a reconnect"

    result = _run(sc.apply_change("ambient_enabled", True))
    assert result["ambient_result"]["status"] == "dark", \
        "no live stack owned in tests — the same safe no-op PUT gets"


def test_undo_reverts_through_the_validated_path():
    from spectra.services import room_controls as rc
    from spectra.services import settings_console as sc

    _run(sc.apply_change("brightness_multiplier", 0.9))
    _run(sc.apply_change("brightness_multiplier", 0.2))
    assert rc.load_room_controls().brightness_multiplier == 0.2

    undone = _run(sc.undo_last_change())
    assert undone["new_value"] == 0.9
    assert rc.load_room_controls().brightness_multiplier == 0.9

    log = sc.load_log()
    assert log[0]["source"] == "undo" and log[0]["new_value"] == 0.9
    assert log[1]["undone"] is True, "the reverted entry is marked, not deleted"


def test_undo_with_empty_log_rejected():
    from spectra.services import settings_console as sc

    with pytest.raises(sc.SettingChangeError):
        _run(sc.undo_last_change())


# ═══ 4. the tool-dispatch boundary itself ════════════════════════════════

def test_dispatch_recognizes_exactly_two_tools():
    from spectra.services import settings_agent as sa

    assert {t["name"] for t in sa.TOOLS} == {"get_settings", "set_setting"}


def test_dispatch_get_settings_is_read_only():
    from spectra import config as scfg
    from spectra.services import settings_agent as sa

    result = _run(sa._dispatch("get_settings", {}))
    assert "settings" in result
    assert not scfg.ROOM_CONTROLS_FILE.exists(), "a read never creates the store"


def test_dispatch_set_setting_applies_a_valid_change():
    from spectra.services import room_controls as rc
    from spectra.services import settings_agent as sa

    result = _run(sa._dispatch("set_setting", {"key": "brightness_multiplier", "value": 0.3}))
    assert result["status"] == "applied"
    assert rc.load_room_controls().brightness_multiplier == 0.3


def test_dispatch_set_setting_rejects_disallowed_key_without_writing():
    from spectra import config as scfg
    from spectra.services import settings_agent as sa

    result = _run(sa._dispatch("set_setting", {"key": "force_scene_enabled", "value": True}))
    assert result["status"] == "rejected"
    assert not scfg.ROOM_CONTROLS_FILE.exists()


def test_dispatch_unknown_tool_name_is_rejected_not_executed():
    """No real model response can ever name a tool outside TOOLS — the
    Anthropic API only emits tool_use blocks for declared tools — but this
    proves the SERVER side of the boundary too: even a fabricated tool_use
    for something like 'run_shell' or 'restart_service' hits the same
    exhaustive if/elif and falls through to rejection, because no such
    branch exists to reach."""
    from spectra import config as scfg
    from spectra.services import settings_agent as sa

    for name in ("run_shell", "restart_service", "http_request", "read_file"):
        result = _run(sa._dispatch(name, {"cmd": "rm -rf /"}))
        assert result["status"] == "rejected"
    assert not scfg.ROOM_CONTROLS_FILE.exists()


# ═══ 5. API layer ═════════════════════════════════════════════════════════

def test_api_registry_and_log_and_undo():
    from fastapi.testclient import TestClient

    from spectra.app import create_app
    from spectra.services import settings_console as sc

    client = TestClient(create_app())

    r = client.get("/api/settings-console/registry")
    assert r.status_code == 200
    assert {s["key"] for s in r.json()["settings"]} == set(sc.SETTINGS_REGISTRY)

    r = client.post("/api/settings-console/undo")
    assert r.status_code == 409, "nothing applied yet — nothing to undo"

    r = client.get("/api/settings-console/log")
    assert r.status_code == 200 and r.json() == []


def test_api_message_503_without_api_key(monkeypatch):
    from fastapi.testclient import TestClient

    from spectra import config as scfg
    from spectra.app import create_app

    monkeypatch.setattr(scfg, "settings_agent_api_key", lambda: "")
    client = TestClient(create_app())
    r = client.post("/api/settings-console/message", json={"text": "set brightness to half"})
    assert r.status_code == 503
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_api_transcribe_503_transcriber_unwired():
    from fastapi.testclient import TestClient

    from spectra.app import create_app

    client = TestClient(create_app())
    r = client.post(
        "/api/settings-console/transcribe",
        files={"audio": ("clip.webm", b"\x00\x01\x02", "audio/webm")},
    )
    assert r.status_code == 503
    assert "type your request" in r.json()["detail"]


def test_vocabulary_hint_degrades_gracefully_with_no_stores():
    from spectra.services import transcription

    hint = transcription.vocabulary_hint()
    assert isinstance(hint, str)


# ═══ the wire contract: a silently-ignored vocabulary is a hard failure ══
# (2026-08-14, coordinated with the ship building the local-Whisper bridge
# against this endpoint — see transcription.py's wire-contract docstring)

def test_api_transcribe_hard_fails_when_vocabulary_silently_ignored(monkeypatch):
    """A concrete transcriber that returns text WITHOUT confirming it used
    the vocabulary hint must be rejected (502), never accepted as a normal
    200 — a request whose vocabulary was silently ignored is a bug in the
    transcriber, not a degraded-but-fine transcription."""
    from fastapi.testclient import TestClient

    from spectra.app import create_app
    from spectra.services import transcription

    async def forgetful_transcribe(audio, mime_type, vocabulary=""):
        return transcription.TranscriptionResult(text="whatever it heard")  # vocabulary_honored left None

    monkeypatch.setattr(transcription, "transcribe", forgetful_transcribe)
    monkeypatch.setattr(transcription, "vocabulary_hint", lambda: "Sunset Drift Warm White")

    client = TestClient(create_app())
    r = client.post(
        "/api/settings-console/transcribe",
        files={"audio": ("clip.webm", b"\x00\x01\x02", "audio/webm;codecs=opus")},
    )
    assert r.status_code == 502
    assert "vocabulary" in r.json()["detail"]


def test_api_transcribe_accepts_a_confirmed_vocabulary_use(monkeypatch):
    from fastapi.testclient import TestClient

    from spectra.app import create_app
    from spectra.services import transcription

    async def honest_transcribe(audio, mime_type, vocabulary=""):
        assert vocabulary == "Sunset Drift Warm White"
        return transcription.TranscriptionResult(text="turn on sunset drift", vocabulary_honored=True)

    monkeypatch.setattr(transcription, "transcribe", honest_transcribe)
    monkeypatch.setattr(transcription, "vocabulary_hint", lambda: "Sunset Drift Warm White")

    client = TestClient(create_app())
    r = client.post(
        "/api/settings-console/transcribe",
        files={"audio": ("clip.webm", b"\x00\x01\x02", "audio/webm;codecs=opus")},
    )
    assert r.status_code == 200
    assert r.json() == {"text": "turn on sunset drift", "vocabulary_honored": True}


def test_api_transcribe_empty_vocabulary_needs_no_confirmation(monkeypatch):
    """No vocabulary to honor (e.g. an empty library) is not a failure —
    only a NON-empty, silently-dropped vocabulary is."""
    from fastapi.testclient import TestClient

    from spectra.app import create_app
    from spectra.services import transcription

    async def bare_transcribe(audio, mime_type, vocabulary=""):
        return transcription.TranscriptionResult(text="turn on sunset drift")

    monkeypatch.setattr(transcription, "transcribe", bare_transcribe)
    monkeypatch.setattr(transcription, "vocabulary_hint", lambda: "")

    client = TestClient(create_app())
    r = client.post(
        "/api/settings-console/transcribe",
        files={"audio": ("clip.webm", b"\x00\x01\x02", "audio/webm;codecs=opus")},
    )
    assert r.status_code == 200


# ═══ 6. live-model smoke test (skipped: no ANTHROPIC_API_KEY here) ═══════

@pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"),
                    reason="needs a real ANTHROPIC_API_KEY — live-model smoke test")
def test_live_model_can_apply_a_change():
    from spectra.services import room_controls as rc
    from spectra.services import settings_agent as sa

    result = _run(sa.run_turn(None, "Set the brightness to 50%."))
    assert result["changes"], "the model should have called set_setting"
    assert rc.load_room_controls().brightness_multiplier == pytest.approx(0.5, abs=0.05)
